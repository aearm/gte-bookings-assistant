"""Charts a user describes in words ("bars for sales with a line for profit % on a second axis", "a
funnel of booking statuses", "a sunburst of region and country"), written by Claude as an ECharts
option and checked here before they are drawn. Nothing in the option is executed - no functions, no
code in formatter text, no links or pictures from the internet - so it is safe to store on a
dashboard and draw again with new numbers: the same safety as dynamic_chart.py gives Plotly specs.

Option (JSON): an ECharts option whose data point at the result's columns.
{
  "prepare": {"group_by": ["Month"], "aggregate": {"Sales": "sum"},       # optional, as dynamic_chart
              "sort_by": "Sales", "descending": true, "top": 10},
  "xAxis": {"type": "category", "data": {"col": "Month"}},
  "yAxis": [{"type": "value", "x-format": {"d3": "~s", "prefix": "AED "}},
            {"type": "value", "position": "right", "x-format": {"d3": ".0%"}}],
  "series": [
    {"type": "bar", "name": "Sales", "data": {"col": "Sales"}},
    {"type": "line", "name": "Profit %", "yAxisIndex": 1, "data": {"col": "Profit %"}},
    {"type": "line", "data": {"cols": ["Month", "Bookings"]}, "split_by": "Channel"},
    {"type": "sunburst", "path": ["Region", "Country"], "value": {"col": "Sales"}}
  ]
}
{"col": "Name"} anywhere becomes that column's values; {"cols": ["A", "B"]} its rows as [a, b]
pairs (scatter points, or [category, value] for a series split by a column); "split_by" makes one
series per value of a column; "path" builds the levels of a treemap / sunburst / tree. A dataset
works too: {"dataset": {"source": {"cols": ["Month", "Sales"]}}} becomes the rows, with the column
names as its dimensions, for series to "encode" by name. "x-format" on an axis, series or visualMap
takes a d3 format (as the standard charts' formats) and becomes chart_options' format description,
which the browser turns into formatters (module notes of chart_options)."""
import copy
import json
import re

import pandas as pd

import chart_options
import dynamic_chart
from charts import FONT, INK, PALETTE

COMPONENTS = {
    "title", "legend", "grid", "xAxis", "yAxis", "polar", "radiusAxis", "angleAxis", "radar", "dataZoom",
    "visualMap", "tooltip", "axisPointer", "toolbox", "brush", "geo", "parallel", "parallelAxis", "singleAxis",
    "calendar", "dataset", "aria", "series", "color", "backgroundColor", "textStyle", "animation",
    "animationDuration", "animationEasing", "darkMode", "useUTC", "prepare",
}
SERIES_TYPES = {
    "line", "bar", "pie", "scatter", "effectScatter", "radar", "tree", "treemap", "sunburst", "boxplot",
    "candlestick", "heatmap", "map", "parallel", "lines", "graph", "sankey", "funnel", "gauge", "pictorialBar",
    "themeRiver",
}
HIERARCHY_TYPES = {"treemap", "sunburst", "tree"}
MAX_SERIES = 40
MAX_LENGTH = 100_000  # characters of option text Claude may write
_CODE = re.compile(r"\bfunction\b|=>|\breturn\b|\beval\b|\bnew\s+Function\b|`|\$\{|\bdocument\s*\.|\bwindow\s*\.",
                   re.IGNORECASE)
_LINK = re.compile(r"\b(?!path://)[a-z][a-z0-9+.-]*://|\bjavascript\s*:|\bvbscript\s*:|\bdata\s*:\s*[a-z]+/|"
                   r"\burl\s*\(|\bwww\.", re.IGNORECASE)
_TAG = re.compile(r"<\s*/?\s*([a-zA-Z][\w-]*)([^>]*)>")
_SAFE_TAGS = {"br", "b", "i", "strong", "em", "sub", "sup"}
_FORMAT_KEYS = {"style", "decimals", "thousands", "sign", "trim", "prefix", "suffix"}


class CustomChartError(dynamic_chart.ChartSpecError):
    """The option can't be drawn or isn't allowed (the message says why, for Claude to fix it)."""


# ---------------------------------------------------------------- reading the option --

