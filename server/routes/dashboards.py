"""Dashboards: the list, each dashboard's charts and their numbers for a period (saved numbers at once,
brought up to date in the background), and every change an admin makes: new / rename / delete
dashboards; add a chart from a question (Claude), from a chat answer or a whole conversation (instant),
edit, restyle, copy or move, reorder and delete charts. Same steps as dashboard_view.py and views/chat.py."""
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, Request

import charts
import config
import cubes
import dashboards
import data_layer
import periods
import plans
from backends import get_backend
from errors import friendly
from server import convert, jobs
from server.auth import require_admin
from server.replies import ApiError, from_exception, not_found
from server.routes import chat
from server.routes.periods import DEFAULTS, period_json, pick, versus
from server.schemas import (ChartChanges, ChartMeta, Dashboard, DashboardName, DashboardSummary, FilterChoices,
                            FromAnswer, FromConversation, JobStarted, MoveStep, NewChart, Ok, Restyle, Results, Send,
                            Starter)

router = APIRouter(tags=["dashboards"])
admin = [Depends(require_admin)]


# ---------------------------------------------------------------- when the cubes were updated --

AS_OF_SECONDS = 300
AS_OF_WAIT = 2.0  # seconds a page waits for the answer; a slow server must not hold up the saved numbers
_as_of: dict[str, tuple[float, str]] = {}
_asking: dict[str, threading.Thread] = {}
_asking_lock = threading.Lock()


def _ask_as_of(cube: str) -> None:
    try:
        text = get_backend(cube).data_as_of()
    except Exception:
        text = ""
    _as_of[cube] = (time.time(), text)


def data_as_of(cube: str, wait: float = AS_OF_WAIT) -> str:
    """When the server last refreshed a cube's data ('6 Oct 2026, 23:37'), asked at most every 5 minutes.
    When the server takes longer than `wait` to say, the last answer is used (or "" before the first) and
    the answer is kept for next time."""
    return data_as_of_many([cube], wait)[cube]


def data_as_of_many(names: list[str], wait: float = AS_OF_WAIT) -> dict[str, str]:
    """data_as_of for several cubes, asked at the same time (waiting `wait` seconds in all)."""
    now, waiting = time.time(), []
    for cube in dict.fromkeys(names):
        hit = _as_of.get(cube)
        if hit and now - hit[0] < AS_OF_SECONDS:
            continue
        with _asking_lock:
            asking = _asking.get(cube)
            if asking is None or not asking.is_alive():
                asking = _asking[cube] = threading.Thread(target=_ask_as_of, args=(cube,), name="data-as-of",
                                                          daemon=True)
                asking.start()
        waiting.append(asking)
    deadline = time.monotonic() + wait
    for asking in waiting:
        asking.join(max(0.0, deadline - time.monotonic()))
    return {cube: (_as_of.get(cube) or (0, ""))[1] for cube in names}


def updated_text(times: dict[str, str]) -> dict:
    """{"text": "Data updated 13 Oct, 18:24", "per_cube": {cube: time}} (the latest of the cubes)."""
    times = {cb: t for cb, t in times.items() if t}
    if not times:
        return {"text": "", "per_cube": {}}
    parsed = {}
    for cb, t in times.items():
        try:
            parsed[cb] = datetime.strptime(t, "%d %b %Y, %H:%M")
        except ValueError:
            pass
    latest = max(parsed.values()) if parsed else None
    head = f"Data updated {latest.day} {latest:%b, %H:%M}" if latest else "Data updated " + next(iter(times.values()))
    return {"text": head, "per_cube": {data_layer.cube_label(cb): t for cb, t in times.items()}}


# ---------------------------------------------------------------- one run at a time --
# Several people opening the same dashboard for the same period (or the nightly run and the first visitor)
# would each run the missing charts on the cubes. They take turns instead: the first runs them, the others
# then find the saved numbers. Other periods and other dashboards don't wait.

_locks: dict[tuple, threading.Lock] = {}
_locks_lock = threading.Lock()


@contextmanager
def one_at_a_time(key: tuple):
    with _locks_lock:
        if len(_locks) > 500:  # forget the locks nobody holds
            for k in [k for k, lock in _locks.items() if not lock.locked()]:
                del _locks[k]
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        yield


# ---------------------------------------------------------------- charts as JSON --

def chart_cubes(c: dict) -> list[str]:
    return plans.Plan.from_chart(c).cubes


