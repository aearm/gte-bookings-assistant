"""Work the server does by itself, so nobody waits for it:
- at start-up: the worker processes started and connected (pool.py), the data layer, meaning layer and
  every cube's value index read into memory, the index cards prepared (as warm_up.py does for Streamlit);
- at start-up and every day at 00:05: the dashboard charts that show periods of their own ("yesterday vs
  the day before") run for the new day, and the charts that follow the dashboard run for the default
  period, so the first visit of the day opens with saved numbers."""
import logging
import threading
import time
from datetime import datetime, timedelta

import config

log = logging.getLogger("server")
PRERUN_AT = (0, 5)               # hour, minute
PRERUN_DEFAULT_PERIOD = True     # also charts that follow the dashboard, for the default period and comparison

state = {"warm": False, "warming": False, "last_prerun": "", "prerun_charts": 0}
_stop = threading.Event()


def start() -> None:
    """Called once when the server starts (main.py)."""
    import cubes
    from server import pool
    _stop.clear()
    cubes.migrate()
    if config.resolve_source() == "ssas":
        pool.install()
    threading.Thread(target=_start_up, name="warm-up", daemon=True).start()
    threading.Thread(target=_daily, name="daily-prerun", daemon=True).start()


def stop() -> None:
    from server import pool
    _stop.set()
    pool.uninstall()


def _start_up() -> None:
    warm()
    try:
        prerun()
    except Exception:
        log.exception("Pre-running dashboard charts failed")


def warm() -> None:
    """Workers connected, the meaning layer and value indexes in memory. A failure is only logged:
    warming up helps, it is never required."""
    from server import pool
    state["warming"] = True
    began = time.perf_counter()
    try:
        workers = pool.active()
        waiting = threading.Thread(target=workers.warm_up, daemon=True) if workers else None
        if waiting:
            waiting.start()
        import data_layer
        import routing
        import semantic
        import value_index
        data_layer.load()
        semantic.decisions()
        for cube in data_layer.layer_cubes():
            value_index.for_cube(cube).load()
        routing.cards_text()
        if waiting:
            waiting.join()
        state["warm"] = True
    except Exception:
        log.exception("Warming up failed")
    finally:
        state["warming"] = False
        log.info("Warm-up done in %.1f s", time.perf_counter() - began)


def prerun() -> int:
    """Run (and save) the charts the first visit of the day shows: those with periods of their own and,
    with PRERUN_DEFAULT_PERIOD, every chart for the default period. Saved numbers that are still
    current are not run again (dashboards.results_for). Returns how many charts were looked at."""
    import dashboards
    from server.routes import periods as period_api
    from server.routes.dashboards import data_as_of_many
    start, end, preset = period_api.pick(None, None, "")
    versus = period_api.versus(period_api.DEFAULTS["compare"], start, end, preset)
    span = (versus["start"], versus["end"]) if versus else None
    count = 0
    dashboards.ensure_builtin(force=True)  # a new version of the built-in dashboards first, so it is what runs
    for board in dashboards.list_dashboards():
        charts = [c for c in board["charts"] if PRERUN_DEFAULT_PERIOD or dashboards.period_mode(c) == "own"]
        if not charts or _stop.is_set():
            continue
        as_of = data_as_of_many([cb for c in charts for cb in dashboards.plans.Plan.from_chart(c).cubes], wait=60)
        charts = dashboards.apply_filters(board, charts)  # a dashboard's filters at their default values
        for chart in charts:  # one at a time; a visitor meanwhile waits only for a chart being run right then
            if _stop.is_set():
                break
            dashboards.results_for([chart], start, end, span, as_of)
        count += len(charts)
    state.update(last_prerun=datetime.now().isoformat(timespec="seconds"), prerun_charts=count)
    return count


def seconds_until_next(now: datetime | None = None) -> float:
    now = now or datetime.now()
    nxt = now.replace(hour=PRERUN_AT[0], minute=PRERUN_AT[1], second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def _daily() -> None:
    while not _stop.wait(seconds_until_next()):
        try:
            prerun()
        except Exception:
            log.exception("Pre-running dashboard charts failed")
