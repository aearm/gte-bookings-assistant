"""The React app's charts (ECharts options built on the server, chart_options.py) follow the same rules
as charts.py: the scenarios of test_formatting.py, drawn as ECharts options."""
import json

import pandas as pd
import pytest

import chart_options as co
import charts
import custom_echarts

DF = pd.DataFrame({"Customer": ["Atlas", "Coral Bay", "Desert Pearl", "Lotus"],
                   "Sales": [1_250_000.0, 4_500_000.0, 320_000.0, 2_000_000.0],
                   "Margin": [0.12, 0.08, 0.2, 0.15]})
STYLE = {"formats": [{"column": "Sales", "d3_format": "~s", "prefix": "AED ", "suffix": ""}],
         "x_title": "", "y_title": "Sales (AED)", "sort": "value_desc", "show_values": True,
         "label_angle": -45, "legend": "none", "log_scale": False}
COMPARE = {"current": "1 Jan – 15 Oct 2026", "name": "1 Jan – 15 Oct 2025"}
D = co.describe_format


def rows(option: dict, index: int = 0) -> list[dict]:
    """The rows a dataset gives its series, as ECharts would (applying the filter transform)."""
    found = option["dataset"][index]
    if "transform" in found:
        config = found["transform"]["config"]
        return [r for r in rows(option, found["fromDatasetIndex"]) if r[config["dimension"]] == config["="]]
    names = [d["name"] for d in found["dimensions"]]
    return [dict(zip(names, r)) for r in found["source"]]


def drawn(option: dict, series: dict) -> list:
    """The values one series draws, in its rows' order."""
    return [r[series["x-value"]] for r in rows(option, series.get("datasetIndex", 0))]


# ---------------------------------------------------------------- number formats --

@pytest.mark.parametrize("value, d3, prefix, suffix, text", [
    (4_512_000, "~s", "AED ", "", "AED 4.5M"),
    (1_260_000_000, "~s", "", "", "1.3B"),
    (0.1234, ".1%", "", "", "12.3%"),
    (12.345, ",.1f", "", "%", "12.3%"),
    (1234.4, ",.0f", "", "", "1,234"),
    (3.14159, ",.2f", "", "", "3.14"),
    (None, "", "", "", "-"),
])
def test_numbers_read_like_the_headline_numbers(value, d3, prefix, suffix, text):
    assert co.format_value(value, D(d3, prefix, suffix)) == text == charts.format_number(value, d3, prefix, suffix)


@pytest.mark.parametrize("value, fmt, text", [  # the browser's formatValue must write the same
    (2_000_000, D("~s"), "2M"), (2_000_000, D("s"), "2.0M"), (125_000, D("~s"), "125k"), (999_999, D("~s"), "1M"),
    (950, D("~s"), "950"), (-4_512_000, D("~s", "AED "), "AED -4.5M"), (12_500, D("~s"), "12.5k"),
    (0.125, D("+.1%"), "+12.5%"), (-0.05, D("+.1%"), "-5.0%"), (0.5, D(".0%"), "50%"), (12.3456, D(".2%"), "1234.56%"),
    (1234.5, D(",.0f"), "1,235"), (2.5, D(",.0f"), "3"), (0.125, D(",.2f"), "0.13"), (1234.5, D(".2f"), "1234.50"),
    (-0.001, D(",.2f"), "0.00"), (-1234.5, D(",.1f"), "-1,234.5"), (1234, D("$,.0f"), "$1,234"), (7, D(",d"), "7"),
    (1500, D(""), "1,500"), (0.125, D(""), "0.13"), (3, D(""), "3"), (40_000_000, D(""), "40M"),
    (12.0, D(",.1f", suffix=" nights"), "12.0 nights"), (1.5, D(".2~f"), "1.5"),
    (float("nan"), D(",.0f"), "-"), (float("inf"), D(",.0f"), "-"), ("Atlas", D(",.0f"), "Atlas"),
])
def test_format_value_examples(value, fmt, text):
    assert co.format_value(value, fmt) == text


def test_d3_formats_become_format_descriptions():
    assert D(",.0f") == {"style": "fixed", "decimals": 0, "thousands": True, "sign": False, "trim": False,
                         "prefix": "", "suffix": ""}
    assert D("~s", "AED ") == {"style": "compact", "decimals": None, "thousands": False, "sign": False, "trim": True,
                               "prefix": "AED ", "suffix": ""}
    assert (D(".1%")["style"], D(".1%")["decimals"], D(".1%")["thousands"]) == ("percent", 1, False)
    assert D("+.1%")["sign"] and D(",.2f")["decimals"] == 2 and D(".0%")["decimals"] == 0
    assert D("")["style"] == D(".3e")["style"] == D("nonsense")["style"] == "auto"
    assert D(".3e", "", " s")["suffix"] == " s"  # an unknown format keeps its unit
    assert co.format_value(5) == "5" and co.format_value(5, None) == "5"


# ---------------------------------------------------------------- formatted as Claude chose --

