"""The app from any Claude conversation (assistant_tools.py behind mcp_server.py): Claude reads the knowledge,
checks queries and adds or changes dashboard charts, each chart run before it is saved. Local mode (DuckDB over
the sample files); the same tools on the live cubes were tried by hand through the connector."""
import asyncio
import json
from datetime import date

import pytest

import assistant_tools as tools
import cubes
import dashboards
from test_answering import layer  # noqa: F401 (fixture)

SPRING = (date(2026, 1, 1), date(2026, 6, 1), "")  # the sample bookings' months
PERIOD = '"Booking Date" >= @START AND "Booking Date" < @END'
BY_AGENCY = f'SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings WHERE {PERIOD} GROUP BY 1 ORDER BY 2 DESC'
TOTAL = f'SELECT SUM("Sales USD") AS "Sales" FROM bookings WHERE {PERIOD}'


def step(query, name="result"):
    return {"name": name, "cube": cubes.LOCAL, "query": query}


def bars(**changes) -> dict:
    return {"title": "Sales by agency", "chart_type": "horizontal_bar", "steps": [step(BY_AGENCY)], "x": "Agency",
            "y": ["Sales"], "style": {"formats": [{"column": "Sales", "d3_format": ",.0f", "prefix": "$", "suffix": ""}],
                                      "sort": "value_desc"}, **changes}


@pytest.fixture
def spring(layer, monkeypatch):  # noqa: F811
    """The dashboards' default period is the sample data's months; filters list the last year's agencies."""
    real = tools._dates
    monkeypatch.setattr(tools, "_dates", lambda start="", end="": real(start, end) if start and end else SPRING)
    monkeypatch.setattr(dashboards, "_today", lambda: date(2026, 6, 1))
    dashboards._options_cache.clear()
    return dashboards.create_dashboard("Agencies")


def test_the_knowledge_has_the_cubes_the_rules_and_the_placeholders(layer):  # noqa: F811
    text = tools.knowledge()
    assert f"Today is" in text and cubes.LOCAL in text
    assert "Rules for SQL queries" in text and "Joining cubes" in text  # the rules the app's own Claude follows
    assert "@START" in text and "@F_" in text and "@KEYS" in text
    assert "Local data" in tools.cube_details("local files")  # a cube by its short name too
    with pytest.raises(tools.ToolError, match="Unknown cube"):
        tools.cube_details("Nope")


def test_a_query_runs_for_the_dates_and_filter_values_given(layer):  # noqa: F811
    out = tools.run_query([step(BY_AGENCY)], start="2026-03-01", end="2026-03-31")
    assert out.startswith("Period 2026-03-01 to 2026-03-31. 2 rows.")
    assert '"Agency" (text/date), "Sales" (number)' in out and "Coral Bay Travel,300.0\nAtlas Voyages,150.0" in out
    one = tools.run_query([step(TOTAL + ' AND "Agency" = @F_AGENCY')], start="2026-01-01", end="2026-05-31",
                          filters={"AGENCY": "Atlas Voyages"})
    assert "162.0" in one
    with pytest.raises(tools.ToolError, match="@F_AGENCY"):
        tools.run_query([step(TOTAL + ' AND "Agency" = @F_AGENCY')])
    assert tools.run_query([step('SELECT "Nope" FROM bookings')]).startswith("The query failed")


def test_a_chart_is_run_before_it_is_saved_and_refused_when_it_fails(spring):
    with pytest.raises(tools.ToolError, match="@START and @END"):
        tools.add_chart(spring, bars(steps=[step('SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings GROUP BY 1')]))
    assert "is not a column of the result" in tools.add_chart(spring, bars(x="Client"))
    assert tools.add_chart(spring, bars(steps=[step(BY_AGENCY.replace("Sales USD", "Nope"))])).startswith("Not saved")
    assert dashboards.get_dashboard(spring)["charts"] == []

    out = tools.add_chart(spring, bars())
    assert out.startswith('Added "Sales by agency"') and f"/dashboard/{spring}" in out and "4 rows" in out
    out = tools.add_chart(spring, {"title": "Sales", "chart_type": "kpi", "steps": [step(TOTAL)]}, position=0)
    assert "Headline:" in out
    charts = dashboards.get_dashboard(spring)["charts"]
    assert [c["title"] for c in charts] == ["Sales", "Sales by agency"]
    saved = charts[1]
    assert saved["period_mode"] == "dashboard" and saved["date_column"] == '"Booking Date"'
    assert saved["style"]["formats"][0]["prefix"] == "$" and saved["width"] == "half"


