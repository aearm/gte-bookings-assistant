"""The app from any Claude conversation, with no Claude key of the app's: what Claude's connector (mcp_server.py)
does for each of its tools. Claude itself reads the cubes' knowledge (the data layer, each cube's details, the
values in the data and the rules for writing queries - the same the app's own Claude reads), checks its queries
on the cubes, and adds or changes dashboard charts, which the app then draws and keeps up to date like any other.
How a chart is described is in skills/bookings-dashboards (the skill Claude follows); every chart is run once on
the cubes before it is saved, so a chart that fails or can't be drawn is never put on a dashboard.

Answers are short text for Claude (or JSON where Claude edits what it gets back: a dashboard's charts)."""
import json
import re
import uuid
from datetime import date

import pandas as pd

import config
import cubes
import dashboards
import data_layer
import plans
from backends import get_backend
from errors import friendly

PREVIEW_ROWS = 30
MATCHES_PER_CUBE = 3
STEP_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
FILTER_KEY = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
STYLE_KEYS = {"formats", "x_title", "y_title", "sort", "show_values", "label_angle", "legend", "log_scale",
              "measures", "lower_is_better"}
FORMAT_KEYS = {"column", "d3_format", "prefix", "suffix"}


class ToolError(Exception):
    """A request Claude should correct (the message says how)."""


# ---------------------------------------------------------------- where things are --

def app_url(path: str = "") -> str:
    """The web app's address on this computer (API_PORT in .env, else 8600)."""
    import start_api
    return f"http://localhost:{start_api.port_from_settings()}{path}"


def dashboard_url(dashboard_id: str) -> str:
    return app_url(f"/dashboard/{dashboard_id}")


def language() -> str:
    return "DAX" if config.resolve_source() == "ssas" else "SQL"


def connected() -> list[str]:
    """The cubes Claude may use: connected and read (their structure is known)."""
    return [c for c in cubes.enabled() if cubes.is_ready(c)]


def _cube(name: str) -> str:
    allowed = connected()
    if name in allowed:
        return name
    by_label = {cubes.label(c).lower(): c for c in allowed}
    if name.strip().lower() in by_label:
        return by_label[name.strip().lower()]
    raise ToolError(f'Unknown cube "{name}". Use one of: ' + ", ".join(f'"{c}"' for c in allowed))


def _setup_problem() -> None:
    problem = dashboards.setup_problem()
    if problem:
        raise ToolError(problem)


# ---------------------------------------------------------------- the cubes' knowledge (context) --

def _joining_rules() -> str:
    import llm
    text = llm.PLAN_RULES
    start = text.find("Joining cubes (several steps):")
    end = text.find("LANGUAGE_RULES", start)
    return text[start:end].strip() if start >= 0 and end > start else ""


PLACEHOLDERS = """## Dashboard charts: periods and filters
- A dashboard chart is re-run for whatever period is picked above the dashboard. Every step filters its date on
  the period with @START and @END, written literally (@END is the day after the last day), e.g. in DAX
  KEEPFILTERS(FILTER(ALL('Calendar'[Date]), 'Calendar'[Date] >= @START && 'Calendar'[Date] < @END)) inside
  SUMMARIZECOLUMNS, in SQL "Booking Date" >= @START AND "Booking Date" < @END. Use the date the chart means
  (by default the cube's default date above).
- A dashboard can have filters (a client, a market...): a placeholder like @F_CLIENT in a query is replaced
  with the value picked above the dashboard, as a quoted text, e.g. 'Customers'[Code] = @F_CLIENT.
- @KEYS(step, column): the values another step returned (top N members across cubes, see joining above).
- run_query fills @START / @END (the dates you give, else the dashboard's default period) and @F_ values."""