def test_bars_are_drawn_the_way_claude_formatted_them():
    option = co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "color": "", "style": STYLE})
    assert option["xAxis"]["type"] == "category" and option["xAxis"]["axisLabel"]["rotate"] == 45
    assert option["yAxis"]["x-format"] == D("~s", "AED ") and option["yAxis"]["name"] == "Sales (AED)"
    assert [r["Customer"] for r in rows(option)] == ["Coral Bay", "Lotus", "Atlas", "Desert Pearl"]  # biggest first
    bar = option["series"][0]
    assert bar["type"] == "bar" and bar["encode"] == {"x": "Customer", "y": "Sales", "tooltip": ["Sales"]}
    assert bar["label"]["show"] and bar["label"]["position"] == "top" and bar["x-label"] == "{value}"
    assert bar["x-format"] == D("~s", "AED ") and co.format_value(drawn(option, bar)[0], bar["x-format"]) == "AED 4.5M"
    assert option["legend"]["show"] is False and option["tooltip"]["trigger"] == "axis"
    assert option["x-app"]["kind"] == "bar" and option["x-app"]["categories"]["order"] == "value_desc"
    assert option["x-app"]["dataset"]["columns"] == ["Customer", "Sales"]


def test_horizontal_bars_read_from_the_top():
    option = co.build_option(DF, {"chart_type": "horizontal_bar", "x": "Customer", "y": ["Sales"], "color": "",
                                  "style": STYLE})
    assert option["yAxis"]["type"] == "category" and option["yAxis"]["inverse"] is True  # the first row at the top
    assert rows(option)[0]["Customer"] == "Coral Bay" and option["xAxis"]["x-format"]["prefix"] == "AED "
    bar = option["series"][0]
    assert bar["encode"] == {"y": "Customer", "x": "Sales", "tooltip": ["Sales"]} and bar["label"]["position"] == "right"
    assert bar["x-tooltip"] == "{name}<br>{value}" and option["tooltip"]["trigger"] == "item"
    plain = co.build_option(DF, {"chart_type": "horizontal_bar", "x": "Customer", "y": ["Sales"]})
    assert rows(plain)[0]["Customer"] == "Coral Bay"  # no order chosen: a ranking, biggest at the top
    by_name = co.build_option(DF, {"chart_type": "horizontal_bar", "x": "Customer", "y": ["Sales"],
                                   "style": {**STYLE, "sort": "label"}})
    assert [r["Customer"] for r in rows(by_name)] == ["Atlas", "Coral Bay", "Desert Pearl", "Lotus"]


def test_percent_donut_and_charts_without_style():
    style = {**STYLE, "formats": [{"column": "Margin", "d3_format": ".1%", "prefix": "", "suffix": ""}]}
    option = co.build_option(DF, {"chart_type": "donut", "x": "Customer", "y": ["Margin"], "style": style})
    pie = option["series"][0]
    assert pie["type"] == "pie" and pie["radius"] == ["54%", "90%"] and pie["encode"]["itemName"] == "Customer"
    assert pie["x-format"] == D(".1%") and rows(option)[0]["Customer"] == "Desert Pearl"  # sorted, biggest first
    assert pie["x-label"] == "{percent}\n{value}" and pie["label"]["position"] == "inside"
    assert co.format_value(rows(option)[0]["Margin"], pie["x-format"]) == "20.0%"
    assert option["legend"]["show"] is False  # "legend": "none"
    plain = co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"]})
    assert plain["yAxis"]["x-format"] == D("")  # charts saved before formatting still draw: Plotly-like ticks
    assert plain["series"][0]["x-format"] == D(",.0f") and "name" not in plain["yAxis"]


# ---------------------------------------------------------------- comparison --

