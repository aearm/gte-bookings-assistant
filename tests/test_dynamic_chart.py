import json

import pandas as pd
import pytest

import charts
import dynamic_chart

DF = pd.DataFrame({
    "Month": ["2026-01", "2026-02", "2026-03", "2026-01", "2026-02", "2026-03"],
    "Channel": ["Online", "Online", "Online", "API", "API", "API"],
    "Region": ["Europe", "Europe", "Asia", "Asia", "Europe", "Asia"],
    "Sales": [100.0, 120.0, 90.0, 40.0, 60.0, 80.0],
    "Profit %": [0.1, 0.12, 0.08, 0.2, 0.15, 0.18],
})


def test_combo_with_second_axis():
    spec = {
        "prepare": {"group_by": ["Month"], "aggregate": {"Sales": "sum", "Profit %": "mean"}},
        "traces": [
            {"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"}, "name": "Sales"},
            {"type": "scatter", "mode": "lines+markers", "x": {"col": "Month"}, "y": {"col": "Profit %"},
             "yaxis": "y2", "name": "Profit %"},
        ],
        "layout": {"yaxis2": {"overlaying": "y", "side": "right", "tickformat": ".0%"}},
    }
    fig = dynamic_chart.build(DF, json.dumps(spec))
    assert [t.type for t in fig.data] == ["bar", "scatter"]
    assert list(fig.data[0].y) == [140.0, 180.0, 170.0]  # summed per month
    assert fig.layout.yaxis2.side == "right" and fig.layout.yaxis2.showgrid is False


def test_split_by_makes_one_series_per_value():
    spec = {"traces": [{"type": "scatter", "mode": "lines", "x": {"col": "Month"}, "y": {"col": "Sales"},
                        "split_by": "Channel"}], "layout": {}}
    fig = dynamic_chart.build(DF, spec)
    assert sorted(t.name for t in fig.data) == ["API", "Online"]
    assert len(fig.data[0].x) == 3


def test_sunburst_path_builds_the_hierarchy():
    spec = {"traces": [{"type": "sunburst", "path": ["Region", "Channel"], "values": {"col": "Sales"}}]}
    trace = dynamic_chart.build(DF, spec).data[0]
    ids = list(trace.ids)
    assert "Europe" in ids and "Europe / Online" in ids
    assert dict(zip(ids, trace.values))["Europe"] == 280.0  # 100 + 120 + 60
    assert dict(zip(ids, trace.parents))["Asia / API"] == "Asia"


def test_prepare_sorts_and_keeps_top_rows():
    spec = {"prepare": {"sort_by": "Sales", "descending": True, "top": 2},
            "traces": [{"type": "bar", "orientation": "h", "y": {"col": "Month"}, "x": {"col": "Sales"}}]}
    fig = dynamic_chart.build(DF, spec)
    assert list(fig.data[0].x) == [120.0, 100.0]


def test_plain_plotly_figure_and_code_fences_are_accepted():
    text = "```json\n" + json.dumps({"data": [{"type": "pie", "labels": {"col": "Channel"},
                                               "values": {"col": "Sales"}, "hole": 0}]}) + "\n```"
    assert dynamic_chart.build(DF, text).data[0].type == "pie"


@pytest.mark.parametrize("spec, problem", [
    ("not json", "not valid JSON"),
    ({"traces": []}, "non-empty"),
    ({"traces": [{"type": "rocket", "x": {"col": "Month"}}]}, "not supported"),
    ({"traces": [{"type": "bar", "x": {"col": "Nope"}, "y": {"col": "Sales"}}]}, "Column 'Nope'"),
    ({"traces": [{"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"}, "notaproperty": 1}]}, "Plotly rejected"),
    ({"traces": [{"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"},
                  "hovertemplate": "<a href='javascript:alert(1)'>x</a>"}]}, "isn't allowed"),
    ({"prepare": {"group_by": ["Month"], "aggregate": {"Sales": "explode"}},
      "traces": [{"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"}}]}, "Unknown aggregate"),
])
def test_bad_specs_explain_what_is_wrong(spec, problem):
    with pytest.raises(dynamic_chart.ChartSpecError, match=problem):
        dynamic_chart.build(DF, spec)
    assert problem.split("'")[0] in dynamic_chart.check(DF, spec)


def test_images_from_the_internet_are_dropped():
    spec = {"traces": [{"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"}}],
            "layout": {"images": [{"source": "https://example.com/x.png"}], "title": {"text": "Sales"}}}
    fig = dynamic_chart.build(DF, spec)
    assert not fig.layout.images and fig.layout.title.text == "Sales"


def test_charts_module_draws_custom_specs_and_falls_back():
    spec = {"chart_type": "custom", "title": "T",
            "custom": {"traces": [{"type": "funnel", "y": {"col": "Channel"}, "x": {"col": "Sales"}}]}}
    assert charts.build_figure(DF, spec).data[0].type == "funnel"
    assert charts.fit(DF, spec) is not None and charts.fit(DF, spec)["chart_type"] == "custom"
    broken = {**spec, "custom": {"traces": [{"type": "bar", "x": {"col": "Gone"}, "y": {"col": "Sales"}}]}}
    assert charts.build_figure(DF, broken) is not None  # data changed: best standard chart instead
    assert "Gone" in dynamic_chart.columns_used(broken["custom"])