def knowledge() -> str:
    """Everything Claude reads first: the data layer (every cube in a card, which cube for what, the dimensions
    the cubes share), today's date, and the rules for writing queries and plans."""
    _setup_problem()
    allowed = connected()
    if not allowed:
        return ("No cube can be used yet: an admin connects the cubes and reads them on the Cubes page of the app ("
                + app_url("/cubes") + ").")
    import llm
    import routing
    parts = [f"Today is {date.today():%A %d %B %Y} ({date.today().isoformat()})."]
    cards = routing.cards_text() if data_layer.is_built() else ""
    if cards.strip():
        parts.append(cards.strip())
    else:
        parts.append("The data layer isn't built yet (an admin builds it on the Cubes page), so there are no index "
                     "cards. The cubes that can be used (read each one's details before writing its query):\n"
                     + "\n".join(f'- "{c}"' for c in allowed))
    rules = llm.DAX_RULES if language() == "DAX" else llm.SQL_RULES
    parts.append("# Writing queries\n" + rules.replace("MAX_ROWS", str(config.MAX_ROWS)))
    parts.append("# Plans: one query per cube, joined in DuckDB\nA plan is a list of steps (name: short lowercase "
                 "letters and _, used as a table name; cube: the exact cube name; query) and combine_sql: empty for "
                 "one step, else ONE DuckDB SELECT joining the steps by their names.\n" + _joining_rules())
    parts.append(PLACEHOLDERS)
    proven = house_rules(allowed)
    if proven:
        parts.append(proven)
    return "\n\n".join(parts)


def house_rules(allowed: list[str]) -> str:
    """How the built-in dashboards filter each cube they use: the period's date, business numbers only, and one
    client, market, destination or supplier - checked on the cubes, so the pattern for new charts."""
    import builtin_dashboards as bd
    scopes = {"client": "one client (@F_CLIENT, a customer code)",
              "market": "one market (@F_MARKET, the client's country)",
              "destination": "one destination (@F_DESTINATION, the hotel's country)",
              "supplier": "one supplier connection (@F_SUPPLIER, a connection code)"}
    lines = []
    for cube, scope in bd._SCOPES.items():
        if cube not in allowed:
            continue
        parts = [f"period: {bd._within(scope['date'])}", f"business numbers only (test data left out): {scope['real']}"]
        parts += [f"{what}: {scope[key]}" for key, what in scopes.items() if key in scope]
        lines.append(f'- {cubes.label(cube)} ("{cube}"):\n  ' + "\n  ".join(parts))
    if not lines:
        return ""
    return ("## How the built-in dashboards filter each cube (checked on the cubes: reuse these in new charts)\n"
            + "\n".join(lines))


def cube_details(cube: str, full: bool = False) -> str:
    _setup_problem()
    return data_layer.cube_details(_cube(cube), full=full)


def find_values(text: str, cube: str = "", column: str = "") -> str:
    _setup_problem()
    import data_tools
    if not text.strip():
        raise ToolError("Say which word or name to look for.")
    if cube:
        return data_tools._find([_cube(cube)], text.strip(), column.strip())
    # every cube: the best few matches of each, so the answer stays short (one cube at a time shows all)
    lines = data_tools._find(connected(), text.strip(), column.strip()).splitlines()
    kept, per_cube, dropped = [], {}, 0
    for line in lines[1:]:
        if not line.startswith("- "):
            kept.append(line if len(line) <= 1500 else line[:1500] + "...")
            continue
        where = line[2:].split(" · ", 1)[0]
        per_cube[where] = per_cube.get(where, 0) + 1
        if per_cube[where] <= MATCHES_PER_CUBE:
            kept.append(line)
        else:
            dropped += 1
    more = [f"({dropped} weaker matches left out: give cube to see all of one cube's.)"] if dropped else []
    return "\n".join(lines[:1] + kept + more)


def join_path(cube_names: list[str]) -> str:
    import routing
    names = [_cube(c) for c in cube_names]
    if len(names) < 2:
        raise ToolError("Give two cubes or more.")
    return routing.join_path(names) or "No shared dimension is known between these cubes."


# ---------------------------------------------------------------- running queries --

def _steps(steps: list[dict]) -> list[plans.Step]:
    if not steps:
        raise ToolError("Give at least one step: {name, cube, query}.")
    out, names = [], set()
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            raise ToolError(f"Step {i} must be an object with name, cube and query.")
        name = str(s.get("name") or ("result" if len(steps) == 1 else "")).strip()
        if not STEP_NAME.match(name):
            raise ToolError(f'Step {i}: name "{name}" must be short lowercase letters, digits and _ (a table name).')
        if name in names:
            raise ToolError(f'Two steps are named "{name}".')
        names.add(name)
        cube = _cube(str(s.get("cube", "")))
        query = str(s.get("query", "")).strip()
        if not query:
            raise ToolError(f'Step "{name}" has no query.')
        if get_backend(cube).language == "DAX":
            import llm
            try:
                llm.validate_dax(query)
            except Exception as exc:
                raise ToolError(f'Step "{name}": {exc}') from exc
        out.append(plans.Step(name, cube, query))
    return out


