"""The question rewrite: a follow-up becomes a standalone question, how to draw it is set apart, and
code (not Claude) turns each period into exact dates; a plan that counts another period is sent back."""
from datetime import date

import pytest

import answering
import llm
import plans
import rewrite
import usage
from fakes import FakeClaude, plan
from test_answering import layer, step  # noqa: F401 (fixture)

TODAY = date(2026, 10, 16)  # a Friday, in ISO week 42


def point(unit, way="relative", offset=0, year=0, number=0, day=""):
    return {"unit": unit, "way": way, "offset": offset, "year": year, "number": number, "date": day}


def dates(first, last=None, to_date=False):
    p = rewrite.resolve({"phrase": "p", "first": first, "last": last or first, "to_date": to_date}, TODAY)
    return p.start.isoformat(), (p.end - __import__("datetime").timedelta(days=1)).isoformat()


def test_code_turns_each_period_into_exact_dates():
    assert dates(point("month", offset=-1)) == ("2026-09-01", "2026-09-30")                     # last month
    assert dates(point("month", "calendar", year=2026, number=7),
                 point("month", "calendar", year=2026, number=9)) == ("2026-07-01", "2026-09-30")  # Jul-Sep 2026
    assert dates(point("year"), to_date=True) == ("2026-01-01", "2026-10-16")                   # this year so far
    assert dates(point("month", "calendar", number=3), point("day")) == ("2026-03-01", "2026-10-16")  # since March
    assert dates(point("day", offset=-6), point("day")) == ("2026-10-10", "2026-10-16")         # last 7 days
    assert dates(point("day", offset=-1)) == ("2026-10-15", "2026-10-15")                       # yesterday
    assert dates(point("week", "calendar", number=41)) == ("2026-10-05", "2026-10-11")          # week 41 (ISO)
    assert dates(point("week", "calendar", number=50)) == ("2025-12-08", "2025-12-14")          # not started: last year's
    assert dates(point("month", "calendar", number=12)) == ("2025-12-01", "2025-12-31")         # "in December"
    assert dates(point("half", "calendar", year=2019, number=1)) == ("2019-01-01", "2019-06-30")  # H1 2019
    assert dates(point("quarter", "calendar", year=2026, number=3)) == ("2026-07-01", "2026-09-30")
    assert dates(point("week", offset=-1)) == ("2026-10-05", "2026-10-11")                      # last week
    assert dates(point("month", offset=1)) == ("2026-11-01", "2026-11-30")                      # next month
    assert dates(point("day", "date", day="2026-10-14")) == ("2026-10-14", "2026-10-14")
    for impossible in (point("week", "calendar", year=2026, number=54), point("quarter", "calendar", year=2026, number=5)):
        with pytest.raises(ValueError):
            dates(impossible)
    with pytest.raises(ValueError, match="ends before it starts"):
        dates(point("month"), point("month", offset=-2))


def test_a_follow_up_becomes_a_standalone_question(monkeypatch):
    fake = FakeClaude(rewrite={
        "standalone_question": "Bookings by market for last month", "chart_request": "as a pie", "kind": "follow_up",
        "periods": [{"phrase": "last month", "first": point("month", offset=-1), "last": point("month", offset=-1),
                     "to_date": False},
                    {"phrase": "week 54", "first": point("week", "calendar", year=2026, number=54),
                     "last": point("week", "calendar", year=2026, number=54), "to_date": False}]})
    monkeypatch.setattr(llm, "_create", fake)
    context = [{"question": "Bookings last month", "understanding": "Bookings by booking date, 1-30 Sep 2026",
                "spec": {"chart_type": "bar"}}]
    with usage.track("question", "and by market, as a pie?"):
        out = rewrite.rewrite("and by market, as a pie?", context, today=TODAY)
    entry = usage.load()[-1]
    assert (out.question, out.kind, out.chart_request) == ("Bookings by market for last month", "follow_up", "as a pie")
    assert out.periods_text() == '- "last month" = 2026-09-01 to 2026-09-30 (1 Sep – 30 Sep 2026)'
    sent = fake.rewrites[0]["messages"][0]["content"]
    assert "Today is Friday 2026-10-16" in sent and "Understood as: Bookings by booking date" in sent
    assert fake.rewrites[0]["model"] == "claude-haiku-5-5" and entry["period_errors"][0].startswith("week 54")
    # with no earlier turn there is nothing to follow or show again
    fake.rewrite = {**fake.rewrite, "kind": "chart_only", "periods": []}
    assert rewrite.rewrite("as a pie", None, today=TODAY).kind == "new"