def chart_meta(c: dict) -> dict:
    plan = plans.Plan.from_chart(c)
    own = dashboards.period_text(c)
    dates = dashboards.date_label(c.get("date_column", ""))
    return {"id": c["id"], "title": c.get("title", ""), "question": c.get("question", ""), "chart_type": c["chart_type"],
            "width": "full" if c.get("width") == "full" else "half", "cubes": plan.cubes,
            "date_column": c.get("date_column", ""), "period": {"mode": dashboards.period_mode(c), "label": own},
            "compares": dashboards.compares(c),
            "lower_is_better": bool((c.get("style") or {}).get("lower_is_better")),
            "caption": (own + (f" · {dates}" if c.get("date_column") else "")) if own else f"Dates: {dates}",
            "date_label": dates, "sources": [data_layer.cube_label(x) for x in plan.cubes],
            "compare_on": c.get("compare", True) is not False, "chart_request": c.get("chart_request", ""),
            "query": plan.steps[0].query if plan.single else plan.text(), "query_editable": plan.single}


def dashboard_json(board: dict, failed: list[dict] | None = None) -> dict:
    return {"id": board["id"], "name": board["name"], "charts": [chart_meta(c) for c in board["charts"]],
            "filters": [{"key": f["key"], "label": f.get("label") or f["key"]} for f in board.get("filters") or []],
            "failed": failed or []}


def board_or_404(dashboard_id: str) -> dict:
    board = dashboards.get_dashboard(dashboard_id)
    if board is None:
        raise not_found("This dashboard")
    return board


def chart_or_404(dashboard_id: str, chart_id: str) -> dict:
    board_or_404(dashboard_id)
    c = dashboards.get_chart(dashboard_id, chart_id)
    if c is None:
        raise not_found("This chart")
    return c


# ---------------------------------------------------------------- headline numbers (as dashboard_view.py) --

def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    return f"{value:,.0f}" if abs(value) >= 1000 or float(value).is_integer() else f"{value:,.2f}"


def first_number(df) -> float | None:
    if df is None or df.empty:
        return None
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    value = df[nums[0]].iloc[0] if nums else None
    return None if value is None or pd.isna(value) else float(value)


def headline(c: dict, df) -> str:
    """A headline number written the way Claude chose for it (AED 4.5M, 12.3%), else plainly."""
    nums = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])] if df is not None else []
    value = first_number(df)
    d3, prefix, suffix = charts.number_format(c, nums[0]) if nums else ("", "", "")
    if not (d3 or prefix or suffix):
        d3, prefix, suffix = next(((f.get("d3_format", ""), f.get("prefix", ""), f.get("suffix", ""))
                                   for f in (c.get("style") or {}).get("formats", [])), ("", "", ""))
    return charts.format_number(value, d3, prefix, suffix) if (d3 or prefix or suffix) else _fmt(value)


def kpi(c: dict, df, prev, compare: dict | None) -> dict:
    value, before = first_number(df), first_number(prev) if compare else None
    change, text = dashboards.headline_change(c, value, before) if compare else (None, "")
    return {"value": value, "text": headline(c, df), "change": change,
            "change_text": f"{text} vs {compare['name']}" if change is not None else "",
            "prev_text": headline(c, prev) if before is not None else "",
            "prev_label": compare["label"] if compare and before is not None else ""}


# ---------------------------------------------------------------- one chart's result --

