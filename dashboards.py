"""Dashboards: named pages of charts saved as query plans that re-run for the period the user picks.
A dashboard can mix charts from different cubes, and a chart can combine several cubes (see
plans.py). Saved in dashboards.json; only admins change them (see dashboard_view.py). Claude is
only used when a chart is created or its question changes - refreshing just re-runs the saved plans."""
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import pandas as pd

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
import rewrite
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


# ---------------------------------------------------------------- dashboard filters --
# A dashboard can have filters above its charts (a client, a market): {"key", "label", "placeholder" ("@F_CLIENT"),
# "options": {"cube", "query" (with @START / @END), "value" (the column whose value fills the placeholder),
# "label" ("{Cliente} - {Code}"), "title_case"}}. Its charts' queries hold the placeholder; the value picked
# replaces it (as a quoted text) before they run, so every value has saved numbers of its own. The values to
# pick from are what the options query returns for the last year, biggest first; the first is the default.

FILTER_MARK = re.compile(r"@F_[A-Z0-9_]+")
OPTIONS_DAYS = 365
OPTIONS_HOURS = 6
_options_cache: dict[tuple, tuple[float, list[dict]]] = {}


class _Blank(dict):
    def __missing__(self, key):
        return ""


def _literal(value: str, language: str) -> str:
    """A value as quoted text in a query: "..." in DAX, '...' in SQL (quotes inside doubled)."""
    if language == "DAX":
        return '"' + value.replace('"', '""') + '"'
    return "'" + value.replace("'", "''") + "'"


def _option_list(df: pd.DataFrame, o: dict) -> list[dict]:
    seen, out = set(), []
    for row in df.to_dict("records"):
        value = row.get(o["value"])
        if value is None or pd.isna(value) or not str(value).strip():
            continue
        value = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value).strip()
        if value in seen:
            continue
        seen.add(value)
        shown = _Blank({k: ("" if v is None or (not isinstance(v, str) and pd.isna(v)) else v) for k, v in row.items()})
        label = (o.get("label") or "{" + o["value"] + "}").format_map(shown).strip(" -")
        out.append({"value": value, "label": (label.title() if o.get("title_case") else label) or value})
    return out


def filter_options(board: dict, today: date | None = None) -> list[dict]:
    """Each filter of a dashboard with the values to pick from ({"value", "label"}, biggest first) and its
    default (the first). Asked from the cube at most every few hours."""
    today = today or _today()
    out = []
    for f in board.get("filters") or []:
        o, error = f.get("options") or {}, ""
        key = (board["id"], f["key"], today.isoformat(), o.get("query", ""))
        hit = _options_cache.get(key)
        if hit and time.time() - hit[0] < OPTIONS_HOURS * 3600:
            options = hit[1]
        else:
            try:
                plan = plans.Plan([plans.Step("options", o["cube"], o["query"])])
                df = plans.run(plan.with_dates(today - timedelta(days=OPTIONS_DAYS), today + timedelta(days=1)), 50_000)
                options = _option_list(df, o)
                _options_cache[key] = (time.time(), options)
            except Exception as exc:
                options, error = [], friendly(exc)
        out.append({"key": f["key"], "label": f.get("label") or f["key"], "options": options,
                    "default": options[0]["value"] if options else "", "error": error})
    return out


def filter_values(board: dict, asked: dict[str, str] | None = None) -> dict[str, str]:
    """The value of each filter: the one asked for when it is in the list, else the default."""
    chosen = {}
    for f in filter_options(board):
        values = [o["value"] for o in f["options"]]
        want = (asked or {}).get(f["key"], "")
        chosen[f["key"]] = want if want and (want in values or not values) else (values[0] if values else want)
    return chosen


def _fill_marks(text: str, marks: dict[str, str], language: str) -> str:
    for mark, value in sorted(marks.items(), key=lambda kv: -len(kv[0])):  # longest first: @F_A before @F_
        text = text.replace(mark, _literal(value, language))
    return text


def apply_filters(board: dict, charts_: list[dict], asked: dict[str, str] | None = None) -> list[dict]:
    """The dashboard's charts with its filters' values in their queries, as they run (the default values for
    a filter not asked for)."""
    defs = board.get("filters") or []
    if not defs:
        return charts_
    values = filter_values(board, asked)
    marks = {f["placeholder"]: values.get(f["key"], "") for f in defs}
    out = []
    for c in charts_:
        plan = c.get("plan")
        if not plan or not any(m in json.dumps(plan) for m in marks):
            out.append(c)
            continue
        steps = [{**s, "query": _fill_marks(s["query"], marks, get_backend(s["cube"]).language)} for s in plan["steps"]]
        out.append({**c, "plan": {**plan, "steps": steps,
                                  "combine_sql": _fill_marks(plan.get("combine_sql") or "", marks, "SQL")}})
    return out


def _plan_of(chart: dict) -> plans.Plan:
    """The chart's plan, ready to run. A chart run on its own (edited, restyled, in the previous app) gets its
    dashboard's filters at their default values; a chart sent to a dashboard without the filter it needs
    says so."""
    plan = plans.Plan.from_chart(chart)
    if not FILTER_MARK.search(json.dumps(plan.to_dict())):
        return plan
    board = next((b for b in _read()["dashboards"] if any(c.get("id") == chart.get("id") for c in b["charts"])), None)
    if board and board.get("filters"):
        plan = plans.Plan.from_chart(apply_filters(board, [chart])[0])
    missing = sorted(set(FILTER_MARK.findall(json.dumps(plan.to_dict()))))
    if missing:
        raise RuntimeError("This chart needs a filter its dashboard doesn't have ("
                           + ", ".join(m.removeprefix("@F_").lower() for m in missing)
                           + "). It works on the dashboard it came from.")
    return plan


