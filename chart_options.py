"""Charts as Apache ECharts options, built on the server for the React app (docs/refactor-plan.md).

build_option(df, spec) draws the same chart as charts.build_figure(df, spec) - the same choice of
chart (fit), the same rows (trim), the formats Claude chose, panels for measures of different size,
one chart with an axis per measure, the comparison in grey, codes as categories, time read left to
right, long day breakdowns over time - but as an ECharts option: plain JSON the browser hands to
ECharts. It returns None when a table shows the result better (as build_figure does).

The rows travel once, in option["dataset"][0] (id "result": the result as drawn - top rows only, in
time order or sorted, summed per category where the chart sums) and every series points at them
with "encode" (column names). A second breakdown (e.g. the day) adds one filtered view of those rows
per value (dataset transform "filter"), so the browser can swap dataset[0].source for filtered rows
without rebuilding the option. Treemaps are the exception: ECharts needs their data inline.

Our additions are keys starting with "x-". ECharts ignores them; the browser acts on them:

  x-format   on an axis, a series or a visualMap: how its numbers are written. JSON can't carry the
             JavaScript functions ECharts formats with, so the format is described instead:
               {"style": "fixed" | "percent" | "compact" | "auto", "decimals": 0 | null,
                "thousands": true, "sign": false, "trim": false, "prefix": "AED ", "suffix": ""}
             fixed     the number with `decimals` places        1234.5 -> "1,235" (0), "1,234.50" (2)
             percent   a fraction as a percentage               0.1234 -> "12.3%" (1 decimal)
             compact   k / M / B, 1 decimal under 100, none from 100: 4512000 -> "4.5M",
                       125000 -> "125k"; `decimals` fixes the places instead; under 1,000 unchanged
             auto      no format chosen: compact from a million (no trailing zeros: "2M"), whole
                       numbers from 1,000 or when whole, else 2 decimals
             thousands "," between thousands     sign  "+" before numbers >= 0 ("+12.5%")
             trim      no trailing zeros ("2M", not "2.0M")
             prefix / suffix around the number ("AED 4.5M"; "12.3%" for numbers already 0-100)
             Missing values read "-". Halves round away from zero, as Intl.NumberFormat does.
             format_value(value, fmt) is the reference: the browser's formatValue must write the
             same text (tests/test_chart_options.py lists examples). describe_format() makes it from
             the d3 formats Claude picks: ",.0f" fixed 0 | ",.2f" fixed 2 | ",.1f" fixed 1 |
             ".1%" percent 1 | ".0%" percent 0 | "+.1%" percent 1 with sign | "~s" compact, trimmed
             | "$,.0f" fixed 0 with prefix "$" | "" auto.
             The browser sets, from it: an axis's axisLabel.formatter (and axisPointer.label);
             a series' tooltip.valueFormatter; a visualMap's formatter.
  x-label    on a series whose label.show is true: the text on each bar / slice / cell, a template:
             {value} (the series' value, formatted), {name} (the category or item), {percent} (share
             of the whole, 1 decimal, donuts), {col:Column} (another column of the same row, formatted
             with x-app.formats[Column] when it has one). ECharts' own formatter string is the fallback.
  x-tooltip  on a series with an item tooltip (donut, treemap, map, heatmap, scatter, horizontal
             bars): the tooltip as a template - the same placeholders plus {series}; "<br>" breaks a
             line; every inserted value is HTML-escaped. In a tooltip {value} is followed by the
             change / date of x-change and x-when; on a label it is the value alone.
  x-value    the dataset column holding the series' value. With a dataset, params.value is the whole
             row: the column's position is its place in the root dataset's "dimensions".
  x-change   (comparison) the column with the change against the comparison period, a fraction: the
             value in the tooltip is followed by " (+12.5%)" (format x-app.formats["_change"]).
  x-when     (comparison over time) the column with the comparison's own date, written after the
             value as " (2025-01)". x-change and x-when are read from dataset[0] at the hovered
             dataIndex (valueFormatter's second argument).
  x-group    the measure a series belongs to (one chart with an axis per measure): for a legend
             grouped by measure.
  x-app      (top level) what the chart is: version; kind (bar, horizontal_bar, stacked_bar, line,
             area, donut, treemap, heatmap, scatter, map, panels, one_chart, custom, plotly);
             chart_type, x, y, color (the fitted spec); theme; height (the least height in pixels the
             chart needs, or null); formats (per column, as in tooltips); note (rows left out);
             dataset (how the rows are laid out); categories (the axis holding them, in which order,
             to redo after a swap); compare (the two periods' names); map (below).

Maps: series "map" on the map "world" with regions named by ISO-3 code (nameProperty "iso_a3"). The
browser registers a world GeoJSON once - echarts.registerMap("world", geojson) - whose features carry
their ISO-3 code in properties.iso_a3, leaving out x-app.map.exclude (Antarctica, as charts.py crops
it). x-app.map.codes maps each country in the result to its code.

A saved Plotly custom chart comes back as {"x-app": {"kind": "plotly", "figure": ...}} for a Plotly
renderer loaded only when needed; custom charts written as ECharts options go through custom_echarts.
"""
import json
import math
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal

import numpy as np
import pandas as pd

from charts import (COMPARABLE, COMPARE_COLOR, FONT, INK, PALETTE, SEQUENTIAL, _shade, country_code, fit,
                    is_time_column, needs_panels, number_format, suggest, time_order, trim, wants_one_chart)

VERSION = 1
LARGE = 2000  # points in one series from which ECharts draws in its fast mode (large / progressive)
MAP_NAME, MAP_KEY = "world", "iso_a3"
BAR_KINDS = ("bar", "horizontal_bar", "stacked_bar")
TITLE_H, LEGEND_H = 28, 26  # pixels for the title line and the legend line above the plot
_BAR_GAPS = {"barCategoryGap": "30%", "barGap": "8%"}  # Plotly's bargap 0.3 and bargroupgap 0.08


# ---------------------------------------------------------------- number formats --

AUTO = {"style": "auto", "decimals": None, "thousands": True, "sign": False, "trim": True, "prefix": "", "suffix": ""}
_D3 = re.compile(r"^(?:.?[<>=^])?([-+( ])?([$#])?0?(\d+)?(,)?(?:\.(\d+))?(~)?([a-zA-Z%])?$")
_STYLES = {"f": "fixed", "d": "fixed", "%": "percent", "s": "compact"}
_UNITS = ((1e9, "B"), (1e6, "M"), (1e3, "k"), (1.0, ""))
_EXACT = Context(prec=400)