def _dates(start: str = "", end: str = "") -> tuple[date, date, str]:
    """The period to run for: the dates given (end = the last day, included), else the dashboard's default."""
    from server.routes.periods import pick
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise ToolError("Write dates as YYYY-MM-DD.") from exc
    if first and last:
        if last < first:
            raise ToolError("The end date is before the start date.")
        return first, date.fromordinal(last.toordinal() + 1), ""
    return pick(None, None, "")


def _fill_filters(plan: plans.Plan, values: dict | None) -> plans.Plan:
    marks = {("@F_" + str(k).upper().removeprefix("@F_")): str(v) for k, v in (values or {}).items()}
    text = json.dumps(plan.to_dict())
    missing = sorted(set(dashboards.FILTER_MARK.findall(text)) - set(marks))
    if missing:
        raise ToolError("Give a value for " + ", ".join(missing) + " (filters={\"CLIENT\": \"...\"}).")
    if not marks:
        return plan
    steps = [plans.Step(s.name, s.cube, dashboards._fill_marks(s.query, marks, get_backend(s.cube).language))
             for s in plan.steps]
    return plans.Plan(steps, dashboards._fill_marks(plan.combine_sql or "", marks, "SQL"))


def _table_text(df: pd.DataFrame, limit: int = PREVIEW_ROWS) -> str:
    kinds = ", ".join(f'"{c}" ({"number" if pd.api.types.is_numeric_dtype(df[c]) else "text/date"})' for c in df.columns)
    if df.empty:
        return f"0 rows. Columns: {kinds}"
    shown = df.head(limit)
    more = f" (first {limit} shown)" if len(df) > limit else ""
    return f"{len(df)} rows{more}. Columns: {kinds}\n{shown.to_csv(index=False, lineterminator=chr(10))}"


def run_query(steps: list[dict], combine_sql: str = "", start: str = "", end: str = "",
              filters: dict | None = None) -> str:
    """Run a plan on the cubes and show its result: to check numbers, column names and filters before a chart
    is made of it. @START / @END: the dates given, else the dashboard's default period."""
    _setup_problem()
    first, after, _ = _dates(start, end)
    plan = _fill_filters(plans.Plan(_steps(steps), combine_sql.strip()), filters)
    if len(plan.steps) > 1 and not plan.combine_sql:
        raise ToolError("Several steps need combine_sql: one DuckDB SELECT joining them by their names.")
    try:
        df = plans.run(plan.with_dates(first, after))
    except Exception as exc:
        return f"The query failed: {friendly(exc)}" + _hint(plan, exc)
    last = date.fromordinal(after.toordinal() - 1)
    return f"Period {first.isoformat()} to {last.isoformat()}. " + _table_text(df)


def _hint(plan: plans.Plan, exc: Exception) -> str:
    import semantic
    hints = [h for h in (semantic.composite_key_hint(s.cube, str(exc)) for s in plan.steps) if h]
    return ("\n" + "\n".join(hints)) if hints else ""


# ---------------------------------------------------------------- dashboards --

def _board(dashboard_id: str) -> dict:
    board = dashboards.get_dashboard(dashboard_id)
    if board is None:
        names = ", ".join(f'{d["id"]} ("{d["name"]}")' for d in dashboards.list_dashboards())
        raise ToolError(f'No dashboard "{dashboard_id}". The dashboards: {names}')
    return board


def list_dashboards() -> str:
    lines = []
    for d in dashboards.list_dashboards():
        notes = []
        if d.get("filters"):
            notes.append("filters: " + ", ".join(f["label"] for f in d["filters"]))
        if d.get("builtin"):
            notes.append("built in, changed here" if d.get("customized") else "built in")
        lines.append(f'- {d["id"]}: "{d["name"]}", {len(d["charts"])} charts'
                     + (f" ({'; '.join(notes)})" if notes else "") + f" - {dashboard_url(d['id'])}")
    return "\n".join(lines) or "No dashboards yet."