def test_a_comparison_is_drawn_in_grey_beside_the_period():
    now = DF[["Customer", "Sales"]]
    before = pd.DataFrame({"Customer": ["Coral Bay", "Atlas", "Nile Star"], "Sales": [4_000_000.0, 1_000_000.0, 9.0]})
    spec = {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "style": STYLE}
    option = co.build_option(now, spec, compare={**COMPARE, "df": before})
    grey, current = option["series"]
    assert (grey["name"], current["name"]) == (COMPARE["name"], COMPARE["current"])
    assert option["legend"]["show"] and option["legend"]["data"] == [COMPARE["current"], COMPARE["name"]]
    assert option["grid"]["top"] >= 36  # both periods named above the chart
    assert grey["itemStyle"]["color"] == charts.COMPARE_COLOR["light"] and "label" not in grey  # no value labels
    assert grey["encode"]["y"] == "_compare" and current["x-change"] == "_change" and "label" in current
    by = {r["Customer"]: r for r in rows(option)}
    assert by["Coral Bay"]["_compare"] == 4_000_000 and by["Lotus"]["_compare"] is None
    assert co.format_value(by["Coral Bay"]["_change"], option["x-app"]["formats"]["_change"]) == "+12.5%"
    assert [r["Customer"] for r in rows(option)][:2] == ["Coral Bay", "Lotus"]  # still sorted by this period
    assert option["x-app"]["compare"] == COMPARE
    dark = co.build_option(now, spec, dark=True, compare={**COMPARE, "df": before})
    assert dark["series"][0]["itemStyle"]["color"] == charts.COMPARE_COLOR["dark"]
    sideways = co.build_option(now, {**spec, "chart_type": "horizontal_bar"}, compare={**COMPARE, "df": before})
    assert [s["name"] for s in sideways["series"]] == [COMPARE["current"], COMPARE["name"]]  # grey below each bar
    assert sideways["series"][1]["encode"]["x"] == "_compare" and sideways["legend"]["data"][0] == COMPARE["current"]

    months = pd.DataFrame({"Month": ["2026-01", "2026-02", "2026-03"], "Sales": [10.0, 20.0, 30.0]})
    last_year = pd.DataFrame({"Month": ["2025-02", "2025-01"], "Sales": [8.0, 5.0]})
    option = co.build_option(months, {"chart_type": "line", "x": "Month", "y": ["Sales"]},
                             compare={**COMPARE, "df": last_year})
    line, dotted = option["series"]
    assert [r["Month"] for r in rows(option)] == ["2026-01", "2026-02", "2026-03"]
    assert [r["_compare"] for r in rows(option)] == [5.0, 8.0, None]  # month 1 with month 1
    assert dotted["lineStyle"]["type"] == "dotted" and dotted["x-when"] == "_compare_label"
    assert [r["_compare_label"] for r in rows(option)] == ["2025-01", "2025-02", None]

    # month names, newest first from the query: drawn left to right in time, January with January
    named = pd.DataFrame({"Month": ["March 2026", "February 2026", "January 2026"], "Bookings": [30.0, 20.0, 10.0]})
    before = pd.DataFrame({"Month": ["February 2025", "March 2025", "January 2025"], "Bookings": [2.0, 3.0, 1.0]})
    option = co.build_option(named, {"chart_type": "line", "x": "Month", "y": ["Bookings"]}, compare={**COMPARE, "df": before})
    assert [r["Month"] for r in rows(option)] == ["January 2026", "February 2026", "March 2026"]
    assert [r["_compare"] for r in rows(option)] == [1.0, 2.0, 3.0]

    split = co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales", "Margin"]}, compare={**COMPARE, "df": before})
    assert len(split["series"]) == 2 and "2025" not in str(split["series"][0]["name"])  # two measures: no comparison
    donut = co.build_option(DF, {"chart_type": "donut", "x": "Customer", "y": ["Sales"]}, compare={**COMPARE, "df": before})
    assert len(donut["series"]) == 1 and donut["x-app"]["compare"] is None  # only columns, bars and lines compare


def test_a_comparison_over_real_dates_uses_a_time_axis():
    days = pd.DataFrame({"Day": pd.to_datetime(["2026-10-03", "2026-10-01", "2026-10-02"]), "Sales": [3.0, 1.0, 2.0]})
    before = pd.DataFrame({"Day": pd.to_datetime(["2025-10-01", "2025-10-02"]), "Sales": [1.5, 1.0]})
    option = co.build_option(days, {"chart_type": "line", "x": "Day", "y": ["Sales"]}, compare={**COMPARE, "df": before})
    assert option["xAxis"]["type"] == "time" and option["dataset"][0]["dimensions"][0]["type"] == "time"
    assert [r["Day"] for r in rows(option)] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert [r["_change"] for r in rows(option)] == [-1 / 3, 1.0, None]


# ---------------------------------------------------------------- panels and one chart --