def chart_result(c: dict, res: dict, start: date, end: date, compare: dict | None) -> dict:
    """A chart's numbers for the period as the contract's ChartResult (as dashboard_view's cards draw them)."""
    out = {"chart": None, "table": None, "prev_table": None, "kpi": None, "error": None, "details": None,
           "period_label": dashboards.period_text(c) or periods.dates_text(start, end)}
    if not res:
        return {**out, "error": "No numbers yet for this chart."}
    if res.get("error"):
        return {**out, "error": res["error"], "details": res.get("details") or None}
    df, prev = res.get("df"), res.get("prev")
    if c["chart_type"] == "kpi":
        return {**out, "chart": {"kind": "kpi", "option": None, "title": c.get("title", ""), "summary": "", "note": ""},
                "table": convert.table(df, c), "prev_table": convert.table(prev, c) if compare else None,
                "kpi": kpi(c, df, prev, compare)}
    shown, grain = dashboards.display_grain(df, c, start, end)  # by week or month over a long period
    if shown is None or shown.empty:
        return {**out, "chart": {"kind": "table", "option": None, "title": c.get("title", ""), "summary": "",
                                 "note": "No data for this period."}, "table": convert.table(shown, c)}
    before = dashboards.display_grain(prev, c, start, end)[0] if compare and prev is not None else None
    against = {"df": before, "current": periods.dates_text(start, end), "name": compare["label"]} if before is not None else None
    drawn = convert.chart(shown, {**c, "summary": "", "note": ""}, compare=against, show_title=False)
    notes = [drawn["note"]] if drawn["note"] else []  # e.g. "couldn't be drawn, shown as a table"
    trimmed =((drawn.get("option") or {}).get("x-app") or {}).get("note", "") if c.get("chart_type") != "custom" else ""
    if trimmed:
        notes.append(trimmed.split(" (")[0] + ".")
    if grain:
        notes.append(f"By {grain} (each {'Monday' if grain == 'week' else 'first of the month'} stands for its {grain}): "
                     f"the period is longer than {'a month' if grain == 'week' else 'six months'}.")
    table, prev_table = convert.table(shown, c), convert.table(before, c) if before is not None else None
    if drawn["kind"] == "table" and before is not None:  # a table gets a change column per measure
        with_changes, spec = charts.with_changes(shown, before, c)
        if with_changes is not shown:
            table = convert.table(with_changes, spec)
            notes.append(f"Change vs {compare['label']}.")
    drawn["note"] = " ".join(notes)
    if drawn.get("option"):  # the chart carries its rows (dataset): sending them again as a table doubled the reply
        table, prev_table = None, None
    return {**out, "chart": drawn, "table": table, "prev_table": prev_table}


# ---------------------------------------------------------------- choices for the dialogs --

def default_date(cube: str) -> str:
    """The date the dashboard's period filters by default (each cube's main date for several cubes)."""
    if not cube:
        return dashboards.AUTO_DATE
    return dashboards.default_date_column(dashboards.date_columns(get_backend(cube).schema_text()), cube)


@router.get("/date-columns")
def date_columns(cube: str = "") -> dict:
    """(extra) The dates a chart on this cube can follow ("" = several cubes: each cube's main date)."""
    cols = dashboards.date_columns(get_backend(cube).schema_text()) if cube else [dashboards.AUTO_DATE]
    options = [{"value": c, "label": dashboards.date_label(c)} for c in cols]
    options.append({"value": "", "label": "Nothing (always show all dates)"})
    return {"options": options, "default": default_date(cube)}


def check_type(chart_type: str, allow_auto: bool = True) -> str:
    chart_type = "donut" if chart_type == "pie" else chart_type
    if chart_type not in dashboards.TYPE_LABELS or (chart_type == "auto" and not allow_auto):
        raise ApiError(400, f"Unknown chart type: {chart_type}.")
    return chart_type


def with_mode(c: dict, mode: str, cube: str, date_col: str, start: date, end: date, preset: str) -> dict:
    """The chart switched to another way of choosing its dates: in code when its query allows it, else (to
    follow the dashboard) Claude writes a query for the dashboard's period (as dashboard_view.with_mode)."""
    if mode == dashboards.period_mode(c):
        return c
    try:
        return dashboards.change_period_mode(c, mode, start, end, preset)
    except dashboards.NeedsClaude as exc:
        if mode != "dashboard":
            raise ApiError(400, str(exc)) from exc
    new = dashboards.build_chart(cube, c.get("question", ""), c["title"], c["chart_type"], c.get("width", "half"),
                                 date_col or default_date(cube), start, end, base_query=c.get("query", ""),
                                 base_spec=c, chart_request=c.get("chart_request", ""))
    return {**new, "id": c["id"]}


@router.get("/dashboards/{dashboard_id}/charts/{chart_id}/modes")
def mode_choices(dashboard_id: str, chart_id: str, start: date | None = None, end: date | None = None,
                 preset: str = "") -> dict:
    """(extra) {mode: label} the chart can switch to in Edit, for the dashboard's current period."""
    c = chart_or_404(dashboard_id, chart_id)
    start, end, preset = pick(start, end, preset)
    return {"current": dashboards.period_mode(c), "choices": dashboards.mode_choices(c, start, end, preset)}


# ---------------------------------------------------------------- dashboards --

