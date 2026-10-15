"""Turns a result into the most suitable chart, in one consistent (Apple-like) style.

suggest(df) picks a chart from the shape of the data; fit(df, spec) corrects a chart that doesn't
suit the data (e.g. a donut with 30 slices); build_figure(df, spec) draws it with Plotly, formatted
the way Claude chose for this data (spec["style"]: number formats, axis titles, order, value
labels...). A chart the user described in words is a "custom" chart, drawn by dynamic_chart.py."""
import re
from functools import lru_cache

import pandas as pd
import plotly.express as px

TYPE_LABELS = {
    "bar": "Columns", "horizontal_bar": "Bars (rankings)", "stacked_bar": "Stacked columns",
    "line": "Line (trend over time)", "area": "Area (trend over time)", "donut": "Donut (share of a whole)",
    "treemap": "Treemap (share, many parts)", "map": "World map (countries)",
    "heatmap": "Heatmap (two breakdowns)", "scatter": "Scatter (two numbers)", "table": "Table",
}
CHART_TYPES = list(TYPE_LABELS)  # chosen automatically; "custom" (described in words) is separate

# Categorical colours in a fixed order (checked for colour-blind safety); dark mode uses the same
# hues stepped for a dark background. Sequential: one blue, light to dark (for maps and heatmaps).
PALETTE = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
SEQUENTIAL = {
    "light": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    "dark": ["#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
}
INK = {"light": {"text": "#1d1d1f", "muted": "#6e6e73", "grid": "#e5e5ea", "land": "#e8e8ed", "surface": "#ffffff"},
       "dark": {"text": "#f5f5f7", "muted": "#98989d", "grid": "#38383a", "land": "#2c2c2e", "surface": "#1c1c1e"}}
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

_COUNTRY_ALIASES = {"UAE": "ARE", "UK": "GBR", "GREAT BRITAIN": "GBR", "ENGLAND": "GBR", "USA": "USA",
                    "US": "USA", "RUSSIA": "RUS", "TURKEY": "TUR", "TURKIYE": "TUR", "SOUTH KOREA": "KOR",
                    "KOREA": "KOR", "NORTH KOREA": "PRK", "IRAN": "IRN", "VIETNAM": "VNM", "SYRIA": "SYR",
                    "LAOS": "LAO", "BOLIVIA": "BOL", "VENEZUELA": "VEN", "TANZANIA": "TZA", "MOLDOVA": "MDA",
                    "MACEDONIA": "MKD", "NORTH MACEDONIA": "MKD", "MACEDONIA, THE FORMER YUGOSLAV REPUBLIC OF": "MKD", "CZECH REPUBLIC": "CZE", "IVORY COAST": "CIV",
                    "KOSOVO": "XKX", "PALESTINE": "PSE", "PALESTINIAN TERRITORY, OCCUPIED": "PSE", "SWAZILAND": "SWZ", "TAIWAN": "TWN", "HOLLAND": "NLD", "BRUNEI": "BRN"}


# ---------------------------------------------------------------- reading the data --

@lru_cache(maxsize=4096)
def country_code(name: str) -> str | None:
    """ISO-3 code for a country name in any common form ("UNITED ARAB EMIRATES", "Iran, Islamic
    Republic of", "UAE"), or None."""
    text = str(name or "").strip()
    if not text or text.lower() in ("unknown", "n/a", "none", "other", "(blank)"):
        return None
    if text.upper() in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[text.upper()]
    try:
        import pycountry
    except ImportError:
        return None
    try:
        return pycountry.countries.lookup(text).alpha_3
    except LookupError:
        pass
    try:
        if len(text) >= 4:
            return pycountry.countries.search_fuzzy(text)[0].alpha_3
    except LookupError:
        pass
    return None


def is_country_column(series: pd.Series) -> bool:
    values = [v for v in series.dropna().astype(str).unique() if v.strip() and v.lower() != "unknown"][:300]
    if len(values) < 3:
        return False
    return sum(country_code(v) is not None for v in values) / len(values) >= 0.6


_TIME_NAME = re.compile(r"date|day|week|month|year|quarter|period|time", re.IGNORECASE)
_TIME_VALUE = re.compile(r"^(\d{1,2}[-/]\d{4}|\d{4}[-/]\d{1,2}([-/]\d{1,2})?|\d{4}|(19|20)\d{2}\s*Q[1-4]|"
                         r"[A-Za-z]{3,9}\.? \d{4})$")


def is_time_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    sample = series.dropna().astype(str).head(20)
    return bool(_TIME_NAME.search(str(series.name))) and (
        len(sample) == 0 or sum(bool(_TIME_VALUE.match(v.strip())) for v in sample) >= len(sample) * 0.6)


def time_order(values) -> list[int]:
    """Positions of time labels from earliest to latest ("January 2026" before "February 2026", which
    sorting the text would not do); their order as given if they aren't dates or numbers."""
    text = pd.Series([str(v) for v in values], dtype=object)
    when = pd.to_datetime(text, errors="coerce", format="mixed")
    if when.isna().any():
        when = pd.to_numeric(text, errors="coerce")
        if when.isna().any():
            return list(range(len(text)))
    return list(when.sort_values(kind="stable").index)


def _numbers(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not is_time_column(df[c])]


def _labels(df: pd.DataFrame) -> list[str]:
    nums = set(_numbers(df))
    return [c for c in df.columns if c not in nums]


# ---------------------------------------------------------------- choosing --

def suggest(df: pd.DataFrame) -> dict:
    """The most suitable chart for this result, from its shape."""
    nums, labels = _numbers(df), _labels(df)
    if df.empty or not nums:
        return {"chart_type": "table", "x": "", "y": [], "color": ""}
    if not labels:
        if len(nums) >= 2 and len(df) > 2:
            return {"chart_type": "scatter", "x": nums[0], "y": [nums[1]], "color": ""}
        return {"chart_type": "table", "x": "", "y": nums, "color": ""}
    time = [c for c in labels if is_time_column(df[c])]
    other = [c for c in labels if c not in time]
    if time:
        x = time[0]
        if other and df[other[0]].nunique() <= 8:
            return {"chart_type": "line", "x": x, "y": [nums[0]], "color": other[0]}
        if other:
            return {"chart_type": "heatmap", "x": x, "y": [nums[0]], "color": other[0]}
        return {"chart_type": "line", "x": x, "y": nums[:4], "color": ""}
    x = other[0]
    if len(other) >= 2:
        second = other[1]
        kind = "stacked_bar" if df[second].nunique() <= 8 else "heatmap"
        return {"chart_type": kind, "x": x, "y": [nums[0]], "color": second}
    if is_country_column(df[x]) and len(df) >= 3:
        return {"chart_type": "map", "x": x, "y": [nums[0]], "color": ""}
    positive = (df[nums[0]].fillna(0) >= 0).all()
    if len(nums) == 1 and 2 <= len(df) <= 6 and positive:
        return {"chart_type": "donut", "x": x, "y": nums[:1], "color": ""}
    if len(nums) == 1 and len(df) > 25 and positive:
        return {"chart_type": "treemap", "x": x, "y": nums[:1], "color": ""}
    long_labels = df[x].astype(str).str.len().mean() > 14
    kind = "horizontal_bar" if (len(df) > 8 or long_labels) else "bar"
    return {"chart_type": kind, "x": x, "y": nums[:3], "color": ""}


def fit(df: pd.DataFrame, spec: dict) -> dict:
    """The chart, corrected where it doesn't suit the data (keeps the choice whenever it works)."""
    spec = {"x": "", "y": [], "color": "", **spec}
    kind = spec.get("chart_type") or "table"
    if kind == "custom":
        return spec if spec.get("custom") else {**spec, **suggest(df)}
    if kind == "pie":
        kind = "donut"
    nums = _numbers(df)
    ys = [y for y in (spec.get("y") or []) if y in nums] or nums[:1]
    x = spec["x"] if spec.get("x") in df.columns else ""
    color = spec["color"] if spec.get("color") in df.columns and spec.get("color") != x else ""
    if kind == "table" or df.empty or not nums:
        return {**spec, "chart_type": "table"}
    if not x and kind != "scatter":
        return {**suggest(df), "title": spec.get("title", ""), "summary": spec.get("summary", "")}
    ok = {
        "map": x and is_country_column(df[x]),
        "donut": 2 <= len(df) <= 7 and len(ys) >= 1 and (df[ys[0]].fillna(0) >= 0).all(),
        "treemap": x and (df[ys[0]].fillna(0) >= 0).all(),
        "heatmap": x and color,
        "stacked_bar": x and (color or len(ys) > 1),
        "scatter": len(nums) >= 2,
    }.get(kind, bool(x))
    if not ok:
        better = suggest(df)
        if better["chart_type"] == kind or better["chart_type"] == "table":
            better = {"chart_type": "horizontal_bar" if len(df) > 8 else "bar", "x": x, "y": ys, "color": ""}
        return {**spec, **better}
    return {**spec, "chart_type": kind, "x": x, "y": ys, "color": color}


SHOW_LIMIT = {"bar": 25, "horizontal_bar": 25, "stacked_bar": 25, "treemap": 100}


def trim(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, str]:
    """The rows worth drawing: a long list of categories keeps its top values (maps and trends over
    time keep everything). Returns (rows, note), the note saying what was left out (or "")."""
    spec = fit(df, spec)
    limit, x, ys = SHOW_LIMIT.get(spec["chart_type"]), spec.get("x"), spec.get("y")
    if not limit or not x or not ys or x not in df.columns or is_time_column(df[x]):
        return df, ""
    count = df[x].nunique()
    if count <= limit:
        return df, ""
    top = df.groupby(x, sort=False)[ys[0]].sum().nlargest(limit).index
    return df[df[x].isin(top)], f"Showing the top {limit} of {count:,} by {ys[0]} (all rows are in the data below)."


# ---------------------------------------------------------------- drawing --

def _style(fig, dark: bool, height: int | None, title: str, legend: bool = True):
    ink = INK["dark" if dark else "light"]
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=15, color=ink["text"])) if title else None,
        font=dict(family=FONT, size=12, color=ink["muted"]),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=44 if title else 8, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text="", font=dict(color=ink["text"]))
        if legend else dict(visible=False),
        hoverlabel=dict(bgcolor=ink["surface"], bordercolor=ink["grid"], font=dict(family=FONT, color=ink["text"])),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=ink["grid"], tickfont=dict(color=ink["muted"]),
                     title_font=dict(color=ink["muted"]))
    fig.update_yaxes(gridcolor=ink["grid"], zeroline=False, showline=False, tickfont=dict(color=ink["muted"]),
                     title_font=dict(color=ink["muted"]))
    if height:
        fig.update_layout(height=height)
    return fig


