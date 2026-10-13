"""Real questions on the live server with the real Claude API (they cost a little).
Run with:  RUN_LIVE=1 python -m pytest tests/test_live.py    (needs the data layer to be built)"""
import pytest

import answering
import charts
import config
import data_layer
import llm

pytestmark = pytest.mark.live

BOOKINGS = "GlobalTravelEngine - Bookings"
PAYMENTS = "GlobalTravelEngine - Booking Payments"


@pytest.fixture(scope="module", autouse=True)
def layer_built():
    if config.resolve_source() != "ssas" or not data_layer.is_built():
        pytest.skip("needs the live server and a built data layer")


def test_claude_picks_the_cube_and_answers():
    out = answering.answer("How many bookings were made last month?")
    assert out.kind == "data", out.question
    assert out.plan.cubes == [BOOKINGS]
    assert len(out.df) == 1 and out.df.select_dtypes("number").iloc[0, 0] > 0


def test_a_question_that_needs_two_cubes_is_joined():
    if PAYMENTS not in data_layer.layer_cubes():
        pytest.skip("Booking Payments is not in the data layer")
    out = answering.answer("For the top 10 customers by sales this year, show their sales from bookings "
                           "next to the amount of their payments")
    assert out.kind == "data", out.question
    assert set(out.plan.cubes) == {BOOKINGS, PAYMENTS} and out.plan.combine_sql
    assert 0 < len(out.df) <= 10 and len(out.df.select_dtypes("number").columns) >= 2


def test_a_described_chart_is_drawn():
    out = answering.answer("Sales and number of bookings by month this year")
    assert out.kind == "data", out.question
    spec = llm.describe_result("Sales and bookings by month", out.df,
                               chart_request="sales as bars and bookings as a line on a second axis on the right")
    assert spec["chart_type"] == "custom"
    fig = charts.build_figure(out.df, spec)
    assert {t.type for t in fig.data} == {"bar", "scatter"} and fig.layout.yaxis2.side == "right"