@router.get("/dashboards", response_model=list[DashboardSummary])
def list_dashboards() -> list[dict]:
    return [{"id": b["id"], "name": b["name"], "charts": len(b["charts"])} for b in dashboards.list_dashboards()]


@router.post("/dashboards", response_model=Dashboard, dependencies=admin)
def create_dashboard(body: DashboardName) -> dict:
    if not body.name.strip():
        raise ApiError(400, "Give the dashboard a name.")
    return dashboard_json(board_or_404(dashboards.create_dashboard(body.name)))


@router.get("/dashboards/{dashboard_id}", response_model=Dashboard)
def read_dashboard(dashboard_id: str) -> dict:
    return dashboard_json(board_or_404(dashboard_id))


@router.patch("/dashboards/{dashboard_id}", response_model=Dashboard, dependencies=admin)
def rename_dashboard(dashboard_id: str, body: DashboardName) -> dict:
    board_or_404(dashboard_id)
    if not body.name.strip():
        raise ApiError(400, "Give the dashboard a name.")
    dashboards.rename_dashboard(dashboard_id, body.name)
    return dashboard_json(board_or_404(dashboard_id))


@router.delete("/dashboards/{dashboard_id}", response_model=Ok, dependencies=admin)
def delete_dashboard(dashboard_id: str) -> dict:
    board_or_404(dashboard_id)
    dashboards.delete_dashboard(dashboard_id)
    return {"ok": True}


@router.get("/dashboards/{dashboard_id}/results", response_model=Results)
def results(request: Request, dashboard_id: str, start: date | None = None, end: date | None = None,
            preset: str = "", compare: str = "", cstart: date | None = None, cend: date | None = None,
            force: bool = False) -> dict:
    """Every chart's numbers for the period: saved ones at once, missing ones run now. updating = some charts
    are being brought up to date in the background (their cube has new data): ask again in 3 s.
    f_<key>=<value> (extra): the value of the dashboard's filter <key> (else its default)."""
    board = board_or_404(dashboard_id)
    asked = {k[2:]: v for k, v in request.query_params.items() if k.startswith("f_") and v}
    chosen = dashboards.filter_values(board, asked) if board.get("filters") else {}
    running = dashboards.apply_filters(board, board["charts"], chosen)
    start, end, preset = pick(start, end, preset)
    against = versus(compare or DEFAULTS["compare"], start, end, preset, cstart, cend)
    board_cubes = list(dict.fromkeys(x for c in board["charts"] for x in chart_cubes(c) if x))
    if force:
        for cb in board_cubes:
            _as_of.pop(cb, None)
    as_of = data_as_of_many(board_cubes)
    span = (against["start"], against["end"]) if against else None
    with one_at_a_time((dashboard_id, start, end, span, tuple(sorted(chosen.items())))):
        found, updating = dashboards.results_for(running, start, end, span, as_of, force=force)
    return {"period": period_json(start, end, preset), "compare": against, "data_as_of": updated_text(as_of),
            "charts": {c["id"]: chart_result(c, found.get(c["id"], {}), start, end, against) for c in board["charts"]},
            "updating": dashboards.still_updating(updating), "filters": chosen}


@router.get("/dashboards/{dashboard_id}/filters", response_model=list[FilterChoices])
def filter_choices(dashboard_id: str) -> list[dict]:
    """The values each filter of the dashboard can take (the clients or markets with sales in the last year,
    biggest first) and its default (the first)."""
    return dashboards.filter_options(board_or_404(dashboard_id))


# ---------------------------------------------------------------- adding charts --

@router.post("/dashboards/{dashboard_id}/charts", response_model=ChartMeta, dependencies=admin)
def add_chart(dashboard_id: str, body: NewChart) -> dict:
    """A chart from a question: Claude writes and tests its query (about half a minute)."""
    board_or_404(dashboard_id)
    chart_type = check_type(body.chart_type)
    if body.cube and body.cube not in cubes.enabled():
        raise ApiError(400, "That cube isn't connected.")
    if chart_type == "custom" and not body.chart_request.strip():
        raise ApiError(400, "Describe the chart you want.")
    start, end, preset = pick(body.start, body.end, body.preset)
    date_col = body.date_column if body.date_column is not None else default_date(body.cube)
    try:
        chart = dashboards.build_chart(body.cube, body.question.strip(), body.title, chart_type, body.width, date_col,
                                       start, end, chart_request=body.chart_request.strip())
        chart = with_mode(chart, body.period_mode, body.cube, date_col, start, end, preset)
    except ApiError:
        raise
    except Exception as exc:
        raise from_exception(exc) from exc
    dashboards.add_chart(dashboard_id, chart)
    return chart_meta(chart)