def _load(option) -> dict:
    if isinstance(option, str):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", option.strip())
        if len(text) > MAX_LENGTH:
            raise CustomChartError(f"The chart option is too long (over {MAX_LENGTH:,} characters).")
        try:
            option = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CustomChartError(f"The chart option is not valid JSON: {exc}") from exc
    if not isinstance(option, dict):
        raise CustomChartError("The chart option must be a JSON object with a 'series' list.")
    return copy.deepcopy(option)


def is_echarts(option) -> bool:
    """True for an ECharts option (has "series"), False for a Plotly spec (dynamic_chart) or nonsense."""
    try:
        option = _load(option)
    except CustomChartError:
        return False
    return "series" in option and "traces" not in option and "data" not in option


def parse(option) -> dict:
    """An option from Claude (JSON text or a dict), checked: known parts and series types only, and
    nothing that runs code or fetches from the internet."""
    option = _load(option)
    if len(json.dumps(option, default=str)) > MAX_LENGTH:
        raise CustomChartError(f"The chart option is too long (over {MAX_LENGTH:,} characters).")
    unknown = sorted(set(option) - COMPONENTS)
    if unknown:
        raise CustomChartError(f"'{unknown[0]}' is not allowed in a chart option. Use only: {', '.join(sorted(COMPONENTS))}.")
    series = option.get("series")
    if isinstance(series, dict):
        series = option["series"] = [series]
    if not isinstance(series, list) or not series:
        raise CustomChartError("The chart option needs a non-empty 'series' list.")
    for s in series:
        if not isinstance(s, dict):
            raise CustomChartError("Each series must be an object.")
        kind = str(s.get("type", "")).strip()
        if kind == "custom":
            raise CustomChartError("Series of type 'custom' need drawing code, which isn't allowed. Use a standard type.")
        if kind not in SERIES_TYPES:
            raise CustomChartError(f"Series type '{kind}' is not supported. Use one of: {', '.join(sorted(SERIES_TYPES))}.")
    _check(option)
    return option


def _check(value, key: str = "") -> None:
    """Refuse anything that could run or fetch: functions' places, code in formatters, event
    handlers, links and pictures, HTML beyond simple line breaks and emphasis."""
    if isinstance(value, dict):
        for k, v in value.items():
            k = str(k)
            if k == "renderItem" or re.match(r"on[A-Z_a-z]", k) and k not in ("onZero", "onZeroAxisIndex"):
                raise CustomChartError(f"'{k}' is not allowed in a chart option (it runs code).")
            if k == "valueFormatter":
                raise CustomChartError("'valueFormatter' is not allowed; use \"x-format\" with a d3 format instead.")
            _check(v, k)
    elif isinstance(value, list):
        for v in value:
            _check(v, key)
    elif isinstance(value, str):
        if key == "formatter" and _CODE.search(value):
            raise CustomChartError("A formatter must be a text template such as '{b}: {c}', not code; "
                                   "use \"x-format\" for number formats.")
        if _LINK.search(value):
            raise CustomChartError("The chart option contains a link, which isn't allowed (no pictures or pages from the internet).")
        if dynamic_chart._UNSAFE_TEXT.search(value) or any(
                m.group(1).lower() not in _SAFE_TAGS or m.group(2).strip() not in ("", "/") for m in _TAG.finditer(value)):
            raise CustomChartError("The chart option contains HTML that isn't allowed (only <br>, <b>, <i>, <strong>, <em>).")


def columns_used(option) -> set[str]:
    """Every result column the option refers to."""
    option = _load(option)
    found = set()

    def walk(v, key=""):
        if isinstance(v, dict):
            if set(v) == {"col"} and isinstance(v["col"], str):
                found.add(v["col"])
                return
            if set(v) == {"cols"} and isinstance(v["cols"], list):
                found.update(str(c) for c in v["cols"])
                return
            for k, x in v.items():
                if k == "split_by" and isinstance(x, str):
                    found.add(x)
                elif k == "path" and isinstance(x, list):
                    found.update(str(p.get("col") if isinstance(p, dict) else p) for p in x)
                elif k == "encode" and isinstance(x, dict):
                    for names in x.values():
                        found.update(n for n in (names if isinstance(names, list) else [names]) if isinstance(n, str))
                else:
                    walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
    walk({k: v for k, v in option.items() if k != "prepare"})
    prep = option.get("prepare") or {}
    found.update(prep.get("group_by") or [])
    found.update((prep.get("aggregate") or {}).keys())
    if prep.get("sort_by"):
        found.add(prep["sort_by"])
    return found