def test_several_measures_of_different_size_get_one_panel_each():
    codes, days = ["1042", "3307", "8114"], ["2026-10-14", "2026-10-15"]
    df = pd.DataFrame([{"Date": d, "Customer Code": c, "Requests": 40_000_000 / (i + 1) + k, "Bookings": 60 - i * 20 + k,
                        "Sales": 140_000.0 / (i + 1)} for k, d in enumerate(days) for i, c in enumerate(codes)])
    style = {"formats": [{"column": "Sales", "d3_format": ",.0f", "prefix": "AED ", "suffix": ""}], "sort": "value_desc"}
    spec = {"chart_type": "bar", "x": "Customer Code", "y": ["Requests", "Bookings", "Sales"], "color": "Date",
            "style": style, "title": "Requests, bookings and sales by customer"}
    option = co.build_option(df, spec)
    assert option["x-app"]["kind"] == "panels" and len(option["series"]) == 6  # 3 measures x 2 days: nothing dropped
    assert option["legend"]["show"] and option["legend"]["data"] == days  # one legend, the days
    assert [t["text"] for t in option["title"]] == [spec["title"], "Requests", "Bookings", "Sales (AED)"]
    assert option["yAxis"][2]["x-format"]["prefix"] == "AED " and len(option["grid"]) == 3
    assert all(a["type"] == "category" and a["data"] == codes for a in option["xAxis"])  # by requests, biggest first
    assert [a["axisLabel"]["show"] for a in option["xAxis"]] == [False, False, True]  # named once, at the bottom
    assert [(s["xAxisIndex"], s["yAxisIndex"]) for s in option["series"]] == [(0, 0), (0, 0), (1, 1), (1, 1), (2, 2), (2, 2)]
    assert [s["name"] for s in option["series"][:2]] == days
    assert [r["Customer Code"] for r in rows(option, option["series"][0]["datasetIndex"])] == codes
    assert option["x-app"]["height"] >= 3 * 175 and option["axisPointer"]["link"] == [{"xAxisIndex": "all"}]

    sales_profit = pd.DataFrame({"Month": ["2026-01", "2026-02"], "Sales": [100.0, 120.0], "Profit": [20.0, 25.0]})
    same_axis = co.build_option(sales_profit, {"chart_type": "line", "x": "Month", "y": ["Sales", "Profit"]})
    assert same_axis["x-app"]["kind"] == "line" and [s["name"] for s in same_axis["series"]] == ["Sales", "Profit"]
    assert isinstance(same_axis["yAxis"], dict) and same_axis["legend"]["show"]  # one axis, the legend names them
    used = pd.DataFrame({"Month": ["July 2026", "August 2026"], "Used Allotment (by stay month)": [5926, 7810],
                         "Bookings": [9018, 11039], "Year": [2026, 2026]})
    option = co.build_option(used, {"chart_type": "bar", "x": "Month", "y": ["Used Allotment (by stay month)", "Bookings"]})
    assert {s["name"] for s in option["series"]} >= {"Used Allotment (by stay month)", "Bookings"}  # both drawn

    sideways = co.build_option(DF, {"chart_type": "horizontal_bar", "x": "Customer", "y": ["Sales", "Margin"]})
    assert sideways["x-app"]["kind"] == "panels" and all(a["inverse"] for a in sideways["yAxis"])
    assert [a["axisLabel"]["show"] for a in sideways["yAxis"]] == [True, False]  # names once, on the left


def test_codes_are_labels_and_the_title_has_room_for_the_legend():
    df = pd.DataFrame({"Customer Code": ["1042", "1142", "9001"], "Requests": [3.0, 2.0, 1.0],
                       "Day": ["14 Oct", "14 Oct", "15 Oct"]})
    option = co.build_option(df, {"chart_type": "bar", "x": "Customer Code", "y": ["Requests"], "title": "Requests"})
    assert option["xAxis"]["type"] == "category" and option["dataset"][0]["dimensions"][0]["type"] == "ordinal"
    numbers = co.build_option(df.assign(**{"Customer Code": [1042, 1142, 9001]}),
                              {"chart_type": "bar", "x": "Customer Code", "y": ["Requests"]})
    assert numbers["xAxis"]["type"] == "category" and [r["Customer Code"] for r in rows(numbers)] == ["1042", "1142", "9001"]
    option = co.build_option(df, {"chart_type": "bar", "x": "Customer Code", "y": ["Requests"], "color": "Day",
                                  "title": "Requests by day"})
    assert option["legend"]["top"] == co.TITLE_H and option["grid"]["top"] >= co.TITLE_H + co.LEGEND_H  # own line
    assert option["title"][0]["top"] == 0 and option["xAxis"]["data"] == ["1042", "1142", "9001"]
    assert option["dataset"][1]["transform"] == {"type": "filter", "config": {"dimension": "Day", "=": "14 Oct"}}
    assert [s["name"] for s in option["series"]] == ["14 Oct", "15 Oct"]


def test_measures_together_in_one_chart_get_an_axis_each():
    days = ["2026-10-14", "2026-10-15"]
    df = pd.DataFrame([{"Day": d, "Customer": c, "Requests": 4e7 / (i + 1), "Bookings": 60.0 - i * 20, "Sales": 1.4e5 / (i + 1)}
                       for d in days for i, c in enumerate(["A", "B", "C"])])
    style = {"measures": "one_chart", "formats": [{"column": "Sales", "d3_format": "~s", "prefix": "AED ", "suffix": ""}]}
    spec = {"chart_type": "bar", "x": "Customer", "y": ["Requests", "Bookings", "Sales"], "color": "Day", "style": style}
    option = co.build_option(df, spec)
    assert option["x-app"]["kind"] == "one_chart" and len(option["series"]) == 6
    assert all(s["type"] == "bar" and "stack" not in s for s in option["series"])  # side by side, none dropped
    assert [s["yAxisIndex"] for s in option["series"]] == [0, 0, 1, 1, 2, 2]
    assert [a["position"] for a in option["yAxis"]] == ["left", "right", "right"] and option["yAxis"][2]["offset"] > 0
    assert option["yAxis"][2]["x-format"]["prefix"] == "AED " and option["yAxis"][2]["name"] == "Sales (AED)"
    assert [(s["x-group"], s["name"]) for s in option["series"][:2]] == [("Requests", "Requests · 2026-10-14"),
                                                                         ("Requests", "Requests · 2026-10-15")]
    light = charts.PALETTE["light"]
    assert option["series"][1]["itemStyle"]["color"] == light[0] != option["series"][0]["itemStyle"]["color"]  # later darker
    assert option["yAxis"][0]["nameTextStyle"]["color"] == option["yAxis"][0]["axisLabel"]["color"] == light[0]
    assert [a["splitLine"]["show"] for a in option["yAxis"]] == [True, False, False]
    assert option["legend"]["top"] == "bottom" and option["x-app"]["height"] == 440
    four = {**spec, "y": ["Requests", "Bookings", "Sales", "Margin"]}
    assert co.build_option(df.assign(Margin=0.1), four)["x-app"]["kind"] == "panels"  # more than 3 axes: panels