def build_figure(df: pd.DataFrame, spec: dict, dark: bool = False, height: int | None = None,
                 show_title: bool = True, compare: dict | None = None):
    """Return a Plotly figure, or None if a table is the better display. A custom chart that can't
    be drawn with this data (e.g. a column is gone) falls back to the best standard chart.
    compare = {"df": the same query for the comparison dates, "current": "1 Jan – 15 Oct 2026",
    "name": "1 Jan – 15 Oct 2025"}: drawn in grey next to the period (see _add_comparison)."""
    spec = fit(df, spec)
    kind = spec["chart_type"]
    if kind == "custom":
        import dynamic_chart
        try:
            return dynamic_chart.build(df, spec["custom"], dark=dark, height=height,
                                       title=spec.get("title", "") if show_title else "")
        except dynamic_chart.ChartSpecError:
            return build_figure(df, {**suggest(df), "title": spec.get("title", ""), "style": spec.get("style")},
                                dark, height, show_title)
    if kind == "table":
        return None
    df, _ = trim(df, spec)
    style = spec.get("style") or {}
    if kind == "donut" and style.get("sort") in ("value_desc", "value_asc") and spec["y"]:
        df = df.sort_values(spec["y"][0], ascending=style["sort"] == "value_asc")
    fig = _draw(df, spec, dark, height, show_title)
    _format(fig, spec, INK["dark" if dark else "light"])
    if compare:
        _add_comparison(fig, spec, compare, dark)
    return fig


