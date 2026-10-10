"""Dashboards: named pages of charts saved as queries that re-run for the period the user picks.
A dashboard can mix charts from different cubes; each chart remembers its cube. Saved in
dashboards.json; only admins change them (see dashboard_view.py). Claude is only used when a chart
is created or its question changes - refreshing just re-runs the saved queries."""
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd

import charts
import config
import cubes
import data_tools
import glossary
import llm
import value_check
from backends import get_backend
from errors import details, friendly

TYPE_LABELS = {"auto": "Best fit (automatic)", "kpi": "Headline number", **charts.TYPE_LABELS}
PERIODS = ["Last 7 days", "This month", "Last month", "This year", "Last 12 months", "Custom"]

# Questions for the first dashboard. Claude turns them into queries for whichever model is connected.
STARTER = [
    {"title": "Bookings", "question": "Total number of bookings", "chart_type": "kpi"},
    {"title": "Sales", "question": "Total sales", "chart_type": "kpi"},
    {"title": "Profit", "question": "Total profit", "chart_type": "kpi"},
    {"title": "Bookings by month", "question": "Number of bookings by month, oldest month first",
     "chart_type": "line", "width": "full"},
    {"title": "Top 10 destination countries", "question": "Top 10 destination countries by number of bookings",
     "chart_type": "horizontal_bar"},
    {"title": "Top 10 suppliers", "question": "Top 10 suppliers by number of bookings",
     "chart_type": "horizontal_bar"},
    {"title": "Sales and profit by month", "question": "Sales and profit by month, oldest month first",
     "chart_type": "bar"},
    {"title": "Bookings by destination", "question": "Number of bookings by destination country",
     "chart_type": "map", "width": "full"},
    {"title": "Bookings by sale channel", "question": "Number of bookings by sale channel", "chart_type": "donut"},
]


# ---------------------------------------------------------------- periods --

def _add_months(d: date, months: int) -> date:
    years, month0 = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + years, month=month0 + 1)


def period_range(name: str, custom: tuple[date, date] | None = None, today: date | None = None) -> tuple[date, date]:
    """(start, end) of a period; end is exclusive (the day after the last day)."""
    today = today or date.today()
    tomorrow, first = today + timedelta(days=1), today.replace(day=1)
    if name == "Last 7 days":
        return today - timedelta(days=6), tomorrow
    if name == "This month":
        return first, tomorrow
    if name == "Last month":
        return _add_months(first, -1), first
    if name == "This year":
        return today.replace(month=1, day=1), tomorrow
    if name == "Last 12 months":
        return _add_months(first, -11), tomorrow
    start, last = custom or (today.replace(month=1, day=1), today)
    return start, last + timedelta(days=1)


def same_period_last_year(start: date, end: date) -> tuple[date, date]:
    shift = lambda d: d.replace(year=d.year - 1) if not (d.month == 2 and d.day == 29) else d.replace(year=d.year - 1, day=28)
    return shift(start), shift(end)


# ---------------------------------------------------------------- date columns --

def date_columns(schema_text: str) -> list[str]:
    """Day-level date columns in the schema, written the way a query uses them."""
    cols = re.findall(r"^- ('[^']+'\[[^\]]+\]) \(Date/time\)", schema_text, flags=re.MULTILINE)
    cols += re.findall(r'^- ("[^"]+") \((?:DATE|TIMESTAMP)', schema_text, flags=re.MULTILINE)
    return list(dict.fromkeys(cols))


def default_date_column(cols: list[str], cube: str = "") -> str:
    """The date the period applies to by default: the cube's agreed default date if the setup
    settled it, else a column that looks like a booking/creation date, else the first one."""
    if cube:
        for row in glossary.load(cube)[0]:
            if row.get("Status") == "Agreed" and re.search(r"date", row["Term"], flags=re.IGNORECASE):
                found = [c for c in cols if c in row.get("Date to use", "") + row.get("Measure", "")]
                if found:
                    return found[0]
    for c in cols:
        if re.search(r"create|booking", c, flags=re.IGNORECASE):
            return c
    return cols[0] if cols else ""


def date_label(col: str) -> str:
    """'Create Date'[Create Date] -> Create Date, 'Calendar'[Date] -> Calendar · Date."""
    if not col:
        return "All dates"
    m = re.match(r"'([^']+)'\[([^\]]+)\]", col)
    if not m:
        return col.strip('"')
    table, column = m.groups()
    return column if column.lower() in table.lower() or table.lower() in column.lower() else f"{table} · {column}"