def test_a_plan_that_counts_another_period_is_sent_back(layer, monkeypatch):  # noqa: F811
    march = {"phrase": "March 2026", "first": point("month", "calendar", year=2026, number=3),
             "last": point("month", "calendar", year=2026, number=3), "to_date": False}
    wrong = step('SELECT COUNT(*) AS "N" FROM bookings WHERE "Booking Date" BETWEEN DATE \'2026-02-01\' AND DATE \'2026-02-28\'')
    right = step('SELECT COUNT(*) AS "N" FROM bookings WHERE "Booking Date" >= DATE \'2026-03-01\' AND "Booking Date" < DATE \'2026-04-01\'')
    fake = FakeClaude(plan([wrong]), plan([right]),
                      rewrite={"standalone_question": "Bookings in March 2026", "chart_request": "", "kind": "new",
                               "periods": [march]})
    monkeypatch.setattr(llm, "_create", fake)
    out = answering.answer("bookings in march 2026")
    assert out.df["N"].iloc[0] == 3
    assert "Question: Bookings in March 2026" in fake.user_text(0)  # the planner gets the standalone question
    assert '"March 2026" = 2026-03-01 to 2026-03-31' in fake.user_text(0)
    assert "filters on 2026-02-01, 2026-02-28, but the question's period is" in fake.user_text(1)


def test_steps_that_filter_by_month_names_are_not_checked():
    period = rewrite.Period("Q3 2026", date(2026, 7, 1), date(2026, 10, 1))
    by_name = plans.Plan([plans.Step("s", "C", "EVALUATE ... 'Calendar'[Month Name] IN {\"July 2026\"} ...")])
    plans.check_periods(by_name, [period])
    exclusive_end = plans.Plan([plans.Step("s", "C", "... >= DATE(2026,7,1) && ... < DATE(2026,10,1)")])
    plans.check_periods(exclusive_end, [period])
    with pytest.raises(ValueError, match="Q3 2026"):
        plans.check_periods(plans.Plan([plans.Step("s", "C", "... >= DATE(2026,6,1) && ... < DATE(2026,9,1)")]), [period])


def test_a_comparison_must_keep_every_period():
    this, last = rewrite.Period("Jan-Sep 2026", date(2026, 1, 1), date(2026, 10, 1)), \
        rewrite.Period("Jan-Sep 2025", date(2025, 1, 1), date(2025, 10, 1))
    only_2025 = plans.Plan([plans.Step("s", "C", "... >= DATE(2025,1,1) && ... <= DATE(2025,9,30)")])
    with pytest.raises(ValueError, match="filters no dates of \"Jan-Sep 2026\""):
        plans.check_periods(only_2025, [this, last])
    one_range = plans.Plan([plans.Step("s", "C", "... >= DATE(2025,1,1) && ... <= DATE(2026,9,30)")])
    plans.check_periods(one_range, [this, last])  # one range over both, grouped by year: fine
    both = plans.Plan([plans.Step("a", "C", "DATE(2026,1,1) DATE(2026,9,30)"), plans.Step("b", "C", "DATE(2025,1,1) DATE(2025,9,30)")])
    plans.check_periods(both, [this, last])
    plans.check_periods(plans.Plan([plans.Step("s", "C", "DATE(2026,2,30)")]), [])  # no periods: nothing checked