# ---------------------------------------------------------------- comparing --
# One comparison for the whole dashboard (picked next to the period): the period in colour, the
# comparison in grey, both named by their dates in the legend, the change in the tooltip. Only where it
# reads clearly: columns, bars and lines of one measure (and tables and headline numbers, elsewhere).

COMPARE_COLOR = {"light": "#b8b8bf", "dark": "#5c5c63"}
COMPARABLE = ("bar", "horizontal_bar", "line", "area")


def change_text(value, before) -> str:
    """' (+12.3%)' - the change from before to value, or '' when it can't be said."""
    if value is None or before is None or pd.isna(value) or pd.isna(before) or before == 0:
        return ""
    return f" ({(value - before) / abs(before):+.1%})"


def _add_comparison(fig, spec: dict, compare: dict, dark: bool) -> None:
    kind, x, ys = spec["chart_type"], spec.get("x"), spec.get("y") or []
    prev = compare.get("df")
    if (kind not in COMPARABLE or len(ys) != 1 or spec.get("color") or len(fig.data) != 1 or prev is None
            or prev.empty or x not in prev.columns or ys[0] not in prev.columns):
        return
    import plotly.graph_objects as go
    y, cur, horizontal = ys[0], fig.data[0], kind == "horizontal_bar"
    cats, values = (list(cur.y), list(cur.x)) if horizontal else (list(cur.x), list(cur.y))
    if kind in ("line", "area"):  # over time: the same position in each period (1st month with 1st month)
        before = prev.iloc[time_order(prev[x])]
        old, labels = [None] * len(cats), [""] * len(cats)
        for slot, (when, v) in zip(time_order(cats), zip(before[x], before[y])):
            old[slot], labels[slot] = (None if pd.isna(v) else v), str(when)
    else:  # categories: the same category in each period
        by_cat = prev.groupby(prev[x].astype(str))[y].sum()
        old = [by_cat.get(str(c)) for c in cats]
        old, labels = [None if v is None or pd.isna(v) else v for v in old], None
    d3, prefix, suffix = number_format(spec, y)
    shown, v = d3 or ",.0f", "x" if horizontal else "y"
    value = f"{prefix}%{{{v}:{shown}}}{suffix}"
    cur.update(name=compare["current"], showlegend=True, customdata=[change_text(a, b) for a, b in zip(values, old)]
               + [""] * (len(values) - len(old)), hovertemplate=f"{compare['current']}: {value}%{{customdata}}<extra></extra>")
    grey = COMPARE_COLOR["dark" if dark else "light"]
    if labels is not None:
        fig.add_trace(go.Scatter(x=cats, y=old, mode="lines", name=compare["name"], customdata=labels,
                                 line=dict(color=grey, width=2, dash="dot"), connectgaps=True,
                                 hovertemplate=f"{compare['name']} (%{{customdata}}): {value}<extra></extra>"))
    else:
        bar = dict(x=old, y=cats, orientation="h") if horizontal else dict(x=cats, y=old)
        fig.add_trace(go.Bar(**bar, name=compare["name"], marker_color=grey,
                             hovertemplate=f"{compare['name']}: {value}<extra></extra>"))
        fig.data = (fig.data[1], fig.data[0])  # the comparison first: beside (or below) each period's bar
        fig.update_layout(barmode="group", legend_traceorder="reversed")  # the legend still names this period first
        axis = fig.layout.yaxis if horizontal else fig.layout.xaxis
        if axis.categoryorder and axis.categoryorder.startswith("total"):  # order by this period, not both
            ascending = axis.categoryorder == "total ascending"
            ordered = sorted(zip(cats, values), key=lambda cv: cv[1] if cv[1] is not None else 0, reverse=not ascending)
            axis.update(categoryorder="array", categoryarray=[c for c, _ in ordered])
    fig.update_layout(showlegend=True, margin=dict(t=max(fig.layout.margin.t or 0, 36)),  # room for the legend
                      legend=dict(visible=True, orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""))


