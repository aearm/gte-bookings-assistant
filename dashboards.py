"""The shared dashboard: charts saved as queries that re-run for the period the user picks.
Saved in dashboard.json; only admins change it (see views/dashboard.py). Claude is only used
when a chart is created or its question changes - refreshing just re-runs the saved queries."""
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd

import config
import data_tools
import glossary
import llm
import value_check
from backends import get_backend
from errors import details, friendly

TYPE_LABELS = {"auto": "Let Claude choose", "kpi": "Headline number", "bar": "Bar",
               "horizontal_bar": "Horizontal bar (rankings)", "line": "Line (trend)", "area": "Area",
               "pie": "Donut (parts of a whole)", "table": "Table"}
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
    {"title": "Bookings by sale channel", "question": "Number of bookings by sale channel", "chart_type": "pie"},
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


def default_date_column(cols: list[str]) -> str:
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

def load() -> list[dict]:
    if not config.DASHBOARD_FILE.exists():
        return []
    return json.loads(config.DASHBOARD_FILE.read_text(encoding="utf-8")).get("charts", [])


def save(charts: list[dict]) -> None:
    data = {"updated": datetime.now().isoformat(timespec="seconds"), "charts": charts}
    tmp = config.DASHBOARD_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.DASHBOARD_FILE)


def get(chart_id: str) -> dict | None:
    return next((c for c in load() if c["id"] == chart_id), None)


def add(chart: dict) -> None:
    save(load() + [chart])


def update(chart: dict) -> None:
    save([chart if c["id"] == chart["id"] else c for c in load()])


def delete(chart_id: str) -> None:
    save([c for c in load() if c["id"] != chart_id])


def move(chart_id: str, step: int) -> None:
    charts = load()
    i = next(i for i, c in enumerate(charts) if c["id"] == chart_id)
    j = min(max(i + step, 0), len(charts) - 1)
    charts.insert(j, charts.pop(i))
    save(charts)


# ---------------------------------------------------------------- running --

def _run_one(backend, chart: dict, start: date, end: date) -> dict:
    out = {"df": None, "prev": None, "error": "", "details": ""}
    try:
        out["df"] = backend.run(fill_dates(chart["query"], start, end, backend), config.MAX_ROWS)
        if chart["chart_type"] == "kpi" and chart.get("date_column"):
            prev_start, prev_end = same_period_last_year(start, end)
            out["prev"] = backend.run(fill_dates(chart["query"], prev_start, prev_end, backend), config.MAX_ROWS)
    except Exception as exc:
        out["error"], out["details"] = friendly(exc), details(exc)
    return out


def run_all(charts: list[dict], start: date, end: date) -> dict[str, dict]:
    """Run every chart's query for the period. Returns {chart id: {df, prev, error, details}}."""
    backend = get_backend()
    workers = 4 if backend.key == "ssas" else 1  # the local database works one query at a time
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {c["id"]: pool.submit(_run_one, backend, c, start, end) for c in charts}
    return {cid: f.result() for cid, f in futures.items()}


# ---------------------------------------------------------------- building --

def guess_axes(df: pd.DataFrame) -> dict:
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    labels = [c for c in df.columns if c not in numeric]
    x = labels[0] if labels else df.columns[0]
    return {"x": x, "y": [c for c in numeric if c != x], "color": ""}


def _check_dates(query: str, date_column: str) -> None:
    if date_column and ("@START" not in query or "@END" not in query):
        raise ValueError("The query does not use the dashboard dates. Filter the period with @START and @END.")


def build_chart(question: str, title: str, chart_type: str, width: str, date_column: str,
                start: date, end: date, base_query: str = "", base_spec: dict | None = None) -> dict:
    """Ask Claude for a dashboard query, test it for the period, and return the chart to save."""
    backend = get_backend()
    if not backend.schema_file.exists():
        raise RuntimeError("Click Refresh data structure on the Chat page first.")
    schema = backend.schema_file.read_text(encoding="utf-8")
    notes = glossary.notes_for_claude()
    instructions = llm.dashboard_instructions(backend.language, date_column, chart_type == "kpi", base_query)
    args = (question, schema, notes, date.today().isoformat(), backend.language)

    def checked(q: str) -> str:
        _check_dates(q, date_column)
        return value_check.require_real_values(value_check.check(q, backend.language, schema, backend))

    checks = dict(tools=data_tools.TOOLS, run_tool=data_tools.run)
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
        spec = guess_axes(df)
    if chart_type != "auto":
        spec["chart_type"] = chart_type
    spec.setdefault("chart_type", "table")
    return {"id": uuid.uuid4().hex[:8], "title": title.strip() or spec.get("title") or question,
            "question": question, "query": query, "date_column": date_column,
            "chart_type": spec["chart_type"], "x": spec.get("x", ""), "y": spec.get("y", []),
            "color": spec.get("color", ""), "width": width}


def create_starter(start: date, end: date, on_done=None) -> list[str]:
    """Build the starter charts (in parallel) and save them. Returns the titles that failed."""
    backend = get_backend()
    cols = date_columns(backend.schema_file.read_text(encoding="utf-8")) if backend.schema_file.exists() else []
    date_col = default_date_column(cols)

    def build(item):
        return build_chart(item["question"], item["title"], item["chart_type"], item.get("width", "half"),
                           date_col, start, end)

    built, failed = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(build, item): item for item in STARTER}
        for future in futures:
            item = futures[future]
            try:
                built[item["title"]] = future.result()
            except Exception:
                failed.append(item["title"])
            if on_done:
                on_done(item["title"])
    save(load() + [built[i["title"]] for i in STARTER if i["title"] in built])
    return failed
