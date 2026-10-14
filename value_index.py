"""A local index of every value in every text column of a cube, built when its structure is read.
It answers "where does 'UAE' (or 'Ok', or 'Hilton') appear in the data, and how much data has it?"
in milliseconds, for Claude's find_values tool and for checking queries before they run.
One index per cube, in models/<cube>/value_index.json (company data: not in git). Columns with too
many values to index (e.g. product names) are searched live on the server instead."""
import difflib
import json
import re
import threading
from datetime import datetime
from pathlib import Path

import cubes

INDEX_LIMIT = 20_000  # columns with more distinct values than this are searched live


def column_label(col: str) -> str:
    m = re.match(r"'((?:[^']|'')+)'\[([^\]]+)\]", col)
    return f"{m.group(1)} › {m.group(2)}" if m else col.strip('"')


def _initials(text: str) -> str:
    return "".join(w[0] for w in re.findall(r"[^\W_]+", text)).lower()  # words, accents included


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.lower()))


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


class ValueIndex:
    """The value index of one cube."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._mtime = None
        self._data = {}

    def save(self, columns: dict, measure: str) -> None:
        """columns: {column: {"group_with": [...], "values": [[value, count], ...]}} or
        {column: {"group_with": [...], "live": True, "count": n}} for columns too big to index."""
        data = {"built": datetime.now().isoformat(timespec="seconds"), "measure": measure, "columns": columns}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> dict:
        """The index (cached in memory until the file changes), or {} if it hasn't been built yet."""
        if not self.path.exists():
            return {}
        mtime = self.path.stat().st_mtime
        with self._lock:
            if self._mtime != mtime:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for info in data.get("columns", {}).values():
                    if "values" in info:
                        info["lookup"] = {str(v).lower().strip(): v for v, _ in info["values"]}
                        info["counts"] = {v: n for v, n in info["values"]}
                self._mtime, self._data = mtime, data
            return self._data

    def columns(self) -> dict:
        return self.load().get("columns", {})

    def column_info(self, column: str) -> dict | None:
        return self.columns().get(column)

    def count_label(self) -> str:
        measure = self.load().get("measure", "")
        return measure.strip("[]") if measure else "rows"

    def resolve_column(self, text: str) -> str:
        """The indexed column meant by text, however it is written: 'Booking Status'[Status Name],
        Booking Status[Status Name], Booking Status › Status Name, or just Status Name if unique."""
        cols = self.columns()
        if not text or text in cols:
            return text
        plain = _plain(text)
        for col in cols:
            if _plain(col) == plain:
                return col
        by_name = [c for c in cols if _plain(re.findall(r"\[([^\]]+)\]", c)[-1] if "[" in c else c) == plain]
        return by_name[0] if len(by_name) == 1 else text

    def lookup(self, column: str, values: list[str]) -> dict[str, str | None] | None:
        """{value: the real value (ignoring case) or None}, or None if the column isn't indexed."""
        info = self.column_info(column)
        if not info or "values" not in info:
            return None
        return {v: info["lookup"].get(v.lower().strip()) for v in values}

    def has_no_data(self, column: str, value: str) -> bool:
        info = self.column_info(column)
        return bool(info and "values" in info and any(v == value and not n for v, n in info["values"]))

    def search(self, text: str, column: str = "", limit: int = 15) -> list[dict]:
        """Indexed values similar to the text, best first: [{column, value, count}]."""
        hits = []
        for col, info in self.columns().items():
            if (column and col != column) or "values" not in info:
                continue
            for value, n in info["values"]:
                s = _score(text, str(value))
                if s:
                    hits.append({"column": col, "value": value, "count": n, "score": s})
        hits.sort(key=lambda h: (-h["score"], -(h["count"] or 0)))
        return hits[:limit]

    def live_columns(self) -> list[str]:
        return [c for c, info in self.columns().items() if info.get("live")]

    def exact(self, text: str) -> list[dict]:
        """Values that are exactly the text (ignoring case), or whose initials are (UAE -> UNITED ARAB
        EMIRATES): [{column, value, count}]. A dictionary lookup per column, so it is instant."""
        key = " ".join(text.lower().split())
        hits = []
        for col, info in self.columns().items():
            if "values" not in info:
                continue
            value = info["lookup"].get(key)
            if value is None and len(key) >= 2 and " " not in key:
                value = self._initials(col, info).get(key)
            if value is not None:
                hits.append({"column": col, "value": value, "count": info["counts"].get(value)})
        return hits

    def _initials(self, column: str, info: dict) -> dict:
        if "initials" not in info:
            info["initials"] = {_initials(v): v for v, _ in reversed(info["values"])
                                if len(str(v).split()) >= 2}  # most data wins when initials repeat
        return info["initials"]


_indexes: dict[Path, ValueIndex] = {}
_indexes_lock = threading.Lock()


def for_cube(cube: str) -> ValueIndex:
    path = cubes.index_file(cube)
    with _indexes_lock:
        if path not in _indexes:
            _indexes[path] = ValueIndex(path)
        return _indexes[path]
