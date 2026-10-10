"""Read-only tools Claude uses to look at a cube before writing a query ("check before you write"):
find_values - where a word like "UAE" or "Ok" appears in the data, and how much data each match has;
preview_query - whether a query runs and returns rows. Answers are short text for Claude."""
from datetime import date, timedelta

import value_index

PREVIEW_ROWS = 10

TOOLS = [
    {
        "name": "find_values",
        "description": (
            "Search the data for a word or name from the question (a status, market, country, channel, "
            "customer, supplier, product...). Returns every column where it appears, the exact value as "
            "stored, and how much data it has. Use it before filtering on any value. Leave column empty to "
            "search everywhere."),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The word or name to look for, e.g. UAE"},
                "column": {"type": "string", "description": "Optional: only this column, written as in the "
                           "schema. Needed for the columns listed as not indexed."},
            },
            "required": ["text", "column"],
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_query",
        "description": (
            f"Run a read-only query and see how many rows it returns and the first {PREVIEW_ROWS} rows. Use it "
            "to check that filters return data before giving your answer. @START and @END are filled in with "
            "this year so far."),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def checks(backend, on_step=None) -> dict:
    """Keyword arguments for llm.question_to_query that let Claude check this backend's cube first.
    on_step(text) receives a line for the progress box for each check."""
    def report(name, args):
        if on_step:
            on_step(describe_step(backend, name, args))
    return {"tools": TOOLS, "run_tool": lambda name, args: run(backend, name, args),
            "on_step": report if on_step else None}


def describe_step(backend, name: str, args: dict) -> str:
    """A line for the progress box, e.g. Looking up "UAE" in the data."""
    if name == "find_values":
        column = backend.index.resolve_column(args.get("column", ""))
        where = f" in {value_index.column_label(column)}" if column else " in the data"
        return f'🔎 Looking up "{args.get("text", "")}"{where}'
    return "🧪 Testing a query on the data"


def run(backend, name: str, args: dict) -> str:
    if name == "find_values":
        return _find(backend, str(args.get("text", "")), backend.index.resolve_column(str(args.get("column", ""))))
    if name == "preview_query":
        return _preview(backend, str(args.get("query", "")))
    return f"Unknown tool: {name}"


def _find(backend, text: str, column: str) -> str:
    index = backend.index
    if not index.load():
        return ("The value index hasn't been built yet (an admin sets up the cube on the Cubes page). "
                "Use the values listed in the schema.")
    unit = index.count_label()
    if column and column in index.live_columns():
        info = index.column_info(column) or {}
        found = backend.search_values(column, info.get("group_with", []), text, 10)
        if not found:
            return f'No value of {column} contains "{text}".'
        return f'Values of {column} containing "{text}" (not counted):\n' + "\n".join(f'- "{v}"' for v in found)

    lines = []
    hits = index.search(text, column=column)
    if hits:
        lines.append(f'Values matching "{text}", best first (column = exact value (number of {unit})):')
        for h in hits:
            amount = f"{h['count']:,.0f} {unit}" if h["count"] else "no data"
            lines.append(f'- {h["column"]} = "{h["value"]}" ({amount})')
    else:
        lines.append(f'"{text}" matches no value' + (f" of {column}." if column else " in the indexed columns."))
    live = index.live_columns()
    if live and not column:
        lines.append("Not indexed (too many values); to search one, call find_values again with its column: "
                     + ", ".join(live))
    return "\n".join(lines)


def _preview(backend, query: str) -> str:
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
    if df.empty:
        return "The query ran and returned 0 rows."
    count = f"More than {PREVIEW_ROWS}" if len(df) > PREVIEW_ROWS else str(len(df))
    return f"{count} rows. First rows (CSV):\n{df.head(PREVIEW_ROWS).to_csv(index=False)}"