def describe_format(d3: str = "", prefix: str = "", suffix: str = "") -> dict:
    """The format description (module notes) for a d3 format and the prefix / suffix Claude chose.
    Formats it doesn't know (e.g. 'e', 'g') keep the prefix and suffix and write numbers 'auto'."""
    fmt = {**AUTO, "prefix": prefix or "", "suffix": suffix or ""}
    match = _D3.match((d3 or "").strip())
    style = _STYLES.get(match.group(7) or "") if match and d3 else None
    if not style:
        return fmt
    sign, symbol, _, comma, precision, tilde, kind = match.groups()
    if symbol == "$" and not fmt["prefix"]:
        fmt["prefix"] = "$"
    decimals = None if style == "compact" else (0 if kind == "d" or precision is None else int(precision))
    return {**fmt, "style": style, "decimals": decimals, "thousands": bool(comma), "sign": sign == "+",
            "trim": bool(tilde)}


def format_value(value, fmt: dict | None = None) -> str:
    """A number written the way its format describes: 'AED 4.5M', '12.3%', '+12.5%', '1,234'; '-' when
    missing. The reference for the browser's formatter (same text for the same value and format)."""
    if isinstance(value, (bool, np.bool_)) or (value is not None and not isinstance(value, (int, float, np.integer, np.floating, Decimal))):
        return "-" if _missing(value) else str(value)
    if value is None or not math.isfinite(float(value)):
        return "-"
    number = float(value)
    fmt = {**AUTO, **(fmt or {})}
    style, size, thousands = fmt.get("style") or "auto", abs(number), bool(fmt.get("thousands"))
    if style == "percent":
        body = _fixed(size * 100, fmt.get("decimals") or 0, thousands, fmt.get("trim")) + "%"
    elif style == "compact":
        body = _compact(size, fmt.get("decimals"), thousands, fmt.get("trim"))
    elif style == "fixed":
        body = _fixed(size, fmt.get("decimals") or 0, thousands, fmt.get("trim"))
    elif size >= 1e6:
        body = _compact(size, None, thousands, True)
    else:
        body = _fixed(size, 0 if size >= 1000 or number.is_integer() else 2, thousands, False)
    sign = "-" if number < 0 and re.search(r"[1-9]", body) else ("+" if fmt.get("sign") else "")
    return f"{fmt.get('prefix') or ''}{sign}{body}{fmt.get('suffix') or ''}"


def _fixed(number: float, places: int, thousands: bool, trim_zeros: bool) -> str:
    """number (>= 0) with `places` decimals, halves rounded up (as the browser's Intl.NumberFormat)."""
    rounded = Decimal(number).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP, context=_EXACT)
    text = f"{rounded:{',' if thousands else ''}.{places}f}"
    return text.rstrip("0").rstrip(".") if trim_zeros and "." in text else text


def _compact(size: float, decimals, thousands: bool, trim_zeros: bool) -> str:
    """size (>= 0) in k / M / B; a value that rounds up to 1,000 of a unit moves to the next one."""
    k = next(i for i, (step, unit) in enumerate(_UNITS) if size >= step or not unit)
    while True:
        step, unit = _UNITS[k]
        scaled = size / step
        if decimals is not None:
            places = decimals
        elif unit:
            places = 1 if scaled < 100 else 0
        else:
            places = 0 if float(size).is_integer() else 2
        text = _fixed(scaled, places, thousands, trim_zeros)
        if k > 0 and float(text.replace(",", "")) >= 1000:
            k -= 1
            continue
        return text + unit


def axis_format(spec: dict, column: str) -> dict:
    """The format of an axis showing a column: Claude's, else 'auto' (like Plotly's own ticks)."""
    return describe_format(*number_format(spec, column))


def value_format(spec: dict, df: pd.DataFrame, column: str) -> dict:
    """The format of a column's values in tooltips and labels: Claude's, else whole numbers when the
    values are whole or reach 100, else 2 decimals (as charts.py's hovers)."""
    d3, prefix, suffix = number_format(spec, column)
    if not d3:
        values = pd.to_numeric(df[column], errors="coerce").dropna() if column in df.columns else pd.Series(dtype=float)
        whole = bool(len(values)) and bool((values % 1 == 0).all())
        d3 = ",.0f" if whole or (len(values) and values.abs().max() >= 100) else ",.2f"
    return describe_format(d3, prefix, suffix)


def _formats(spec: dict, df: pd.DataFrame, columns) -> dict:
    return {c: value_format(spec, df, c) for c in dict.fromkeys(columns) if c in df.columns}


# ---------------------------------------------------------------- data as JSON --

def _missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cell(value):
    """A value as JSON: numbers, text, dates as 'YYYY-MM-DD' (with the time when there is one), None."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating, Decimal)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, datetime):
        if _missing(value):
            return None
        midnight = (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)
        return value.strftime("%Y-%m-%d") if midnight else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None if _missing(value) else str(value)


def _plain(obj):
    """The option with every value JSON can carry (dataset rows are made plain when built)."""
    if isinstance(obj, dict):
        return {str(k): (v if k == "source" and isinstance(v, list) else _plain(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return _cell(obj)


def _label(value) -> str:
    """A category as text: a date as '2026-10-14', a whole number without '.0', missing as ''."""
    if isinstance(value, datetime):
        return "" if _missing(value) else str(_cell(value)).replace("T", " ")[:16]
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(value):
            return ""
        if float(value).is_integer():
            return str(int(value))
    return "" if value is None or _missing(value) else str(value)


def _labels(values: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(values):
        clean = values.dropna()
        whole_days = bool((clean == clean.dt.normalize()).all())
        return values.dt.strftime("%Y-%m-%d" if whole_days else "%Y-%m-%d %H:%M").fillna("").astype(object)
    return values.map(_label).astype(object)


def _is_number(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _dataset(frame: pd.DataFrame, time_columns=()) -> dict:
    """The rows as an ECharts dataset: named, typed columns and one list per row."""
    dims = [{"name": str(c), "type": "time" if c in time_columns else ("number" if _is_number(frame[c]) else "ordinal")}
            for c in frame.columns]
    rows = [[_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)]
    return {"id": "result", "dimensions": dims, "source": rows}


def _view(column: str, value: str, j: int) -> dict:
    """The rows of one breakdown value (e.g. one day), filtered by ECharts from dataset 0."""
    return {"id": f"view-{j}", "fromDatasetIndex": 0,
            "transform": {"type": "filter", "config": {"dimension": column, "=": value}}}


def _in_time(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if pd.api.types.is_datetime64_any_dtype(frame[column]):
        return frame.sort_values(column, kind="stable")
    return frame.iloc[time_order(frame[column])]


def _by_position(frame: pd.DataFrame, column: str, order: list) -> pd.DataFrame:
    position = {c: i for i, c in enumerate(order)}
    keys = frame[column].map(position).fillna(len(order)).to_numpy()
    return frame.iloc[np.argsort(keys, kind="stable")]


def _sorted(labels: pd.Series, values: pd.Series, how: str) -> list:
    """The categories in the order asked: by the total of `values`, by name, or as they come."""
    order = list(dict.fromkeys(labels))
    if how in ("value_desc", "value_asc"):
        totals = pd.Series(values.to_numpy()).groupby(labels.to_numpy(), sort=False).sum()
        return list(totals.sort_values(ascending=how == "value_asc", kind="stable").index)
    return sorted(order) if how == "label" else order


def _breakdown(keys: pd.Series, original: pd.Series) -> list:
    """The values of the second breakdown, earliest first when they are dates, else as they come."""
    if is_time_column(original):
        keys = keys.iloc[time_order(keys.tolist())]
    return list(dict.fromkeys(keys))


# ---------------------------------------------------------------- look --

def _frame(spec: dict, dark: bool, show_title: bool) -> tuple[dict, dict, str]:
    """The option's common parts: colours, font, title, tooltip. Returns (option, ink, title)."""
    mode = "dark" if dark else "light"
    ink = INK[mode]
    title = str(spec.get("title") or "") if show_title else ""
    option = {
        "backgroundColor": "transparent",
        "color": list(PALETTE[mode]),
        "textStyle": {"fontFamily": FONT, "fontSize": 12, "color": ink["muted"]},
        "title": [{"text": title, "left": 0, "top": 0,
                   "textStyle": {"fontSize": 15, "fontWeight": 600, "color": ink["text"]}}] if title else [],
        "tooltip": {"trigger": "item", "confine": True, "backgroundColor": ink["surface"], "borderColor": ink["grid"],
                    "textStyle": {"color": ink["text"], "fontFamily": FONT, "fontSize": 12}},
    }
    return option, ink, title