def test_changing_a_chart_keeps_what_isnt_mentioned(spring):
    tools.add_chart(spring, bars())
    chart = tools.get_dashboard(spring)["charts"][0]
    assert chart["steps"] == [step(BY_AGENCY)] and chart["x"] == "Agency"
    out = tools.update_chart(spring, chart["id"], {"chart_type": "donut", "title": "Share of sales"})
    assert out.startswith('Changed "Share of sales"')
    after = tools.get_dashboard(spring)["charts"][0]
    assert after["chart_type"] == "donut" and after["steps"] == chart["steps"] and after["id"] == chart["id"]
    with pytest.raises(tools.ToolError, match="Unknown style setting"):
        tools.update_chart(spring, chart["id"], {"style": {"colour": "red"}})
    assert "is not a column" in tools.update_chart(spring, chart["id"], {"y": ["Profit"]})
    assert tools.get_dashboard(spring)["charts"][0]["y"] == ["Sales"]  # refused: unchanged


def test_filters_copies_moves_and_deletes(spring):
    options = {"cube": cubes.LOCAL, "query": BY_AGENCY, "value": "Agency"}
    out = tools.set_filters(spring, [{"key": "agency", "label": "Agency", "options": options}])
    assert '4 values, default "Lotus Travel House"' in out
    with pytest.raises(tools.ToolError, match="no filter for @F_MARKET"):
        tools.add_chart(spring, bars(steps=[step(BY_AGENCY.replace("WHERE", 'WHERE "Agency" = @F_MARKET AND'))]))
    one = {"title": "Agency sales", "chart_type": "kpi", "steps": [step(TOTAL + ' AND "Agency" = @F_AGENCY')]}
    assert "Headline:" in tools.add_chart(spring, one)  # run with the filter's default value
    tools.add_chart(spring, bars())

    copy = tools.copy_dashboard(spring, "Agencies (mine)")
    copied = dashboards.get_dashboard(copy.split("(id ")[1][:8])
    assert copied["filters"][0]["placeholder"] == "@F_AGENCY" and len(copied["charts"]) == 2
    other = dashboards.create_dashboard("Plain")
    agency_chart, bar_chart = dashboards.get_dashboard(spring)["charts"]
    with pytest.raises(tools.ToolError, match="no filter for @F_AGENCY"):
        tools.copy_chart(spring, agency_chart["id"], other)
    assert "Copied" in tools.copy_chart(spring, bar_chart["id"], other)

    assert "0. Sales by agency" in tools.move_chart(spring, bar_chart["id"], 0)
    assert "Removed" in tools.delete_chart(spring, bar_chart["id"])
    assert [c["title"] for c in dashboards.get_dashboard(spring)["charts"]] == ["Agency sales"]
    assert "Deleted the dashboard" in tools.delete_dashboard(other)


def test_a_built_in_dashboard_changed_from_claude_is_kept(layer, monkeypatch):  # noqa: F811
    import builtin_dashboards as bd
    import config
    monkeypatch.setattr(config, "BUILTIN_DASHBOARDS", True)
    dashboards._builtin_checked["time"] = 0.0
    dashboards.ensure_builtin(force=True)
    assert "new versions of the app update it" in tools.get_dashboard("overview")["note"]
    dashboards.delete_chart("overview", "ov-sales")
    assert "leave it as it is" in tools.get_dashboard("overview")["note"]
    assert "built in, changed here" in tools.list_dashboards()
    monkeypatch.setattr(bd, "VERSION", bd.VERSION + 1)
    dashboards.ensure_builtin(force=True)
    assert "ov-sales" not in [c["id"] for c in dashboards.get_dashboard("overview")["charts"]]
    dashboards._builtin_checked["time"] = 0.0


def test_the_connector_offers_the_tools_and_explains_problems(spring):
    import mcp_server
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"get_knowledge", "get_cube_details", "find_values", "run_query", "add_chart", "update_chart",
            "set_dashboard_filters", "get_dashboard_guide"} <= names
    content = asyncio.run(mcp_server.mcp.call_tool("list_dashboards", {}))
    text = json.dumps(content, default=str)
    assert "Agencies" in text and f"/dashboard/{spring}" in text
    with pytest.raises(Exception, match="Give the dashboard a name"):
        asyncio.run(mcp_server.mcp.call_tool("create_dashboard", {"name": " "}))
    guide = asyncio.run(mcp_server.mcp.call_tool("get_dashboard_guide", {}))
    assert "name: bookings-dashboards" in json.dumps(guide, default=str)
