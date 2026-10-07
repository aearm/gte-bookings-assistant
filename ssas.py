"""Talks to the Analysis Services model. Windows only (needs Microsoft ADOMD.NET)."""
import ctypes
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

_DLL_NAME = "Microsoft.AnalysisServices.AdomdClient.dll"
# Places ADOMD.NET can be, in order of preference
_SEARCH_ROOTS = [
    config.BASE_DIR / "adomd",  # downloaded by get_adomd.py
    Path(r"C:\Windows\Microsoft.NET\assembly\GAC_MSIL\Microsoft.AnalysisServices.AdomdClient"),  # MSI v19+
    Path(r"C:\Program Files\Microsoft.NET\ADOMD.NET"),        # older MSI versions
    Path(r"C:\Program Files (x86)\Microsoft.NET\ADOMD.NET"),
]
_adomd_ready = False


def _version_key(path: Path) -> tuple:
    """'v4.0_19.84.1.0__89845dcd8080cc91' or '160' -> comparable numbers (newest wins)."""
    name = path.parent.name.split("__")[0]
    return tuple(int(n) for n in re.findall(r"\d+", name))


def _load_adomd() -> None:
    """Put the ADOMD.NET folder on the path so pyadomd can load it."""
    global _adomd_ready
    if _adomd_ready:
        return
    folder = config.ADOMD_PATH
    if not folder:
        for root in _SEARCH_ROOTS:
            if root.exists():
                dlls = sorted(root.rglob(_DLL_NAME), key=_version_key, reverse=True)
                if dlls:
                    folder = str(dlls[0].parent)
                    break
    if not folder or not (Path(folder) / _DLL_NAME).exists():
        raise RuntimeError(
            "ADOMD.NET was not found. Install it from Microsoft (README step 2), or run "
            "'python get_adomd.py' to download it into this folder, or set ADOMD_PATH "
            f"in .env to the folder that contains {_DLL_NAME}."
        )
    sys.path.append(folder)
    _adomd_ready = True


def _quote(value: str) -> str:
    """Make a value safe inside a connection string (handles ; = and quotes)."""
    if any(ch in value for ch in ';="\'') or value != value.strip():
        return '"' + value.replace('"', '""') + '"'
    return value


def get_password() -> str:
    if config.SSAS_PASSWORD:
        return config.SSAS_PASSWORD
    try:
        import keyring
        return keyring.get_password(config.KEYRING_SERVICE, config.SSAS_USERNAME) or ""
    except Exception:
        return ""


def _require_password() -> str:
    password = get_password()
    if not password:
        raise RuntimeError(
            f"No password saved for {config.SSAS_USERNAME}. Run: python set_password.py")
    return password


def _is_http() -> bool:
    return config.SSAS_SERVER.lower().startswith(("http://", "https://"))


def connection_string() -> str:
    if not config.SSAS_SERVER:
        raise RuntimeError("No bookings server is set yet. An admin can add it on the ⚙️ Settings page.")
    parts = [f"Data Source={_quote(config.SSAS_SERVER)}",
             f"Catalog={_quote(config.SSAS_DATABASE)}"]
    # Over HTTP the login goes in the connection string. Over TCP ADOMD.NET ignores it and
    # signs in as the current Windows user, so run_query uses _network_login() instead.
    if config.SSAS_USERNAME and _is_http():
        parts += [f"User ID={_quote(config.SSAS_USERNAME)}", f"Password={_quote(_require_password())}"]
    return ";".join(parts) + ";" + config.SSAS_CONNECTION_EXTRA