# ---------------------------------------------------------------- dashboards the app ships with --
# builtin_dashboards.py: added to dashboards.json as soon as the app runs on the live cubes, first in the list
# (the overview then opens the app); until the cube server is set up they say so (setup_problem). "builtin" in dashboards.json notes the version added; a newer version
# replaces the dashboard's charts and filters (its name stays), and one deleted is not added again.

_builtin_checked = {"time": 0.0}


def setup_problem() -> str:
    """Why a dashboard can't show its numbers yet (live mode without the cube server set up), else ""."""
    if config.resolve_source() != "ssas":
        return ""
    if not config.SSAS_SERVER:
        return "The cube server isn't set up yet: an admin enters it on the Settings page, then the numbers appear."
    if config.SSAS_USERNAME:
        import ssas
        if not ssas.get_password():
            return ("The cube server's password isn't saved yet: an admin enters it on the Settings page, then the "
                    "numbers appear.")
    return ""


def ensure_builtin(force: bool = False) -> None:
    if not config.BUILTIN_DASHBOARDS or (not force and time.time() - _builtin_checked["time"] < 60):
        return
    _builtin_checked["time"] = time.time()
    if config.resolve_source() != "ssas":  # they are built on the live cubes: not for local files
        return
    import builtin_dashboards
    shipped = builtin_dashboards.all_dashboards()
    seen = _read().get("builtin") or {}
    if all(seen.get(b["id"]) == b["builtin"] for b in shipped):
        return

    def fn(data):
        noted = data.setdefault("builtin", {})
        have = {d["id"]: d for d in data["dashboards"]}
        added = []
        for b in shipped:
            if noted.get(b["id"]) == b["builtin"]:
                continue
            if b["id"] in have:
                have[b["id"]].update(charts=b["charts"], filters=b["filters"], builtin=b["builtin"])
            elif b["id"] not in noted:
                added.append(b)
            noted[b["id"]] = b["builtin"]
        boards, order = added + data["dashboards"], [b["id"] for b in shipped]
        first = sorted((d for d in boards if d["id"] in order), key=lambda d: order.index(d["id"]))
        data["dashboards"] = first + [d for d in boards if d["id"] not in order]  # the built-in ones first, in order
    _change(fn)


# ---------------------------------------------------------------- storage --
# dashboards.json: {"dashboards": [{"id", "name", "charts": [chart, ...]}, ...]}. A chart is
# {"id", "cube", "title", "question", "query", "plan", "date_column", "chart_type", "x", "y", "color",
#  "custom", "chart_request", "width", "period_mode", "periods"}: "cube" is the cube ("" when it combines
# several), "query" the plan as readable text, "plan" the steps (plans.py), "custom" a chart described
# in words, "period_mode" and "periods" whose dates it shows (see "chart periods" below; a chart without
# them follows the dashboard's period, like every chart from before).

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
    ensure_builtin()
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

def headline_change(chart: dict, value, before) -> tuple[float | None, str]:
    """A headline number's change against the comparison: relative ("+12.5%"), or for a percentage (a margin,
    a rate) the difference in percentage points ("+3.2 pts": 5.7% -> 8.9% is not "+57%")."""
    if value is None or before is None or pd.isna(value) or pd.isna(before):
        return None, ""
    if any((f.get("d3_format") or "").endswith("%") for f in (chart.get("style") or {}).get("formats", [])):
        return value - before, f"{(value - before) * 100:+.1f} pts"
    if not before:
        return None, ""
    change = (value - before) / abs(before)
    return change, f"{change:+.1%}"


def compares(chart: dict) -> bool:
    """Whether a chart shows the dashboard's comparison: a headline number, a table, or columns, bars
    or a line of one measure not split by a second breakdown (anything more gets too busy to read),
    whose dates follow the dashboard - unless an admin switched it off for this chart. A chart with
    periods of its own never does (it compares its own periods, if it has several)."""
    if chart.get("compare") is False or not chart.get("date_column") or period_mode(chart) != "dashboard":
        return False
    kind = chart.get("chart_type")
    return kind in ("kpi", "table") or (kind in ("bar", "horizontal_bar", "line", "area")
                                        and len(chart.get("y") or []) <= 1 and not chart.get("color"))


def runnable(chart: dict, start: date, end: date) -> plans.Plan:
    """The chart's plan with its dates filled in: its own periods', or else the dashboard's period."""
    plan = _plan_of(chart)
    own = own_dates(chart)
    return plan.with_periods(own) if own is not None else plan.with_dates(start, end)


def _run_one(chart: dict, start: date, end: date, compare: tuple[date, date] | None = None) -> dict:
    out = {"df": None, "prev": None, "error": "", "details": ""}
    try:
        if compare and chart.get("compares", compares(chart)):
            previous = _plan_of(chart).with_dates(*compare)
            if config.resolve_source() == "ssas":  # both periods at once (the local database runs one query at a time)
                with ThreadPoolExecutor(max_workers=2) as pair:
                    now, before = pair.submit(plans.run, runnable(chart, start, end)), pair.submit(plans.run, previous)
                    out["df"], out["prev"] = now.result(), before.result()
            else:
                out["df"], out["prev"] = plans.run(runnable(chart, start, end)), plans.run(previous)
        else:
            out["df"] = plans.run(runnable(chart, start, end))
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


# ---------------------------------------------------------------- saved results --
# A dashboard opens with the numbers each chart had the last time it ran (data/dashboard_results/), so
# it never waits for the cubes just to show them again. A chart is run again - in the background, the
# page updating itself when it's done - only when one of its cubes has new data since (the server's last
# update time) or its numbers are a day old. A chart never run for this period runs straight away.