def spec_of(chart: dict) -> dict:
    """A chart as Claude reads and edits it (what add_chart takes)."""
    plan = plans.Plan.from_chart(chart)
    spec = {"id": chart["id"], "title": chart.get("title", ""), "question": chart.get("question", ""),
            "chart_type": chart.get("chart_type", ""), "x": chart.get("x", ""), "y": list(chart.get("y") or []),
            "color": chart.get("color", ""), "width": "full" if chart.get("width") == "full" else "half",
            "style": chart.get("style") or {}, "steps": [{"name": s.name, "cube": s.cube, "query": s.query}
                                                        for s in plan.steps],
            "combine_sql": plan.combine_sql or "", "compare": chart.get("compare") is not False,
            "date_column": chart.get("date_column", "")}
    if chart.get("custom"):
        spec["custom"] = chart["custom"]
    mode = dashboards.period_mode(chart)
    if mode != "dashboard":
        spec["period"] = (f"{mode}: {dashboards.period_text(chart)} - its own dates, not the dashboard's (changing its "
                          "steps makes it follow the dashboard's period: use @START / @END)")
    return spec


def get_dashboard(dashboard_id: str) -> dict:
    board = _board(dashboard_id)
    out = {"id": board["id"], "name": board["name"], "link": dashboard_url(board["id"]),
           "filters": board.get("filters") or [], "charts": [spec_of(c) for c in board["charts"]]}
    if board.get("builtin"):
        out["note"] = ("A built-in dashboard: " + ("it has been changed here, so new versions of the app leave it as "
                       "it is." if board.get("customized") else "new versions of the app update it until its charts "
                       "or filters are changed here; then it is yours and stays as you leave it."))
    return out


def create_dashboard(name: str) -> str:
    if not name.strip():
        raise ToolError("Give the dashboard a name.")
    new_id = dashboards.create_dashboard(name)
    return f'Created "{name.strip()}" (id {new_id}): {dashboard_url(new_id)}'


def copy_dashboard(dashboard_id: str, name: str) -> str:
    board = _board(dashboard_id)
    new_id = dashboards.copy_dashboard(board["id"], name)
    return f'Copied "{board["name"]}" to "{dashboards.get_dashboard(new_id)["name"]}" (id {new_id}): {dashboard_url(new_id)}'


def rename_dashboard(dashboard_id: str, name: str) -> str:
    board = _board(dashboard_id)
    if not name.strip():
        raise ToolError("Give the new name.")
    dashboards.rename_dashboard(board["id"], name)
    return f'Renamed "{board["name"]}" to "{name.strip()}".'


def delete_dashboard(dashboard_id: str) -> str:
    board = _board(dashboard_id)
    dashboards.delete_dashboard(board["id"])
    return f'Deleted the dashboard "{board["name"]}" and its {len(board["charts"])} charts.'


def set_filters(dashboard_id: str, filters: list[dict]) -> str:
    """Check and save a dashboard's filters; each one's list of values is read from the cubes once to check it."""
    board = _board(dashboard_id)
    clean = []
    for i, f in enumerate(filters or [], 1):
        key = str(f.get("key", "")).strip().lower()
        if not FILTER_KEY.match(key):
            raise ToolError(f"Filter {i}: key must be short lowercase letters, digits and _ (e.g. client).")
        o = f.get("options") or {}
        if not isinstance(o, dict) or not o.get("query") or not o.get("value"):
            raise ToolError(f'Filter "{key}": options needs cube, query (with @START / @END: the values with data '
                            "in the last year, biggest first) and value (the column whose value fills the placeholder).")
        step = _steps([{"name": "options", "cube": o.get("cube", ""), "query": o["query"]}])[0]
        clean.append({"key": key, "label": str(f.get("label") or key.title()).strip(),
                      "placeholder": "@F_" + key.upper(),
                      "options": {"cube": step.cube, "query": step.query, "value": str(o["value"]),
                                  "label": str(o.get("label") or "{" + str(o["value"]) + "}"),
                                  **({"title_case": True} if o.get("title_case") else {})}})
    trial = {**board, "filters": clean}
    lines = []
    for f in dashboards.filter_options(trial):
        if f["error"]:
            raise ToolError(f'Filter "{f["key"]}": its values could not be read: {f["error"]}')
        if not f["options"]:
            raise ToolError(f'Filter "{f["key"]}": its query returned no values for the last year.')
        first = ", ".join(o["label"] for o in f["options"][:5])
        lines.append(f'- {f["label"]} (@F_{f["key"].upper()}): {len(f["options"])} values, default "{f["options"][0]["label"]}"; '
                     f"first: {first}")
    dashboards.set_filters(board["id"], clean)
    used = {m for c in board["charts"] for m in dashboards.FILTER_MARK.findall(json.dumps(c.get("plan") or {}))}
    gone = sorted(used - {f["placeholder"] for f in clean})
    return ("Saved the filters:\n" + "\n".join(lines) if lines else "Removed the filters.") + (
        "\nThese charts' placeholders now have no filter: " + ", ".join(gone) if gone else "")


