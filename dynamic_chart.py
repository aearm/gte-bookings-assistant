"""Charts drawn the way a user describes them: "bars for sales with a line for profit % on a second
axis", "a funnel of booking statuses", "a sunburst of region and country", "stacked area by
channel, as percentages"... Claude writes a declarative spec - a Plotly figure whose data point at
columns of the result - and this module checks it, fills in the data and lets Plotly validate it.
Nothing in the spec is executed, so it is safe to store on a dashboard and re-draw with new data.

Spec (JSON):
{
  "prepare": {"group_by": ["Month"], "aggregate": {"Sales": "sum"},      # optional, in this order
              "sort_by": "Sales", "descending": true, "top": 10},
  "traces": [
    {"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"}, "name": "Sales"},
    {"type": "scatter", "mode": "lines+markers", "x": {"col": "Month"}, "y": {"col": "Profit %"},
     "yaxis": "y2", "name": "Profit %"},
    {"type": "bar", "x": {"col": "Month"}, "y": {"col": "Bookings"}, "split_by": "Channel"},
    {"type": "sunburst", "path": ["Region", "Country"], "values": {"col": "Sales"}}
  ],
  "layout": {"barmode": "stack", "yaxis2": {"overlaying": "y", "side": "right"}}
}
{"col": "Name"} anywhere in a trace becomes that column's values; "split_by" makes one trace per
value of a column; "path" builds the levels of a treemap / sunburst / icicle."""
import copy
import json
import re

import pandas as pd
import plotly.graph_objects as go

import charts

TRACE_TYPES = {
    "bar", "scatter", "pie", "funnel", "funnelarea", "waterfall", "indicator", "treemap", "sunburst",
    "icicle", "heatmap", "histogram", "histogram2d", "box", "violin", "scatterpolar", "barpolar",
    "choropleth", "scattergeo", "sankey", "table", "contour", "candlestick", "ohlc", "scatterternary",
}
HIERARCHY_TYPES = {"treemap", "sunburst", "icicle"}
AGGREGATES = {"sum", "mean", "min", "max", "count", "median", "first", "last"}
MAX_TRACES = 40
_BLOCKED_LAYOUT = {"images"}  # pictures from the internet
_UNSAFE_TEXT = re.compile(r"javascript:|<\s*script|<\s*iframe|<[^>]*\bon\w+\s*=", re.IGNORECASE)


class ChartSpecError(ValueError):
    """The spec can't be drawn (the message says why, for Claude to fix it)."""


# ---------------------------------------------------------------- reading the spec --

def parse(spec) -> dict:
    """A spec from Claude (JSON text or a dict) as a dict with "traces"."""
    if isinstance(spec, str):
        text = spec.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            spec = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ChartSpecError(f"The chart spec is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise ChartSpecError("The chart spec must be a JSON object with a 'traces' list.")
    spec = copy.deepcopy(spec)
    if "data" in spec and "traces" not in spec:  # a plain Plotly figure
        spec["traces"] = spec.pop("data")
    traces = spec.get("traces")
    if not isinstance(traces, list) or not traces:
        raise ChartSpecError("The chart spec needs a non-empty 'traces' list.")
    for t in traces:
        if not isinstance(t, dict):
            raise ChartSpecError("Each trace must be an object.")
        kind = str(t.get("type", "scatter")).lower()
        if kind not in TRACE_TYPES:
            raise ChartSpecError(f"Trace type '{kind}' is not supported. Use one of: {', '.join(sorted(TRACE_TYPES))}.")
        t["type"] = kind
    if not isinstance(spec.get("layout", {}), dict):
        raise ChartSpecError("'layout' must be an object.")
    _check_text(spec)
    return spec


def _check_text(value) -> None:
    if isinstance(value, str) and _UNSAFE_TEXT.search(value):
        raise ChartSpecError("The chart spec contains text that isn't allowed (links to scripts).")
    if isinstance(value, dict):
        for v in value.values():
            _check_text(v)
    elif isinstance(value, list):
        for v in value:
            _check_text(v)


def columns_used(spec: dict) -> set[str]:
    """Every result column the spec refers to."""
    found = set()

    def walk(v):
        if isinstance(v, dict):
            if set(v) == {"col"} and isinstance(v["col"], str):
                found.add(v["col"])
                return
            for k, x in v.items():
                if k in ("split_by",) and isinstance(x, str):
                    found.add(x)
                elif k == "path" and isinstance(x, list):
                    found.update(str(p.get("col") if isinstance(p, dict) else p) for p in x)
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(spec.get("traces", []))
    prep = spec.get("prepare") or {}
    found.update(prep.get("group_by") or [])
    found.update((prep.get("aggregate") or {}).keys())
    if prep.get("sort_by"):
        found.add(prep["sort_by"])
    return found


# ---------------------------------------------------------------- data --

def _column(df: pd.DataFrame, name: str) -> str:
    """The real column name (ignoring case and spaces), or ChartSpecError listing the columns."""
    if name in df.columns:
        return name
    plain = lambda s: re.sub(r"\s+", " ", str(s)).strip().lower()
    for c in df.columns:
        if plain(c) == plain(name):
            return c
    raise ChartSpecError(f"Column '{name}' is not in the result. Columns: {', '.join(map(str, df.columns))}.")


def prepare(df: pd.DataFrame, prep: dict | None) -> pd.DataFrame:
    """Group, sort and keep the top rows, as the spec asks."""
    if not prep:
        return df
    out = df
    group_by = [_column(out, c) for c in (prep.get("group_by") or [])]
    aggregate = {_column(out, c): str(how).lower() for c, how in (prep.get("aggregate") or {}).items()}
    bad = [h for h in aggregate.values() if h not in AGGREGATES]
    if bad:
        raise ChartSpecError(f"Unknown aggregate '{bad[0]}'. Use one of: {', '.join(sorted(AGGREGATES))}.")
    if group_by:
        aggregate = aggregate or {c: "sum" for c in out.columns
                                  if c not in group_by and pd.api.types.is_numeric_dtype(out[c])}
        out = out.groupby(group_by, sort=False, dropna=False).agg(aggregate).reset_index()
    if prep.get("sort_by"):
        out = out.sort_values(_column(out, prep["sort_by"]), ascending=not prep.get("descending", False))
    if prep.get("top"):
        try:
            out = out.head(max(1, int(prep["top"])))
        except (TypeError, ValueError):
            raise ChartSpecError("'top' must be a number.")
    return out.reset_index(drop=True)


def _values(series: pd.Series) -> list:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.strftime("%Y-%m-%d").tolist()
    return [None if (isinstance(v, float) and pd.isna(v)) else v for v in series.tolist()]


def _fill(value, df: pd.DataFrame):
    """Replace {"col": name} with the column's values, everywhere in a trace."""
    if isinstance(value, dict):
        if set(value) == {"col"}:
            return _values(df[_column(df, str(value["col"]))])
        return {k: _fill(v, df) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, df) for v in value]
    return value