def _legend_place(spec: dict, shown: bool, force: bool = False) -> str:
    """Where the legend goes: 'top' (its own line below the title), 'right', 'bottom' or 'none'."""
    if force:
        return "top"
    place = (spec.get("style") or {}).get("legend") or "top"
    return place if shown and place in ("top", "right", "bottom") else "none"


def _legend(place: str, ink: dict, title: str, **extra) -> dict:
    legend = {"show": place != "none", "type": "scroll", "left": 0, "top": TITLE_H if title else 0,
              "icon": "roundRect", "itemWidth": 12, "itemHeight": 12, "itemGap": 16,
              "textStyle": {"color": ink["text"]}, "pageIconColor": ink["muted"],
              "pageIconInactiveColor": ink["grid"], "pageTextStyle": {"color": ink["muted"]}}
    if place == "right":
        legend.update(orient="vertical", left="right")
    elif place == "bottom":
        legend.update(top="bottom")
    legend.update(extra)
    return legend


def _grid(place: str, title: str, top: int = 0, bottom: int = 0, right: int = 0) -> dict:
    return {"left": 8, "right": 8 + right + (150 if place == "right" else 0),
            "top": 12 + (TITLE_H if title else 0) + (LEGEND_H if place == "top" else 0) + top,
            "bottom": 8 + (LEGEND_H if place == "bottom" else 0) + bottom, "containLabel": True}


def _category_axis(ink: dict, data=None, name: str = "", rotate: int = 0, inverse: bool = False,
                   show_labels: bool = True, **extra) -> dict:
    axis = {"type": "category", "axisLine": {"show": True, "lineStyle": {"color": ink["grid"]}},
            "axisTick": {"show": False}, "splitLine": {"show": False},
            "axisLabel": {"show": show_labels, "color": ink["muted"], "hideOverlap": True}}
    if data is not None:
        axis["data"] = list(data)
    if rotate:
        axis["axisLabel"]["rotate"] = rotate
    if inverse:  # the first category at the top: horizontal bars read from the top
        axis["inverse"] = True
    if name:
        axis.update(name=name, nameLocation="start" if inverse else "middle", nameGap=28 + (40 if rotate else 0),
                    nameTextStyle={"color": ink["muted"]})
    axis.update(extra)
    return axis


def _time_axis(ink: dict, name: str = "") -> dict:
    axis = {"type": "time", "axisLine": {"show": True, "lineStyle": {"color": ink["grid"]}},
            "axisTick": {"show": False}, "splitLine": {"show": False},
            "axisLabel": {"color": ink["muted"], "hideOverlap": True}}
    if name:
        axis.update(name=name, nameLocation="middle", nameGap=28, nameTextStyle={"color": ink["muted"]})
    return axis


def _value_axis(ink: dict, fmt: dict, name: str = "", log: bool = False, color: str | None = None,
                grid_lines: bool = True, across: bool = False, align: str = "left", **extra) -> dict:
    """A number axis; `across` for one drawn left to right (horizontal bars), named below its middle."""
    axis = {"type": "log" if log else "value", "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": color or ink["muted"], "hideOverlap": True},
            "splitLine": {"show": grid_lines, "lineStyle": {"color": ink["grid"]}}, "x-format": fmt}
    if name:
        axis.update(name=name, nameTextStyle={"color": color or ink["muted"], **({} if across else {"align": align})},
                    nameLocation="middle" if across else "end", nameGap=28 if across else 12)
    axis.update(extra)
    return axis


def _fast(series: dict, points: int) -> dict:
    """Big series drawn in ECharts' fast modes (nothing is left out beyond charts.trim)."""
    if points >= LARGE:
        if series["type"] in ("bar", "scatter"):
            series.update(large=True, largeThreshold=LARGE, progressive=LARGE, progressiveThreshold=LARGE * 2)
        elif series["type"] == "line":
            series.update(sampling="lttb", showSymbol=False)
        elif series["type"] == "heatmap":
            series.update(progressive=LARGE, progressiveThreshold=LARGE * 2)
    return series


def _scale(values: pd.Series, fmt: dict, ink: dict, dark: bool) -> dict:
    """The colour scale of a heatmap or map: light to dark blue, its ends written in the column's format
    (text the browser may rewrite after swapping the data; x-format for its own formatter)."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    low, high = (float(clean.min()), float(clean.max())) if len(clean) else (0.0, 1.0)
    high = high if high > low else low + 1
    return {"type": "continuous", "min": low, "max": high, "dimension": 2, "seriesIndex": 0, "calculable": False,
            "orient": "vertical", "right": 0, "top": "middle", "itemWidth": 10, "itemHeight": 140, "textGap": 6,
            "text": [format_value(high, fmt), format_value(low, fmt)],
            "inRange": {"color": list(SEQUENTIAL["dark" if dark else "light"])},
            "textStyle": {"color": ink["muted"]}, "x-format": fmt}


def _unit_title(spec: dict, y: str) -> str:
    """'Sales (AED)': a panel's or axis's name with its unit, unless the name says it already."""
    _, prefix, suffix = number_format(spec, y)
    unit = (prefix or suffix).strip()
    return f"{y} ({unit})" if unit and unit != "%" and unit.lower() not in y.lower() else y


def _blend(stops: list[str], t: float) -> str:
    """The colour at t (0-1) along a sequential scale."""
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return _shade(stops[i], stops[i + 1], t - i)


def _ink_on(color: str) -> str:
    """Dark or white text, whichever reads on this colour."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#1d1d1f" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff"


