"""Dashboards: named pages of charts saved as query plans that re-run for the period the user picks.
A dashboard can mix charts from different cubes, and a chart can combine several cubes (see
plans.py). Saved in dashboards.json; only admins change them (see dashboard_view.py). Claude is
only used when a chart is created or its question changes - refreshing just re-runs the saved plans."""
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

import answering
import charts
import config
import cubes
import data_layer
import dynamic_chart
import glossary
import llm
import periods
import plans
import usage
from backends import get_backend
from errors import details, friendly

TYPE_LABELS = {"auto": "Best fit (automatic)", "kpi": "Headline number", **charts.TYPE_LABELS,
               "custom": "Custom (describe it in words)"}
AUTO_DATE = "auto"  # a chart on several cubes: each cube filters on its own main date

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


# ---------------------------------------------------------------- date columns --

def date_columns(schema_text: str) -> list[str]:
    """Day-level date columns in the schema, written the way a query uses them."""
    cols = re.findall(r"^- ('[^']+'\[[^\]]+\]) \(Date/time\)", schema_text, flags=re.MULTILINE)
    cols += re.findall(r'^- ("[^"]+") \((?:DATE|TIMESTAMP)', schema_text, flags=re.MULTILINE)
    return list(dict.fromkeys(cols))


def default_date_column(cols: list[str], cube: str = "") -> str:
    """The date the period applies to by default: the cube's agreed default date if the setup
    settled it, else the data layer's default date, else a column that looks like a booking/creation
    date, else the first one."""
    if not cube:  # all data: each cube's own main date
        return AUTO_DATE
    for row in glossary.load(cube)[0]:
        if row.get("Status") == "Agreed" and re.search(r"\bdates?\b", row["Term"], flags=re.IGNORECASE):
            found = [c for c in cols if c in row.get("Date to use", "") + row.get("Measure", "")]
            if found:
                return found[0]
    layer_default = data_layer.profile(cube).get("default_date")
    if layer_default in cols:
        return layer_default
    for c in cols:
        if re.search(r"create|booking", c, flags=re.IGNORECASE):
            return c
    return cols[0] if cols else ""


def date_label(col: str) -> str:
    """'Create Date'[Create Date] -> Create Date, 'Calendar'[Date] -> Calendar · Date."""
    if not col:
        return "All dates"
    if col == AUTO_DATE:
        return "Each cube's main date"
    m = re.match(r"'([^']+)'\[([^\]]+)\]", col)
    if not m:
        return col.strip('"')
    table, column = m.groups()
    return column if column.lower() in table.lower() or table.lower() in column.lower() else f"{table} · {column}"


def fill_dates(query: str, start: date, end: date, backend) -> str:
    return query.replace("@START", backend.date_literal(start)).replace("@END", backend.date_literal(end))


# ---------------------------------------------------------------- storage --
# dashboards.json: {"dashboards": [{"id", "name", "charts": [chart, ...]}, ...]}. A chart is
# {"id", "cube", "title", "question", "query", "plan", "date_column", "chart_type", "x", "y", "color",
#  "custom", "chart_request", "width"}: "cube" is the cube ("" when it combines several), "query"
# the plan as readable text, "plan" the steps (plans.py), "custom" a chart described in words.

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

def compares(chart: dict) -> bool:
    """Whether a chart shows the dashboard's comparison: a headline number, a table, or columns, bars
    or a line of one measure not split by a second breakdown (anything more gets too busy to read),
    whose dates follow the dashboard - unless an admin switched it off for this chart."""
    if chart.get("compare") is False or not chart.get("date_column"):
        return False
    kind = chart.get("chart_type")
    return kind in ("kpi", "table") or (kind in ("bar", "horizontal_bar", "line", "area")
                                        and len(chart.get("y") or []) <= 1 and not chart.get("color"))


def _run_one(chart: dict, start: date, end: date, compare: tuple[date, date] | None = None) -> dict:
    out = {"df": None, "prev": None, "error": "", "details": ""}
    try:
        plan = plans.Plan.from_chart(chart)
        out["df"] = plans.run(plan.with_dates(start, end))
        if compare and chart.get("compares", compares(chart)):
            out["prev"] = plans.run(plan.with_dates(*compare))
    except Exception as exc:
        out["error"], out["details"] = friendly(exc), details(exc)
    return out


def run_all(charts: list[dict], start: date, end: date, compare: tuple[date, date] | None = None) -> dict[str, dict]:
    """Run every chart's plan (each on its own cubes) for the period, and for the charts that show it
    (compares()) also for the comparison dates. Returns {chart id: {df, prev, error, details}}."""
    workers = 4 if config.resolve_source() == "ssas" else 1  # the local database runs one query at a time
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {c["id"]: pool.submit(_run_one, c, start, end, compare) for c in charts}
    return {cid: f.result() for cid, f in futures.items()}


def run_key(chart: dict) -> tuple:
    """What a chart's numbers depend on (for caching the results)."""
    return (chart["id"], json.dumps(plans.Plan.from_chart(chart).to_dict(), sort_keys=True),
            chart.get("date_column", ""), chart["chart_type"], compares(chart))


def chart_from_key(key: tuple) -> dict:
    chart_id, plan, date_column, chart_type, compared = key
    return {"id": chart_id, "plan": json.loads(plan), "date_column": date_column, "chart_type": chart_type,
            "compares": compared}


# ---------------------------------------------------------------- building --