MAX_AGE_HOURS = 24
_background = ThreadPoolExecutor(max_workers=2)
_running: dict[str, object] = {}   # saved-result key -> its background run (a Future or a _Refresh)
_failed: dict[str, float] = {}     # key -> when its last background run failed (not retried for 5 minutes)
_saved_lock = threading.Lock()


def _saved_dir():
    return config.DATA_DIR / "dashboard_results"


def saved_key(chart: dict, start: date, end: date, compare: tuple[date, date] | None) -> str:
    """Where a chart's numbers for a period are saved. A chart with its own periods is saved under its own
    dates, so changing the dashboard's period or comparison doesn't run it again."""
    import hashlib
    own = own_dates(chart)
    if own is not None:
        text = json.dumps([run_key(chart), "own", [[str(s), str(e)] for s, e in own]])
    else:
        text = json.dumps([run_key(chart), str(start), str(end), [str(d) for d in compare] if compare else None])
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def _load_saved(key: str) -> dict | None:
    import pickle
    path = _saved_dir() / f"{key}.pkl"
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ImportError):
        return None


def _save(key: str, result: dict, as_of: dict[str, str], saved: str = "") -> None:
    """saved = when the numbers were read (now, unless they came from an earlier chat answer)."""
    import os
    import pickle
    folder = _saved_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{key}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as f:
        pickle.dump({"result": result, "as_of": as_of, "saved": saved or datetime.now().isoformat()}, f)
    os.replace(tmp, folder / f"{key}.pkl")


_computing: dict[str, threading.Event] = {}  # saved-result key -> set when the chart being run is saved
_computing_lock = threading.Lock()


def _run_and_save(chart: dict, start: date, end: date, compare, as_of: dict[str, str]) -> dict:
    """Run a chart and save its numbers - once: when the same chart for the same dates is already
    running (the night pre-run, another visitor), wait for that run and use its numbers. Each chart on
    its own, so nobody waits for charts they aren't looking at."""
    key = saved_key(chart, start, end, compare)
    with _computing_lock:
        running = _computing.get(key)
        if running is None:
            _computing[key] = threading.Event()
    if running is not None:
        running.wait(timeout=900)
        saved = _load_saved(key)
        if saved is not None:
            return saved["result"]
        return _run_one(chart, start, end, compare)  # that run failed: show this one's own error
    try:
        result = _run_one(chart, start, end, compare)
        if result["error"]:
            _failed[key] = datetime.now().timestamp()
        else:
            _save(key, result, {cb: as_of.get(cb, "") for cb in plans.Plan.from_chart(chart).cubes})
        return result
    finally:
        with _computing_lock:
            _computing.pop(key).set()


class _Refresh:
    """A chart being brought up to date in its own Python process (see _start_refresh)."""

    def __init__(self, proc, key: str, started: str):
        self.proc, self.key, self.started, self.checked = proc, key, started, False

    def done(self) -> bool:
        if self.proc.poll() is None:
            return False
        if not self.checked:  # ended without saving newer numbers: failed (not retried for 5 minutes)
            self.checked = True
            saved = _load_saved(self.key)
            if not saved or saved["saved"] < self.started:
                _failed[self.key] = datetime.now().timestamp()
        return True

    def result(self, timeout: float | None = None) -> None:
        self.proc.wait(timeout)