# ---------------------------------------------------------------- charts --

def _style(style) -> dict:
    if not style:
        return {}
    if not isinstance(style, dict):
        raise ToolError("style must be an object.")
    unknown = sorted(set(style) - STYLE_KEYS)
    if unknown:
        raise ToolError(f"Unknown style setting {unknown[0]}. Use: {', '.join(sorted(STYLE_KEYS))}.")
    for fmt in style.get("formats") or []:
        if not isinstance(fmt, dict) or not fmt.get("column") or set(fmt) - FORMAT_KEYS:
            raise ToolError("Each format is {column, d3_format, prefix, suffix}, e.g. {\"column\": \"Sales\", "
                            "\"d3_format\": \"~s\", \"prefix\": \"AED \", \"suffix\": \"\"}.")
    return dict(style)


def make_chart(spec: dict, board: dict, keep: dict | None = None) -> dict:
    """A dashboard chart from Claude's description (checked; not run yet). keep: the chart it replaces."""
    if not isinstance(spec, dict):
        raise ToolError("The chart must be an object.")
    title = str(spec.get("title", "")).strip()
    if not title:
        raise ToolError("Give the chart a title.")
    kind = str(spec.get("chart_type", "")).strip().lower()
    kind = "donut" if kind == "pie" else kind
    if kind not in dashboards.TYPE_LABELS or kind == "auto":
        raise ToolError("chart_type must be one of: " + ", ".join(k for k in dashboards.TYPE_LABELS if k != "auto") + ".")
    plan = plans.Plan(_steps(spec.get("steps") or []), str(spec.get("combine_sql") or "").strip())
    if len(plan.steps) > 1 and not plan.combine_sql:
        raise ToolError("Several steps need combine_sql: one DuckDB SELECT joining them by their names.")
    text = json.dumps(plan.to_dict())
    if "@START" not in text or "@END" not in text:
        raise ToolError("A dashboard chart follows the dashboard's period: filter each step's date with @START and "
                        "@END (see 'Dashboard charts: periods and filters' in the knowledge).")
    have = {f["placeholder"] for f in board.get("filters") or []}
    missing = sorted(set(dashboards.FILTER_MARK.findall(text)) - have)
    if missing:
        raise ToolError(f'The dashboard "{board["name"]}" has no filter for ' + ", ".join(missing)
                        + (". Its filters: " + ", ".join(sorted(have)) if have else ". It has no filters (set_filters adds them)."))
    width = str(spec.get("width") or ("full" if kind in ("map", "custom", "table") else "half"))
    if width not in ("half", "full"):
        raise ToolError("width is half or full.")
    y = spec.get("y") or []
    y = [y] if isinstance(y, str) else [str(v) for v in y]
    cube_names = plan.cubes
    date_col = str(spec.get("date_column") or "")
    if not date_col:
        date_col = (dashboards.default_date_column(dashboards.date_columns(get_backend(cube_names[0]).schema_text()),
                                                   cube_names[0]) if len(cube_names) == 1 else dashboards.AUTO_DATE)
    chart = {"id": keep["id"] if keep else uuid.uuid4().hex[:8],
             "cube": cube_names[0] if len(cube_names) == 1 else "", "title": title,
             "question": str(spec.get("question") or title).strip(), "query": plan.text(), "plan": plan.to_dict(),
             "date_column": date_col, "chart_type": kind, "x": str(spec.get("x") or ""), "y": y,
             "color": str(spec.get("color") or ""), "style": _style(spec.get("style")), "width": width,
             "period_mode": "dashboard"}
    if spec.get("compare") is False:
        chart["compare"] = False
    if kind == "custom":
        import custom_echarts
        option = spec.get("custom")
        if not option:
            raise ToolError("A custom chart needs custom: an ECharts option whose data point at the result's columns "
                            '({"col": "Sales"}); see the charts reference of the skill.')
        try:
            chart["custom"] = custom_echarts.parse(option)
        except Exception as exc:
            raise ToolError(f"The custom chart can't be used: {exc}") from exc
        chart["chart_request"] = str(spec.get("chart_request") or "")
    if keep and keep.get("builtin"):
        chart["builtin"] = keep["builtin"]
    return chart


