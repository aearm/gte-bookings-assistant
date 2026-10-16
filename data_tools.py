"""Read-only tools Claude uses to look at the data before writing a plan ("check before you write"):
get_cube_details - a cube's exact measures, columns and values (its physical layer);
find_values - where a word like "UAE" or "Ok" appears in any cube, and how much data each match has;
preview_query - whether a query runs on a cube, which columns it returns, and its first rows.
Answers are short text for Claude."""
from datetime import date, timedelta

import cubes
import data_layer
import value_index
from backends import get_backend

PREVIEW_ROWS = 10


def tools_for(allowed: list[str]) -> list[dict]:
    """The tool definitions, with the cubes Claude may use."""
    cube_prop = {"type": "string", "enum": allowed, "description": "Exact cube name."}
    find_cube = {"type": "string", "enum": [""] + allowed, "description": "Only this cube, or empty for every cube."}
    return [
        {
            "name": "get_cube_details",
            "description": ("The exact measures, columns (with helper columns and sort columns), values with how "
                            "much data each has, business notes and glossary of one cube. Read it before writing a "
                            "query on that cube."),
            "strict": True,
            "input_schema": {"type": "object", "properties": {"cube": cube_prop}, "required": ["cube"],
                             "additionalProperties": False},
        },
        {
            "name": "find_values",
            "description": (
                "Search the data for a word or name from the question (a status, market, country, channel, "
                "customer, supplier, hotel...). Returns every cube and column where it appears, the exact value "
                "as stored, and how much data it has. Use it before filtering on any value."),
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The word or name to look for, e.g. UAE"},
                    "cube": find_cube,
                    "column": {"type": "string", "description": "Optional: only this column, written as in the "
                               "cube details. Needed for the columns listed as not indexed."},
                },
                "required": ["text", "cube", "column"],
                "additionalProperties": False,
            },
        },
        {
            "name": "preview_query",
            "description": (
                f"Run a read-only query on one cube and see its column names, how many rows it returns and the "
                f"first {PREVIEW_ROWS} rows. Use it to check that filters return data and which columns a step "
                "returns before joining it. @START and @END are filled in with this year so far."),
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"cube": cube_prop, "query": {"type": "string"}},
                "required": ["cube", "query"],
                "additionalProperties": False,
            },
        },
    ]


def checks(allowed: list[str], on_step=None) -> dict:
    """Keyword arguments for llm.question_to_plan that let Claude check these cubes first.
    on_step(text) receives a line for the progress box for each check."""
    def report(name, args):
        if on_step:
            on_step(describe_step(name, args))
    return {"tools": tools_for(allowed), "run_tool": lambda name, args: run(allowed, name, args),
            "on_step": report if on_step else None}


def describe_step(name: str, args: dict) -> str:
    """A line for the progress box, e.g. Looking up "UAE" in the data."""
    cube = args.get("cube", "")
    if name == "get_cube_details":
        return f"📖 Reading the details of {data_layer.cube_label(cube)}"
    if name == "find_values":
        where = f" in {data_layer.cube_label(cube)}" if cube else " in the data"
        if cube and args.get("column"):
            column = get_backend(cube).index.resolve_column(args["column"])
            where += f" › {value_index.column_label(column)}"
        return f'🔎 Looking up "{args.get("text", "")}"{where}'
    return f"🧪 Testing a query on {data_layer.cube_label(cube)}"


def run(allowed: list[str], name: str, args: dict) -> str:
    cube = str(args.get("cube", ""))
    if cube and cube not in allowed:
        return f"Unknown cube \"{cube}\". Use one of: " + ", ".join(f'"{c}"' for c in allowed)
    if name == "get_cube_details":
        return data_layer.cube_details(cube, full=True)  # everything, when the compact details given lack something
    if name == "find_values":
        return _find(allowed if not cube else [cube], str(args.get("text", "")), str(args.get("column", "")))
    if name == "preview_query":
        return _preview(cube, str(args.get("query", "")))
    return f"Unknown tool: {name}"


def _find(cube_names: list[str], text: str, column: str) -> str:
    lines, live_lines, built = [], [], False
    for cube in cube_names:
        backend = get_backend(cube)
        index = backend.index
        if not index.load():
            continue
        built = True
        col = index.resolve_column(column) if column else ""
        unit = index.count_label()
        label = data_layer.cube_label(cube) if len(cube_names) > 1 else ""
        if col and col in index.live_columns():
            info = index.column_info(col) or {}
            found = backend.search_values(col, info.get("group_with", []), text, 10)
            lines += [f'- {label + " · " if label else ""}{col} = "{v}" (not counted)' for v in found]
            continue
        for h in index.search(text, column=col, limit=10 if len(cube_names) > 1 else 15):
            amount = f"{h['count']:,.0f} {unit}" if h["count"] else "no data"
            lines.append(f'- {label + " · " if label else ""}{h["column"]} = "{h["value"]}" ({amount})')
        live = index.live_columns()
        if live and not column:
            live_lines.append(f"{label or cubes.label(cube)}: " + ", ".join(live))
    if not built:
        return "The value index hasn't been built yet (an admin builds the data layer on the Cubes page)."
    out = [f'Values matching "{text}", best first (cube · column = exact value (amount of data)):'] + lines if lines \
        else [f'"{text}" matches no indexed value' + (f" of {column}." if column else ".")]
    if live_lines:
        out.append("Not indexed (too many values); to search one, call find_values again with its cube and column: "
                   + " | ".join(live_lines))
    return "\n".join(out)


def _preview(cube: str, query: str) -> str:
    backend = get_backend(cube)
    if backend.language == "DAX":
        import llm
        try:
            llm.validate_dax(query)  # read-only: must be EVALUATE / DEFINE ... EVALUATE
        except Exception as exc:
            return f"Not run: {exc}"
    if "@START" in query or "@END" in query:
        today = date.today()
        query = (query.replace("@START", backend.date_literal(today.replace(month=1, day=1)))
                      .replace("@END", backend.date_literal(today + timedelta(days=1))))
    try:
        df = backend.run(query, PREVIEW_ROWS + 1)
    except Exception as exc:
        return f"The query failed: {str(exc).splitlines()[0][:500]}"
    columns = "Columns: " + ", ".join(f'"{c}"' for c in df.columns)
    if df.empty:
        return f"The query ran and returned 0 rows. {columns}"
    count = f"More than {PREVIEW_ROWS}" if len(df) > PREVIEW_ROWS else str(len(df))
    return f"{count} rows. {columns}\nFirst rows (CSV):\n{df.head(PREVIEW_ROWS).to_csv(index=False)}"