def answer_defaults(turn: dict) -> dict:
    """How an answer goes on a dashboard unless the admin changes it (as views/chat.dashboard_defaults): its
    cube (or several), the date the dashboard's period applies to, its chart, its title without the dates."""
    used = turn.get("cubes") or []
    cube = used[0] if len(used) == 1 else ""
    spec = turn.get("spec") or {}
    cols = dashboards.date_columns(get_backend(cube).schema_text()) if cube else [dashboards.AUTO_DATE]
    used_date = next((c for c in cols if c in turn.get("query", "")), None) if cube else None
    chart_type = {"pie": "donut"}.get(spec.get("chart_type", "auto"), spec.get("chart_type", "auto"))
    chart_type = chart_type if chart_type in dashboards.TYPE_LABELS else "auto"
    return {"cube": cube, "date_column": used_date or dashboards.default_date_column(cols, cube),
            "chart_type": chart_type, "title": periods.without_dates(spec.get("title") or turn["question"]),
            "request": spec.get("chart_request", "") if chart_type == "custom" else "",
            "width": "full" if chart_type in ("map", "custom") else "half"}


def claude_job(turn: dict, d: dict) -> dict:
    """dashboards.build_chart's arguments (all but the period) for an answer that needs a new plan."""
    return {"cube": d["cube"], "question": turn["question"], "title": d["title"], "chart_type": d["chart_type"],
            "width": d["width"], "date_column": d["date_column"], "base_query": turn.get("query", ""),
            "base_spec": turn.get("spec") or {}, "chart_request": d["request"]}


def keep_numbers(chart: dict, turn: dict, start: date, end: date, against: dict | None) -> None:
    """The chat's numbers become the chart's first ones on the dashboard (when they are what it shows)."""
    dashboards.keep_answer_numbers(chart, turn, data_as_of_many(turn.get("cubes") or []),
                                   (start, end), (against["start"], against["end"]) if against else None)


@router.post("/dashboards/{dashboard_id}/charts/from-answer", response_model=ChartMeta, dependencies=admin)
def add_from_answer(dashboard_id: str, body: FromAnswer) -> dict:
    """A chat answer on a dashboard as it was drawn, at once: no Claude call and no query (its plan with its
    dates as placeholders, its numbers as the first ones). Only "follow the dashboard" for an answer whose
    dates can't simply be swapped needs Claude to write a new plan (see the turn's dashboard_modes)."""
    board_or_404(dashboard_id)
    turn = chat.turn_of(chat.conversation(body.conversation_id), body.turn_id)
    if not chat.has_chart(turn) or not turn.get("plan"):
        raise ApiError(400, "This answer has no chart to add.")
    d = answer_defaults(turn)
    d.update({k: v for k, v in (("title", body.title), ("width", body.width)) if v})
    if body.chart_type:
        d["chart_type"] = check_type(body.chart_type)
    ways = {w["mode"]: w for w in dashboards.period_choices(turn)}
    mode = body.period_mode or next(iter(ways))
    if mode not in ways:
        raise ApiError(400, "This answer can't go on a dashboard that way. Choose one of: "
                       + "; ".join(w["label"] for w in ways.values()) + ".")
    quick = ways[mode]["instant"]
    if quick and mode == "dashboard" and d["chart_type"] == "kpi" and len(turn["df"]) != 1:
        quick = False  # a headline number needs a query that returns one number
    start, end, preset = pick(body.start, body.end, body.preset)
    against = versus(body.compare or DEFAULTS["compare"], start, end, preset, body.cstart, body.cend)
    try:
        if quick:
            keep = d["chart_type"] != "custom" or (turn.get("spec") or {}).get("custom")
            chart = dashboards.chart_from_answer(turn, mode, title=d["title"], chart_type=d["chart_type"] if keep else "",
                                                 width=d["width"], date_column=d["date_column"])
        else:
            chart = dashboards.build_chart(start=start, end=end, **claude_job(turn, d))
    except Exception as exc:
        raise from_exception(exc) from exc
    dashboards.add_chart(dashboard_id, chart)
    if quick:
        keep_numbers(chart, turn, start, end, against)
    return chart_meta(chart)