def check_chart(chart: dict, board: dict) -> tuple[bool, str, dict]:
    """Run the chart once for the dashboard's default period (its filters at their default values) and draw it
    as the dashboard would. Returns (whether it can be saved, a report for Claude, the drawn result)."""
    from server.routes.dashboards import chart_result
    start, end, _ = _dates()
    running = dashboards.apply_filters(board, [chart])[0] if board.get("filters") else chart
    res = dashboards._run_one(running, start, end)
    if res.get("error"):
        plan = plans.Plan.from_chart(running)
        return False, (f"Not saved: the chart's query failed: {res['error']}"
                       + _hint(plan, RuntimeError(res.get("details") or res["error"]))), {}
    drawn = chart_result(chart, res, start, end, None)
    df = res.get("df")
    last = date.fromordinal(end.toordinal() - 1)
    lines = [f"Ran it for {start.isoformat()} to {last.isoformat()}"
             + (" (the filters at their default values)" if board.get("filters") else "") + ": "
             + _table_text(df, 8)]
    kind = (drawn.get("chart") or {}).get("kind")
    note = (drawn.get("chart") or {}).get("note") or ""
    if df is not None and chart["chart_type"] not in ("kpi", "custom"):
        named = [c for c in [chart.get("x"), *(chart.get("y") or []), chart.get("color")] if c]
        missing = [c for c in named if c not in df.columns]
        if missing:
            return False, ("Not saved: " + ", ".join(f'"{c}"' for c in missing) + " is not a column of the result. Its "
                           "columns: " + ", ".join(f'"{c}"' for c in df.columns) + "."), drawn
        if not chart.get("y") and chart["chart_type"] != "table":
            return False, "Not saved: say which number column(s) to plot in y.", drawn
    if chart["chart_type"] == "kpi":
        if df is None or df.empty or not any(pd.api.types.is_numeric_dtype(df[c]) for c in df.columns):
            return False, "Not saved: a headline number (kpi) needs a query that returns one row with a number.", drawn
        lines.append(f"Headline: {(drawn.get('kpi') or {}).get('text', '')}")
    elif chart["chart_type"] != "table" and kind == "table" and df is not None and not df.empty:
        return False, (f"Not saved: it can't be drawn as {chart['chart_type']} ({note or 'check x, y and color: they must be columns of the result'}). "
                       "Use the result's exact column names, or another chart type."), drawn
    if note:
        lines.append(f"Note: {note}")
    if df is not None and df.empty:
        lines.append("It returned no rows for this period: check its filters if it should have data.")
    return True, "\n".join(lines), drawn


def _option_text(drawn: dict) -> str:
    option = (drawn.get("chart") or {}).get("option")
    if not option:
        return ""
    text = json.dumps(option, default=str)
    return text if len(text) <= 30_000 else ""


def preview_chart(dashboard_id: str, chart: dict) -> str:
    board = _board(dashboard_id)
    made = make_chart(chart, board)
    ok, report, drawn = check_chart(made, board)
    option = _option_text(drawn) if ok else ""
    return report + (f"\nThe ECharts option the app draws (for drawing it in this conversation): {option}" if option else "")


def add_chart(dashboard_id: str, chart: dict, position: int | None = None) -> str:
    _setup_problem()
    board = _board(dashboard_id)
    made = make_chart(chart, board)
    ok, report, _ = check_chart(made, board)
    if not ok:
        return report
    dashboards.add_chart(board["id"], made)
    if position is not None:
        dashboards.place_chart(board["id"], made["id"], int(position))
    return (f'Added "{made["title"]}" (chart {made["id"]}) to "{board["name"]}": {dashboard_url(board["id"])}\n'
            + report)


