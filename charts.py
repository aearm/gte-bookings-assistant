"""Turns a result into the most suitable chart, in one consistent (Apple-like) style.

suggest(df) picks a chart from the shape of the data; fit(df, spec) corrects a chart that doesn't
suit the data (e.g. a donut with 30 slices); build_figure(df, spec) draws it with Plotly."""
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
CHART_TYPES = list(TYPE_LABELS)

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
    if not limit or not x or not ys or is_time_column(df[x]):
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
                 show_title: bool = True):
    """Return a Plotly figure, or None if a table is the better display."""
    spec = fit(df, spec)
    kind, x, ys, color = spec["chart_type"], spec["x"], spec["y"], spec["color"] or None
    if kind == "table":
        return None
    df, _ = trim(df, spec)
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
        fig = draw(df, x=x, y=y_arg, color=color, **common)
        fig.update_traces(line=dict(width=2))
        if kind == "line" and len(df) <= 40:
            fig.update_traces(mode="lines+markers", marker=dict(size=8))
    elif kind == "horizontal_bar":
        plot_df = df.sort_values(ys[0]) if not color else df
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
