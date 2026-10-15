"""Claude formats each chart for its data; the app draws it exactly that way."""
import pandas as pd

import charts
import data_layer
import llm
import secrets_store
from fakes import FakeClaude, chart

DF = pd.DataFrame({"Customer": ["Atlas", "Coral Bay", "Desert Pearl", "Lotus"],
                   "Sales": [1_250_000.0, 4_500_000.0, 320_000.0, 2_000_000.0],
                   "Margin": [0.12, 0.08, 0.2, 0.15]})
STYLE = {"formats": [{"column": "Sales", "d3_format": "~s", "prefix": "AED ", "suffix": ""}],
         "x_title": "", "y_title": "Sales (AED)", "sort": "value_desc", "show_values": True,
         "label_angle": -45, "legend": "none", "log_scale": False}


def test_format_number():
    assert charts.format_number(4_512_000, "~s", "AED ") == "AED 4.5M"
    assert charts.format_number(1_260_000_000, "~s") == "1.3B"
    assert charts.format_number(0.1234, ".1%") == "12.3%"
    assert charts.format_number(12.345, ",.1f", suffix="%") == "12.3%"
    assert charts.format_number(1234.4, ",.0f") == "1,234"
    assert charts.format_number(3.14159, ",.2f") == "3.14"
    assert charts.format_number(None) == "-"
    assert charts.number_format({"style": STYLE}, "Sales") == ("~s", "AED ", "")
    assert charts.number_format({"style": STYLE}, "Margin") == ("", "", "")


def test_bars_are_drawn_the_way_claude_formatted_them():
    spec = {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "color": "", "style": STYLE}
    fig = charts.build_figure(DF, spec)
    assert fig.layout.yaxis.tickformat == "~s" and fig.layout.yaxis.tickprefix == "AED "
    assert fig.layout.yaxis.title.text == "Sales (AED)"
    assert fig.layout.xaxis.categoryorder == "total descending" and fig.layout.xaxis.tickangle == -45
    assert fig.data[0].texttemplate == "AED %{y:~s}" and fig.layout.showlegend is False
    assert "AED %{y:~s}" in fig.data[0].hovertemplate


def test_horizontal_bars_read_from_the_top():
    spec = {"chart_type": "horizontal_bar", "x": "Customer", "y": ["Sales"], "color": "", "style": STYLE}
    fig = charts.build_figure(DF, spec)
    assert fig.layout.xaxis.tickprefix == "AED " and fig.layout.yaxis.categoryorder == "total ascending"
    assert fig.data[0].texttemplate == "AED %{x:~s}"


