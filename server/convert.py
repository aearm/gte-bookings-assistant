"""Results as the API sends them: tables with typed columns (numbers, text, dates as ISO text, missing
values as null) and charts as ECharts options (chart_options.build_option)."""
import logging
import math
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd

import chart_options

MAX_ROWS = 5000  # rows sent with a table; the rest stay on the server (CSV download has them all)
log = logging.getLogger("server")


# ---------------------------------------------------------------- plain JSON --

def plain(obj):
    """Anything JSON can carry: numbers (NaN and infinity become null), text, ISO dates, lists, dicts."""
    if obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [plain(v) for v in obj.tolist()]
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating, Decimal)):
        number = float(obj)
        return number if math.isfinite(number) else None
    if isinstance(obj, (datetime, date)):
        return _date_text(obj)
    if _missing(obj):
        return None
    return str(obj)


def _missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _date_text(value) -> str | None:
    """'2026-10-14' for a day, '2026-10-14T09:30:00' when it has a time; None when missing."""
    if _missing(value):
        return None
    if isinstance(value, datetime):
        midnight = (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)
        return value.strftime("%Y-%m-%d") if midnight else value.replace(tzinfo=None).isoformat()
    return value.isoformat()


# ---------------------------------------------------------------- tables --

def _is_number(value) -> bool:
    return isinstance(value, (int, float, Decimal, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))


def column_type(series: pd.Series) -> str:
    """"number", "date" or "text" for a result column (DuckDB decimals and dates come as Python objects)."""
    if pd.api.types.is_bool_dtype(series):
        return "text"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    values = series.dropna()
    if len(values) and all(_is_number(v) for v in values):
        return "number"
    if len(values) and all(isinstance(v, (date, datetime)) for v in values):
        return "date"
    return "text"


def _cell(value, kind: str):
    if value is None or _missing(value):
        return None
    if kind == "number":
        return plain(value)
    if kind == "date":
        return _date_text(value) if isinstance(value, (date, datetime)) else str(value)
    return value if isinstance(value, str) else str(value)


def table(df: pd.DataFrame | None, spec: dict | None = None, limit: int = MAX_ROWS) -> dict | None:
    """A result as the contract's Table. Number columns carry the format the chart uses for them
    ("format", see chart_options.py), so the browser writes them the same way."""
    if df is None:
        return None
    kinds = [column_type(df.iloc[:, i]) for i in range(df.shape[1])]
    shown = df.head(limit)
    rows = [[_cell(v, k) for v, k in zip(row, kinds)] for row in shown.itertuples(index=False, name=None)]
    columns = []
    for i, (name, kind) in enumerate(zip(df.columns, kinds)):
        fmt = None
        if kind == "number":
            try:
                fmt = chart_options.value_format(spec or {}, df.iloc[:, [i]].set_axis([str(name)], axis=1), str(name))
            except Exception:
                fmt = None
        columns.append({"name": str(name), "type": kind, "format": fmt})
    return {"columns": columns, "rows": rows, "row_count": int(len(df)), "truncated": len(df) > limit}


# ---------------------------------------------------------------- charts --

def chart(df: pd.DataFrame | None, spec: dict | None, compare: dict | None = None, show_title: bool = True) -> dict | None:
    """A result and its chart spec as the contract's Chart: the ECharts option, or none when a table
    shows it better (kind "table"); headline numbers are kind "kpi" (the browser shows the number)."""
    if df is None:
        return None
    spec = spec or {}
    out = {"kind": spec.get("chart_type") or "table", "option": None, "title": str(spec.get("title") or ""),
           "summary": str(spec.get("summary") or ""), "note": str(spec.get("note") or "")}
    if out["kind"] == "kpi":
        return out
    try:
        option = chart_options.build_option(df, spec, dark=False, compare=compare, show_title=show_title)
    except Exception:
        log.exception("Could not draw a %s chart", out["kind"])
        option = None
        out["note"] = " ".join(x for x in (out["note"], "The chart couldn't be drawn, so the numbers are shown as a table.") if x)
    if option is None:
        out["kind"] = "table"
    else:
        out.update(kind=(option.get("x-app") or {}).get("chart_type") or out["kind"], option=option)
    return out