# ---------------------------------------------------------------- the option --

def build_option(df: pd.DataFrame, spec: dict, dark: bool = False, compare: dict | None = None,
                 show_title: bool = True) -> dict | None:
    """The ECharts option for this result and chart spec, or None if a table is the better display.
    compare = {"df": the same query for the comparison dates, "current": "1 Jan – 15 Oct 2026",
    "name": "1 Jan – 15 Oct 2025"}: drawn in grey next to the period where it reads clearly (columns,
    bars and lines of one measure), as charts.build_figure does."""
    spec = fit(df, spec)
    kind = spec["chart_type"]
    if kind == "custom":
        return _custom(df, spec, dark, show_title)
    if kind == "table":
        return None
    df, note = trim(df, spec)
    if wants_one_chart(df, spec):
        option = _one_chart(df, spec, dark, show_title)
    elif needs_panels(df, spec):
        option = _panels(df, spec, dark, show_title)
    elif kind in _DRAW:
        option = _DRAW[kind](df, spec, dark, show_title)
    else:
        option = _cartesian(df, spec, dark, show_title, compare)
    option["x-app"] = {"version": VERSION, "chart_type": kind, "x": spec.get("x") or "", "y": list(spec.get("y") or []),
                       "color": spec.get("color") or "", "theme": "dark" if dark else "light", "height": None,
                       "note": note, "compare": None, **option.get("x-app", {})}
    if sum(len(d.get("source") or []) for d in option.get("dataset") or []) > LARGE * 5:
        option["animation"] = False  # many points: draw at once
    return _plain(option)