def build_chart(cube: str, question: str, title: str, chart_type: str, width: str, date_column: str,
                start: date, end: date, base_query: str = "", base_spec: dict | None = None,
                chart_request: str = "") -> dict:
    """Ask Claude for a dashboard plan (on one cube, or "" = any cubes), test it for the period, and
    return the chart. chart_request = the user's own description of the chart (a custom chart).
    Its Claude calls are recorded in usage as one "dashboard_chart"."""
    with usage.track("dashboard_chart", question):
        return _build_chart(cube, question, title, chart_type, width, date_column, start, end, base_query,
                            base_spec, chart_request)


def build_many(jobs: dict, start: date, end: date, workers: int = 4):
    """Several charts prepared at the same time (each job = build_chart's arguments except the period).
    Yields (key, chart, None) or (key, None, exception) as each one is ready, so one that fails
    doesn't stop the others."""
    if not jobs:
        return
    with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
        futures = {pool.submit(build_chart, start=start, end=end, **job): key for key, job in jobs.items()}
        for future in as_completed(futures):
            try:
                yield futures[future], future.result(), None
            except Exception as exc:
                yield futures[future], None, exc


def _build_chart(cube, question, title, chart_type, width, date_column, start, end, base_query, base_spec,
                 chart_request) -> dict:
    ok, why = answering.ready(cube)
    if not ok:
        raise RuntimeError(why)
    language = get_backend(answering.cubes_in(cube)[0]).language
    instructions = llm.dashboard_instructions(language, date_column, chart_type == "kpi", base_query)
    outcome = answering.require_values(answering.answer(
        question, cube, instructions=instructions, period=(start, end), needs_dates=bool(date_column)))
    if outcome.kind != "data":
        raise RuntimeError("Claude didn't write a query for this chart. Try rephrasing the question.")
    df, plan = outcome.df, outcome.plan

    context = {"query": plan.text(), "measures": data_layer.measure_notes(plan.cubes, plan.text())}
    if chart_type == "kpi":  # Claude still picks how the number is written (AED 4.5M, 12.3%...)
        style = llm.describe_result(question, df, **context).get("style", {}) if not df.empty else {}
        spec = {"chart_type": "kpi", "x": "", "y": [], "color": "", "style": style}
    elif (chart_type in ("custom", "auto") and base_spec and base_spec.get("custom")
          and chart_request in ("", base_spec.get("chart_request", ""))
          and dynamic_chart.columns_used(base_spec["custom"]) <= set(map(str, df.columns))):
        spec = dict(base_spec)  # the chart drawn in Chat, as it was
    elif chart_type == "custom" or chart_request:
        spec = llm.describe_result(question, df, chart_request=chart_request or question, **context)
    elif base_spec and (base_spec.get("x") in df.columns or base_spec.get("custom")):
        spec = {**base_spec, "y": [y for y in base_spec.get("y", []) if y in df.columns]}
    elif not df.empty:  # Claude picks the chart (unless one was chosen) and formats it for the data
        asked = question if chart_type in ("auto", "") else f"{question} (draw it as: {TYPE_LABELS[chart_type]})"
        spec = llm.describe_result(asked, df, **context)
    else:
        spec = charts.suggest(df)
    if chart_type not in ("auto", "", "custom"):
        spec["chart_type"] = chart_type
    spec = charts.fit(df, spec) if spec.get("chart_type") != "kpi" else spec
    title = title.strip() or spec.get("title") or question
    chart = {"id": uuid.uuid4().hex[:8], "cube": plan.cubes[0] if len(plan.cubes) == 1 else "",
             "title": periods.without_dates(title) if date_column else title, "question": question,
             "query": plan.text(), "plan": plan.to_dict(), "date_column": date_column,
             "chart_type": spec.get("chart_type", "table"), "x": spec.get("x", ""), "y": spec.get("y", []),
             "color": spec.get("color", ""), "style": spec.get("style", {}), "width": width}
    if spec.get("chart_type") == "custom":
        chart.update(custom=spec["custom"], chart_request=spec.get("chart_request") or chart_request)
    return chart


def restyle_chart(chart: dict, chart_request: str, start: date, end: date) -> dict:
    """The same numbers drawn as the user describes (no new query)."""
    with usage.track("chart_restyle", chart.get("title", "")):
        return _restyle_chart(chart, chart_request, start, end)


def _restyle_chart(chart: dict, chart_request: str, start: date, end: date) -> dict:
    plan = plans.Plan.from_chart(chart)
    df = plans.run(plan.with_dates(start, end))
    spec = llm.describe_result(chart["question"], df, chart_request=chart_request, query=plan.text(),
                               measures=data_layer.measure_notes(plan.cubes, plan.text()))
    chart = {k: v for k, v in chart.items() if k not in ("custom", "chart_request")}
    chart.update(chart_type=spec.get("chart_type", "table"), x=spec.get("x", ""), y=spec.get("y", []),
                 color=spec.get("color", ""), style=spec.get("style", {}))
    if spec.get("chart_type") == "custom":
        chart.update(custom=spec["custom"], chart_request=chart_request)
    return chart


def starter_items(cube: str) -> list[dict]:
    """Suggested charts: the cube's from its setup, or the generic starter set."""
    import cube_setup
    return (cube_setup.suggested_charts(cube) if cube else []) or STARTER


def create_starter(dashboard_id: str, cube: str, start: date, end: date, on_done=None) -> list[str]:
    """Build a cube's starter charts (in parallel) into a dashboard. Returns the titles that failed."""
    date_col = default_date_column(date_columns(get_backend(cube).schema_text()), cube) if cube else AUTO_DATE
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
