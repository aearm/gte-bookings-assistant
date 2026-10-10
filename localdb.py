"""Local data mode: loads CSV / Excel files from data/local and queries them with SQL.
Works on Mac, Windows and Linux (no server needed)."""
import re
import threading
from datetime import datetime

import duckdb
import pandas as pd

import config
import cubes
import value_index

_lock = threading.Lock()
_con = None
_signature = None
_tables: dict[str, str] = {}  # table name -> source file name

SUPPORTED = (".csv", ".xlsx", ".xls", ".parquet")


def _files():
    folder = config.LOCAL_DATA_DIR
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in SUPPORTED and not p.name.startswith(("~", ".")))


def _table_name(text: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "data"
    return name if not name[0].isdigit() else f"t_{name}"


def _connection():
    """Load (or reload, if files changed) all data files into an in-memory database."""
    global _con, _signature, _tables
    files = _files()
    signature = tuple((p.name, p.stat().st_mtime, p.stat().st_size) for p in files)
    with _lock:
        if _con is not None and signature == _signature:
            return _con
        con = duckdb.connect(":memory:")
        tables = {}
        for path in files:
            suffix = path.suffix.lower()
            if suffix == ".csv":
                name = _table_name(path.stem)
                con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM read_csv_auto(?, header=true)', [str(path)])
                tables[name] = path.name
            elif suffix == ".parquet":
                name = _table_name(path.stem)
                con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM read_parquet(?)', [str(path)])
                tables[name] = path.name
            else:
                sheets = pd.read_excel(path, sheet_name=None)
                for sheet, df in sheets.items():
                    df.columns = [str(c).strip() for c in df.columns]
                    name = _table_name(path.stem if len(sheets) == 1 else f"{path.stem}_{sheet}")
                    con.register("_tmp_df", df)
                    con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _tmp_df')
                    con.unregister("_tmp_df")
                    tables[name] = f"{path.name} (sheet {sheet})"
        # Queries can only read the loaded tables: no access to other files or the internet.
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        _con, _signature, _tables = con, signature, tables
        return con


def validate_sql(sql: str) -> None:
    body = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL).strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", body, flags=re.IGNORECASE):
        raise ValueError("Generated query is not a SELECT statement, so it was not run.")
    if ";" in body:
        raise ValueError("Generated query contains more than one statement, so it was not run.")


def run_query(sql: str, max_rows: int | None = None) -> pd.DataFrame:
    validate_sql(sql)
    cur = _connection().cursor()  # a cursor per query keeps it thread-safe
    try:
        cur.execute(sql.strip().rstrip(";"))
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows) if max_rows else cur.fetchall()
    finally:
        cur.close()
    return pd.DataFrame(rows, columns=columns)


def _tables_with(column: str) -> list[str]:
    name = column.strip('"')
    return [t for (t,) in _connection().execute(
        "SELECT table_name FROM information_schema.columns WHERE column_name = ?", [name]).fetchall()]


def find_values(column: str, group_with: list[str], values: list[str]) -> dict[str, str | None]:
    """For each value, the matching value in the data (ignoring case), or None if there is none."""
    found = {}
    cur = _connection().cursor()
    try:
        for table in _tables_with(column):
            marks = ", ".join("?" * len(values))
            rows = cur.execute(f'SELECT DISTINCT {column} FROM "{table}" '
                               f'WHERE lower(CAST({column} AS VARCHAR)) IN ({marks})',
                               [v.lower() for v in values]).fetchall()
            found.update({str(r[0]).lower(): str(r[0]) for r in rows})
    finally:
        cur.close()
    return {v: found.get(v.lower()) for v in values}


def search_values(column: str, group_with: list[str], text: str, limit: int = 6) -> list[str]:
    """Values of the column containing the text (ignoring case)."""
    out = []
    cur = _connection().cursor()
    try:
        for table in _tables_with(column):
            rows = cur.execute(f'SELECT DISTINCT {column} FROM "{table}" WHERE CAST({column} AS VARCHAR) ILIKE ? '
                               f'LIMIT {int(limit)}', [f"%{text}%"]).fetchall()
            out += [str(r[0]) for r in rows]
    finally:
        cur.close()
    return list(dict.fromkeys(out))[:limit]


def build_schema_text() -> tuple[str, int, int]:
    """Describe every table: columns, types, value ranges and example values."""
    con = _connection()
    if not _tables:
        raise RuntimeError(f"No data files found. Put CSV or Excel files in {config.LOCAL_DATA_DIR}")
    lines = [
        "# Local data (DuckDB SQL)",
        f"Folder: data/local | Read on {datetime.now():%Y-%m-%d %H:%M}",
        "Table and column names are case-sensitive; wrap column names in double quotes.",
    ]
    n_cols = 0
    index = {}  # every text value, for value_index (Claude's find_values tool)
    for table, source in _tables.items():
        rows = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        lines += ["", f'## Table "{table}"  ({rows:,} rows, from {source})']
        columns = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [table]).fetchall()
        for col, dtype in columns:
            n_cols += 1
            q = f'"{col}"'
            info = ""
            if any(t in dtype for t in ("INT", "DOUBLE", "DECIMAL", "FLOAT", "DATE", "TIMESTAMP", "BIGINT", "HUGEINT")):
                lo, hi = con.execute(f'SELECT MIN({q}), MAX({q}) FROM "{table}"').fetchone()
                info = f"range {lo} to {hi}"
            elif "VARCHAR" in dtype:
                n_distinct = con.execute(f'SELECT COUNT(DISTINCT {q}) FROM "{table}"').fetchone()[0]
                top = con.execute(f'SELECT {q}, COUNT(*) FROM "{table}" WHERE {q} IS NOT NULL '
                                  f'GROUP BY 1 ORDER BY 2 DESC LIMIT {value_index.INDEX_LIMIT + 1}').fetchall()
                index[q] = ({"group_with": [], "values": [[str(v), n] for v, n in top]}
                            if n_distinct <= value_index.INDEX_LIMIT else
                            {"group_with": [], "live": True, "count": n_distinct})
                top = top[:25]
                quoted = lambda v: '"' + str(v).replace('"', '""') + '"'
                info = ("| values: " + ", ".join(f"{quoted(v)} ({n:,} rows)" for v, n in top) if n_distinct <= 25
                        else f"| {n_distinct:,} values, e.g. " + ", ".join(quoted(v) for v, _ in top[:6]))
            lines.append(f'- "{col}" ({dtype}) {info}'.rstrip())
    value_index.for_cube(cubes.LOCAL).save(index, "")
    return "\n".join(lines) + "\n", n_cols, len(_tables)
