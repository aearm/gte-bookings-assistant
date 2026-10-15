"""A local index of every value in every text column of a cube, built when its structure is read.
It answers "where does 'UAE' (or 'Ok', or 'Hilton') appear in the data, and how much data has it?"
in milliseconds, for Claude's find_values tool and for checking queries before they run.
Columns with up to MEMORY_LIMIT values (statuses, markets, countries, channels...) are kept in memory,
from models/<cube>/value_index.json. Bigger ones (customers, hotels, zones...) stay on disk in one
SQLite file shared by all cubes, models/values.db, where each value is stored once and found with an
index, so they cost no memory. Columns with more than INDEX_LIMIT values aren't read at all; they're
searched live on the server. Company data: not in git."""
import difflib
import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import config
import cubes

INDEX_LIMIT = 20_000  # columns with more distinct values than this are searched live
MEMORY_LIMIT = 2_000  # columns with more values than this are kept on disk (models/values.db), not in memory


def column_label(col: str) -> str:
    m = re.match(r"'((?:[^']|'')+)'\[([^\]]+)\]", col)
    return f"{m.group(1)} › {m.group(2)}" if m else col.strip('"')


def _initials(text: str) -> str:
    return "".join(w[0] for w in re.findall(r"[^\W_]+", text)).lower()  # words, accents included


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.lower()))


def _key(text) -> str:
    """How a value or a phrase is compared: lower case, single spaces."""
    return " ".join(str(text).lower().split())


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


# ---------------------------------------------------------------- the disk store (big columns) --

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vals (id INTEGER PRIMARY KEY, col TEXT NOT NULL, value TEXT NOT NULL,
                                 norm TEXT NOT NULL, initials TEXT, UNIQUE (col, value));