@router.post("/dashboards/from-conversation", response_model=Dashboard, dependencies=admin)
def from_conversation(body: FromConversation) -> dict:
    """The conversation's charts on a new dashboard, in the conversation's order. Answers that name their own
    dates keep them and are added at once, as drawn; the others follow the dashboard's dates and Claude
    prepares them at the same time. One that can't be prepared is reported ("failed"), the others added."""
    conv = chat.conversation(body.conversation_id)
    turns = [t for t in conv.turns if chat.has_chart(t) and t.get("plan")
             and (body.turn_ids is None or t["id"] in body.turn_ids)]
    if not turns:
        raise ApiError(400, "This conversation has no charts to put on a dashboard yet.")
    start, end, preset = pick(body.start, body.end, body.preset)
    against = versus(body.compare or DEFAULTS["compare"], start, end, preset, body.cstart, body.cend)
    looks = {t["id"]: answer_defaults(t) for t in turns}
    ways = {t["id"]: dashboards.period_choices(t)[0] for t in turns}  # each answer's suggested way
    built, failed = {}, {}
    for t in [t for t in turns if ways[t["id"]]["instant"]]:
        d = looks[t["id"]]
        try:
            built[t["id"]] = dashboards.chart_from_answer(t, ways[t["id"]]["mode"], title=d["title"], width=d["width"],
                                                          date_column=d["date_column"])
        except Exception as exc:
            failed[t["id"]] = friendly(exc)
    slow = {t["id"]: claude_job(t, looks[t["id"]]) for t in turns if not ways[t["id"]]["instant"]}
    for key, chart, exc in dashboards.build_many(slow, start, end):
        if chart:
            built[key] = chart
        else:
            failed[key] = friendly(exc)
    problems = [{"turn_id": k, "title": looks[k]["title"], "error": v} for k, v in failed.items()]
    if not built:
        raise ApiError(400, "None of the charts could be prepared, so no dashboard was made.",
                       "; ".join(f"{p['title']}: {p['error']}" for p in problems))
    board_id = dashboards.create_dashboard(body.name)
    for t in turns:
        if t["id"] in built:
            dashboards.add_chart(board_id, built[t["id"]])
            if ways[t["id"]]["instant"]:
                keep_numbers(built[t["id"]], t, start, end, against)
    return dashboard_json(board_or_404(board_id), problems)


@router.post("/dashboards/{dashboard_id}/starter", response_model=JobStarted, dependencies=admin)
def starter_charts(dashboard_id: str, body: Starter) -> dict:
    """(extra) Suggested charts for an empty dashboard, built by Claude from a cube's setup (a job)."""
    board_or_404(dashboard_id)
    if body.cube not in cubes.enabled() or not cubes.is_ready(body.cube):
        raise ApiError(400, "That cube isn't connected or hasn't been read yet.")
    start, end, _ = pick(body.start, body.end, body.preset)

    def work(job):
        job.say("Claude is creating the charts...")
        failed = dashboards.create_starter(dashboard_id, body.cube, start, end, on_done=lambda t: job.say(f"✓ {t}"))
        if failed:
            job.say("These charts could not be created: " + ", ".join(failed))
        return failed
    return {"job": jobs.start("starter", work).id}


# ---------------------------------------------------------------- changing charts --