def _paired(df: pd.DataFrame, prev: pd.DataFrame, nums: list[str]) -> pd.DataFrame | None:
    """prev's numbers lined up with df's rows (same index), or None when rows can't be paired clearly:
    by category (same name), by date (same position: 1st month with 1st month), or a single row."""
    labels = _labels(df)
    if any(c not in prev.columns for c in labels):
        return None
    time = [c for c in labels if is_time_column(df[c])]
    keys = [c for c in labels if c not in time]
    if time and keys:  # by date and by something else: no clear pairing
        return None
    if keys:
        before = prev.assign(**{k: prev[k].astype(str) for k in keys}).groupby(keys, sort=False)[nums].sum()
        found = df[keys].astype(str).merge(before.reset_index(), on=keys, how="left")[nums]
        return found.set_axis(df.index)
    if time:
        order = df.index[time_order(df[time[0]])]
        before = prev.iloc[time_order(prev[time[0]])][nums].reset_index(drop=True).head(len(order))
        return before.set_axis(order[:len(before)]).reindex(df.index)
    if len(df) == 1 and len(prev) == 1:
        return prev[nums].set_axis(df.index)
    return None


def with_changes(df: pd.DataFrame, prev: pd.DataFrame | None, spec: dict) -> tuple[pd.DataFrame, dict]:
    """A table with a change column after each measure ("Sales change", +12.3%) against the comparison
    period, and the spec with those columns formatted as percentages. Unchanged if rows can't be paired."""
    nums = [n for n in _numbers(df)[:4] if prev is not None and n in prev.columns]
    before = _paired(df, prev, nums) if nums and not prev.empty else None
    if before is None:
        return df, spec
    out = df.copy()
    formats = list((spec.get("style") or {}).get("formats", []))
    for n in reversed(nums):
        old = before[n]
        out.insert(out.columns.get_loc(n) + 1, f"{n} change", (df[n] - old) / old.abs().where(old != 0))
        formats.append({"column": f"{n} change", "d3_format": "+.1%"})
    return out, {**spec, "style": {**(spec.get("style") or {}), "formats": formats}}