# ---------------------------------------------------------------- data --

def _column(df: pd.DataFrame, name) -> str:
    try:
        return dynamic_chart._column(df, str(name))
    except dynamic_chart.ChartSpecError as exc:
        raise CustomChartError(str(exc)) from exc


def _values(series: pd.Series) -> list:
    return [chart_options._cell(v) for v in series.tolist()]


def _fill(value, df: pd.DataFrame):
    """{"col": name} -> the column's values; {"cols": [names]} -> the rows; everywhere in the value."""
    if isinstance(value, dict):
        if set(value) == {"col"}:
            return _values(df[_column(df, value["col"])])
        if set(value) == {"cols"} and isinstance(value["cols"], list):
            cols = [_column(df, c) for c in value["cols"]]
            return [[chart_options._cell(v) for v in row] for row in df[cols].itertuples(index=False, name=None)]
        return {k: _fill(v, df) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, df) for v in value]
    return value


def _tree(df: pd.DataFrame, path: list, value) -> list[dict]:
    """"path": [outer, ..., inner] -> nested {"name", "value", "children"} with summed values."""
    cols = [_column(df, p.get("col") if isinstance(p, dict) else p) for p in path]
    measure = _column(df, value["col"]) if isinstance(value, dict) and "col" in value else None
    frame = df.assign(_n=1.0) if measure is None else df
    measure = measure or "_n"

    def level(part: pd.DataFrame, depth: int) -> list[dict]:
        nodes = []
        for key, group in part.groupby(cols[depth], sort=False, dropna=False):
            node = {"name": chart_options._label(key[0] if isinstance(key, tuple) else key),
                    "value": float(group[measure].sum())}
            if depth + 1 < len(cols):
                node["children"] = level(group, depth + 1)
            nodes.append(node)
        return nodes
    return level(frame, 0)


def _series(option: dict, df: pd.DataFrame) -> list[dict]:
    out = []
    for s in option["series"]:
        s = copy.deepcopy(s)
        split = s.pop("split_by", None)
        if s["type"] in HIERARCHY_TYPES and "path" in s:
            s["data"] = _tree(df, s.pop("path"), s.pop("value", None))
            out.append(s)
        elif split:
            col, base = _column(df, split), s.get("name")
            for value in pd.unique(df[col]):
                part = df[df[col].isna()] if pd.isna(value) else df[df[col] == value]
                piece = _fill(s, part)
                label = chart_options._label(value)
                piece["name"] = f"{base} · {label}" if base else label
                out.append(piece)
        else:
            out.append(_fill(s, df))
        if len(out) > MAX_SERIES:
            raise CustomChartError(f"The chart would have more than {MAX_SERIES} series; split by a column with fewer values.")
    return out


def _datasets(option: dict, df: pd.DataFrame) -> None:
    """A dataset whose source is {"cols": [...]} gets the rows and the column names as dimensions."""
    sets = option.get("dataset")
    for d in (sets if isinstance(sets, list) else [sets] if isinstance(sets, dict) else []):
        source = d.get("source")
        if isinstance(source, dict) and set(source) == {"cols"}:
            d.setdefault("dimensions", [_column(df, c) for c in source["cols"]])
        if "source" in d:
            d["source"] = _fill(source, df)


def _check_encodes(option: dict, df: pd.DataFrame) -> None:
    for s in option["series"]:
        for names in (s.get("encode") or {}).values():
            for name in names if isinstance(names, list) else [names]:
                if isinstance(name, str):
                    _column(df, name)


# ---------------------------------------------------------------- formats and look --