def _hierarchy(trace: dict, df: pd.DataFrame) -> dict:
    """"path": [outer, ..., inner] -> ids / labels / parents (and summed values) for treemap etc."""
    path = [_column(df, p.get("col") if isinstance(p, dict) else p) for p in trace.pop("path")]
    values = trace.pop("values", None)
    value_col = _column(df, values["col"]) if isinstance(values, dict) and "col" in values else None
    ids, labels, parents, sums = [], [], [], []
    for depth in range(len(path)):
        cols = path[: depth + 1]
        grouped = (df.groupby(cols, sort=False, dropna=False)[value_col].sum().reset_index() if value_col
                   else df[cols].drop_duplicates().assign(_n=1).rename(columns={"_n": "_value"}))
        for _, row in grouped.iterrows():
            key = [str(row[c]) for c in cols]
            ids.append(" / ".join(key))
            labels.append(key[-1])
            parents.append(" / ".join(key[:-1]))
            sums.append(float(row[value_col]) if value_col else 1)
    trace.update(ids=ids, labels=labels, parents=parents, values=sums, branchvalues="total")
    return trace


def _traces(spec: dict, df: pd.DataFrame) -> list[dict]:
    out = []
    for t in spec["traces"]:
        t = copy.deepcopy(t)
        split = t.pop("split_by", None)
        if t["type"] in HIERARCHY_TYPES and "path" in t:
            out.append(_hierarchy(t, df))
            continue
        if split:
            col = _column(df, split)
            base_name = t.get("name")
            for value in pd.unique(df[col]):
                part = df[df[col] == value] if not pd.isna(value) else df[df[col].isna()]
                piece = _fill(t, part)
                piece["name"] = f"{base_name} · {value}" if base_name else str(value)
                piece.setdefault("legendgroup", str(value))
                out.append(piece)
        else:
            out.append(_fill(t, df))
        if len(out) > MAX_TRACES:
            raise ChartSpecError(f"The chart would have more than {MAX_TRACES} series; split by a column with fewer values.")
    return out


# ---------------------------------------------------------------- drawing --

def build(df: pd.DataFrame, spec, dark: bool = False, height: int | None = None, title: str = "") -> go.Figure:
    """The figure for a spec, styled like the app's other charts. Raises ChartSpecError."""
    spec = parse(spec)
    data = prepare(df, spec.get("prepare"))
    traces = _traces(spec, data)
    layout = {k: v for k, v in (spec.get("layout") or {}).items() if k not in _BLOCKED_LAYOUT}
    mode = "dark" if dark else "light"
    try:
        fig = go.Figure(data=traces)
        charts._style(fig, dark, height, title, legend=len(traces) > 1)
        fig.update_layout(colorway=charts.PALETTE[mode])
        if any(t["type"] in ("bar", "waterfall", "funnel") for t in traces):
            fig.update_layout(barcornerradius=4, bargap=0.3)
        fig.update_layout(**layout)
        _extra_axes(fig, layout, charts.INK[mode])
    except (ValueError, TypeError) as exc:
        first = str(exc).strip().splitlines()
        raise ChartSpecError("Plotly rejected the chart: " + " ".join(first[:3])[:400]) from exc
    return fig


def _extra_axes(fig: go.Figure, layout: dict, ink: dict) -> None:
    """Second, third... y axes: the app's colours, no extra grid, and moved outwards when several sit
    on the same side, so their numbers don't print on top of each other."""
    names = sorted((k for k, v in layout.items() if re.fullmatch(r"yaxis\d+", k) and isinstance(v, dict)),
                   key=lambda k: int(k[5:]))
    on_side: dict[str, int] = {}
    for name in names:
        axis = layout[name]
        side = axis.get("side", "left")
        on_side[side] = on_side.get(side, 0) + 1
        style = {"showgrid": False, "tickfont": {"color": ink["muted"]}, "title_font": {"color": ink["muted"]}}
        if axis.get("overlaying") and (side == "left" or on_side[side] > 1):  # the side's edge is taken
            style.update(anchor="free", autoshift=True, position=0 if side == "left" else 1)
        fig.update_layout({name: {**style, **{k: v for k, v in axis.items() if k not in ("anchor", "position")
                                               or not style.get("autoshift")}}})


def check(df: pd.DataFrame, spec) -> str:
    """'' if the spec draws with this data, else the reason it doesn't."""
    try:
        build(df, spec)
        return ""
    except ChartSpecError as exc:
        return str(exc)