def _start_refresh(chart: dict, start: date, end: date, compare, as_of: dict[str, str]):
    """Runs a chart again in the background. With the cubes on the server, in a process of its own:
    reading thousands of rows through the .NET connector in a thread of the app slows every page of
    the app many times over (each row hands Python's lock back and forth), and the pages slow it down."""
    if config.resolve_source() != "ssas":
        return _background.submit(_run_and_save, chart, start, end, compare, as_of)
    import subprocess
    import sys
    from pathlib import Path
    key = saved_key(chart, start, end, compare)
    folder = _saved_dir()
    folder.mkdir(parents=True, exist_ok=True)
    job = folder / f"{key}.job.json"
    job.write_text(json.dumps({"chart": chart, "start": start.isoformat(), "end": end.isoformat(),
                               "compare": [d.isoformat() for d in compare] if compare else None,
                               "as_of": as_of}), encoding="utf-8")
    started = datetime.now().isoformat()
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "refresh", str(job)],
                            cwd=str(config.BASE_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return _Refresh(proc, key, started)


def results_for(charts_: list[dict], start: date, end: date, compare: tuple[date, date] | None,
                as_of: dict[str, str], force: bool = False) -> tuple[dict[str, dict], list[str]]:
    """Every chart's numbers: saved ones at once, missing ones run now (in parallel). Returns (results by
    chart id, ids of charts being brought up to date in the background). force = run everything now."""
    results, missing, stale = {}, [], []
    now = datetime.now()
    for c in charts_:
        saved = None if force else _load_saved(saved_key(c, start, end, compare))
        if saved is None:
            missing.append(c)
            continue
        results[c["id"]] = saved["result"]
        newer = any(as_of.get(cb) and saved["as_of"].get(cb) != as_of[cb] for cb in plans.Plan.from_chart(c).cubes)
        old = (now - datetime.fromisoformat(saved["saved"])).total_seconds() > MAX_AGE_HOURS * 3600
        if newer or old:
            stale.append(c)
    if missing:
        workers = 4 if config.resolve_source() == "ssas" else 1
        with ThreadPoolExecutor(max_workers=min(workers, len(missing))) as pool:
            futures = {c["id"]: pool.submit(_run_and_save, c, start, end, compare, as_of) for c in missing}
        results.update({cid: f.result() for cid, f in futures.items()})
    updating = []
    with _saved_lock:
        for c in stale:
            key = saved_key(c, start, end, compare)
            if key in _running and not _running[key].done():
                updating.append(key)  # already on its way
                continue
            if now.timestamp() - _failed.get(key, 0) < 300:
                continue  # failed a moment ago: keep showing the saved numbers
            _running[key] = _start_refresh(c, start, end, compare, as_of)
            updating.append(key)
    return results, updating


def still_updating(keys: list[str]) -> bool:
    return any(k in _running and not _running[k].done() for k in keys)


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
    return restyled(chart, plans.run(runnable(chart, start, end)), chart_request)


def restyled(chart: dict, df, chart_request: str) -> dict:
    """The chart drawn as described, for numbers already at hand (one Claude call, no query)."""
    plan = plans.Plan.from_chart(chart)
    spec = llm.describe_result(chart["question"], df, chart_request=chart_request, query=plan.text(),
                               measures=data_layer.measure_notes(plan.cubes, plan.text()))
    chart = {k: v for k, v in chart.items() if k not in ("custom", "chart_request")}
    chart.update(chart_type=spec.get("chart_type", "table"), x=spec.get("x", ""), y=spec.get("y", []),
                 color=spec.get("color", ""), style=spec.get("style", {}))
    if spec.get("chart_type") == "custom":
        chart.update(custom=spec["custom"], chart_request=chart_request)
    return chart


# ---------------------------------------------------------------- chart periods --
# A chart shows the dashboard's period (the default, and every chart from before) or periods of its own:
# - "own": periods kept in the grammar of rewrite.py ("yesterday" = day -1), worked out again from today's
#   date whenever the chart runs, so "yesterday vs the day before" moves forward every day;
# - "fixed": the exact dates it was added with, never moving (no periods at all: all dates).
# chart["periods"] = [{"phrase", "first", "last", "to_date", "start", "end"}] (rewrite.record; end
# exclusive). The plan has placeholders for them: @P1_START, @P1_LAST and @P1_END (the first period's
# first day, last day and the day after it), @P2_... for the second; a chart that follows the dashboard
# has @START and @END (and @LAST). A chart with periods of its own ignores the dashboard's period and its
# Compare: when it has several periods, it compares them itself.

PERIOD_MODES = {"dashboard": "Follow the dashboard", "own": "Own period", "fixed": "Fixed dates"}


class NeedsClaude(Exception):
    """This can't be done in code: Claude has to write the chart's plan again (build_chart)."""


def _today() -> date:
    return date.today()


def period_mode(chart: dict) -> str:
    return chart.get("period_mode") if chart.get("period_mode") in ("own", "fixed") else "dashboard"


def own_dates(chart: dict, today: date | None = None) -> list[tuple[date, date]] | None:
    """(start, end exclusive) of each of a chart's own periods as of today; None when it follows the dashboard."""
    mode = period_mode(chart)
    if mode == "dashboard":
        return None
    if mode == "fixed":
        return _spans(chart.get("periods") or [])
    today = today or _today()
    return [_resolved(item, today) for item in chart.get("periods") or []]


def _resolved(item: dict, today: date) -> tuple[date, date]:
    """A period worked out for today; the dates it had when it was added if that's impossible (week 53)."""
    try:
        p = rewrite.resolve(item, today)
        return p.start, p.end
    except (ValueError, KeyError, TypeError):
        return date.fromisoformat(item["start"]), date.fromisoformat(item["end"])


def _spans(records: list[dict]) -> list[tuple[date, date]]:
    return [(date.fromisoformat(p["start"]), date.fromisoformat(p["end"])) for p in records]


def _short_dates(start: date, end: date, year: bool = True) -> str:
    """'15 Oct', '14–15 Oct', '28 Sep – 3 Oct', '28 Dec 2025 – 3 Jan 2026' (with the year if asked)."""
    last = end - timedelta(days=1)
    tail = f" {last.year}" if year else ""
    if start == last:
        return f"{start.day} {start:%b}{tail}"
    if (start.year, start.month) == (last.year, last.month):
        return f"{start.day}–{last.day} {last:%b}{tail}"
    if start.year == last.year:
        return f"{start.day} {start:%b} – {last.day} {last:%b}{tail}"
    return f"{start.day} {start:%b %Y} – {last.day} {last:%b %Y}"


def _dates_text(spans: list[tuple[date, date]], year: bool) -> str:
    """The dates of a chart's periods: one span when they follow each other ('14–15 Oct'), else each."""
    ordered = sorted(spans)
    if all(a[1] == b[0] for a, b in zip(ordered, ordered[1:])):
        return _short_dates(ordered[0][0], ordered[-1][1], year)
    return " vs ".join(_short_dates(s, e, year) for s, e in spans)


def period_text(chart: dict, today: date | None = None) -> str:
    """A chart's own dates in a few words, for its card: 'Own period: yesterday vs the day before
    (14–15 Oct)', 'Fixed: 14–15 Oct 2026', 'All dates'; "" for a chart that follows the dashboard."""
    mode, records = period_mode(chart), chart.get("periods") or []
    if mode == "dashboard":
        return ""
    if not records:
        return "All dates"
    today = today or _today()
    spans = own_dates(chart, today)
    if mode == "fixed":
        return f"Fixed: {_dates_text(spans, True)}"
    this_year = all(s.year == today.year == (e - timedelta(days=1)).year for s, e in spans)
    return f"Own period: {' vs '.join(p['phrase'] for p in records)} ({_dates_text(spans, not this_year)})"


# ---------------------------------------------------------------- from a chat answer --

def chart_from_answer(turn: dict, mode: str, title: str = "", chart_type: str = "", width: str = "",
                      date_column: str = "") -> dict:
    """A chat answer as a dashboard chart, made in code - no Claude call and no query: the chat's plan
    with its periods' dates replaced by placeholders, its chart as it was drawn in Chat, and its periods.
    turn = the answer: {"question", "plan", "spec", "df", "periods" (rewrite.record each)}. mode: "own"
    (its periods move forward with the days), "fixed" (the dates asked about; all dates when it named
    none) or "dashboard" (follows the dashboard's period: in code only for a question with one period).
    Raises NeedsClaude when that can't be done in code (then build_chart asks Claude for a plan)."""
    plan = plans.Plan.from_dict(turn["plan"])
    records = [dict(p) for p in turn.get("periods") or []]
    if mode == "own" and not records:
        raise NeedsClaude("The question names no period of its own.")
    if mode == "dashboard" and len(records) != 1:
        raise NeedsClaude("Only a question about one period can follow the dashboard's period as it is."
                          if records else "The question has no dates for the dashboard's period to replace.")
    spans = _spans(records)
    stems = ["@"] if mode == "dashboard" else [f"@P{i}_" for i in range(1, len(records) + 1)]
    try:
        if records:
            plan = plans.parametrize(plan, spans, stems)
        if mode != "fixed" and _named_after_dates(_names(turn), spans):
            raise plans.CannotParametrize("Its columns are named after the dates.")
        if mode == "dashboard" and not plans.filters_a_range(plan):
            raise plans.CannotParametrize("It filters single days, which can't stretch to the dashboard's period.")
    except plans.CannotParametrize as exc:
        if mode != "fixed":
            raise NeedsClaude(str(exc)) from exc
        plan = plans.Plan.from_dict(turn["plan"])  # fixed: the plan as asked already has its dates
    spec = _chat_spec(turn, chart_type)
    kind = spec["chart_type"]
    chart = {"id": uuid.uuid4().hex[:8], "cube": plan.cubes[0] if len(plan.cubes) == 1 else "",
             "title": _title_without_periods(title.strip() or spec.get("title") or turn["question"], records),
             "question": turn.get("standalone") or turn["question"], "query": plan.text(), "plan": plan.to_dict(),
             "date_column": "", "chart_type": kind,
             "x": spec.get("x", ""), "y": list(spec.get("y") or []), "color": spec.get("color", ""),
             "style": spec.get("style") or {}, "width": width or ("full" if kind in ("map", "custom") else "half"),
             "period_mode": mode, "periods": records}
    if records:  # the date its periods are on (a chart that follows the dashboard needs one to compare)
        chart["date_column"] = _filtered_date(plan, date_column) or (AUTO_DATE if mode == "dashboard" else "")
    if kind == "custom":
        chart.update(custom=spec["custom"], chart_request=spec.get("chart_request", ""))
    return chart


def _chat_spec(turn: dict, chart_type: str = "") -> dict:
    """The chart as drawn in Chat (type, columns, colours, one chart or panels, formats), or another type
    the admin picked for the same columns (fitted to the data when it's drawn)."""
    spec = {k: v for k, v in (turn.get("spec") or {}).items() if k not in ("summary", "note")}
    kind = {"pie": "donut"}.get(spec.get("chart_type") or "table", spec.get("chart_type") or "table")
    if chart_type and chart_type not in ("auto", kind):
        kind = chart_type
        spec.pop("custom", None)
    if kind == "custom" and not spec.get("custom"):
        raise NeedsClaude("A chart described in words needs Claude to draw it.")
    if kind == "kpi":
        spec.update(x="", y=[], color="")
    return {**spec, "chart_type": kind}


def _names(turn: dict) -> list[str]:
    df = turn.get("df")
    return [str(c) for c in (df.columns if df is not None else [])]


def _named_after_dates(names: list[str], spans: list[tuple[date, date]]) -> bool:
    """Whether a result's columns are named after the periods' days ("Bookings 15 Oct"): such names
    would no longer match the numbers once the periods move."""
    text = " | ".join(names).lower()
    if not text or not spans:
        return False
    days = [s + timedelta(days=i) for s, e in spans for i in range(min((e - s).days, 400))]
    for d in days:
        for form in (d.isoformat(), f"{d.day} {d:%b}", f"{d:%b} {d.day}", f"{d.day} {d:%B}", f"{d:%B} {d.day}",
                     f"{d.day}/{d.month}", f"{d:%d/%m}", f"{d:%b} {d.year}", f"{d:%B} {d.year}"):
            if re.search(rf"(?<![\w]){re.escape(form.lower())}(?![\w])", text):
                return True
    return False


_FILTERED = re.compile(r"('(?:[^']|'')+'\[[^\]]+\]|\b\w+\[[^\]]+\]|\"[^\"]+\")\s*(?:>=|<=|<>|=|<|>)\s*@(?:P\d+_)?(?:START|LAST|END)\b"
                       r"|DATESBETWEEN\s*\(\s*('(?:[^']|'')+'\[[^\]]+\]|\b\w+\[[^\]]+\])\s*,\s*@"
                       r"|(\"[^\"]+\")\s+BETWEEN\s+@", re.IGNORECASE)


def _filtered_date(plan: plans.Plan, fallback: str = "") -> str:
    """The date column the plan filters its periods on (for the card and the date picker): each cube's main
    date when it combines several cubes; fallback when it can't be told."""
    if len(plan.cubes) > 1:
        return AUTO_DATE
    for s in plan.steps:
        m = _FILTERED.search(s.query)
        if m:
            return next(g for g in m.groups() if g)
    return fallback


def _title_without_periods(title: str, records: list[dict]) -> str:
    """A title without the question's periods ("Bookings yesterday vs the day before by customer" ->
    "Bookings by customer"): the card says which dates the chart shows."""
    text = title
    for phrase in sorted((p.get("phrase", "").strip() for p in records), key=len, reverse=True):
        if phrase:
            text = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", "\x00", text, flags=re.IGNORECASE)
    joiner = r"\s*(?:,|vs\.?|versus|and|compared (?:with|to)|to)\s*"
    text = re.sub(rf"(?:\b(?:over|for|on|in|between|from|during)\s+)?\x00(?:{joiner}\x00)*", " ", text, flags=re.IGNORECASE)
    text = periods.without_dates(re.sub(r"\s{2,}", " ", text).strip())
    text = re.sub(r"(?:^|(?<=[\s,;:(]))(?:vs\.?|versus)\s*(?=$|[,;:)]|by\b|per\b)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,;:)])", r"\1", re.sub(r"\s{2,}", " ", text))
    return re.sub(r"[\s,;:\-–—·|]+$", "", text).strip() or title


def keep_answer_numbers(chart: dict, turn: dict, as_of: dict[str, str] | None = None,
                        period: tuple[date, date] | None = None, compare: tuple[date, date] | None = None) -> bool:
    """The chat's numbers saved as the chart's first ones, so the dashboard shows them at once without
    running anything - when they are what the chart shows now: its own periods as of today are the
    question's dates, or, for a chart that follows the dashboard, the dashboard's period (period) is the
    question's and nothing has to be compared. as_of = the cubes' last update times (see results_for)."""
    df = turn.get("df")
    if df is None:
        return False
    asked = _spans(turn.get("periods") or [])
    own = own_dates(chart)
    if own is not None:
        if own != asked:
            return False
        key = saved_key(chart, date.min, date.min, None)
    else:
        if not period or asked != [tuple(period)] or (compare and compares(chart)):
            return False
        key = saved_key(chart, period[0], period[1], compare)
    used = plans.Plan.from_chart(chart).cubes
    _save(key, {"df": df, "prev": None, "error": "", "details": ""}, {cb: (as_of or {}).get(cb, "") for cb in used},
          saved=turn.get("asked", ""))
    return True


def add_from_answer(dashboard_id: str, turn: dict, mode: str, as_of: dict[str, str] | None = None,
                    period: tuple[date, date] | None = None, compare: tuple[date, date] | None = None,
                    **look) -> dict:
    """chart_from_answer, added to the dashboard with the chat's numbers as its first ones. look = title,
    chart_type, width, date_column."""
    chart = chart_from_answer(turn, mode, **look)
    add_chart(dashboard_id, chart)
    keep_answer_numbers(chart, turn, as_of, period, compare)
    return chart


def period_choices(turn: dict, today: date | None = None) -> list[dict]:
    """How a chat answer can go on a dashboard, the suggested way first: [{"mode", "label", "instant"}].
    instant = made in code at once (chart_from_answer); otherwise Claude prepares it (build_chart)."""
    records = turn.get("periods") or []
    in_code = {}
    for mode in ("own", "dashboard"):
        try:
            chart_from_answer(turn, mode)
            in_code[mode] = True
        except NeedsClaude:
            in_code[mode] = False
    follow = {"mode": "dashboard", "label": "Follow the dashboard's period", "instant": in_code["dashboard"]}
    if not records:
        return [follow, {"mode": "fixed", "label": "All dates, as in Chat", "instant": True}]
    shown = {"periods": records}
    fixed = {"mode": "fixed", "label": "Fixed dates: " + _dates_text(_spans(records), True), "instant": True}
    if not in_code["own"]:
        return [follow, fixed]
    own = {"mode": "own", "label": period_text({**shown, "period_mode": "own"}, today), "instant": True}
    return [own, fixed, follow]


# ---------------------------------------------------------------- switching modes --

def _dates_item(start: date, end: date) -> dict:
    """Exact dates as a period of the grammar (the same days whatever the day)."""
    day = lambda d: {"unit": "day", "way": "date", "offset": 0, "year": 0, "number": 0, "date": d.isoformat()}
    return {"phrase": periods.dates_text(start, end), "first": day(start), "last": day(end - timedelta(days=1)),
            "to_date": False}


def _periods_in(chart: dict, mode: str, start: date, end: date, preset: str, today: date) -> list[dict] | None:
    """The periods a chart would have in another mode, done in code; None when only a new plan can do it.
    start, end, preset = the dashboard's period now (a quick choice like "This month" can become a
    chart's own period)."""
    current, records = period_mode(chart), [dict(p) for p in chart.get("periods") or []]
    plan = plans.Plan.from_chart(chart)
    if mode == current:
        return records
    if mode == "dashboard":  # its one period becomes the dashboard's
        return records if len(records) == 1 and plan.own_periods() == 1 and plans.filters_a_range(plan, 1) else None
    if current == "dashboard":  # the dashboard's period (or the question's, if it had one) becomes its own
        if plan.own_periods() or not re.search(r"@(?:START|LAST|END)\b", plan.text()):
            return None
        if mode == "own":
            item = records[0] if len(records) == 1 else rewrite.preset_item(preset)
            return [rewrite.record(item, rewrite.Period(item["phrase"], *_resolved(item, today)))] if item else None
        item = rewrite.preset_item(preset) or _dates_item(start, end)
        return [rewrite.record(item, rewrite.Period(item["phrase"], start, end))]
    if mode == "fixed":  # own -> fixed: the dates it shows today
        return [{**p, "start": s.isoformat(), "end": e.isoformat()}
                for p, (s, e) in zip(records, own_dates(chart, today))]
    return records if records and plan.own_periods() == len(records) else None  # fixed -> own


def mode_choices(chart: dict, start: date, end: date, preset: str = "", today: date | None = None) -> dict[str, str]:
    """{mode: label} an admin can switch a chart to (Edit). Following the dashboard is always possible
    (if not in code, Claude writes a new plan for it)."""
    today = today or _today()
    choices = {}
    for mode in ("dashboard", "own", "fixed"):
        target = _periods_in(chart, mode, start, end, preset, today)
        if mode == "dashboard":
            choices[mode] = "Follow the dashboard's period" + ("" if target is not None or period_mode(chart) == mode
                                                              else " (Claude writes a new query for it)")
        elif target is not None:
            choices[mode] = (period_text({"period_mode": mode, "periods": target}, today) if target
                             else "Fixed: all dates").replace("Fixed:", "Fixed dates:")
    return choices


def change_period_mode(chart: dict, mode: str, start: date, end: date, preset: str = "",
                       today: date | None = None) -> dict:
    """The chart with its dates following another mode, done in code (the plan's placeholders renamed).
    Raises NeedsClaude when only a new plan can do it, e.g. a chart comparing two periods of its own
    can't follow the dashboard's one period."""
    today = today or _today()
    current = period_mode(chart)
    target = _periods_in(chart, mode, start, end, preset, today)
    if target is None:
        raise NeedsClaude(f"This chart's dates can't be switched to \"{PERIOD_MODES[mode]}\" without a new query.")
    if mode == current:
        return chart
    plan = plans.Plan.from_chart(chart)
    if mode == "dashboard":
        plan = plans.rename_placeholders(plan, "@P1_", "@")
    elif current == "dashboard":
        plan = plans.rename_placeholders(plan, "@", "@P1_")
    new = {**chart, "plan": plan.to_dict(), "query": plan.text(), "period_mode": mode, "periods": target}
    if mode == "dashboard" and not new.get("date_column"):
        new["date_column"] = _filtered_date(plan) or AUTO_DATE
    return new


# ---------------------------------------------------------------- grain --
# A chart by day that follows a long dashboard period gets hundreds of points or colours. Drawn by ISO
# week (Monday) or by month instead, its numbers added up - only when every measure drawn can be added up
# over days: counts and amounts, not averages, ratios or distinct counts (the meaning layer says which).

GRAIN_KINDS = ("bar", "horizontal_bar", "stacked_bar", "line", "area", "heatmap")
DAYS_BY_DAY, DAYS_BY_WEEK = 31, 183


def display_grain(df: pd.DataFrame | None, chart: dict, start: date, end: date) -> tuple[pd.DataFrame | None, str]:
    """The rows to draw: by day up to 31 days, by week up to 183 (about six months), by month beyond, for a
    chart that follows the dashboard and has days along its axis or as its colours. Returns (rows, "week",
    "month" or "" when drawn as they are)."""
    if df is None or df.empty or period_mode(chart) != "dashboard" or chart.get("chart_type") not in GRAIN_KINDS:
        return df, ""
    days = (end - start).days
    if days <= DAYS_BY_DAY:
        return df, ""
    grain = "week" if days <= DAYS_BY_WEEK else "month"
    x, color = chart.get("x") or "", chart.get("color") or ""
    col = next((c for c in (x, color) if c and c in df.columns and _by_day(df[c])), None)
    ys = [y for y in chart.get("y") or [] if y in df.columns]
    if (not col or not ys or not all(pd.api.types.is_numeric_dtype(df[y]) for y in ys)
            or not all(additive(chart, y) for y in ys)):
        return df, ""
    when = _as_dates(df[col])
    bucket = (when - pd.to_timedelta(when.dt.weekday, unit="D") if grain == "week"
              else when.dt.to_period("M").dt.to_timestamp())
    keys = [c for c in df.columns if c not in ys and (c in (x, color) or not pd.api.types.is_numeric_dtype(df[c]))]
    out = df.assign(**{col: bucket}).groupby(keys, sort=False, dropna=False, as_index=False)[ys].sum(min_count=1)
    return out, grain


def _as_dates(series: pd.Series) -> pd.Series | None:
    """The column as dates, if it holds dates (or text like 2026-10-15); else None."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if series.dtype != object:
        return None
    values = series.dropna()
    if values.empty:
        return None
    if all(isinstance(v, (date, pd.Timestamp)) for v in values) or all(
            isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]00:00:00)?", v) for v in values):
        return pd.to_datetime(series, errors="coerce")
    return None


def _by_day(series: pd.Series) -> bool:
    """Whether a column holds days (not months or weeks, which are already grouped)."""
    when = _as_dates(series)
    if when is None:
        return False
    days = when.dropna()
    if days.empty or (days != days.dt.normalize()).any():
        return False
    distinct = days.drop_duplicates().sort_values()
    if len(distinct) < 2:
        return False
    if (distinct.diff().dropna() == pd.Timedelta(days=1)).any():
        return True
    return not ((distinct.dt.day == 1).all() or (distinct.dt.weekday == 0).all())


_NOT_ADDED_UP = re.compile(r"\b(?:DISTINCTCOUNT\w*|AVERAGE\w*|AVG|MEDIAN\w*|MINX?|MAXX?|MINA|MAXA|DIVIDE|RANKX|RANK|"
                           r"PERCENTILE\w*|STDEV\w*|VAR\.\w+|VARX\.\w+|LASTNONBLANK\w*|FIRSTNONBLANK\w*|"
                           r"CLOSINGBALANCE\w*|OPENINGBALANCE\w*|LASTDATE|FIRSTDATE)\s*\(|\bCOUNT\s*\(\s*DISTINCT\b|/",
                           re.IGNORECASE)
_ADDING_UP = re.compile(r"\b(?:SUMX?|COUNT\w*)\s*\(", re.IGNORECASE)
_NEVER_ADD = re.compile(r"never add|do not add|don.t add|not be added|cannot be added|can.t be added|not additive|"
                        r"non.additive|semi.additive|snapshot", re.IGNORECASE)


def additive(chart: dict, column: str) -> bool:
    """Whether a measure of a chart's result can be added up across days (a count or an amount; not an
    average, a ratio or a distinct count): from the query that makes it and its cube's meaning layer.
    False when unsure."""
    try:
        return _added_up(plans.Plan.from_chart(chart), column, 0)
    except Exception:
        return False


def _added_up(plan: plans.Plan, column: str, depth: int) -> bool:
    if depth > 4:
        return False
    if plan.combine_sql:
        expr = _sql_expression(_code(plan.combine_sql), column)
        if expr is not None:  # made in the combining SQL: from the steps' columns it uses
            refs = [a or b for a, b in re.findall(r'"((?:[^"]|"")+)"|\.\s*(\w+)', expr)]
            steps_only = plans.Plan(plan.steps, "")
            return bool(refs) and not _NOT_ADDED_UP.search(expr) and all(
                _added_up(steps_only, r, depth + 1) for r in dict.fromkeys(refs))
    for s in plan.steps:
        query = _code(s.query)
        dax = bool(re.match(r"\s*(?:DEFINE|EVALUATE)\b", query, re.IGNORECASE))
        expr = _dax_expression(query, column) if dax else _sql_expression(query, column)
        if expr is not None:
            return _step_added_up(s.cube, query, expr, dax, depth)
    return False


def _step_added_up(cube: str, query: str, expr: str, dax: bool, depth: int) -> bool:
    if depth > 4 or _NOT_ADDED_UP.search(expr):
        return False
    if not dax:
        return bool(_ADDING_UP.search(expr))
    defined = {m.group(1).lower(): m.group(2) for m in re.finditer(
        r"\bMEASURE\s+(?:'(?:[^']|'')+'|\w+)\[([^\]]+)\]\s*=\s*(.*?)(?=\bMEASURE\b|\bEVALUATE\b|\bVAR\b|\bCOLUMN\b|\bTABLE\b|$)",
        query, flags=re.IGNORECASE | re.DOTALL)}
    measures = re.findall(r"(?<!['\w\]])\[([^\]]+)\]", expr)
    if not measures:
        return bool(_ADDING_UP.search(expr))  # SUM('Bookings'[Amount]), COUNTROWS(...)
    for name in measures:
        if name.lower() in defined:
            if not _step_added_up(cube, query, defined[name.lower()], True, depth + 1):
                return False
        elif _measure_added_up(cube, f"[{name}]") is not True:
            return False
    return True


def _measure_added_up(cube: str, name: str) -> bool | None:
    """From the meaning layer (aggregation "sum" and nothing saying otherwise), else the data layer's
    profile ("additive"); None when neither knows the measure."""
    import semantic
    for m in (semantic.cube(cube) or {}).get("measures", []):
        if m.get("name", "").lower() == name.lower():
            return m.get("aggregation") == "sum" and not _NEVER_ADD.search(f"{m.get('notes', '')} {m.get('definition', '')}")
    for m in data_layer.profile(cube).get("measures", []):
        if str(m.get("name", "")).lower() == name.lower():
            return m.get("aggregation") == "additive"
    return None


def _code(text: str) -> str:
    """A query without its comments."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"(?:--|//)[^\n]*", " ", text)


def _skip_quoted(text: str, i: int) -> int:
    """The position after the quoted text starting at i ('...' or "...", doubled quotes inside)."""
    quote, j = text[i], i + 1
    while j < len(text):
        if text[j] == quote:
            if j + 1 < len(text) and text[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return j


def _dax_expression(query: str, label: str) -> str | None:
    """The DAX expression a query gives a result column: "Bookings", [Reservations] -> [Reservations]."""
    for m in re.finditer(r'"((?:[^"]|"")*)"\s*,', query):
        if m.group(1).replace('""', '"').strip().lower() != label.strip().lower():
            continue
        depth, i = 0, m.end()
        while i < len(query):
            ch = query[i]
            if ch in "'\"":
                i = _skip_quoted(query, i)
                continue
            if ch in "({":
                depth += 1
            elif ch in ")}":
                if depth == 0:
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                break
            i += 1
        expr = query[m.end():i].strip()
        if expr:
            return expr
    return None


def _sql_expression(sql: str, label: str) -> str | None:
    """The SQL expression a SELECT gives a result column: SUM("Sales USD") AS "Sales" -> SUM("Sales USD")."""
    masked = re.sub(r"'(?:[^']|'')*'", lambda m: "'" + "_" * (len(m.group(0)) - 2) + "'", sql)
    for m in re.finditer(r'\bAS\s+("(?:[^"]|"")+"|\w+)', masked, flags=re.IGNORECASE):
        if m.group(1).strip('"').replace('""', '"').lower() != label.strip().lower():
            continue
        depth, i = 0, m.start() - 1
        while i >= 0:
            ch = masked[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and (ch == "," or re.search(r"\bSELECT\s+(?:DISTINCT\s+)?$", masked[:i + 1], re.IGNORECASE)):
                break
            i -= 1
        expr = sql[i + 1:m.start()].strip()
        if expr:
            return expr
    return None


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


if __name__ == "__main__":
    import sys
    from pathlib import Path
    if sys.argv[1:2] == ["refresh"]:  # a background refresh in its own process (see _start_refresh)
        job_file = Path(sys.argv[2])
        job = json.loads(job_file.read_text(encoding="utf-8"))
        period = (date.fromisoformat(job["start"]), date.fromisoformat(job["end"]))
        versus = tuple(date.fromisoformat(d) for d in job["compare"]) if job["compare"] else None
        _run_and_save(job["chart"], *period, versus, job["as_of"])
        job_file.unlink(missing_ok=True)
