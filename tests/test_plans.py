from datetime import date

import duckdb
import pandas as pd
import pytest

import plans


class FakeBackend:
    """A cube that returns fixed rows and records the queries it ran."""
    language = "DAX"

    def __init__(self, df):
        self.df, self.queries = df, []

    def run(self, query, max_rows=None):
        self.queries.append(query)
        if "FAIL" in query:
            raise RuntimeError("Query (1, 1) The column 'X'[Y] does not exist.")
        return self.df

    @staticmethod
    def date_literal(d):
        return f"DATE({d.year},{d.month},{d.day})"


@pytest.fixture
def two_cubes(monkeypatch):
    backends = {
        "Bookings": FakeBackend(pd.DataFrame({"Code": ["A1", "b2", "C3"], "Sales": [100.0, 200.0, 50.0]})),
        "Payments": FakeBackend(pd.DataFrame({"Code": ["a1 ", "B2", "D4"], "Paid": [90.0, 200.0, 10.0]})),
    }
    monkeypatch.setattr(plans, "get_backend", lambda cube: backends[cube])
    return backends


PLAN = {
    "steps": [{"name": "Bookings!", "cube": "Bookings", "query": "EVALUATE ... @START @END"},
              {"name": "payments", "cube": "Payments", "query": "EVALUATE ... @START @END"}],
    "combine_sql": '''SELECT COALESCE(upper(trim(b."Code")), upper(trim(p."Code"))) AS "Customer",
                             b."Sales", p."Paid"
                      FROM bookings b FULL OUTER JOIN payments p ON upper(trim(b."Code")) = upper(trim(p."Code"))
                      ORDER BY 1''',
}


def test_plan_names_text_and_round_trip():
    plan = plans.Plan.from_dict(PLAN)
    assert [s.name for s in plan.steps] == ["bookings", "payments"]
    assert plan.cubes == ["Bookings", "Payments"] and not plan.single
    assert '-- Step payments: cube "Payments"' in plan.text() and "-- Combine the steps (SQL)" in plan.text()
    assert plans.Plan.from_dict(plan.to_dict()) == plan
    assert plans.Plan.from_dict({"steps": [{"name": "x", "cube": "C", "query": "Q"}], "combine_sql": "SELECT 1"}).combine_sql == ""


def test_old_dashboard_charts_still_work():
    plan = plans.Plan.from_chart({"cube": "Bookings", "query": "EVALUATE X"})
    assert plan.single and plan.steps[0].cube == "Bookings" and plan.text() == "EVALUATE X"


def test_run_joins_cubes_on_shared_keys(two_cubes):
    plan = plans.Plan.from_dict(PLAN).with_dates(date(2026, 1, 1), date(2026, 2, 1))
    assert plan.steps[0].query == "EVALUATE ... DATE(2026,1,1) DATE(2026,2,1)"
    df = plans.run(plan)
    df = df.astype(object).where(df.notna(), None)
    assert df.to_dict("records") == [
        {"Customer": "A1", "Sales": 100.0, "Paid": 90.0},
        {"Customer": "B2", "Sales": 200.0, "Paid": 200.0},
        {"Customer": "C3", "Sales": 50.0, "Paid": None},
        {"Customer": "D4", "Sales": None, "Paid": 10.0},
    ]


def test_a_failing_step_is_named(two_cubes):
    plan = plans.Plan.from_dict({**PLAN, "steps": [PLAN["steps"][0], {**PLAN["steps"][1], "query": "FAIL"}]})
    with pytest.raises(plans.StepError, match='Step payments \\(cube "Payments"\\) failed'):
        plans.run(plan)


def test_combine_errors_list_the_columns_each_step_returned():
    frames = {"bookings": pd.DataFrame({"Code": ["A"], "Sales": [1]})}
    with pytest.raises(plans.StepError, match='bookings: "Code", "Sales"'):
        plans.combine(frames, 'SELECT "Customer Code" FROM bookings')


def test_combine_cannot_read_files_or_change_anything(tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n")
    frames = {"bookings": pd.DataFrame({"x": [1]})}
    with pytest.raises((plans.StepError, duckdb.Error)):
        plans.combine(frames, f"SELECT * FROM read_csv_auto('{secret.as_posix()}')")
    for bad in ("DROP TABLE bookings", "SELECT 1; SELECT 2", "COPY bookings TO 'x.csv'"):
        with pytest.raises(ValueError):
            plans.combine(frames, bad)


def test_validate(two_cubes):
    plans.validate(plans.Plan.from_dict(PLAN), ["Bookings", "Payments"])
    with pytest.raises(ValueError, match="not one of the connected cubes"):
        plans.validate(plans.Plan.from_dict(PLAN), ["Bookings"])
    with pytest.raises(ValueError, match="no combine_sql"):
        plans.validate(plans.Plan.from_dict({**PLAN, "combine_sql": ""}))
    with pytest.raises(RuntimeError):
        plans.validate(plans.Plan())
    assert plans.Plan.from_dict(PLAN).uses_dates()
    assert not plans.Plan.from_dict({"steps": [{"name": "a", "cube": "Bookings", "query": "EVALUATE 1"}]}).uses_dates()