def fill_dates(query: str, start: date, end: date, backend) -> str:
    return query.replace("@START", backend.date_literal(start)).replace("@END", backend.date_literal(end))


# ---------------------------------------------------------------- storage --
# dashboards.json: {"dashboards": [{"id", "name", "charts": [chart, ...]}, ...]}. A chart is
# {"id", "cube", "title", "question", "query", "date_column", "chart_type", "x", "y", "color", "width"}.

_lock = threading.Lock()


def _read() -> dict:
    if config.DASHBOARDS_FILE.exists():
        return json.loads(config.DASHBOARDS_FILE.read_text(encoding="utf-8"))
    data = {"dashboards": []}
    if config.DASHBOARD_FILE.exists():  # one-time move of the single dashboard from before
        charts = json.loads(config.DASHBOARD_FILE.read_text(encoding="utf-8")).get("charts", [])
        for c in charts:
            c.setdefault("cube", config.SSAS_DATABASE or cubes.default())
            if c.get("chart_type") == "pie":
                c["chart_type"] = "donut"
        data["dashboards"].append({"id": "main", "name": "Main dashboard", "charts": charts})
        _write(data)
        config.DASHBOARD_FILE.replace(config.DASHBOARD_FILE.with_suffix(".json.bak"))
    return data


def _write(data: dict) -> None:
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = config.DASHBOARDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.DASHBOARDS_FILE)


def _change(fn) -> None:
    """Apply fn(data) to dashboards.json under a lock (several people may edit at once)."""
    with _lock:
        data = _read()
        fn(data)
        _write(data)


def list_dashboards() -> list[dict]:
    """All dashboards; creates an empty "Main dashboard" the first time."""
    data = _read()
    if not data["dashboards"]:
        create_dashboard("Main dashboard")
        data = _read()
    return data["dashboards"]


def get_dashboard(dashboard_id: str) -> dict | None:
    return next((d for d in _read()["dashboards"] if d["id"] == dashboard_id), None)


def create_dashboard(name: str) -> str:
    new_id = uuid.uuid4().hex[:8]
    _change(lambda data: data["dashboards"].append({"id": new_id, "name": name.strip() or "Dashboard",
                                                    "charts": []}))
    return new_id


def rename_dashboard(dashboard_id: str, name: str) -> None:
    def fn(data):
        for d in data["dashboards"]:
            if d["id"] == dashboard_id:
                d["name"] = name.strip() or d["name"]
    _change(fn)


def delete_dashboard(dashboard_id: str) -> None:
    _change(lambda data: data.update(dashboards=[d for d in data["dashboards"] if d["id"] != dashboard_id]))


def _charts_fn(dashboard_id: str, fn):
    def apply(data):
        for d in data["dashboards"]:
            if d["id"] == dashboard_id:
                d["charts"] = fn(d["charts"])
    _change(apply)


def get_chart(dashboard_id: str, chart_id: str) -> dict | None:
    d = get_dashboard(dashboard_id)
    return next((c for c in d["charts"] if c["id"] == chart_id), None) if d else None


def add_chart(dashboard_id: str, chart: dict) -> None:
    _charts_fn(dashboard_id, lambda charts: charts + [chart])


def update_chart(dashboard_id: str, chart: dict) -> None:
    _charts_fn(dashboard_id, lambda charts: [chart if c["id"] == chart["id"] else c for c in charts])


def delete_chart(dashboard_id: str, chart_id: str) -> None:
    _charts_fn(dashboard_id, lambda charts: [c for c in charts if c["id"] != chart_id])


def move_chart(dashboard_id: str, chart_id: str, step: int) -> None:
    def fn(charts):
        i = next(i for i, c in enumerate(charts) if c["id"] == chart_id)
        charts.insert(min(max(i + step, 0), len(charts) - 1), charts.pop(i))
        return charts
    _charts_fn(dashboard_id, fn)


def send_chart(chart: dict, to_dashboard_id: str, remove_from: str = "") -> None:
    """Copy a chart to another dashboard (or move it, if remove_from is its current dashboard)."""
    add_chart(to_dashboard_id, {**chart, "id": uuid.uuid4().hex[:8]})
    if remove_from:
        delete_chart(remove_from, chart["id"])


# ---------------------------------------------------------------- running --