@router.patch("/dashboards/{dashboard_id}/charts/{chart_id}", response_model=ChartMeta, dependencies=admin)
def edit_chart(dashboard_id: str, chart_id: str, body: ChartChanges) -> dict:
    """Edit a chart (as dashboard_view.edit_dialog): a new question, another date to follow, or switching to
    or from a headline number has Claude write a new query; a new description of a custom chart has Claude
    redraw it; everything else is done in code."""
    c = chart_or_404(dashboard_id, chart_id)
    plan = plans.Plan.from_chart(c)
    cube = c.get("cube", "") if plan.single else ""
    title = (body.title if body.title is not None else c.get("title", "")).strip()
    question = (body.question if body.question is not None else c.get("question", "")).strip()
    chart_type = check_type(body.chart_type, allow_auto=False) if body.chart_type else c["chart_type"]
    request = ((body.chart_request if body.chart_request is not None else c.get("chart_request", "")).strip()
               if chart_type == "custom" else "")
    mode_now = dashboards.period_mode(c)
    mode = body.period_mode or mode_now
    date_col = body.date_column if mode == "dashboard" and body.date_column is not None else c.get("date_column", "")
    show_compare = body.compare if body.compare is not None else c.get("compare", True) is not False
    width = body.width or c.get("width", "half")
    query = body.query if body.query is not None and plan.single else (plan.steps[0].query if plan.single else "")
    if chart_type == "custom" and not request:
        raise ApiError(400, "Describe the chart you want.")
    if not question:
        raise ApiError(400, "Say what the chart should show.")
    start, end, preset = pick(body.start, body.end, body.preset)
    kpi_changed = (chart_type == "kpi") != (c["chart_type"] == "kpi")
    date_changed = mode_now == "dashboard" and mode == "dashboard" and date_col != c.get("date_column", "")
    try:
        if question != c.get("question", "") or date_changed or kpi_changed:
            new = dashboards.build_chart(cube, question, title, chart_type, width, date_col, start, end,
                                         chart_request=request)
            c = {**new, "id": c["id"], "periods": c.get("periods", [])}  # follows the dashboard (see with_mode)
        elif chart_type == "custom" and request != c.get("chart_request", ""):
            c = dashboards.restyle_chart(c, request, start, end)
            c.update(title=title or c["title"], width=width)
        else:
            query_changed = plan.single and query.strip() != plan.steps[0].query.strip()
            if query_changed:
                plan = plans.Plan([plans.Step(plan.steps[0].name, plan.steps[0].cube, query)])
                c.update(plan=plan.to_dict(), query=plan.text())
            if plan.single and (query_changed or (chart_type not in ("kpi", "table", "custom") and not c.get("x"))):
                df = plans.run(dashboards.runnable(c, start, end), config.MAX_ROWS)
                if c.get("x") not in df.columns:
                    c.update({k: v for k, v in charts.suggest(df).items() if k in ("x", "y", "color")})
            if chart_type != "custom":
                c.pop("custom", None)
                c.pop("chart_request", None)
            c.update(title=title or c["title"], chart_type=chart_type, width=width)
        c = with_mode(c, mode, cube, date_col, start, end, preset)
    except ApiError:
        raise
    except Exception as exc:
        raise from_exception(exc) from exc
    c.pop("compare", None)
    if not show_compare:
        c["compare"] = False
    dashboards.update_chart(dashboard_id, c)
    return chart_meta(c)


@router.post("/dashboards/{dashboard_id}/charts/{chart_id}/restyle", response_model=ChartMeta, dependencies=admin)
def restyle(dashboard_id: str, chart_id: str, body: Restyle) -> dict:
    """The same numbers drawn the way the request describes (one Claude call)."""
    c = chart_or_404(dashboard_id, chart_id)
    if c["chart_type"] == "kpi":
        raise ApiError(400, "A headline number can't be drawn as a chart. Edit it to change its type.")
    start, end, _ = pick(body.start, body.end, body.preset)
    try:
        new = dashboards.restyle_chart(c, body.request.strip(), start, end)
    except Exception as exc:
        raise from_exception(exc) from exc
    dashboards.update_chart(dashboard_id, new)
    return chart_meta(new)


@router.post("/dashboards/{dashboard_id}/charts/{chart_id}/send", dependencies=admin)
def send(dashboard_id: str, chart_id: str, body: Send) -> dict:
    """Copy the chart to another dashboard, or move it there (to="new" with a name makes that dashboard)."""
    c = chart_or_404(dashboard_id, chart_id)
    if body.to == "new":
        target = dashboards.create_dashboard(body.name or "New dashboard")
    else:
        board_or_404(body.to)
        target = body.to
    if target == dashboard_id:
        raise ApiError(400, "Pick another dashboard.")
    dashboards.send_chart(c, target, remove_from=dashboard_id if body.move else "")
    return {"ok": True, "to": target}


@router.post("/dashboards/{dashboard_id}/charts/{chart_id}/move", response_model=Dashboard, dependencies=admin)
def move(dashboard_id: str, chart_id: str, body: MoveStep) -> dict:
    chart_or_404(dashboard_id, chart_id)
    dashboards.move_chart(dashboard_id, chart_id, body.step)
    return dashboard_json(board_or_404(dashboard_id))


@router.delete("/dashboards/{dashboard_id}/charts/{chart_id}", response_model=Ok, dependencies=admin)
def delete_chart(dashboard_id: str, chart_id: str) -> dict:
    chart_or_404(dashboard_id, chart_id)
    dashboards.delete_chart(dashboard_id, chart_id)
    return {"ok": True}