def _formats(value):
    """"x-format": {"d3": ",.0f", "prefix": "AED "} -> the format description chart_options uses."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = _format(v) if k == "x-format" else _formats(v)
        return out
    if isinstance(value, list):
        return [_formats(v) for v in value]
    return value


def _format(fmt) -> dict:
    if isinstance(fmt, str):
        return chart_options.describe_format(fmt)
    if not isinstance(fmt, dict):
        raise CustomChartError("\"x-format\" must be a d3 format, e.g. {\"d3\": \",.0f\", \"prefix\": \"AED \"}.")
    if "d3" in fmt:
        return chart_options.describe_format(str(fmt.get("d3") or ""), str(fmt.get("prefix") or ""), str(fmt.get("suffix") or ""))
    clean = {**chart_options.AUTO, **{k: v for k, v in fmt.items() if k in _FORMAT_KEYS}}
    if clean["style"] not in ("auto", "fixed", "percent", "compact") or not (
            clean["decimals"] is None or (isinstance(clean["decimals"], int) and 0 <= clean["decimals"] <= 10)):
        raise CustomChartError("\"x-format\" has a style or decimals that aren't allowed.")
    return clean


def _look(option: dict, dark: bool, title: str) -> dict:
    """The app's colours, font and title, wherever the option doesn't set its own; extra y axes without
    grid lines and moved outwards when several share a side (as dynamic_chart does for Plotly)."""
    mode = "dark" if dark else "light"
    ink = INK[mode]
    option.setdefault("color", list(PALETTE[mode]))
    option.setdefault("backgroundColor", "transparent")
    option["textStyle"] = {"fontFamily": FONT, "fontSize": 12, "color": ink["muted"], **(option.get("textStyle") or {})}
    tip = option.get("tooltip")
    if tip is None or isinstance(tip, dict):
        option["tooltip"] = {"confine": True, "backgroundColor": ink["surface"], "borderColor": ink["grid"],
                             "textStyle": {"color": ink["text"], "fontFamily": FONT}, **(tip or {"trigger": "item"})}
    heading = {"left": 0, "top": 0, "textStyle": {"fontSize": 15, "fontWeight": 600, "color": ink["text"]}}
    if title and not option.get("title"):
        option["title"] = [{"text": title, **heading}]
    elif isinstance(option.get("title"), dict):
        option["title"] = {**heading, **option["title"]}
    legend = option.get("legend")
    if isinstance(legend, dict):
        option["legend"] = {"type": "scroll", "top": chart_options.TITLE_H if option.get("title") else 0,
                            "textStyle": {"color": ink["text"]}, **legend}
    for key in ("xAxis", "yAxis"):
        axes = option.get(key)
        listed = axes if isinstance(axes, list) else [axes] if isinstance(axes, dict) else []
        on_side: dict[str, int] = {}
        for i, axis in enumerate(listed):
            axis.setdefault("axisLabel", {}).setdefault("color", ink["muted"])
            axis.setdefault("axisLine", {}).setdefault("lineStyle", {"color": ink["grid"]})
            axis.setdefault("splitLine", {}).setdefault("lineStyle", {"color": ink["grid"]})
            if key == "yAxis" and i > 0:
                axis["splitLine"].setdefault("show", False)
                side = axis.get("position", "left" if i == 0 else "right")
                on_side[side] = on_side.get(side, 0) + 1
                if on_side[side] > 1 or side == "left":
                    axis.setdefault("offset", 64 * (on_side[side] - (0 if side == "left" else 1)))
    return option


# ---------------------------------------------------------------- building --

def build(df: pd.DataFrame, option, dark: bool = False, title: str = "") -> dict:
    """The ECharts option with the result's data filled in and the app's look. Raises CustomChartError."""
    option = parse(option)
    used = columns_used(option)
    data = dynamic_chart.prepare(df, option.pop("prepare", None))
    _datasets(option, data)
    option["series"] = _series(option, data)
    _check_encodes(option, data)
    option = _formats({k: (_fill(v, data) if k not in ("series", "dataset") else v) for k, v in option.items()})
    option = _look(option, dark, title)
    option["x-app"] = {"version": chart_options.VERSION, "kind": "custom", "chart_type": "custom", "x": "", "y": [],
                       "color": "", "theme": "dark" if dark else "light", "height": None, "note": "",
                       "compare": None, "formats": {}, "columns": sorted(used)}
    return chart_options._plain(option)


def check(df: pd.DataFrame, option) -> str:
    """'' if the option draws with this data, else the reason it doesn't."""
    try:
        build(df, option)
        return ""
    except dynamic_chart.ChartSpecError as exc:
        return str(exc)
