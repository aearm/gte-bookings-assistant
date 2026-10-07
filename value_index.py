"""A local index of every value in every text column, built when the data structure is refreshed.
It answers "where does 'UAE' (or 'Ok', or 'Hilton') appear in the data, and how much data has it?"
in milliseconds, for Claude's find_values tool and for checking queries before they run.
Saved in data/value_index.json (company data: not in git). Columns with too many values to index
(e.g. product names) are searched live on the server instead."""
import difflib
import json
import re
import threading
from datetime import datetime

import config

INDEX_LIMIT = 20_000  # columns with more distinct values than this are searched live

_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def column_label(col: str) -> str:
    m = re.match(r"'((?:[^']|'')+)'\[([^\]]+)\]", col)
    return f"{m.group(1)} › {m.group(2)}" if m else col.strip('"')


# ---------------------------------------------------------------- storage --

def save(columns: dict, measure: str) -> None:
    """columns: {column: {"group_with": [...], "values": [[value, count], ...]}} or
    {column: {"group_with": [...], "live": True, "count": n}} for columns too big to index."""
    data = {"built": datetime.now().isoformat(timespec="seconds"), "measure": measure, "columns": columns}
    config.VALUE_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.VALUE_INDEX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.VALUE_INDEX_FILE)


def load() -> dict:
    """The index (cached in memory until the file changes), or {} if it hasn't been built yet."""
    path = config.VALUE_INDEX_FILE
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    with _lock:
        if _cache["mtime"] != mtime:
            data = json.loads(path.read_text(encoding="utf-8"))
            for info in data.get("columns", {}).values():
                if "values" in info:
                    info["lookup"] = {str(v).lower().strip(): v for v, _ in info["values"]}
            _cache.update(mtime=mtime, data=data)
        return _cache["data"]


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.lower()))


def resolve_column(text: str) -> str:
    """The indexed column meant by text, however it is written: 'Booking Status'[Status Name],
    Booking Status[Status Name], Booking Status › Status Name, or just Status Name if unique."""
    columns = load().get("columns", {})
    if not text or text in columns:
        return text
    plain = _plain(text)
    for col in columns:
        if _plain(col) == plain:
            return col
    by_name = [col for col in columns if _plain(re.findall(r"\[([^\]]+)\]", col)[-1] if "[" in col else col) == plain]
    return by_name[0] if len(by_name) == 1 else text


def column_info(column: str) -> dict | None:
    return load().get("columns", {}).get(column)


def count_label() -> str:
    measure = load().get("measure", "")
    return measure.strip("[]") if measure else "rows"


# ---------------------------------------------------------------- lookups --

def lookup(column: str, values: list[str]) -> dict[str, str | None] | None:
    """{value: the real value (ignoring case) or None}, or None if the column isn't indexed."""
    info = column_info(column)
    if not info or "values" not in info:
        return None
    return {v: info["lookup"].get(v.lower().strip()) for v in values}


def has_no_data(column: str, value: str) -> bool:
    info = column_info(column)
    if not info or "values" not in info:
        return False
    return any(v == value and not n for v, n in info["values"])


def _initials(text: str) -> str:
    return "".join(w[0] for w in re.findall(r"[^\W_]+", text)).lower()  # words, accents included


def _score(text: str, value: str) -> float:
    t, v = text.lower().strip(), value.lower().strip()
    if not t or not v:
        return 0
    if t == v:
        return 100
    if len(t) >= 2 and _initials(value) == t:   # UAE -> UNITED ARAB EMIRATES
        return 90
    if re.search(rf"\b{re.escape(t)}\b", v):    # whole word: "Confirmed" in "Confirmed Orders"
        return 80
    if re.search(rf"\b{re.escape(t)}", v):      # start of a word
        return 70
    if len(t) >= 4 and t in v:
        return 55
    if abs(len(t) - len(v)) <= max(3, len(t) // 2):
        ratio = difflib.SequenceMatcher(None, t, v).ratio()
        if ratio >= 0.8:
            return ratio * 60
    return 0


def search(text: str, column: str = "", limit: int = 15) -> list[dict]:
    """Indexed values similar to the text, best first: [{column, value, count}]."""
    hits = []
    for col, info in load().get("columns", {}).items():
        if (column and col != column) or "values" not in info:
            continue
        for value, n in info["values"]:
            s = _score(text, str(value))
            if s:
                hits.append({"column": col, "value": value, "count": n, "score": s})
    hits.sort(key=lambda h: (-h["score"], -(h["count"] or 0)))
    return hits[:limit]


def live_columns() -> list[str]:
    return [c for c, info in load().get("columns", {}).items() if info.get("live")]
