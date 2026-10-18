"""Cube queries in worker processes, so they never share Python's lock with the web server.

Reading a cube result through the .NET connector makes many calls into .NET; inside the web server's
process every one of them hands Python's lock back and forth, and pages and queries slow each other
down (docs/refactor-plan.md §2). Here a small pool of separate Python processes (WORKERS, started
with "spawn") does that work: each loads ADOMD.NET and opens a first connection when the server
starts, then runs queries for the web server, which only waits for the rows (pickled back to it).

install() swaps ssas.run_query in the web server's process for a function that sends the call to a
worker, so backends, plans, dashboards and data_layer keep calling ssas.run_query as before. The
workers import ssas themselves and call the real function. The connection settings (server, cube,
login) are sent with every call, so a change on the Settings page applies at once. Local mode and
the tests don't use the pool: everything runs in the web server's process.
"""
import concurrent.futures
import multiprocessing
import os
import pickle
import sys
import threading
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import config

APP_DIR = str(Path(__file__).resolve().parent.parent)  # where the domain modules (ssas.py...) are

# 6: a dashboard runs a few charts at once, each with its comparison alongside (dashboards._run_one); a
# worker takes about 130 MB. Three charts with comparisons for a new period: 1.7 s with 3 workers, 1.0 s with 6.
WORKERS = max(1, int(os.getenv("API_WORKERS", "6")))
SETTINGS = ("SSAS_SERVER", "SSAS_DATABASE", "SSAS_USERNAME", "SSAS_CONNECTION_EXTRA", "ADOMD_PATH")


class CubeError(Exception):
    """An error from a worker that couldn't travel back as it was (.NET errors): its type and message."""


# ---------------------------------------------------------------- in the worker processes --

def _start_worker(base: str, connect: bool) -> None:
    """Runs once in each new worker: the app folder, then (connect) the connector loaded and a first
    connection opened (a failure here only means the first query does that work)."""
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.chdir(base)
    if base not in sys.path:
        sys.path.insert(0, base)
    parent = multiprocessing.parent_process()
    if parent is not None:
        threading.Thread(target=_end_with, args=(parent,), name="end-with-server", daemon=True).start()
    if connect:
        try:
            _warm()
        except Exception:
            pass


def _end_with(parent) -> None:
    """Ends this worker when the web server ends. Nothing else would: a worker waits for its next query on
    a pipe it holds both ends of, so when Windows ends the server (the task's End, a restart, an update)
    its workers would otherwise keep running, 130 MB each, one more set at every restart."""
    parent.join()
    os._exit(0)


def _warm() -> int:
    """Loads ADOMD.NET and opens a connection (when a server is set). Returns the worker's process id."""
    import ssas
    if config.SSAS_SERVER:
        ssas.list_databases()
    return os.getpid()


def _portable(exc: Exception) -> Exception:
    """The error as it is if it can travel between processes, else a CubeError with its type and text."""
    try:
        pickle.loads(pickle.dumps(exc))
        return exc
    except Exception:
        return CubeError(f"{type(exc).__name__}: {exc}")


def _run_query(query: str, max_rows, conn_str, database, settings: dict, extra: dict | None = None):
    import ssas
    for name, value in settings.items():
        setattr(config, name, value)
    try:
        return ssas.run_query(query, max_rows=max_rows, conn_str=conn_str, database=database, **(extra or {}))
    except Exception as exc:
        raise _portable(exc) from None


# ---------------------------------------------------------------- in the web server --

class QueryPool:
    """The worker processes, started again if one of them dies (a crash in .NET breaks the whole pool)."""

    def __init__(self, workers: int = WORKERS, connect: bool = True):
        self.workers, self.connect = workers, connect
        self.warm = False
        self._lock = threading.Lock()
        self._executor = self._new()

    def _new(self) -> concurrent.futures.ProcessPoolExecutor:
        return concurrent.futures.ProcessPoolExecutor(
            max_workers=self.workers, mp_context=multiprocessing.get_context("spawn"),
            initializer=_start_worker, initargs=(APP_DIR, self.connect))

    def call(self, fn, *args):
        """fn(*args) in a worker; waits for the result. Starts the pool again once if it broke."""
        executor = self._executor
        try:
            return executor.submit(fn, *args).result()
        except BrokenProcessPool:
            with self._lock:
                if self._executor is executor:
                    executor.shutdown(wait=False, cancel_futures=True)
                    self._executor = self._new()
                    self.warm = False
                    threading.Thread(target=self._warm_quietly, name="pool-rewarm", daemon=True).start()
            return self._executor.submit(fn, *args).result()

    def _warm_quietly(self) -> None:
        try:
            self.warm_up()
        except Exception:
            pass  # broke again: the next call starts it once more

    def warm_up(self) -> list[int]:
        """Start every worker now instead of on the first queries: one small task each, all at once, so the
        pool starts them all; each connects as it starts (_start_worker) and then answers the task."""
        futures = [self._executor.submit(os.getpid) for _ in range(self.workers)]
        pids = [f.result() for f in futures]
        self.warm = True
        return pids

    def pids(self) -> list[int]:
        return sorted(getattr(self._executor, "_processes", None) or {})

    def shutdown(self) -> None:
        executor = self._executor
        for process in list((getattr(executor, "_processes", None) or {}).values()):
            try:
                process.terminate()  # a worker may be inside a long .NET call
            except Exception:
                pass
        executor.shutdown(wait=False, cancel_futures=True)


_pool: QueryPool | None = None
_originals: dict = {}


def active() -> QueryPool | None:
    return _pool


def install(workers: int = WORKERS) -> QueryPool:
    """Send every ssas.run_query of this process to the worker processes (once)."""
    global _pool
    import dashboards
    import ssas
    if _pool is not None:
        return _pool
    _pool = QueryPool(workers)
    _originals.update(run_query=ssas.run_query, start_refresh=dashboards._start_refresh)

    def run_query(query: str, max_rows: int | None = None, conn_str: str | None = None,
                  database: str | None = None, **extra):
        settings = {name: getattr(config, name) for name in SETTINGS}
        # the cube is worked out here: ssas.using() sets it for this thread only
        return _pool.call(_run_query, query, max_rows, conn_str, ssas.current_database(database), settings, extra)

    run_query.__doc__ = ssas.run_query.__doc__
    run_query.pooled = True
    ssas.run_query = run_query
    # Dashboards bring charts up to date in a process of their own each (dashboards._start_refresh), to keep
    # .NET reads out of the app; with the pool the reads are already elsewhere, so a thread that waits for
    # the workers does the same without starting Python and the connector again for every chart.
    dashboards._start_refresh = _refresh_in_thread
    return _pool


def _refresh_in_thread(chart, start, end, compare, as_of):
    import dashboards
    return dashboards._background.submit(dashboards._run_and_save, chart, start, end, compare, as_of)


def uninstall() -> None:
    """Back to running queries in this process (and the workers stopped)."""
    global _pool
    import dashboards
    import ssas
    if _pool is None:
        return
    ssas.run_query = _originals["run_query"]
    dashboards._start_refresh = _originals["start_refresh"]
    _pool.shutdown()
    _pool = None