@contextmanager
def _network_login():
    """Use SSAS_USERNAME + password as the Windows login for network connections only,
    like 'runas /netonly' or Power BI's 'alternate credentials'. Does nothing without a username."""
    if not config.SSAS_USERNAME or _is_http():
        yield
        return
    domain, _, user = config.SSAS_USERNAME.rpartition("\\")  # DOMAIN\user or user@domain
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    token = ctypes.c_void_p()
    # 9 = LOGON32_LOGON_NEW_CREDENTIALS, 3 = LOGON32_PROVIDER_WINNT50
    if not advapi32.LogonUserW(user, domain or None, _require_password(), 9, 3, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not advapi32.ImpersonateLoggedOnUser(token):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            advapi32.RevertToSelf()
    finally:
        ctypes.windll.kernel32.CloseHandle(token)


def run_query(query: str, max_rows: int | None = None, conn_str: str | None = None) -> pd.DataFrame:
    """Run a DAX (or DMV) query and return the result as a table."""
    _load_adomd()
    from pyadomd import Pyadomd  # imported here because it needs the DLL path first

    with _network_login(), Pyadomd(conn_str or connection_string()) as conn:
        with conn.cursor().execute(query) as cur:
            columns = [c.name for c in cur.description]
            rows = []
            for row in cur.fetchone():  # pyadomd's fetchone() yields rows one by one
                rows.append(row)
                if max_rows and len(rows) >= max_rows:
                    break
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:  # .NET decimals etc. come back as objects; make them numbers
        if df[col].dtype == object:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
    return df


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """'Date'[Year] -> Year, [Total Bookings] -> Total Bookings (keeps names unique)."""
    short = []
    for col in df.columns:
        parts = re.findall(r"\[([^\]]+)\]", str(col))
        short.append(parts[-1] if parts else str(col))
    final = []
    for orig, name in zip(df.columns, short):
        if short.count(name) > 1:
            name = re.sub(r"[\[\]']", " ", str(orig)).strip()
            name = re.sub(r"\s+", " ", name)
        final.append(name)
    out = df.copy()
    out.columns = final
    return out


# ---------------------------------------------------------------- schema --

_DATA_TYPES = {2: "Text", 6: "Whole number", 8: "Decimal", 9: "Date/time",
               10: "Currency", 11: "True/False", 17: "Binary", 20: "Variant"}


def _is_true(value) -> bool:
    return str(value).strip().lower() in ("true", "1")


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short(text, limit=200) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _tabular_schema() -> tuple[list[dict], list[dict]]:
    tables = run_query("SELECT * FROM $SYSTEM.TMSCHEMA_TABLES")
    columns = run_query("SELECT * FROM $SYSTEM.TMSCHEMA_COLUMNS")
    measures = run_query("SELECT * FROM $SYSTEM.TMSCHEMA_MEASURES")
    table_names = dict(zip(tables["ID"], tables["Name"]))
    hidden_tables = set(tables.loc[tables["IsHidden"].map(_is_true), "ID"])

    cols = []
    for _, c in columns.iterrows():
        if c["TableID"] in hidden_tables or _is_true(c.get("IsHidden")):
            continue
        if _int(c.get("Type"), 1) == 3:  # internal RowNumber column
            continue
        name = _short(c.get("ExplicitName")) or _short(c.get("InferredName"))
        if not name:
            continue
        dtype = _DATA_TYPES.get(_int(c.get("ExplicitDataType")), "")
        cols.append({"table": table_names.get(c["TableID"], "?"), "column": name,
                     "type": dtype, "description": _short(c.get("Description"))})

    meas = []
    for _, m in measures.iterrows():
        if _is_true(m.get("IsHidden")):
            continue
        meas.append({"name": m["Name"], "table": table_names.get(m["TableID"], "?"),
                     "description": _short(m.get("Description")),
                     "format": _short(m.get("FormatString"), 40),
                     "formula": _short(m.get("Expression"), 250)})
    return cols, meas


def _multidimensional_schema() -> tuple[list[dict], list[dict]]:
    """Fallback for older cube-style models. Names are a best guess for DAX."""
    measures = run_query("SELECT * FROM $SYSTEM.MDSCHEMA_MEASURES")
    levels = run_query("SELECT * FROM $SYSTEM.MDSCHEMA_LEVELS")
    measures = measures[~measures["CUBE_NAME"].astype(str).str.startswith("$")]
    levels = levels[~levels["CUBE_NAME"].astype(str).str.startswith("$")]

    meas, seen = [], set()
    for _, m in measures.iterrows():
        if "MEASURE_IS_VISIBLE" in m and not _is_true(m["MEASURE_IS_VISIBLE"]):
            continue
        if m["MEASURE_NAME"] in seen:
            continue
        seen.add(m["MEASURE_NAME"])
        meas.append({"name": m["MEASURE_NAME"], "table": m.get("MEASUREGROUP_NAME", ""),
                     "description": _short(m.get("DESCRIPTION")),
                     "format": _short(m.get("DEFAULT_FORMAT_STRING"), 40), "formula": ""})

    cols, seen = [], set()
    for _, lv in levels.iterrows():
        dim = str(lv["DIMENSION_UNIQUE_NAME"]).strip("[]")
        level = str(lv["LEVEL_NAME"])
        if dim == "Measures" or level == "(All)" or (dim, level) in seen:
            continue
        if "LEVEL_IS_VISIBLE" in lv and not _is_true(lv["LEVEL_IS_VISIBLE"]):
            continue
        seen.add((dim, level))
        cols.append({"table": dim, "column": level, "type": "",
                     "description": _short(lv.get("DESCRIPTION"))})
    return cols, meas


def build_schema_text() -> tuple[str, int, int]:
    """Read the model's tables, columns and measures and format them for Claude."""
    try:
        cols, meas = _tabular_schema()
        kind = "Tabular"
    except Exception:
        cols, meas = _multidimensional_schema()
        kind = "Multidimensional (cube) - column names are approximate"

    lines = [
        f"# Model: {config.SSAS_DATABASE}",
        f"Server: {config.SSAS_SERVER} | Type: {kind} | Read on {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "## Measures (use these for any numbers)",
    ]
    for m in sorted(meas, key=lambda x: (str(x["table"]), str(x["name"]))):
        line = f"- [{m['name']}]  (in '{m['table']}')"
        if m["description"]:
            line += f" - {m['description']}"
        if m["format"]:
            line += f" | format: {m['format']}"
        if m["formula"]:
            line += f" | formula: {m['formula']}"
        lines.append(line)

    lines += ["", "## Tables and columns (use these to group and filter)"]
    current = None
    for c in sorted(cols, key=lambda x: (str(x["table"]), str(x["column"]))):
        if c["table"] != current:
            current = c["table"]
            lines += ["", f"### '{current}'"]
        line = f"- '{c['table']}'[{c['column']}]"
        if c["type"]:
            line += f" ({c['type']})"
        if c["description"]:
            line += f" - {c['description']}"
        lines.append(line)
    return "\n".join(lines) + "\n", len(cols), len(meas)