def test_one_chart_with_real_dates_as_the_breakdown():
    days = pd.to_datetime(["2026-10-15", "2026-10-14", "2026-10-15", "2026-10-14"])
    df = pd.DataFrame({"Date": days, "Customer": ["A", "A", "B", "B"], "Requests": [4e7, 3e7, 2e6, 1e6],
                       "Bookings": [79, 62, 20, 14], "Sales": [1.7e5, 1.4e5, 5e4, 6e4]})
    spec = {"chart_type": "bar", "x": "Customer", "y": ["Requests", "Bookings", "Sales"], "color": "Date",
            "style": {"measures": "one_chart"}}
    option = co.build_option(df, spec)
    series = option["series"]
    assert [s["name"] for s in series[:2]] == ["Requests · 14 Oct 2026", "Requests · 15 Oct 2026"]  # earliest first
    assert all(len([v for v in drawn(option, s) if v is not None]) == 2 for s in series)  # every bar has its value
    assert drawn(option, series[1]) == [4e7, 2e6]  # 15 Oct requests of A and B


def test_a_two_day_chart_over_a_whole_year_is_drawn_over_time():
    days = pd.date_range("2026-01-01", periods=30)
    df = pd.DataFrame([{"Day": d, "Customer": c, "Requests": 1e6 * (i + 1), "Bookings": 10.0 + i, "Sales": 5e4}
                       for d in days for i, c in enumerate(["A", "B", "C"])])
    spec = {"chart_type": "bar", "x": "Customer", "y": ["Requests", "Bookings", "Sales"], "color": "Day",
            "style": {"measures": "one_chart"}}
    option = co.build_option(df, spec)
    assert option["x-app"]["kind"] == "panels" and option["x-app"]["chart_type"] == "line"
    assert len(option["series"]) == 9 and all(s["type"] == "line" for s in option["series"])  # a line per customer
    assert option["xAxis"][0]["data"][:2] == ["2026-01-01", "2026-01-02"] and len(option["xAxis"][0]["data"]) == 30
    assert option["legend"]["data"] == ["A", "B", "C"]


# ---------------------------------------------------------------- other kinds --

def test_maps_colour_countries_by_iso_code():
    df = pd.DataFrame({"Destination Country": ["UNITED ARAB EMIRATES", "Spain", "UK", "Egypt", "Atlantis"],
                       "Bookings": [120, 80, 45, 30, 2]})
    option = co.build_option(df, {"chart_type": "map", "x": "Destination Country", "y": ["Bookings"],
                                  "style": {"formats": [{"column": "Bookings", "d3_format": ",.0f"}]}})
    world = option["series"][0]
    assert (world["type"], world["map"], world["nameProperty"]) == ("map", "world", "iso_a3")
    assert world["encode"]["itemName"] == "_iso" and world["encode"]["value"] == "Bookings"
    assert option["x-app"]["map"]["codes"] == {"UNITED ARAB EMIRATES": "ARE", "Spain": "ESP", "UK": "GBR", "Egypt": "EGY"}
    assert option["x-app"]["map"]["unmatched"] == ["Atlantis"] and option["x-app"]["map"]["exclude"] == ["ATA"]
    scale = option["visualMap"][0]
    assert scale["inRange"]["color"] == charts.SEQUENTIAL["light"] and (scale["min"], scale["max"]) == (30, 120)
    assert scale["dimension"] == 2 and [d["name"] for d in option["dataset"][0]["dimensions"]][2] == "Bookings"
    assert scale["text"] == ["120", "30"] and scale["x-format"] == D(",.0f")  # the scale's ends, formatted
    assert world["x-tooltip"] == "{col:Destination Country}<br>{value}" and option["x-app"]["height"] == 420


def test_heatmap_has_a_cell_per_pair_and_a_colour_scale():
    months, channels = ["2026-07", "2026-08", "2026-09"], ["Online", "API", "Agent"]
    df = pd.DataFrame([{"Month": m, "Channel": c, "Bookings": 10.0 * i + j}
                       for i, m in reversed(list(enumerate(months))) for j, c in enumerate(channels)])
    option = co.build_option(df, {"chart_type": "heatmap", "x": "Month", "y": ["Bookings"], "color": "Channel"})
    cells = option["series"][0]
    assert cells["type"] == "heatmap" and cells["encode"]["x"] == "Month" and cells["encode"]["y"] == "Channel"
    assert option["xAxis"]["data"] == months and option["yAxis"]["data"] == channels and option["yAxis"]["inverse"]
    assert [d["name"] for d in option["dataset"][0]["dimensions"]] == ["Month", "Channel", "Bookings"]
    assert option["visualMap"][0]["dimension"] == 2 and option["visualMap"][0]["max"] == 22
    assert cells["label"]["show"] and cells["x-format"] == D(",.0f")  # a small grid shows its numbers