def _run_one(chart: dict, start: date, end: date) -> dict:
    out = {"df": None, "prev": None, "error": "", "details": ""}
    try:
        backend = get_backend(chart.get("cube"))
        out["df"] = backend.run(fill_dates(chart["query"], start, end, backend), config.MAX_ROWS)
        if chart["chart_type"] == "kpi" and chart.get("date_column"):
            prev_start, prev_end = same_period_last_year(start, end)
            out["prev"] = backend.run(fill_dates(chart["query"], prev_start, prev_end, backend), config.MAX_ROWS)
    except Exception as exc:
        out["error"], out["details"] = friendly(exc), details(exc)
    return out


def run_all(charts: list[dict], start: date, end: date) -> dict[str, dict]:
    """Run every chart's query (each on its own cube) for the period.
    Returns {chart id: {df, prev, error, details}}."""
    workers = 4 if config.resolve_source() == "ssas" else 1  # the local database runs one query at a time
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {c["id"]: pool.submit(_run_one, c, start, end) for c in charts}
    return {cid: f.result() for cid, f in futures.items()}


# ---------------------------------------------------------------- building --

def _check_dates(query: str, date_column: str) -> None:
    if date_column and ("@START" not in query or "@END" not in query):
        raise ValueError("The query does not use the dashboard dates. Filter the period with @START and @END.")


def build_chart(cube: str, question: str, title: str, chart_type: str, width: str, date_column: str,
                start: date, end: date, base_query: str = "", base_spec: dict | None = None) -> dict:
    """Ask Claude for a dashboard query on a cube, test it for the period, and return the chart."""
    backend = get_backend(cube)
    if not backend.schema_file.exists():
        raise RuntimeError(f"The {cubes.label(cube)} cube isn't set up yet. An admin sets it up on the Cubes page.")
    schema = backend.schema_text()
    notes = glossary.notes_for_claude(cube)
    instructions = llm.dashboard_instructions(backend.language, date_column, chart_type == "kpi", base_query)
    args = (question, schema, notes, date.today().isoformat(), backend.language)

    def checked(q: str) -> str:
        _check_dates(q, date_column)
        return value_check.require_real_values(value_check.check(q, backend.language, schema, backend))

    checks = data_tools.checks(backend)
    query = llm.question_to_query(*args, instructions=instructions, **checks)["query"]
    try:
        query = checked(query)
        df = backend.run(fill_dates(query, start, end, backend), config.MAX_ROWS)
    except value_check.ValueProblem:
        raise  # only the person asking can say which real value they mean
    except Exception as first_error:  # one retry, with the error, like the chat
        query = checked(llm.question_to_query(*args, instructions=instructions, failed_query=query, **checks,
                                              error=str(first_error)[:1500])["query"])
        df = backend.run(fill_dates(query, start, end, backend), config.MAX_ROWS)

    if chart_type == "kpi":
        spec = {"chart_type": "kpi", "x": "", "y": [], "color": ""}
    elif base_spec and base_spec.get("x") in df.columns:
        spec = {**base_spec, "y": [y for y in base_spec.get("y", []) if y in df.columns]}
    elif chart_type == "auto" and not df.empty:
        spec = llm.describe_result(question, df)
    else:
        spec = charts.suggest(df)
    if chart_type not in ("auto", ""):
        spec["chart_type"] = chart_type
    spec = charts.fit(df, spec) if spec.get("chart_type") != "kpi" else spec
    return {"id": uuid.uuid4().hex[:8], "cube": cube, "title": title.strip() or spec.get("title") or question,
            "question": question, "query": query, "date_column": date_column,
            "chart_type": spec.get("chart_type", "table"), "x": spec.get("x", ""), "y": spec.get("y", []),
            "color": spec.get("color", ""), "width": width}


def starter_items(cube: str) -> list[dict]:
    """The cube's suggested charts from its setup, or the generic starter set."""
    import cube_setup
    return cube_setup.suggested_charts(cube) or STARTER


def create_starter(dashboard_id: str, cube: str, start: date, end: date, on_done=None) -> list[str]:
    """Build a cube's starter charts (in parallel) into a dashboard. Returns the titles that failed."""
    backend = get_backend(cube)
    date_col = default_date_column(date_columns(backend.schema_text()), cube)
    items = starter_items(cube)

    def build(item):
        kind = "donut" if item["chart_type"] == "pie" else item["chart_type"]
        return build_chart(cube, item["question"], item["title"], kind, item.get("width", "half"),
                           date_col, start, end)

    built, failed = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(build, item): item for item in items}
        for future in futures:
            item = futures[future]
            try:
                built[item["title"]] = future.result()
            except Exception:
                failed.append(item["title"])
            if on_done:
                on_done(item["title"])
    for item in items:
        if item["title"] in built:
            add_chart(dashboard_id, built[item["title"]])
    return failed