def _custom(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict | None:
    """A chart described in words: an ECharts option Claude wrote (checked by custom_echarts), or a
    saved Plotly spec drawn by the Plotly fallback; the best standard chart when it no longer draws."""
    import custom_echarts
    import dynamic_chart
    title = str(spec.get("title") or "") if show_title else ""
    try:
        if custom_echarts.is_echarts(spec["custom"]):
            return custom_echarts.build(df, spec["custom"], dark=dark, title=title)
        figure = dynamic_chart.build(df, spec["custom"], dark=dark, title=title)
    except dynamic_chart.ChartSpecError:
        fallback = {**suggest(df), "title": spec.get("title", ""), "style": spec.get("style")}
        return build_option(df, fallback, dark, show_title=show_title)
    return {"x-app": {"version": VERSION, "kind": "plotly", "chart_type": "custom", "x": "", "y": [], "color": "",
                      "theme": "dark" if dark else "light", "figure": json.loads(figure.to_json())}}


# ---------------------------------------------------------------- columns, bars, lines, areas --

def _arrange(data: pd.DataFrame, x: str, first: str, kind: str, sort: str, broken_down: bool,
             time_axis: bool) -> tuple[pd.DataFrame, list, str]:
    """The rows in drawing order, the categories in order, and how they were ordered: time left to
    right; bars as Claude sorted them; horizontal bars biggest first unless told otherwise."""
    if is_time_column(data[x]):
        data = _in_time(data, x)
        if time_axis:
            return data, [], "time"
        labels = _labels(data[x])
        return data.assign(**{x: labels}), list(dict.fromkeys(labels)), "time"
    labels = _labels(data[x])
    how = "data"
    if kind in BAR_KINDS and sort in ("value_desc", "value_asc", "label"):
        how = sort
    elif kind == "horizontal_bar" and not broken_down and not sort:
        how = "value_desc"
    order = _sorted(labels, data[first], how)
    return _by_position(data.assign(**{x: labels}), x, order), order, how


def _comparable(kind: str, ys: list, color: str, compare: dict | None, x: str) -> bool:
    prev = (compare or {}).get("df")
    return (kind in COMPARABLE and len(ys) == 1 and not color and prev is not None and not prev.empty
            and x in prev.columns and ys[0] in prev.columns)


def _with_comparison(data: pd.DataFrame, x: str, y: str, kind: str, prev: pd.DataFrame) -> pd.DataFrame:
    """The rows with the comparison's value (_compare), its date over time (_compare_label) and the
    change (_change, a fraction): over time the same position in each period (1st month with 1st
    month), else the same category."""
    if kind in ("line", "area"):
        before = prev.iloc[time_order(prev[x])]
        old, when = [None] * len(data), [None] * len(data)
        for slot, w, v in zip(time_order(data[x].tolist()), before[x], before[y]):
            old[slot], when[slot] = _cell(v), _label(w)
        data = data.assign(_compare=pd.to_numeric(pd.Series(old, index=data.index, dtype=object), errors="coerce"),
                           _compare_label=when)
    else:
        by_cat = prev.groupby(_labels(prev[x]).to_numpy())[y].sum()
        data = data.assign(_compare=data[x].map(by_cat).astype(float))
    before = data["_compare"]
    return data.assign(_change=(data[y] - before) / before.abs().where(before != 0))


def _cartesian(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool, compare: dict | None) -> dict:
    kind, x, ys, color = spec["chart_type"], spec["x"], list(spec["y"]), spec.get("color") or ""
    style = spec.get("style") or {}
    option, ink, title = _frame(spec, dark, show_title)
    horizontal, bars = kind == "horizontal_bar", kind in BAR_KINDS
    time_axis = kind in ("line", "area") and pd.api.types.is_datetime64_any_dtype(df[x])
    data = df[list(dict.fromkeys([x, *([color] if color else []), *ys]))]
    data, order, how = _arrange(data, x, ys[0], kind, style.get("sort") or "", bool(color), time_axis)
    names = []
    if color:
        data = data.assign(**{color: _labels(data[color])})
        names = _breakdown(data[color], df[color])
    compared = _comparable(kind, ys, color, compare, x)
    if compared:
        data = _with_comparison(data, x, ys[0], kind, compare["df"])
    option["dataset"] = [_dataset(data, {x} if time_axis else ())] + [_view(color, n, j) for j, n in enumerate(names)]

    value_dim, label_dim = ("x", "y") if horizontal else ("y", "x")
    radius = [0, 4, 4, 0] if horizontal else [4, 4, 0, 0]
    several = bool(color) or len(ys) > 1

    def one(name: str, y: str, index: int, last: bool) -> dict:
        s = {"type": "bar" if bars else "line", "name": name, "datasetIndex": index,
             "encode": {label_dim: x, value_dim: y, "tooltip": [y]}, "x-format": value_format(spec, df, y), "x-value": y}
        if bars:
            s.update(_BAR_GAPS, itemStyle={"borderRadius": radius if kind != "stacked_bar" or last else 0})
        else:
            s.update(symbol="circle", symbolSize=8, showSymbol=kind == "line" and len(data) <= 40, lineStyle={"width": 2})
        if kind == "stacked_bar" or (kind == "area" and several):  # Plotly's areas stack, like stacked columns
            s["stack"] = "total"
        if kind == "area":
            s["areaStyle"] = {"opacity": 0.35}
        if bars and style.get("show_values"):
            stacked = kind == "stacked_bar"
            s.update(label={"show": True, "position": "inside" if stacked else ("right" if horizontal else "top"),
                            "fontSize": 11, "color": "#ffffff" if stacked else ink["text"]},
                     labelLayout={"hideOverlap": True}, **{"x-label": "{value}"})
        if horizontal:
            s["x-tooltip"] = "{name}<br>{series}: {value}" if several else "{name}<br>{value}"
        return _fast(s, len(data))

    if color:
        series = [one(n, ys[0], j + 1, j == len(names) - 1) for j, n in enumerate(names)]
    else:
        series = [one(y, y, 0, i == len(ys) - 1) for i, y in enumerate(ys)]
    legend_data = None
    if compared:
        series, legend_data = _comparison_series(series[0], kind, x, compare, dark, label_dim, value_dim, radius)

    place = _legend_place(spec, several, force=compared)
    option["legend"] = _legend(place, ink, title, **({"data": legend_data} if legend_data else {}))
    value_name, label_name = style.get("y_title") or "", style.get("x_title") or ""
    if time_axis:
        label_axis = _time_axis(ink, label_name)
    else:
        label_axis = _category_axis(ink, data=order if color else None, name=label_name, inverse=horizontal,
                                    rotate=0 if horizontal else -(style.get("label_angle") or 0))
    value_axis = _value_axis(ink, axis_format(spec, ys[0]), name=value_name, log=bool(style.get("log_scale")),
                             across=horizontal)
    option["xAxis"], option["yAxis"] = (value_axis, label_axis) if horizontal else (label_axis, value_axis)
    option["series"] = series
    if not horizontal:
        option["tooltip"].update(trigger="axis", axisPointer={"type": "shadow" if bars else "line"})
    rotated = 40 if style.get("label_angle") and not horizontal else 0
    option["grid"] = _grid(place, title, top=18 if value_name and not horizontal else 0,
                           bottom=(24 if (label_name if not horizontal else value_name) else 0) + rotated,
                           right=24 if horizontal else 0)  # room for the last number along the bottom
    option["x-app"] = {
        "kind": kind, "formats": {**_formats(spec, df, ys), **(_compare_formats(spec, df, ys[0]) if compared else {})},
        "dataset": {"id": "result", "columns": list(map(str, data.columns)), "breakdown": color or None, "views": names},
        "categories": {"axis": "yAxis" if horizontal else "xAxis", "column": x, "order": how,
                       "type": "time" if time_axis else "category", "explicit": bool(color) and not time_axis},
        "compare": {"current": compare["current"], "name": compare["name"]} if compared else None,
    }
    return option


def _comparison_series(current: dict, kind: str, x: str, compare: dict, dark: bool, label_dim: str,
                       value_dim: str, radius: list) -> tuple[list, list]:
    """The period in colour (the change in its tooltip) and the comparison in grey: bars beside each
    period's bar, or a dotted line over time. Both named by their dates, this period first."""
    grey = COMPARE_COLOR["dark" if dark else "light"]
    current.update(name=compare["current"], **{"x-change": "_change"})
    other = {"name": compare["name"], "datasetIndex": 0, "encode": {label_dim: x, value_dim: "_compare", "tooltip": ["_compare"]},
             "x-format": current["x-format"], "x-value": "_compare"}
    if kind in ("line", "area"):
        other.update(type="line", showSymbol=False, connectNulls=True, itemStyle={"color": grey},
                     lineStyle={"color": grey, "width": 2, "type": "dotted"}, **{"x-when": "_compare_label"})
        return [current, other], [compare["current"], compare["name"]]
    other.update(type="bar", itemStyle={"color": grey, "borderRadius": radius}, **_BAR_GAPS)
    if "x-tooltip" in current:  # horizontal bars (read from the top): the comparison below each period's bar
        current["x-tooltip"] = other["x-tooltip"] = "{name}<br>{series}: {value}"
        return [current, other], [compare["current"], compare["name"]]
    return [other, current], [compare["current"], compare["name"]]  # columns: the comparison left of each


def _compare_formats(spec: dict, df: pd.DataFrame, y: str) -> dict:
    return {"_compare": value_format(spec, df, y), "_change": describe_format("+.1%")}


# ---------------------------------------------------------------- scatter --

def _scatter(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    ys, color, style = list(spec["y"]), spec.get("color") or "", spec.get("style") or {}
    x, y = spec.get("x") or ys[0], ys[-1]
    option, ink, title = _frame(spec, dark, show_title)
    data = df[list(dict.fromkeys([x, *([color] if color else []), y]))]
    numeric_x = _is_number(df[x]) and not is_time_column(df[x])
    dated_x = pd.api.types.is_datetime64_any_dtype(df[x])
    if not numeric_x and not dated_x:
        data = data.assign(**{x: _labels(data[x])})
    names = []
    if color:
        data = data.assign(**{color: _labels(data[color])})
        names = _breakdown(data[color], df[color])
    option["dataset"] = [_dataset(data, {x} if dated_x else ())] + [_view(color, n, j) for j, n in enumerate(names)]
    head = "{series}<br>" if color else ""
    series = [_fast({"type": "scatter", "name": n or y, "datasetIndex": j + 1 if color else 0,
                     "encode": {"x": x, "y": y, "tooltip": [y]}, "symbolSize": 9,
                     "itemStyle": {"borderColor": ink["surface"], "borderWidth": 1},
                     "x-format": value_format(spec, df, y), "x-value": y,
                     "x-tooltip": f"{head}{x}: {{col:{x}}}<br>{y}: {{value}}"}, len(data))
              for j, n in enumerate(names or [""])]
    if numeric_x:
        x_axis = _value_axis(ink, axis_format(spec, x), name=style.get("x_title") or "", across=True, grid_lines=False,
                             axisLine={"show": True, "lineStyle": {"color": ink["grid"]}})
    elif dated_x:
        x_axis = _time_axis(ink, style.get("x_title") or "")
    else:
        x_axis = _category_axis(ink, name=style.get("x_title") or "")
    place = _legend_place(spec, bool(color))
    option.update(legend=_legend(place, ink, title), xAxis=x_axis, series=series,
                  yAxis=_value_axis(ink, axis_format(spec, y), name=style.get("y_title") or "", log=bool(style.get("log_scale"))),
                  grid=_grid(place, title, top=18 if style.get("y_title") else 0, bottom=24 if style.get("x_title") else 0))
    option["x-app"] = {"kind": "scatter", "formats": _formats(spec, df, [x, y]),
                       "dataset": {"id": "result", "columns": list(map(str, data.columns)), "breakdown": color or None,
                                   "views": names}}
    return option


# ---------------------------------------------------------------- donut --

def _donut(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    x, y, style = spec["x"], spec["y"][0], spec.get("style") or {}
    option, ink, title = _frame(spec, dark, show_title)
    data = df[[x, y]].assign(**{x: _labels(df[x])})
    if style.get("sort") in ("value_desc", "value_asc"):
        data = data.sort_values(y, ascending=style["sort"] == "value_asc", kind="stable")
    place = _legend_place(spec, True)
    option["dataset"] = [_dataset(data)]
    option["legend"] = _legend(place, ink, title)
    with_values = bool(style.get("show_values"))
    option["series"] = [{
        "type": "pie", "radius": ["54%", "90%"], "center": ["50%", "50%"],  # the hole 0.6 of the radius, as Plotly's
        "top": 12 + (TITLE_H if title else 0) + (LEGEND_H if place == "top" else 0),
        "bottom": 8 + (LEGEND_H if place == "bottom" else 0), "right": 150 if place == "right" else 0,
        "datasetIndex": 0, "encode": {"itemName": x, "value": y, "tooltip": [y]}, "avoidLabelOverlap": False,
        "percentPrecision": 1, "labelLine": {"show": False},
        "label": {"show": True, "position": "inside", "formatter": "{d}%\n{c}" if with_values else "{d}%",
                  "color": "#ffffff", "fontSize": 12},
        "itemStyle": {"borderColor": ink["surface"], "borderWidth": 2},
        "x-format": value_format(spec, df, y), "x-value": y,
        "x-label": "{percent}\n{value}" if with_values else "{percent}", "x-tooltip": "{name}<br>{value}<br>{percent}",
    }]
    option["x-app"] = {"kind": "donut", "formats": _formats(spec, df, [y]),
                       "dataset": {"id": "result", "columns": [x, y], "breakdown": None, "views": []},
                       "categories": {"axis": None, "column": x, "order": style.get("sort") or "data"}}
    return option


# ---------------------------------------------------------------- treemap --

def _treemap(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    """Shares across many parts, coloured light to dark by value (a parent by its parts' weighted
    mean, as Plotly does); with a second breakdown, its values hold the parts."""
    x, y, color = spec["x"], spec["y"][0], spec.get("color") or ""
    option, ink, title = _frame(spec, dark, show_title)
    seq = SEQUENTIAL["dark" if dark else "light"]
    data = df.assign(**{x: _labels(df[x]), **({color: _labels(df[color])} if color else {})})
    leaves = data.groupby([color, x] if color else [x], sort=False)[y].sum()
    low, high = float(leaves.min()), float(leaves.max())

    def node(name, value: float, mean: float | None = None) -> dict:
        paint = _blend(seq, 1.0 if high <= low else ((value if mean is None else mean) - low) / (high - low))
        return {"name": str(name), "value": float(value), "itemStyle": {"color": paint},
                "label": {"color": _ink_on(paint)}, "upperLabel": {"color": _ink_on(paint)}}

    if color:
        items = []
        for parent, part in leaves.groupby(level=0, sort=False):
            total = float(part.sum())
            mean = float((part * part).sum() / total) if total else low
            children = [node(key[-1] if isinstance(key, tuple) else key, v) for key, v in part.items()]
            outer = node(parent, total, mean)  # ECharts paints a parent's name band in its border colour
            outer["itemStyle"]["borderColor"] = outer["itemStyle"]["color"]
            items.append({**outer, "children": children})
    else:
        items = [node(key[0] if isinstance(key, tuple) else key, v) for key, v in leaves.items()]
    border = {"borderColor": ink["surface"], "borderWidth": 2, "gapWidth": 2, "borderRadius": 6}
    option["series"] = [{
        "type": "treemap", "name": y, "data": items, "top": 12 + (TITLE_H if title else 0), "left": 0, "right": 0,
        "bottom": 30 if color else 0, "roam": False, "nodeClick": "zoomToNode" if color else False,
        "breadcrumb": {"show": bool(color), "bottom": 0, "left": 0,
                       "itemStyle": {"color": ink["land"], "borderColor": ink["surface"], "textStyle": {"color": ink["text"]}}},
        "itemStyle": border, "label": {"show": True, "formatter": "{b}\n{c}", "fontSize": 12},
        "upperLabel": {"show": bool(color), "height": 22, "fontWeight": 600},
        "levels": [{"itemStyle": {"borderWidth": 0, "gapWidth": 4}, "upperLabel": {"show": False}},
                   {"itemStyle": {"borderWidth": 3, "gapWidth": 2, "borderRadius": 6}},
                   {"itemStyle": {**border, "borderWidth": 1}}] if color else [{"itemStyle": border}],
        "x-format": value_format(spec, df, y), "x-label": "{name}\n{value}", "x-tooltip": "{name}<br>{value}",
    }]
    option["x-app"] = {"kind": "treemap", "formats": _formats(spec, df, [y]),
                       "dataset": None, "data": "inline: treemaps take their data in the series (no dataset)"}
    return option


# ---------------------------------------------------------------- heatmap --

def _heatmap(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    """Two breakdowns: x along, the second breakdown down (first value at the top), a cell per pair."""
    x, y, color = spec["x"], spec["y"][0], spec["color"]
    option, ink, title = _frame(spec, dark, show_title)
    data = _in_time(df, x) if is_time_column(df[x]) else df
    data = data[[x, color, y]].assign(**{x: _labels(data[x]), color: _labels(data[color])})
    data = data.groupby([x, color], sort=False)[y].first().reset_index()  # one value per cell, as pivot_table "first"
    columns, rows = list(dict.fromkeys(data[x])), _breakdown(data[color], df[color])
    small = len(columns) * len(rows) <= 120  # small grids show their numbers
    d3, prefix, suffix = number_format(spec, y)
    option["dataset"] = [_dataset(data)]
    option["xAxis"] = _category_axis(ink, data=columns, axisLine={"show": False})
    option["yAxis"] = _category_axis(ink, data=rows, inverse=True, axisLine={"show": False})
    option["visualMap"] = [_scale(data[y], axis_format(spec, y), ink, dark)]
    option["series"] = [_fast({
        "type": "heatmap", "datasetIndex": 0, "encode": {"x": x, "y": color, "value": y, "tooltip": [y]},
        "label": {"show": small, "fontSize": 11},  # no colour: ECharts picks dark or white text for each cell
        "itemStyle": {"borderColor": ink["surface"], "borderWidth": 1},
        "emphasis": {"itemStyle": {"borderColor": ink["text"], "borderWidth": 1}},
        "x-format": describe_format(d3 or ",.0f", prefix, suffix), "x-value": y, "x-label": "{value}",
        "x-tooltip": f"{{col:{color}}} · {{col:{x}}}<br>{{value}}",
    }, len(data))]
    option["grid"] = _grid("none", title, right=64)
    option["x-app"] = {"kind": "heatmap", "formats": _formats(spec, df, [y]),
                       "dataset": {"id": "result", "columns": [x, color, y], "breakdown": None, "views": []},
                       "categories": {"axis": "xAxis", "column": x, "order": "time" if is_time_column(df[x]) else "data",
                                      "type": "category", "explicit": True, "rows": color}}
    return option


# ---------------------------------------------------------------- map --

def _map(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    """Countries coloured light to dark by value; names the result spells its own way are matched to
    ISO-3 codes (charts.country_code); countries that can't be matched are listed in x-app.map."""
    x, y = spec["x"], spec["y"][0]
    option, ink, title = _frame(spec, dark, show_title)
    data = df[[x, y]].assign(**{x: _labels(df[x])})
    codes = data[x].map(country_code)
    unmatched = sorted(set(data.loc[codes.isna(), x]) - {""})
    data = data.assign(_iso=codes).dropna(subset=["_iso"])
    data = data.groupby("_iso", sort=False).agg({x: "first", y: "sum"}).reset_index()[[x, "_iso", y]]
    mode = "dark" if dark else "light"
    option["dataset"] = [_dataset(data)]
    option["visualMap"] = [_scale(data[y], axis_format(spec, y), ink, dark)]
    option["series"] = [{
        "type": "map", "map": MAP_NAME, "nameProperty": MAP_KEY, "datasetIndex": 0,
        "encode": {"itemName": "_iso", "value": y, "tooltip": [y]}, "roam": False, "selectedMode": False,
        "top": 12 + (TITLE_H if title else 0), "bottom": 0, "left": 0, "right": 48, "showLegendSymbol": False,
        "itemStyle": {"areaColor": ink["land"], "borderColor": ink["surface"], "borderWidth": 0.5},
        "emphasis": {"label": {"show": False}, "itemStyle": {"areaColor": PALETTE[mode][3], "borderColor": ink["surface"]}},
        "x-format": value_format(spec, df, y), "x-value": y, "x-tooltip": f"{{col:{x}}}<br>{{value}}",
    }]
    option["x-app"] = {"kind": "map", "height": 420, "formats": _formats(spec, df, [y]),
                       "dataset": {"id": "result", "columns": [x, "_iso", y], "breakdown": None, "views": []},
                       "map": {"name": MAP_NAME, "nameProperty": MAP_KEY, "exclude": ["ATA"],
                               "codes": dict(zip(data[x], data["_iso"])), "unmatched": unmatched}}
    return option


_DRAW = {"donut": _donut, "treemap": _treemap, "heatmap": _heatmap, "map": _map, "scatter": _scatter}


# ---------------------------------------------------------------- panels (small multiples) --
# Measures of different size or unit (requests in millions, bookings in tens, sales in AED) each get
# a panel with its own scale and format; the panels share the categories, the second breakdown is
# drawn the same way in each, with one legend (series of the same name toggle together).

def _tick_width(df: pd.DataFrame, column: str, fmt: dict) -> int:
    """Pixels the widest tick label of a number axis needs (panels line their plots up by it)."""
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    texts = [format_value(v, fmt) for v in (values.max(), values.min(), 0)] if len(values) else ["0"]
    return 14 + 7 * max(len(t) for t in texts)


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.2f}%"


def _panels(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    kind, x, color = spec["chart_type"], spec["x"], spec.get("color") or ""
    ys = [y for y in spec["y"] if y in df.columns]
    style = spec.get("style") or {}
    option, ink, title = _frame(spec, dark, show_title)
    colors = PALETTE["dark" if dark else "light"]
    horizontal, over_time = kind == "horizontal_bar", kind in ("line", "area")
    if over_time and is_time_column(df[x]):
        df = _in_time(df, x)
    labels = _labels(df[x])
    order = list(dict.fromkeys(labels))
    sort = style.get("sort") or ""
    if sort in ("value_desc", "value_asc") and not over_time:
        order = _sorted(labels, df[ys[0]], sort)
    elif sort == "label":
        order = sorted(order)
    data = df[list(dict.fromkeys([x, *([color] if color else []), *ys]))].assign(**{x: labels})
    names = []
    if color:
        data = data.assign(**{color: _labels(data[color])})
        names = list(dict.fromkeys(data[color]))
    if not over_time:  # one bar per category (and breakdown value)
        data = data.groupby([x, *([color] if color else [])], sort=False)[ys].sum().reset_index()
    data = _by_position(data, x, order)
    option["dataset"] = [_dataset(data)] + [_view(color, n, j) for j, n in enumerate(names)]

    n, header = len(ys), 8 + (TITLE_H if title else 0)
    height = 360 if horizontal else 175 * n + 70
    rotate = -(style.get("label_angle") or 0) if not horizontal else 0
    grids, axes_x, axes_y, titles, series = [], [], [], [], []
    if horizontal:  # the names once, left of the first panel (in pixels), the panels in equal parts after it
        labels_px = int(min(220, 14 + 6.5 * max((len(c) for c in order), default=1)))
        gap = 6.0
        width = (98 - gap * (n - 1)) / n
    else:  # the panels' plots lined up behind the widest numbers
        left = max(_tick_width(data, y, axis_format(spec, y)) for y in ys)
        bottom = 28 + (40 if rotate else 0)
        slot = (height - header - bottom) / n
    for i, y in enumerate(ys):
        axis_fmt = axis_format(spec, y)
        if horizontal:
            start = labels_px if i == 0 else f"{i * (width + gap):.2f}%"
            grids.append({"left": start, "right": f"{100 - i * (width + gap) - width:.2f}%", "top": header + 24, "bottom": 28})
            titles.append({"text": _unit_title(spec, y), "left": start, "top": header})
            names_axis = _category_axis(ink, data=order, inverse=True, show_labels=i == 0, gridIndex=i)
            names_axis["axisLabel"].update(width=labels_px - 12, overflow="truncate")
            axes_y.append(names_axis)
            numbers_axis = _value_axis(ink, axis_fmt, gridIndex=i, splitNumber=3)
            numbers_axis["axisLabel"]["showMaxLabel"] = False  # clear of the next panel's first number
            axes_x.append(numbers_axis)
        else:
            top = header + i * slot
            grids.append({"left": left, "right": 12, "top": _pct(top + 30, height), "height": _pct(slot - 42, height)})
            titles.append({"text": _unit_title(spec, y), "left": 0, "top": _pct(top, height)})
            axes_x.append(_category_axis(ink, data=order, show_labels=i == n - 1, rotate=rotate if i == n - 1 else 0,
                                         gridIndex=i))
            axes_y.append(_value_axis(ink, axis_fmt, gridIndex=i, splitNumber=3))
        fmt = value_format(spec, df, y)
        for j, name in enumerate(names or [""]):
            colour = colors[j % len(colors)]
            s = {"name": name or y, "datasetIndex": j + 1 if color else 0, "xAxisIndex": i, "yAxisIndex": i,
                 "encode": {"y": x, "x": y, "tooltip": [y]} if horizontal else {"x": x, "y": y, "tooltip": [y]},
                 "itemStyle": {"color": colour}, "x-format": fmt, "x-value": y}
            if over_time:
                s.update(type="line", symbol="circle", symbolSize=6, showSymbol=len(order) <= 40,
                         lineStyle={"color": colour, "width": 2}, **({"areaStyle": {"opacity": 0.35}} if kind == "area" else {}))
            else:
                s.update(type="bar", barCategoryGap="25%", barGap="6%",
                         itemStyle={"color": colour, "borderRadius": [0, 3, 3, 0] if horizontal else [3, 3, 0, 0]})
            if horizontal:
                s["x-tooltip"] = "{name} · {series}: {value}"
            series.append(_fast(s, len(data)))
    for t in titles:
        t["textStyle"] = {"fontSize": 12, "fontWeight": 500, "color": ink["text"]}
    option["title"] = option["title"] + titles
    option.update(grid=[{**g, "containLabel": False} for g in grids], xAxis=axes_x, yAxis=axes_y, series=series,
                  legend=_legend("top" if color else "none", ink, title, top=header, left="right", data=names))
    if horizontal:
        option["tooltip"]["trigger"] = "item"
    else:
        option["tooltip"].update(trigger="axis", axisPointer={"type": "line" if over_time else "shadow"})
        option["axisPointer"] = {"link": [{"xAxisIndex": "all"}]}  # the same category pointed at in every panel
    option["x-app"] = {"kind": "panels", "height": height, "formats": _formats(spec, df, ys),
                       "panels": [_unit_title(spec, y) for y in ys],
                       "dataset": {"id": "result", "columns": list(map(str, data.columns)), "breakdown": color or None,
                                   "views": names},
                       "categories": {"axis": "yAxis" if horizontal else "xAxis", "column": x, "type": "category",
                                      "order": "time" if over_time and is_time_column(df[x]) else (sort or "data"),
                                      "explicit": True}}
    return option


# ---------------------------------------------------------------- one chart, an axis per measure --
# When the user asks for the measures together ("6 bars for each customer, 3 for each day"): up to 3
# measures, each on its own axis in its own colour (axis and bars alike), the bars side by side, and
# a second breakdown (e.g. the day) in shades of each measure's colour, earliest lightest.

def _one_chart(df: pd.DataFrame, spec: dict, dark: bool, show_title: bool) -> dict:
    kind, x, color = spec["chart_type"], spec["x"], spec.get("color") or ""
    ys = [y for y in spec["y"] if y in df.columns]
    style = spec.get("style") or {}
    option, ink, title = _frame(spec, dark, show_title)
    mode = "dark" if dark else "light"
    colors = PALETTE[mode]
    over_time = kind in ("line", "area")
    if is_time_column(df[x]):
        df = _in_time(df, x)
    labels = _labels(df[x])
    order = list(dict.fromkeys(labels))
    sort = style.get("sort") or ""
    if sort in ("value_desc", "value_asc") and not over_time:
        order = _sorted(labels, df[ys[0]], sort)
    elif sort == "label":
        order = sorted(order)
    data = df[list(dict.fromkeys([x, *([color] if color else []), *ys]))].assign(**{x: labels})
    names = []
    if color:
        key, in_time = _day_names(data[color])
        names = list(dict.fromkeys(key[in_time]))
        data = data.assign(**{color: key})
    data = data.groupby([x, *([color] if color else [])], sort=False)[ys].sum().reset_index()
    data = _by_position(data, x, order)
    option["dataset"] = [_dataset(data)] + [_view(color, n, j) for j, n in enumerate(names)]

    series, axes = [], []
    groups = names or [""]
    for i, y in enumerate(ys):
        base, fmt = colors[i % len(colors)], value_format(spec, df, y)
        for j, name in enumerate(groups):
            # earliest lightest: with 2 days the first is a light shade, the second the measure's own colour
            hue = _shade(base, ink["surface"], 0.55 * (len(groups) - 1 - j) / max(len(groups) - 1, 1))
            s = {"name": f"{y} · {name}" if name else y, "datasetIndex": j + 1 if color else 0, "yAxisIndex": i,
                 "encode": {"x": x, "y": y, "tooltip": [y]}, "itemStyle": {"color": hue},
                 "x-format": fmt, "x-value": y, "x-group": y}
            if over_time:
                s.update(type="line", symbol="circle", symbolSize=6, showSymbol=len(order) <= 40,
                         lineStyle={"color": hue, "width": 2},
                         **({"areaStyle": {"opacity": 0.35}} if kind == "area" and i == 0 else {}))
            else:
                s.update(type="bar", barCategoryGap="20%", barGap="4%", itemStyle={"color": hue, "borderRadius": [3, 3, 0, 0]})
            series.append(_fast(s, len(data)))
        axes.append(_value_axis(ink, axis_format(spec, y), name=_unit_title(spec, y), color=base, grid_lines=i == 0,
                                align="left" if i == 0 else "right", position="left" if i == 0 else "right",
                                offset=72 * (i - 1) if i >= 2 else 0, alignTicks=False))
    rotate = -(style.get("label_angle") or 0)
    entries = [s["name"] for s in series]
    lines = min(3, math.ceil(sum(30 + 7 * len(e) for e in entries) / 560))  # the legend wraps on a ~600 px card
    option.update(
        xAxis=_category_axis(ink, data=order, name=style.get("x_title") or "", rotate=rotate),
        yAxis=axes, series=series,
        legend=_legend("bottom", ink, title, data=entries, type="plain"),
        grid=_grid("bottom", title, top=18, right=72 if len(ys) >= 3 else 0,
                   bottom=(24 if style.get("x_title") else 0) + (40 if rotate else 0) + LEGEND_H * (lines - 1)))
    option["tooltip"].update(trigger="axis", axisPointer={"type": "line" if over_time else "shadow"})
    option["x-app"] = {"kind": "one_chart", "height": 440, "formats": _formats(spec, df, ys),
                       "dataset": {"id": "result", "columns": list(map(str, data.columns)), "breakdown": color or None,
                                   "views": names},
                       "categories": {"axis": "xAxis", "column": x, "type": "category", "explicit": True,
                                      "order": "time" if is_time_column(df[x]) else (sort or "data")}}
    return option


def _day_names(values: pd.Series) -> tuple[pd.Series, pd.Index]:
    """The breakdown's names ('14 Oct 2026' for real dates, without the time) and the rows' index in
    time order (earliest first) when they are times, else as they come."""
    if pd.api.types.is_datetime64_any_dtype(values):
        days = values.dt.normalize()
        key = days.map(lambda d: f"{d.day} {d:%b %Y}" if pd.notna(d) else "").astype(object)
        return key, values.sort_values(kind="stable").index
    key = _labels(values)
    return key, (key.index[time_order(key.tolist())] if is_time_column(values) else key.index)