def test_treemap_shares_coloured_by_value():
    many = pd.DataFrame({"Agency": [f"Agency {i:02d}" for i in range(30)], "Sales": [1000.0 + i * 37 for i in range(30)],
                         "Region": ["North", "South", "East"] * 10})
    option = co.build_option(many, {"chart_type": "treemap", "x": "Agency", "y": ["Sales"]})
    tiles = option["series"][0]
    assert tiles["type"] == "treemap" and len(tiles["data"]) == 30 and "dataset" not in option
    by_value = sorted(tiles["data"], key=lambda n: n["value"])
    seq = charts.SEQUENTIAL["light"]
    assert (by_value[0]["itemStyle"]["color"], by_value[-1]["itemStyle"]["color"]) == (seq[0], seq[-1])
    assert by_value[-1]["label"]["color"] == "#ffffff" and tiles["x-label"] == "{name}\n{value}"
    nested = co.build_option(many, {"chart_type": "treemap", "x": "Agency", "y": ["Sales"], "color": "Region"})
    regions = nested["series"][0]["data"]
    assert [r["name"] for r in regions] == ["North", "South", "East"] and len(regions[0]["children"]) == 10
    assert regions[0]["value"] == sum(c["value"] for c in regions[0]["children"])
    assert regions[0]["itemStyle"]["borderColor"] == regions[0]["itemStyle"]["color"]  # its name band in its colour


def test_stacked_columns_areas_lines_scatter_and_dark_mode():
    by_channel = pd.DataFrame({"Month": ["2026-02", "2026-02", "2026-01", "2026-01"], "Channel": ["Online", "API"] * 2,
                               "Sales": [30.0, 10.0, 20.0, 5.0]})
    stacked = co.build_option(by_channel, {"chart_type": "stacked_bar", "x": "Month", "y": ["Sales"], "color": "Channel"})
    assert [s["name"] for s in stacked["series"]] == ["Online", "API"] and all(s["stack"] == "total" for s in stacked["series"])
    assert stacked["xAxis"]["data"] == ["2026-01", "2026-02"]  # months in time order
    area = co.build_option(by_channel, {"chart_type": "area", "x": "Month", "y": ["Sales"], "color": "Channel"})
    assert all(s["type"] == "line" and "areaStyle" in s and s["stack"] == "total" for s in area["series"])
    days = pd.DataFrame({"Booking Date": pd.date_range("2026-01-01", periods=5), "Sales": [1.0, 2.0, 3.0, 2.0, 1.0]})
    line = co.build_option(days, {"chart_type": "line", "x": "Booking Date", "y": ["Sales"]})
    assert line["xAxis"]["type"] == "time" and line["series"][0]["showSymbol"] is True
    points = pd.DataFrame({"Nights": [1.0, 2.0, 3.0, 5.0], "Sales": [100.0, 180.0, 310.0, 420.0]})
    scatter = co.build_option(points, {"chart_type": "scatter", "x": "Nights", "y": ["Sales"]})
    assert scatter["series"][0]["type"] == "scatter" and scatter["xAxis"]["type"] == "value"
    assert scatter["series"][0]["x-tooltip"] == "Nights: {col:Nights}<br>Sales: {value}"
    dark = co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "title": "Sales"}, dark=True)
    assert dark["color"] == charts.PALETTE["dark"] and dark["title"][0]["textStyle"]["color"] == charts.INK["dark"]["text"]
    assert dark["tooltip"]["backgroundColor"] == charts.INK["dark"]["surface"] and dark["x-app"]["theme"] == "dark"
    assert dark["yAxis"]["splitLine"]["lineStyle"]["color"] == charts.INK["dark"]["grid"]
    assert co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "title": "T"},
                           show_title=False)["title"] == []


def test_big_results_draw_fast_and_long_lists_keep_their_top():
    # (numbered steps, not 3,000 dates: charts.fit looks every new label up as a possible country)
    long = pd.DataFrame({"Step": range(3000), "Requests": [float(i % 97) for i in range(3000)]})
    line = co.build_option(long, {"chart_type": "line", "x": "Step", "y": ["Requests"]})
    assert line["series"][0]["sampling"] == "lttb" and line["series"][0]["showSymbol"] is False
    assert len(rows(line)) == 3000  # nothing left out
    cloud = pd.DataFrame({"Nights": [float(i % 30) for i in range(12_000)], "Sales": [float(i) for i in range(12_000)]})
    scatter = co.build_option(cloud, {"chart_type": "scatter", "x": "Nights", "y": ["Sales"]})
    assert scatter["series"][0]["large"] is True and scatter["animation"] is False
    agencies = pd.DataFrame({"Agency": [f"Agency {i}" for i in range(40)], "Sales": [float(i) for i in range(40)]})
    bars = co.build_option(agencies, {"chart_type": "bar", "x": "Agency", "y": ["Sales"]})
    assert len(rows(bars)) == 25 and bars["x-app"]["note"].startswith("Showing the top 25 of 40")