def _draw(df: pd.DataFrame, spec: dict, dark: bool, height: int | None, show_title: bool):
    kind, x, ys, color = spec["chart_type"], spec["x"], spec["y"], spec["color"] or None
    mode = "dark" if dark else "light"
    colors, seq, ink = PALETTE[mode], SEQUENTIAL[mode], INK[mode]
    title = spec.get("title", "") if show_title else ""
    y_arg = ys[0] if (len(ys) == 1 or color) else ys  # several measures -> one series each
    common = dict(color_discrete_sequence=colors)

    if kind == "map":
        data = df.assign(_iso=df[x].map(country_code)).dropna(subset=["_iso"])
        fig = px.choropleth(data, locations="_iso", color=ys[0], hover_name=x, color_continuous_scale=seq,
                            projection="natural earth", hover_data={"_iso": False, ys[0]: ":,"})
        fig.update_geos(showframe=False, showcoastlines=False, showcountries=True, countrycolor=ink["surface"],
                        landcolor=ink["land"], showland=True, bgcolor="rgba(0,0,0,0)", showocean=False,
                        lataxis_range=[-58, 85])
        fig.update_layout(coloraxis_colorbar=dict(title="", thickness=10, len=0.7, tickfont=dict(color=ink["muted"])))
        return _style(fig, dark, height or 420, title, legend=False)
    if kind == "donut":
        fig = px.pie(df, names=x, values=ys[0], hole=0.6, **common)
        fig.update_traces(sort=False, textinfo="percent", textfont=dict(color="#ffffff", size=12),
                          marker=dict(line=dict(color=ink["surface"], width=2)),
                          hovertemplate="%{label}<br>%{value:,}<br>%{percent}<extra></extra>")
        return _style(fig, dark, height, title)
    if kind == "treemap":
        path = [px.Constant("All"), color, x] if color else [px.Constant("All"), x]
        fig = px.treemap(df, path=path, values=ys[0], color=ys[0], color_continuous_scale=seq)
        fig.update_traces(marker=dict(cornerradius=6, line=dict(color=ink["surface"], width=2)),
                          root_color="rgba(0,0,0,0)", texttemplate="%{label}<br>%{value:,}",
                          hovertemplate="%{label}<br>%{value:,}<extra></extra>")
        fig.update_layout(coloraxis_showscale=False)
        return _style(fig, dark, height, title, legend=False)
    if kind == "heatmap":
        grid = df.pivot_table(index=color, columns=x, values=ys[0], aggfunc="first", sort=False)
        fig = px.imshow(grid, color_continuous_scale=seq, aspect="auto",
                        text_auto=",.0f" if grid.size <= 120 else False, labels=dict(color=ys[0]))
        fig.update_layout(coloraxis_colorbar=dict(title="", thickness=10, tickfont=dict(color=ink["muted"])))
        fig.update_xaxes(title=""), fig.update_yaxes(title="")
        return _style(fig, dark, height, title, legend=False)
    if kind == "scatter":
        fig = px.scatter(df, x=x or ys[0], y=ys[-1], color=color, **common)
        fig.update_traces(marker=dict(size=9, line=dict(color=ink["surface"], width=1)))
    elif kind in ("line", "area"):
        draw = px.line if kind == "line" else px.area
        if is_time_column(df[x]):  # time reads left to right, whatever order the query returned
            df = df.iloc[time_order(df[x])]
        fig = draw(df, x=x, y=y_arg, color=color, **common)
        fig.update_traces(line=dict(width=2))
        if kind == "line" and len(df) <= 40:
            fig.update_traces(mode="lines+markers", marker=dict(size=8))
    elif kind == "horizontal_bar":
        plot_df = df.sort_values(ys[0]) if not color and not (spec.get("style") or {}).get("sort") else df
        fig = px.bar(plot_df, x=y_arg, y=x, color=color, orientation="h", barmode="group", **common)
    else:
        fig = px.bar(df, x=x, y=y_arg, color=color, barmode="stack" if kind == "stacked_bar" else "group",
                     **common)
    if kind in ("bar", "horizontal_bar", "stacked_bar"):
        fig.update_layout(barcornerradius=4, bargap=0.3, bargroupgap=0.08)
    if isinstance(y_arg, list):  # several measures: the legend names them, so no "value" axis title
        fig.update_layout(**{"xaxis_title" if kind == "horizontal_bar" else "yaxis_title": ""})
    if kind == "horizontal_bar":
        fig.update_xaxes(showgrid=True, gridcolor=ink["grid"])
        fig.update_yaxes(showgrid=False, title="")
    fig.update_layout(hovermode="x unified" if kind in ("line", "area", "bar", "stacked_bar") else "closest")
    return _style(fig, dark, height, title, legend=bool(color) or isinstance(y_arg, list))