def test_percent_donut_and_charts_without_style():
    style = {**STYLE, "formats": [{"column": "Margin", "d3_format": ".1%", "prefix": "", "suffix": ""}]}
    fig = charts.build_figure(DF, {"chart_type": "donut", "x": "Customer", "y": ["Margin"], "style": style})
    assert "%{value:.1%}" in fig.data[0].hovertemplate and list(fig.data[0].labels)[0] == "Desert Pearl"
    plain = charts.build_figure(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales"]})
    assert plain.layout.yaxis.tickprefix is None  # charts saved before formatting still draw


def test_claude_is_given_the_data_the_query_and_the_units(monkeypatch):
    fake = FakeClaude({**chart("bar", x="Customer", y=["Sales"]), "style": STYLE})
    monkeypatch.setattr(llm, "_create", fake)
    spec = llm.describe_result("Sales by customer", DF, query="EVALUATE ... [Final Sales]",
                               measures="- [Final Sales] = Sales: currency in AED")
    assert spec["style"]["y_title"] == "Sales (AED)"
    user, system = fake.user_text(), fake.system_text()
    assert "Sales: number, min 320,000, median 1.625e+06, max 4.5e+06" in user
    assert "Customer: text/date, 4 different, up to 12 characters" in user
    assert "[Final Sales]" in user and "currency in AED" in user
    assert "Format the chart so it reads best" in system
    schema = fake.requests[0]["output_config"]["format"]["schema"]
    assert "style" in schema["required"] and schema["properties"]["style"]["additionalProperties"] is False


def test_measure_notes_explain_the_numbers(monkeypatch):
    monkeypatch.setattr(data_layer, "profile", lambda cube: {
        "label": "Bookings", "description": "Sales in AED.", "variants": "LY = last year",
        "measures": [{"name": "[Final Sales]", "label": "Sales", "unit": "currency", "aggregation": "additive",
                      "meaning": "Sales after discounts."},
                     {"name": "[Paxes]", "label": "Passengers", "unit": "count", "aggregation": "additive",
                      "meaning": ""}]})
    notes = data_layer.measure_notes(["Bookings"], 'SUMMARIZECOLUMNS("Sales", [Final Sales])')
    assert "Bookings: Sales in AED." in notes and "[Final Sales] = Sales: currency, additive" in notes
    assert "[Paxes]" not in notes and "LY = last year" in notes


def test_keep_me_signed_in_tokens(monkeypatch):
    stored = {"hash": "salt$digest-1"}
    monkeypatch.setattr(secrets_store.config, "stored_secret", lambda name: stored["hash"])
    token = secrets_store.make_login_token(30)
    assert secrets_store.check_login_token(token)
    assert not secrets_store.check_login_token(token[:-1] + ("0" if token[-1] != "0" else "1"))
    assert not secrets_store.check_login_token("garbage") and not secrets_store.check_login_token("")
    assert not secrets_store.check_login_token(secrets_store.make_login_token(-1))  # expired
    stored["hash"] = "salt$digest-2"  # the admin password changed: every computer is signed out
    assert not secrets_store.check_login_token(token)


def test_a_comparison_is_drawn_in_grey_beside_the_period():
    now = DF[["Customer", "Sales"]]
    before = pd.DataFrame({"Customer": ["Coral Bay", "Atlas", "Nile Star"], "Sales": [4_000_000.0, 1_000_000.0, 9.0]})
    spec = {"chart_type": "bar", "x": "Customer", "y": ["Sales"], "style": STYLE}
    compare = {"df": before, "current": "1 Jan – 15 Oct 2026", "name": "1 Jan – 15 Oct 2025"}
    fig = charts.build_figure(now, spec, compare=compare)
    grey, current = fig.data
    assert (grey.name, current.name) == ("1 Jan – 15 Oct 2025", "1 Jan – 15 Oct 2026") and fig.layout.showlegend
    assert fig.layout.legend.visible and fig.layout.margin.t >= 36  # both periods named above the chart
    assert fig.layout.legend.traceorder == "reversed"  # this period first in the legend, as for lines
    assert grey.marker.color == charts.COMPARE_COLOR["light"] and grey.texttemplate is None  # no value labels
    assert dict(zip(grey.x, grey.y))["Coral Bay"] == 4_000_000 and dict(zip(grey.x, grey.y))["Lotus"] is None
    assert dict(zip(current.x, current.customdata))["Coral Bay"] == " (+12.5%)"  # the change, on hover
    assert list(fig.layout.xaxis.categoryarray)[:2] == ["Coral Bay", "Lotus"]  # still sorted by this period

    months = pd.DataFrame({"Month": ["2026-01", "2026-02", "2026-03"], "Sales": [10.0, 20.0, 30.0]})
    last_year = pd.DataFrame({"Month": ["2025-02", "2025-01"], "Sales": [8.0, 5.0]})
    fig = charts.build_figure(months, {"chart_type": "line", "x": "Month", "y": ["Sales"]},
                              compare={**compare, "df": last_year})
    line, dotted = fig.data
    assert list(dotted.x) == ["2026-01", "2026-02", "2026-03"] and list(dotted.y) == [5.0, 8.0, None]  # month 1 with 1
    assert dotted.line.dash == "dot" and list(dotted.customdata) == ["2025-01", "2025-02", ""]

    # month names, newest first from the query: drawn left to right in time, January with January
    named = pd.DataFrame({"Month": ["March 2026", "February 2026", "January 2026"], "Bookings": [30.0, 20.0, 10.0]})
    before = pd.DataFrame({"Month": ["February 2025", "March 2025", "January 2025"], "Bookings": [2.0, 3.0, 1.0]})
    fig = charts.build_figure(named, {"chart_type": "line", "x": "Month", "y": ["Bookings"]},
                              compare={**compare, "df": before})
    line, dotted = fig.data
    assert list(line.x) == ["January 2026", "February 2026", "March 2026"] and list(dotted.y) == [1.0, 2.0, 3.0]
    assert charts.time_order(["W2", "W1"]) == [0, 1]  # not dates: kept as the query returned them

    split = charts.build_figure(DF, {"chart_type": "bar", "x": "Customer", "y": ["Sales", "Margin"]}, compare=compare)
    assert len(split.data) == 2 and "2025" not in str(split.data[0].name)  # two measures: no comparison


def test_tables_get_a_change_column():
    before = pd.DataFrame({"Customer": ["Atlas", "Lotus"], "Sales": [1_000_000.0, 2_500_000.0], "Margin": [0.1, 0.1]})
    shown, spec = charts.with_changes(DF, before, {"style": STYLE})
    assert list(shown.columns) == ["Customer", "Sales", "Sales change", "Margin", "Margin change"]
    assert shown["Sales change"].round(3).tolist()[0] == 0.25 and pd.isna(shown["Sales change"][1])
    assert {"column": "Sales change", "d3_format": "+.1%"} in spec["style"]["formats"]
    by_month = pd.DataFrame({"Month": ["2026-02", "2026-01"], "Sales": [30.0, 10.0]})
    shown, _ = charts.with_changes(by_month, pd.DataFrame({"Month": ["2025-01", "2025-02"], "Sales": [5.0, 20.0]}), {})
    assert shown["Sales change"].tolist() == [0.5, 1.0]  # paired by position in time