def update_chart(dashboard_id: str, chart_id: str, changes: dict) -> str:
    """Change some of a chart's settings (any of add_chart's); the rest stays."""
    _setup_problem()
    board = _board(dashboard_id)
    old = next((c for c in board["charts"] if c["id"] == chart_id), None)
    if old is None:
        raise ToolError(f'"{board["name"]}" has no chart {chart_id}. Its charts: '
                        + ", ".join(f'{c["id"]} ("{c.get("title", "")}")' for c in board["charts"]))
    if not isinstance(changes, dict) or not changes:
        raise ToolError("Say what to change, e.g. {\"chart_type\": \"line\"}.")
    unknown = sorted(set(changes) - {"title", "question", "chart_type", "x", "y", "color", "width", "style", "steps",
                                     "combine_sql", "compare", "date_column", "custom", "chart_request"})
    if unknown:
        raise ToolError(f"Can't change {unknown[0]}.")
    spec = {**spec_of(old), **changes}
    if "period" in spec:
        spec.pop("period")
        if "steps" not in changes:  # its own dates stay: only how it looks changes
            return _restyle_own_period(board, old, changes)
    made = make_chart(spec, board, keep=old)
    ok, report, _ = check_chart(made, board)
    if not ok:
        return report
    dashboards.update_chart(board["id"], made)
    return f'Changed "{made["title"]}" on "{board["name"]}": {dashboard_url(board["id"])}\n' + report


def _restyle_own_period(board: dict, old: dict, changes: dict) -> str:
    """A chart with dates of its own (from a chat answer): its look changes, its plan and dates stay."""
    looks = {k: v for k, v in changes.items() if k in ("title", "question", "chart_type", "x", "y", "color", "width",
                                                         "style", "compare", "custom", "chart_request")}
    made = {**old, **looks}
    if "style" in looks:
        made["style"] = _style(looks["style"])
    if "compare" in looks:
        made.pop("compare", None)
        if looks["compare"] is False:
            made["compare"] = False
    ok, report, _ = check_chart(made, board)
    if not ok:
        return report
    dashboards.update_chart(board["id"], made)
    return f'Changed "{made.get("title", "")}" on "{board["name"]}": {dashboard_url(board["id"])}\n' + report


def delete_chart(dashboard_id: str, chart_id: str) -> str:
    board = _board(dashboard_id)
    chart = next((c for c in board["charts"] if c["id"] == chart_id), None)
    if chart is None:
        raise ToolError(f'"{board["name"]}" has no chart {chart_id}.')
    dashboards.delete_chart(board["id"], chart_id)
    return f'Removed "{chart.get("title", "")}" from "{board["name"]}".'


def move_chart(dashboard_id: str, chart_id: str, position: int) -> str:
    board = _board(dashboard_id)
    if not any(c["id"] == chart_id for c in board["charts"]):
        raise ToolError(f'"{board["name"]}" has no chart {chart_id}.')
    dashboards.place_chart(board["id"], chart_id, int(position))
    order = [c.get("title", c["id"]) for c in dashboards.get_dashboard(board["id"])["charts"]]
    return "The charts are now in this order: " + " · ".join(f"{i}. {t}" for i, t in enumerate(order))


def copy_chart(dashboard_id: str, chart_id: str, to_dashboard_id: str) -> str:
    board, target = _board(dashboard_id), _board(to_dashboard_id)
    chart = next((c for c in board["charts"] if c["id"] == chart_id), None)
    if chart is None:
        raise ToolError(f'"{board["name"]}" has no chart {chart_id}.')
    needs = set(dashboards.FILTER_MARK.findall(json.dumps(chart.get("plan") or {})))
    have = {f["placeholder"] for f in target.get("filters") or []}
    if needs - have:
        raise ToolError(f'"{target["name"]}" has no filter for ' + ", ".join(sorted(needs - have)) + ".")
    copy = {k: v for k, v in chart.items() if k != "builtin"}
    dashboards.send_chart(copy, target["id"])
    return f'Copied "{chart.get("title", "")}" to "{target["name"]}": {dashboard_url(target["id"])}'