# ---------------------------------------------------------------- formatting --
# Claude formats every chart for its data (llm.describe_result): spec["style"] = {"formats":
# [{"column", "d3_format", "prefix", "suffix"}], "x_title", "y_title", "sort", "show_values",
# "label_angle", "legend", "log_scale"}. x_title names the axis with the categories or dates,
# y_title the axis with the numbers (whichever way round the chart is drawn).

def number_format(spec: dict, column: str) -> tuple[str, str, str]:
    """(d3 format, prefix, suffix) Claude chose for a column, or ("", "", "")."""
    for f in (spec.get("style") or {}).get("formats", []):
        if f.get("column") == column:
            return f.get("d3_format") or "", f.get("prefix") or "", f.get("suffix") or ""
    return "", "", ""


def _compact(value: float) -> str:
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= size:
            scaled = value / size
            return f"{scaled:,.{1 if abs(scaled) < 100 else 0}f}{unit}"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def format_number(value, d3: str = "", prefix: str = "", suffix: str = "") -> str:
    """A number the way the chart shows it, for headline numbers: 'AED 4.5M', '12.3%', '1,234'."""
    if value is None or pd.isna(value):
        return "-"
    decimals = re.search(r"\.(\d+)", d3 or "")
    if d3.endswith("%"):
        text = f"{value * 100:,.{int(decimals.group(1)) if decimals else 0}f}%"
    elif "s" in d3 or (not d3 and abs(value) >= 1_000_000):
        text = _compact(value)
    elif decimals:
        text = f"{value:,.{int(decimals.group(1))}f}"
    else:
        text = f"{value:,.0f}" if abs(value) >= 1000 or float(value).is_integer() else f"{value:,.2f}"
    return f"{prefix}{text}{suffix}"