CREATE TABLE IF NOT EXISTS counts (cube TEXT NOT NULL, id INTEGER NOT NULL, n REAL,
                                   PRIMARY KEY (cube, id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS vals_norm ON vals (norm);
CREATE INDEX IF NOT EXISTS vals_initials ON vals (initials);
CREATE INDEX IF NOT EXISTS counts_id ON counts (id);
"""
_threads = threading.local()
_write_lock = threading.Lock()


def store_file() -> Path:
    return config.MODELS_DIR / "values.db"


def _read(sql: str, params: list) -> list[tuple]:
    """Rows from the disk store ([] before it exists). One connection per thread, kept open."""
    path = store_file()
    if not path.exists():
        return []
    cons = _threads.__dict__.setdefault("cons", {})
    if path not in cons:
        cons[path] = sqlite3.connect(path, timeout=10, check_same_thread=False)
        cons[path].execute("PRAGMA query_only = 1")
    return cons[path].execute(sql, params).fetchall()


def close() -> None:
    """Close this thread's connections to the disk store (before it is deleted, e.g. in tests)."""
    for con in _threads.__dict__.pop("cons", {}).values():
        con.close()


def _write(cube_key: str, columns: dict[str, list]) -> None:
    """Replace one cube's big columns in the disk store: {column: [[value, count], ...]}. A value shared
    by several cubes is stored once; each cube keeps its own count."""
    path = store_file()
    if not columns and not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        con = sqlite3.connect(path, timeout=60)
        try:
            con.executescript(_SCHEMA)
            con.execute("DELETE FROM counts WHERE cube = ?", (cube_key,))
            for col, values in columns.items():
                con.executemany("INSERT OR IGNORE INTO vals (col, value, norm, initials) VALUES (?, ?, ?, ?)",
                                [(col, str(v), _key(v), _initials(str(v)) if len(str(v).split()) >= 2 else None)
                                 for v, _ in values])
                ids = dict(con.execute("SELECT value, id FROM vals WHERE col = ?", (col,)))
                con.executemany("INSERT OR REPLACE INTO counts VALUES (?, ?, ?)",
                                [(cube_key, ids[str(v)], n) for v, n in values])
            con.execute("DELETE FROM vals WHERE id NOT IN (SELECT id FROM counts)")  # in no cube any more
            con.commit()
        finally:
            con.close()


# ---------------------------------------------------------------- one cube's index --

class ValueIndex:
    """The value index of one cube."""

    def __init__(self, path: Path):
        self.path = path
        self.key = path.parent.name  # the cube's rows in the disk store
        self._lock = threading.Lock()
        self._mtime = None
        self._data = {}

    def save(self, columns: dict, measure: str, built: str | None = None) -> None:
        """columns: {column: {"group_with": [...], "values": [[value, count], ...]}} or
        {column: {"group_with": [...], "live": True, "count": n}} for columns too big to index.
        Columns with more than MEMORY_LIMIT values go to the disk store."""
        kept, big = {}, {}
        for col, info in columns.items():
            if len(info.get("values", ())) > MEMORY_LIMIT:
                big[col] = info["values"]
                kept[col] = {"group_with": info.get("group_with", []), "on_disk": True, "count": len(info["values"])}
            else:
                kept[col] = info
        _write(self.key, big)
        data = {"built": built or datetime.now().isoformat(timespec="seconds"), "measure": measure, "columns": kept}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> dict:
        """The index (cached in memory until the file changes), or {} if it hasn't been built yet.
        An index saved before big columns went to disk is converted the first time it is read."""
        if not self.path.exists():
            return {}
        mtime = self.path.stat().st_mtime
        with self._lock:
            if self._mtime != mtime:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if any(len(i.get("values", ())) > MEMORY_LIMIT for i in data.get("columns", {}).values()):
                    self.save(data["columns"], data.get("measure", ""), built=data.get("built"))
                    mtime = self.path.stat().st_mtime
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

    def indexed(self, column: str) -> bool:
        """Whether every value of the column is known here (in memory or on disk)."""
        info = self.column_info(column)
        return bool(info and ("values" in info or info.get("on_disk")))

    def disk_columns(self) -> list[str]:
        return [c for c, info in self.columns().items() if info.get("on_disk")]

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

    def _disk(self, where: str, params: list, column: str = "") -> list[tuple]:
        """(column, value, count, norm, initials) of this cube's values on disk matching `where`."""
        if not self.disk_columns():
            return []
        sql = ("SELECT v.col, v.value, c.n, v.norm, v.initials FROM counts c JOIN vals v ON v.id = c.id "
               "WHERE c.cube = ?" + (" AND v.col = ?" if column else "") + f" AND ({where})")
        return _read(sql, [self.key] + ([column] if column else []) + params)

    def lookup(self, column: str, values: list[str]) -> dict[str, str | None] | None:
        """{value: the real value (ignoring case) or None}, or None if the column isn't indexed."""
        info = self.column_info(column)
        if info and "values" in info:
            return {v: info["lookup"].get(v.lower().strip()) for v in values}
        if not (info and info.get("on_disk")):
            return None
        keys = {v: _key(v) for v in values}
        found = {}
        for _, value, n, norm, _ in self._disk(f"v.norm IN ({','.join('?' * len(keys))})", list(keys.values()), column):
            if norm not in found or (n or 0) > found[norm][1]:
                found[norm] = (value, n or 0)
        return {v: found[k][0] if k in found else None for v, k in keys.items()}

    def has_no_data(self, column: str, value: str) -> bool:
        info = self.column_info(column)
        if info and "values" in info:
            return any(v == value and not n for v, n in info["values"])
        if info and info.get("on_disk"):
            return any(not n for _, _, n, _, _ in self._disk("v.value = ?", [value], column))
        return False

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
        if any(not column or c == column for c in self.disk_columns()):
            for col, value, n, _, _ in self._disk_candidates(text, column):
                s = _score(text, str(value))
                if s:
                    hits.append({"column": col, "value": value, "count": n, "score": s})
        hits.sort(key=lambda h: (-h["score"], -(h["count"] or 0)))
        return hits[:limit]

    def _disk_candidates(self, text: str, column: str) -> list[tuple]:
        """Values on disk that could score: containing the text, with it as initials, or (for typos)
        of a similar length with the same first two letters. _score then ranks them."""
        t = _key(text)
        if not t:
            return []
        like = "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where, params = "v.norm LIKE ? ESCAPE '\\' OR v.initials = ?", [like, t]
        if len(t) >= 4:
            where += " OR (substr(v.norm, 1, 2) = ? AND length(v.norm) BETWEEN ? AND ?)"
            params += [t[:2], len(t) - max(3, len(t) // 2), len(t) + max(3, len(t) // 2)]
        return self._disk(where, params, column)

    def live_columns(self) -> list[str]:
        return [c for c, info in self.columns().items() if info.get("live")]

    def exact(self, text: str) -> list[dict]:
        """Values that are exactly the text (ignoring case), or whose initials are (UAE -> UNITED ARAB
        EMIRATES): [{column, value, count}]."""
        return [{k: h[k] for k in ("column", "value", "count")} for h in self.exact_many([text])]

    def exact_many(self, phrases: list[str]) -> list[dict]:
        """exact() for several phrases at once (one look on disk): [{text, column, value, count}].
        A dictionary lookup per column in memory, an index lookup on disk, so it is instant."""
        typed = {}  # key -> the phrase as written
        for p in phrases:
            if _key(p):
                typed.setdefault(_key(p), p)
        keys = list(typed)
        by_initials = [k for k in keys if len(k) >= 2 and " " not in k]
        hits = []
        for col, info in self.columns().items():
            if "values" not in info:
                continue
            for key in keys:
                value = info["lookup"].get(key)
                if value is None and key in by_initials:
                    value = self._initials(col, info).get(key)
                if value is not None:
                    hits.append({"text": typed[key], "column": col, "value": value, "count": info["counts"].get(value)})
        if keys and self.disk_columns():
            marks = lambda items: ",".join("?" * len(items)) or "NULL"
            best = {}  # (column, phrase) -> (rank, count, value): the exact value, else the most data
            for col, value, n, norm, initials in self._disk(
                    f"v.norm IN ({marks(keys)}) OR v.initials IN ({marks(by_initials)})", keys + by_initials):
                for key, rank in ((norm, 2), (initials, 1)):
                    if key in keys and (rank == 2 or key in by_initials):
                        if (col, key) not in best or (rank, n or 0) > best[(col, key)][:2]:
                            best[(col, key)] = (rank, n or 0, value, n)
            hits += [{"text": typed[key], "column": col, "value": v[2], "count": v[3]} for (col, key), v in best.items()]
        return hits

    def all_values(self) -> list[tuple[str, list]]:
        """(column, its values) for every indexed column, in memory or on disk (to compare cubes)."""
        out = [(col, [v for v, _ in info["values"]]) for col, info in self.columns().items() if "values" in info]
        disk: dict[str, list] = {}
        for col, value, *_ in self._disk("1 = 1", []):
            disk.setdefault(col, []).append(value)
        return out + list(disk.items())

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