def test_tables_and_custom_charts():
    assert co.build_option(DF, {"chart_type": "table"}) is None
    assert co.build_option(DF.iloc[0:0], {"chart_type": "bar", "x": "Customer", "y": ["Sales"]}) is None
    plotly_spec = {"chart_type": "custom", "title": "T",
                   "custom": {"traces": [{"type": "funnel", "y": {"col": "Customer"}, "x": {"col": "Sales"}}]}}
    saved = co.build_option(DF, plotly_spec)
    assert saved["x-app"]["kind"] == "plotly" and saved["x-app"]["figure"]["data"][0]["type"] == "funnel"
    written = {"chart_type": "custom", "title": "Sales",
               "custom": {"xAxis": {"type": "category", "data": {"col": "Customer"}}, "yAxis": {"type": "value"},
                          "series": [{"type": "bar", "data": {"col": "Sales"}}]}}
    option = co.build_option(DF, written)
    assert option["x-app"]["kind"] == "custom" and option["series"][0]["data"] == DF["Sales"].tolist()
    assert option["title"][0]["text"] == "Sales"
    broken = {**written, "custom": {**written["custom"], "series": [{"type": "bar", "data": {"col": "Gone"}}]}}
    assert co.build_option(DF, broken)["x-app"]["kind"] in ("bar", "horizontal_bar", "panels")  # best standard chart


# ---------------------------------------------------------------- every option is JSON --

def _every_option():
    months = pd.DataFrame({"Month": pd.to_datetime(["2026-01-01", "2026-02-01"]), "Sales": [10.0, None],
                           "Channel": ["Online", None]})
    codes = pd.DataFrame({"Code": [1042.0, None, 9001.0], "Requests": [3, 2, 1]})
    yield co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "style": STYLE})
    yield co.build_option(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"]},
                          compare={**COMPARE, "df": DF.assign(Sales=DF["Sales"] * 0.9)})
    yield co.build_option(DF, {"chart_type": "horizontal_bar", "x": "Customer", "y": ["Sales", "Margin"]}, dark=True)
    yield co.build_option(DF, {"chart_type": "donut", "x": "Customer", "y": ["Sales"]})
    yield co.build_option(DF, {"chart_type": "treemap", "x": "Customer", "y": ["Sales"]})
    yield co.build_option(months, {"chart_type": "line", "x": "Month", "y": ["Sales"], "color": "Channel"})
    yield co.build_option(months, {"chart_type": "area", "x": "Month", "y": ["Sales"]},
                          compare={**COMPARE, "df": months})
    yield co.build_option(codes, {"chart_type": "bar", "x": "Code", "y": ["Requests"]})
    yield co.build_option(DF, {"chart_type": "scatter", "x": "Sales", "y": ["Margin"]})
    yield co.build_option(DF.assign(Region=["N", "S", "N", "S"]), {"chart_type": "heatmap", "x": "Customer",
                                                                    "y": ["Sales"], "color": "Region"})


@pytest.mark.parametrize("index", range(10))
def test_every_option_is_plain_json(index):
    option = list(_every_option())[index]
    text = json.dumps(option, allow_nan=False)
    assert json.loads(text) == option and "x-app" in option and option["x-app"]["version"] == co.VERSION


# ---------------------------------------------------------------- charts described in words --

SALES = pd.DataFrame({
    "Month": ["2026-01", "2026-02", "2026-03", "2026-01", "2026-02", "2026-03"],
    "Channel": ["Online", "Online", "Online", "API", "API", "API"],
    "Region": ["Europe", "Europe", "Asia", "Asia", "Europe", "Asia"],
    "Sales": [100.0, 120.0, 90.0, 40.0, 60.0, 80.0],
    "Profit %": [0.1, 0.12, 0.08, 0.2, 0.15, 0.18],
})


def test_described_chart_with_a_second_axis():
    option = {"prepare": {"group_by": ["Month"], "aggregate": {"Sales": "sum", "Profit %": "mean"}},
              "xAxis": {"type": "category", "data": {"col": "Month"}},
              "yAxis": [{"type": "value", "x-format": {"d3": "~s", "prefix": "AED "}},
                        {"type": "value", "position": "right", "x-format": ".0%"}],
              "series": [{"type": "bar", "name": "Sales", "data": {"col": "Sales"}},
                         {"type": "line", "name": "Profit %", "yAxisIndex": 1, "data": {"col": "Profit %"}}]}
    built = custom_echarts.build(SALES, json.dumps(option), title="Sales and profit")
    assert built["xAxis"]["data"] == ["2026-01", "2026-02", "2026-03"]
    assert built["series"][0]["data"] == [140.0, 180.0, 170.0]  # summed per month
    assert built["yAxis"][0]["x-format"] == D("~s", "AED ") and built["yAxis"][1]["x-format"] == D(".0%")
    assert built["yAxis"][1]["splitLine"]["show"] is False and built["title"][0]["text"] == "Sales and profit"
    assert built["color"] == charts.PALETTE["light"] and built["x-app"]["kind"] == "custom"
    assert set(built["x-app"]["columns"]) == {"Month", "Sales", "Profit %"}
    json.dumps(built, allow_nan=False)