def _format(fig, spec: dict, ink: dict) -> None:
    """Apply Claude's formatting to a standard chart."""
    style = spec.get("style") or {}
    kind, ys = spec["chart_type"], spec.get("y") or []
    if not style or not ys:
        return
    d3, prefix, suffix = number_format(spec, ys[0])
    shown = d3 or ",.0f"
    horizontal = kind == "horizontal_bar"
    value_axis, label_axis = (fig.update_xaxes, fig.update_yaxes) if horizontal else (fig.update_yaxes, fig.update_xaxes)
    v, lbl = ("x", "y") if horizontal else ("y", "x")
    cartesian = kind in ("bar", "horizontal_bar", "stacked_bar", "line", "area", "scatter")

    if cartesian:
        if d3 or prefix or suffix:
            value_axis(tickformat=d3 or None, tickprefix=prefix, ticksuffix=suffix, hoverformat=d3 or None)
            several = len(fig.data) > 1
            for t in fig.data:
                name = "%{fullData.name}: " if several else ""
                head = "" if kind in ("line", "area", "bar", "stacked_bar") else f"%{{{lbl}}}<br>"
                t.hovertemplate = f"{head}{name}{prefix}%{{{v}:{shown}}}{suffix}<extra></extra>"
        if style.get("y_title") is not None:
            value_axis(title_text=style.get("y_title", ""))
        if style.get("x_title") is not None:
            label_axis(title_text=style.get("x_title", ""))
        if style.get("log_scale"):
            value_axis(type="log")
        if style.get("label_angle") and not horizontal:
            fig.update_xaxes(tickangle=style["label_angle"])
        order = {"value_desc": "total descending", "value_asc": "total ascending", "label": "category ascending",
                 "none": "trace"}.get(style.get("sort", ""))
        if order and kind in ("bar", "stacked_bar", "horizontal_bar"):
            if horizontal:  # the first bar is drawn at the bottom: flip, so the list reads from the top
                order = {"total descending": "total ascending", "total ascending": "total descending",
                         "category ascending": "category descending"}.get(order, order)
            label_axis(categoryorder=order)
        if style.get("show_values") and kind in ("bar", "horizontal_bar", "stacked_bar"):
            fig.update_traces(texttemplate=f"{prefix}%{{{v}:{shown}}}{suffix}",
                              textposition="inside" if kind == "stacked_bar" else "outside",
                              cliponaxis=False, textfont=dict(size=11))
            fig.update_layout(uniformtext=dict(minsize=9, mode="hide"))
    elif kind == "donut":
        fig.update_traces(hovertemplate=f"%{{label}}<br>{prefix}%{{value:{shown}}}{suffix}<br>%{{percent}}<extra></extra>")
        if style.get("show_values"):
            fig.update_traces(texttemplate=f"%{{percent}}<br>{prefix}%{{value:{shown}}}{suffix}")
    elif kind == "treemap":
        fig.update_traces(texttemplate=f"%{{label}}<br>{prefix}%{{value:{shown}}}{suffix}",
                          hovertemplate=f"%{{label}}<br>{prefix}%{{value:{shown}}}{suffix}<extra></extra>")
    elif kind in ("map", "heatmap"):
        fig.update_layout(coloraxis_colorbar=dict(tickformat=d3 or None, tickprefix=prefix, ticksuffix=suffix))
        if kind == "heatmap":
            if fig.data[0].texttemplate:  # small grids show their numbers
                fig.update_traces(texttemplate=f"{prefix}%{{z:{shown}}}{suffix}")
            fig.update_traces(hovertemplate=f"%{{y}} · %{{x}}<br>{prefix}%{{z:{shown}}}{suffix}<extra></extra>")
        else:
            fig.update_traces(hovertemplate=f"%{{hovertext}}<br>{prefix}%{{z:{shown}}}{suffix}<extra></extra>")

    legend = style.get("legend")
    if legend == "none":
        fig.update_layout(showlegend=False)
    elif legend == "right":
        fig.update_layout(legend=dict(orientation="v", x=1.02, y=1, yanchor="top", xanchor="left"))
    elif legend == "bottom":
        fig.update_layout(legend=dict(orientation="h", x=0, y=-0.2, yanchor="top"))
