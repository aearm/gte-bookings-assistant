"""What each question costs and how long each part takes: every Claude call (model, tokens, cache
use, seconds, dollars) and each stage (planning, checks, the query, the chart). Saved one line per
question in data/usage.jsonl; the Usage page (admins) shows it, and bench.py compares runs.

    with usage.track("question", "Top 10 customers by sales"):
        with usage.stage("plan"):
            ...                       # Claude calls inside are recorded by llm._create
"""
import contextvars
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime

import config

# $ per million tokens: (input, output, cache read). Cache writes cost 1.25x input (5-minute cache)
# or 2x input (1-hour cache).
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
_current = contextvars.ContextVar("usage_recorder", default=None)
_write_lock = threading.Lock()


def usage_file():
    return config.DATA_DIR / "usage.jsonl"


def call_cost(model: str, tokens: dict) -> float:
    price_in, price_out, price_read = next((p for m, p in PRICES.items() if model.startswith(m)), PRICES["claude-sonnet-5-5"])
    return (tokens["input"] * price_in + tokens["output"] * price_out + tokens["cache_read"] * price_read
            + tokens["cache_write_5m"] * price_in * 1.25 + tokens["cache_write_1h"] * price_in * 2) / 1_000_000


def _tokens(u) -> dict:
    """The token counts of a response's usage (works for messages and beta messages)."""
    created = getattr(u, "cache_creation", None)
    write_1h = (getattr(created, "ephemeral_1h_input_tokens", 0) or 0) if created else 0
    write_all = getattr(u, "cache_creation_input_tokens", 0) or 0
    return {"input": getattr(u, "input_tokens", 0) or 0, "output": getattr(u, "output_tokens", 0) or 0,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write_1h": write_1h, "cache_write_5m": max(write_all - write_1h, 0)}


class Recorder:
    def __init__(self, kind: str, label: str, **meta):
        self.kind, self.label, self.meta = kind, label, meta
        self.calls: list[dict] = []
        self.stages: dict[str, float] = {}
        self.started = time.perf_counter()
        self._lock = threading.Lock()

    def add_call(self, purpose: str, model: str, usage, seconds: float) -> None:
        tokens = _tokens(usage)
        call = {"purpose": purpose, "model": model, "seconds": round(seconds, 2), **tokens,
                "cost": round(call_cost(model, tokens), 5)}
        with self._lock:
            self.calls.append(call)

    def summary(self) -> dict:
        calls = list(self.calls)
        total = lambda key: sum(c[key] for c in calls)
        read, uncached = total("cache_read"), total("input") + total("cache_write_5m") + total("cache_write_1h")
        return {"time": datetime.now().isoformat(timespec="seconds"), "kind": self.kind, "label": self.label,
                **self.meta, "seconds": round(time.perf_counter() - self.started, 2),
                "stages": {k: round(v, 2) for k, v in self.stages.items()},
                "claude_calls": len(calls), "claude_seconds": round(total("seconds"), 2),
                "input_tokens": total("input"), "output_tokens": total("output"), "cache_read_tokens": read,
                "cache_write_tokens": total("cache_write_5m") + total("cache_write_1h"),
                "cache_hit": round(read / (read + uncached), 3) if read + uncached else 0.0,
                "cost": round(total("cost"), 4), "calls": calls}


@contextmanager
def track(kind: str, label: str = "", **meta):
    """Record everything inside as one entry of data/usage.jsonl (also when it fails)."""
    rec = Recorder(kind, label, **meta)
    token = _current.set(rec)
    try:
        yield rec
    except Exception as exc:
        rec.meta["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        raise
    finally:
        _current.reset(token)
        save(rec.summary())


@contextmanager
def stage(name: str):
    """Time a part of the current entry (does nothing outside track())."""
    rec, started = _current.get(), time.perf_counter()
    try:
        yield
    finally:
        if rec is not None:
            with rec._lock:
                rec.stages[name] = rec.stages.get(name, 0.0) + time.perf_counter() - started


def note(**meta) -> None:
    """Add facts to the current entry, e.g. note(outcome="data", cubes=[...])."""
    rec = _current.get()
    if rec is not None:
        rec.meta.update(meta)


def record_call(purpose: str, model: str, usage, seconds: float) -> None:
    """Called for every Claude response (by llm._create). Outside track() it is saved on its own."""
    rec = _current.get()
    if rec is not None:
        rec.add_call(purpose, model, usage, seconds)
        return
    single = Recorder("claude_call", purpose)
    single.add_call(purpose, model, usage, seconds)
    save(single.summary())


def save(entry: dict) -> None:
    try:
        path = usage_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # measuring must never break answering


def load(limit: int | None = None, kind: str | None = None) -> list[dict]:
    path = usage_file()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind is None or row.get("kind") == kind:
            rows.append(row)
    return rows[-limit:] if limit else rows


def in_thread(fn):
    """fn wrapped so it records into the current entry when run in worker threads."""
    rec = _current.get()

    def run(*args, **kwargs):
        token = _current.set(rec)
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)
    return run