def test_described_chart_split_by_dataset_and_hierarchy():
    split = custom_echarts.build(SALES, {"xAxis": {"type": "category"}, "yAxis": {},
                                         "series": [{"type": "line", "data": {"cols": ["Month", "Sales"]},
                                                     "split_by": "Channel"}]})
    assert [s["name"] for s in split["series"]] == ["Online", "API"]
    assert split["series"][1]["data"] == [["2026-01", 40.0], ["2026-02", 60.0], ["2026-03", 80.0]]
    table = custom_echarts.build(SALES, {"dataset": {"source": {"cols": ["Month", "Sales"]}}, "xAxis": {"type": "category"},
                                         "yAxis": {}, "series": [{"type": "bar", "encode": {"x": "Month", "y": "Sales"}}]})
    assert table["dataset"]["dimensions"] == ["Month", "Sales"] and table["dataset"]["source"][0] == ["2026-01", 100.0]
    sun = custom_echarts.build(SALES, {"series": [{"type": "sunburst", "path": ["Region", "Channel"], "value": {"col": "Sales"}}]})
    europe = next(n for n in sun["series"][0]["data"] if n["name"] == "Europe")
    assert europe["value"] == 280.0 and {c["name"] for c in europe["children"]} == {"Online", "API"}
    assert custom_echarts.is_echarts({"series": []}) and not custom_echarts.is_echarts({"traces": []})
    assert not custom_echarts.is_echarts("not json") and custom_echarts.check(SALES, {"series": [{"type": "pie"}]}) == ""


@pytest.mark.parametrize("option, problem", [
    ("not json", "not valid JSON"),
    ({"series": []}, "non-empty"),
    ({"series": [{"type": "rocket"}]}, "not supported"),
    ({"series": [{"type": "custom", "renderItem": "x"}]}, "drawing code"),
    ({"series": [{"type": "bar", "data": {"col": "Nope"}}]}, "Column 'Nope'"),
    ({"series": [{"type": "bar", "encode": {"x": "Nope"}}]}, "Column 'Nope'"),
    ({"series": [{"type": "bar", "label": {"formatter": "function (p) { return p.value }"}}]}, "not code"),
    ({"series": [{"type": "bar", "label": {"formatter": "(p) => p.value"}}]}, "not code"),
    ({"tooltip": {"valueFormatter": "x"}, "series": [{"type": "bar"}]}, "valueFormatter"),
    ({"series": [{"type": "bar", "onclick": "alert(1)"}]}, "runs code"),
    ({"series": [{"type": "pictorialBar", "symbol": "image://https://example.com/a.png"}]}, "link"),
    ({"title": {"text": "Sales", "link": "https://example.com"}, "series": [{"type": "bar"}]}, "link"),
    ({"series": [{"type": "bar", "itemStyle": {"color": {"image": "url(x.png)"}}}]}, "link"),
    ({"tooltip": {"formatter": "<img src=x onerror=alert(1)>"}, "series": [{"type": "bar"}]}, "HTML"),
    ({"title": {"text": "<script>alert(1)</script>"}, "series": [{"type": "bar"}]}, "HTML"),
    ({"graphic": [{"type": "image"}], "series": [{"type": "bar"}]}, "'graphic' is not allowed"),
    ({"prepare": {"group_by": ["Month"], "aggregate": {"Sales": "explode"}}, "series": [{"type": "bar"}]},
     "Unknown aggregate"),
    ({"series": [{"type": "bar", "data": {"col": "Sales"}, "split_by": "Sales"}]}, "more than 40 series"),
])
def test_described_charts_that_could_run_code_or_fetch_are_refused(option, problem):
    data = SALES if "more than" not in problem else pd.DataFrame({"Sales": [float(i) for i in range(50)]})
    with pytest.raises(custom_echarts.CustomChartError if problem != "Unknown aggregate" else Exception, match=problem):
        custom_echarts.build(data, option)
    assert problem.split("'")[0] in custom_echarts.check(data, option)


def test_safe_templates_and_symbols_are_kept():
    option = {"tooltip": {"formatter": "{b}<br/>{c} ({d}%)"},
              "series": [{"type": "pictorialBar", "symbol": "path://M0,0 L10,0 L10,10 Z", "data": {"col": "Sales"}}]}
    built = custom_echarts.build(SALES, option)
    assert built["tooltip"]["formatter"] == "{b}<br/>{c} ({d}%)" and built["series"][0]["symbol"].startswith("path://")
