"""Answering questions end to end in local mode (real DuckDB on small CSVs, Claude scripted)."""
from datetime import date

import pytest

import answering
import cubes
import dashboards
import data_layer
import llm
from fakes import FakeClaude, chart, plan
from test_data_layer import build_local_layer

BY_MANAGER = ('SELECT a."Account Manager" AS "Manager", SUM(b."Sales USD") AS "Sales" '
              'FROM bookings b JOIN agencies a ON upper(trim(b."Agency")) = upper(trim(a."Agency")) '
              "WHERE b.\"Status\" = 'confirmed' GROUP BY 1 ORDER BY 2 DESC")


_real_structured_call = llm._structured_call


@pytest.fixture
def layer(app_dirs, monkeypatch):
    """A data layer built over the local files (the profile is scripted); questions then go
    through the real prompts with a scripted Claude."""
    build_local_layer(monkeypatch)
    monkeypatch.setattr(llm, "_structured_call", _real_structured_call)
    return data_layer.load()


def step(query, name="result"):
    return {"name": name, "cube": cubes.LOCAL, "query": query}


def test_not_ready_before_the_layer_is_built(app_dirs):
    ok, why = answering.ready(answering.ALL)
    assert not ok and "data layer" in why


def test_answer_joins_tables_and_fixes_capitals(layer, monkeypatch):
    fake = FakeClaude(plan([step(BY_MANAGER)]))
    monkeypatch.setattr(llm, "_create", fake)
    steps = []
    out = answering.answer("Confirmed sales by account manager", on_step=steps.append)
    assert out.kind == "data"
    assert out.df.to_dict("records") == [{"Manager": "Sara", "Sales": 785.5}, {"Manager": "Omar", "Sales": 550.5},
                                         {"Manager": "Lina", "Sales": 150.0}]
    assert "'Confirmed'" in out.plan.steps[0].query  # 'confirmed' corrected to the real value
    assert "Pulling the data" in steps
    assert "### Bookings and agencies" in fake.system_text()  # Claude was given the data layer


def test_a_value_that_is_not_in_the_data_becomes_a_question(layer, monkeypatch):
    query = 'SELECT COUNT(*) AS "Bookings" FROM bookings WHERE "Status" = \'Pending\''
    monkeypatch.setattr(llm, "_create", FakeClaude(plan([step(query)])))
    out = answering.answer("Pending bookings")
    assert out.kind == "clarify" and '"Pending" isn\'t a value of Status' in out.question
    assert set(out.options) == {"Confirmed", "Cancelled"}
    with pytest.raises(Exception, match="Pending"):
        answering.require_values(out)


def test_a_failing_plan_is_fixed_once(layer, monkeypatch):
    fake = FakeClaude(plan([step('SELECT "Nope" FROM bookings')]), plan([step('SELECT COUNT(*) AS "N" FROM bookings')]))
    monkeypatch.setattr(llm, "_create", fake)
    out = answering.answer("How many bookings")
    assert out.df["N"].iloc[0] == 12
    assert "Your previous plan failed" in fake.user_text(1) and "Nope" in fake.user_text(1)


def test_clarify_and_reuse_outcomes(layer, monkeypatch):
    ask_back = {**plan([]), "needs_clarification": True, "clarifying_question": "Which date?", "options": ["A", "B"]}
    monkeypatch.setattr(llm, "_create", FakeClaude(ask_back))
    out = answering.answer("Bookings in March")
    assert (out.kind, out.question, out.options) == ("clarify", "Which date?", ["A", "B"])
    reuse = {**plan([]), "reuse_previous": True, "chart_request": "as a pie"}
    monkeypatch.setattr(llm, "_create", FakeClaude(reuse))
    out = answering.answer("show it as a pie", context=[{"question": "q", "query": "SELECT 1"}])
    assert out.kind == "reuse" and out.result["chart_request"] == "as a pie"


def test_dashboard_chart_follows_the_period(layer, monkeypatch):
    query = ('SELECT strftime("Booking Date", \'%Y-%m\') AS "Month", SUM("Sales USD") AS "Sales" FROM bookings '
             'WHERE "Booking Date" >= @START AND "Booking Date" < @END GROUP BY 1 ORDER BY 1')
    fake = FakeClaude(plan([step(query)]), chart("bar", x="Month", y=["Sales"]))
    monkeypatch.setattr(llm, "_create", fake)
    built = dashboards.build_chart(cubes.LOCAL, "Sales by month", "", "auto", "half", '"Booking Date"',
                                   date(2026, 1, 1), date(2026, 3, 1))
    assert built["plan"]["steps"][0]["query"] == query and built["chart_type"] == "bar"
    assert "Filter the period with \"Booking Date\" >= @START" in fake.user_text(0)
    board = dashboards.create_dashboard("Test")
    dashboards.add_chart(board, built)
    res = dashboards.run_all([built], date(2026, 3, 1), date(2026, 6, 1))[built["id"]]
    assert res["error"] == "" and list(res["df"]["Month"]) == ["2026-03", "2026-04", "2026-05"]


def test_dashboard_chart_must_use_the_dates(layer, monkeypatch):
    no_dates = plan([step('SELECT SUM("Sales USD") AS "Sales" FROM bookings')])
    monkeypatch.setattr(llm, "_create", FakeClaude(no_dates, no_dates))
    with pytest.raises(ValueError, match="dashboard dates"):
        dashboards.build_chart(cubes.LOCAL, "Sales", "", "kpi", "half", '"Booking Date"',
                               date(2026, 1, 1), date(2026, 3, 1))


def test_kpi_compares_with_the_same_weeks_last_year(layer, monkeypatch):
    query = ('SELECT COUNT(*) AS "Bookings" FROM bookings '
             'WHERE "Booking Date" >= @START AND "Booking Date" < @END')
    kpi = {"id": "k1", "chart_type": "kpi", "date_column": '"Booking Date"',
           "plan": {"steps": [step(query)], "combine_sql": ""}}
    seen = []
    real_run = dashboards.plans.run
    monkeypatch.setattr(dashboards.plans, "run", lambda p, *a: seen.append(p.steps[0].query) or real_run(p, *a))
    dashboards.run_all([kpi], date(2026, 10, 12), date(2026, 10, 19), weekly=True)
    assert "DATE '2025-10-13'" in seen[1]  # Monday of week 42 in 2025


def test_custom_chart_on_a_dashboard_and_restyle(layer, monkeypatch):
    query = 'SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings GROUP BY 1 ORDER BY 2 DESC'
    funnel = '{"traces": [{"type": "funnel", "y": {"col": "Agency"}, "x": {"col": "Sales"}}]}'
    monkeypatch.setattr(llm, "_create", FakeClaude(plan([step(query)]), chart("custom", custom_chart=funnel)))
    built = dashboards.build_chart(cubes.LOCAL, "Sales by agency", "", "custom", "full", "",
                                   date(2026, 1, 1), date(2027, 1, 1), chart_request="a funnel")
    assert built["chart_type"] == "custom" and built["custom"]["traces"][0]["type"] == "funnel"
    assert built["chart_request"] == "a funnel"
    pie = '{"traces": [{"type": "pie", "labels": {"col": "Agency"}, "values": {"col": "Sales"}}]}'
    monkeypatch.setattr(llm, "_create", FakeClaude(chart("custom", custom_chart=pie)))
    restyled = dashboards.restyle_chart(built, "a pie", date(2026, 1, 1), date(2027, 1, 1))
    assert restyled["custom"]["traces"][0]["type"] == "pie" and restyled["plan"] == built["plan"]
