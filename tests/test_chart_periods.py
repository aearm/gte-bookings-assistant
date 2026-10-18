"""Chart periods: a chat answer goes on a dashboard at once (no Claude call, no query) with its own dates
as placeholders, its chart as drawn in Chat and its numbers; own periods move forward with the days,
fixed ones never move, and both ignore the dashboard's period and its comparison. Charts that follow
the dashboard are drawn by week or month over long periods when their numbers can be added up."""
import hashlib
import json
import time
from datetime import date, timedelta

import pandas as pd
import pytest

import answering
import cubes
import dashboards
import llm
import periods
import plans
import rewrite
from fakes import FakeClaude, plan
from test_answering import layer, step  # noqa: F401 (fixture)


def point(unit, way="relative", offset=0, year=0, number=0, day=""):
    return {"unit": unit, "way": way, "offset": offset, "year": year, "number": number, "date": day}


def item(phrase, first, last=None, to_date=False):
    return {"phrase": phrase, "first": first, "last": last or first, "to_date": to_date}


YESTERDAY, DAY_BEFORE = item("yesterday", point("day", offset=-1)), item("the day before", point("day", offset=-2))


def records(today, *items):
    return [rewrite.record(i, rewrite.resolve(i, today)) for i in items]


class FixedDay(date):
    """date, with today() fixed (for code that asks for today's date)."""
    day_today = date(2026, 5, 3)

    @classmethod
    def today(cls):
        return cls(cls.day_today.year, cls.day_today.month, cls.day_today.day)


def dax_plan(query, combine=""):
    return plans.Plan([plans.Step("result", "Desert Cube", query)], combine)


# ---------------------------------------------------------------- placeholders --

def test_dax_and_sql_dates_become_each_periods_placeholders(app_dirs):
    y, before = (date(2026, 10, 15), date(2026, 10, 16)), (date(2026, 10, 14), date(2026, 10, 15))
    dax = dax_plan("EVALUATE SUMMARIZECOLUMNS('Client'[Name], 'Day'[Date], KEEPFILTERS(FILTER(ALL('Day'[Date]), "
                   "'Day'[Date] >= DATE(2026,10,14) && 'Day'[Date] <= DATE(2026, 10, 15))), \"Bookings\", [Bookings])")
    out = plans.parametrize(dax, [y, before], ["@P1_", "@P2_"]).steps[0].query
    assert "'Day'[Date] >= @P2_START && 'Day'[Date] <= @P1_LAST" in out  # the last day, not the day after
    sql = plans.Plan([plans.Step("a", cubes.LOCAL, "SELECT 1 FROM t WHERE d >= DATE '2026-10-14' AND d < DATE '2026-10-16'"),
                      plans.Step("b", cubes.LOCAL, "SELECT 2 FROM t WHERE d BETWEEN DATE '2026-10-15' AND DATE '2026-10-15' "
                                                   "OR d = DATE '2026-10-14' OR d >= DATE '2020-01-01'")],
                     "SELECT * FROM a, b WHERE a.d < DATE '2026-10-16'")
    out = plans.parametrize(sql, [y, before], ["@P1_", "@P2_"])
    assert out.steps[0].query.endswith("d >= @P2_START AND d < @P1_END")  # the day after the last: END
    assert "BETWEEN @P1_START AND @P1_LAST OR d = @P2_START" in out.steps[1].query
    assert "DATE '2020-01-01'" in out.steps[1].query  # not one of the periods' dates: kept
    assert out.combine_sql.endswith("a.d < @P1_END") and out.own_periods() == 2
    # filled in again for other days, each in its own language (the joining SQL in DuckDB's)
    later = out.with_periods([(date(2026, 10, 20), date(2026, 10, 21)), (date(2026, 10, 19), date(2026, 10, 20))])
    assert later.steps[0].query.endswith("d >= DATE '2026-10-19' AND d < DATE '2026-10-21'")
    assert later.combine_sql.endswith("a.d < DATE '2026-10-21'")
    with pytest.raises(ValueError, match="2 period"):
        plans.Plan([plans.Step("a", cubes.LOCAL, "@P3_START")]).with_periods([y, before])


def test_one_period_can_follow_the_dashboard_and_last_day_filters_still_work(app_dirs):
    sept = (date(2026, 9, 1), date(2026, 10, 1))
    query = "EVALUATE CALCULATETABLE(X, DATESBETWEEN('Day'[Date], DATE(2026,9,1), DATE(2026,9,30)))"
    out = plans.parametrize(dax_plan(query), [sept], ["@"])
    assert out.steps[0].query == "EVALUATE CALCULATETABLE(X, DATESBETWEEN('Day'[Date], @START, @LAST))"
    assert plans.filters_a_range(out)
    local = plans.Plan([plans.Step("r", cubes.LOCAL, "SELECT 1 WHERE d >= @START AND d <= @LAST")])
    assert local.with_dates(date(2026, 3, 1), date(2026, 4, 1)).steps[0].query.endswith(
        "d >= DATE '2026-03-01' AND d <= DATE '2026-03-31'")  # @LAST = the day before @END
    one_day = plans.parametrize(dax_plan("... 'Day'[Date] = DATE(2026,9,30)"), [(date(2026, 9, 30), date(2026, 10, 1))], ["@"])
    assert not plans.filters_a_range(one_day)  # a single day can't stretch to a longer period
    in_vars = dax_plan("DEFINE VAR _from = DATE(2026,9,1) VAR _to = DATE(2026,10,1) EVALUATE ...")
    assert plans.parametrize(in_vars, [sept], ["@P1_"]).steps[0].query.startswith(
        "DEFINE VAR _from = @P1_START VAR _to = @P1_END")  # not said how they're used: first day, day after


def test_plans_that_cant_move_with_their_periods_are_refused():
    y = [(date(2026, 10, 15), date(2026, 10, 16))]
    for query, why in [("... 'Day'[Month] = \"October\"", "no dates of period 1"),
                       ("... d > DATE '2026-10-14' AND d < DATE '2026-10-16'", "can't be moved"),
                       ("SELECT '2026-10-15' AS label WHERE d = DATE '2026-10-15'", "as text")]:
        with pytest.raises(plans.CannotParametrize, match=why):
            plans.parametrize(plans.Plan([plans.Step("r", cubes.LOCAL, query)]), y, ["@P1_"])
    week = [(date(2026, 10, 5), date(2026, 10, 12))]
    with pytest.raises(plans.CannotParametrize, match="can't be moved"):  # a day in the middle of the week
        plans.parametrize(plans.Plan([plans.Step("r", cubes.LOCAL, "... d IN (DATE '2026-10-05', DATE '2026-10-08')")]),
                          week, ["@P1_"])


def test_the_dashboards_quick_choices_are_periods_of_the_grammar():
    for today in (date(2026, 10, 16), date(2026, 1, 1), date(2026, 3, 31), date(2026, 10, 12)):
        for name in periods.PRESETS:
            p = rewrite.resolve(rewrite.preset_item(name), today)
            assert (p.start, p.end) == periods.preset_range(name, today), (name, today)
    assert rewrite.preset_item("") is None


def test_the_rewrite_keeps_each_periods_grammar(monkeypatch):
    fake = FakeClaude(rewrite={"standalone_question": "Bookings yesterday vs the day before", "chart_request": "",
                               "kind": "new", "periods": [YESTERDAY, DAY_BEFORE, item("week 54", point(
                                   "week", "calendar", year=2026, number=54))]})
    monkeypatch.setattr(llm, "_create", fake)
    out = rewrite.rewrite("bookings yesterday vs the day before", today=date(2026, 10, 16))
    assert out.records() == [
        {**YESTERDAY, "start": "2026-10-15", "end": "2026-10-16"},
        {**DAY_BEFORE, "start": "2026-10-14", "end": "2026-10-15"}]  # the impossible week 54 is dropped


# ---------------------------------------------------------------- from Chat, at once --

BY_AGENCY_AND_DAY = ('SELECT "Agency", "Booking Date" AS "Day", COUNT(*) AS "Bookings", SUM("Sales USD") AS "Sales" '
                     'FROM bookings WHERE "Booking Date" >= DATE \'2026-05-01\' AND "Booking Date" < DATE \'2026-05-03\' '
                     'GROUP BY 1, 2 ORDER BY 1, 2')
ONE_CHART = {"chart_type": "bar", "x": "Agency", "y": ["Bookings", "Sales"], "color": "Day",
             "style": {"measures": "one_chart", "formats": [{"column": "Sales", "prefix": "USD "}]},
             "title": "Bookings and sales by agency, yesterday vs the day before", "summary": "Two agencies."}


@pytest.fixture
def asked(layer, monkeypatch):  # noqa: F811
    """A chat answer to "yesterday vs the day before" on 3 May 2026: (turn as Chat keeps it, Claude)."""
    monkeypatch.setattr(rewrite, "date", FixedDay)
    monkeypatch.setattr(dashboards, "_today", lambda: date(2026, 5, 3))
    fake = FakeClaude(plan([step(BY_AGENCY_AND_DAY)]), ONE_CHART,
                      rewrite={"standalone_question": "Bookings and sales by agency yesterday vs the day before",
                               "chart_request": "one chart", "kind": "new", "periods": [YESTERDAY, DAY_BEFORE]})
    monkeypatch.setattr(llm, "_create", fake)
    out = answering.ask("bookings and sales by agency yesterday vs the day before, in one chart")
    turn = {"question": "bookings and sales by agency yesterday vs the day before, in one chart",
            "plan": out.plan.to_dict(), "query": out.plan.text(), "cubes": out.plan.cubes, "df": out.df,
            "spec": out.spec, "periods": out.result["periods"], "standalone": out.result["standalone_question"]}
    return turn, fake


def counting_runs(monkeypatch) -> list:
    runs, real_run = [], plans.run
    monkeypatch.setattr(plans, "run", lambda p, *a, **k: runs.append(p) or real_run(p, *a, **k))
    return runs


def test_an_answer_keeps_its_periods_also_when_asked_again_today(asked, monkeypatch):
    turn, _ = asked
    assert [(p["phrase"], p["start"], p["end"]) for p in turn["periods"]] == [
        ("yesterday", "2026-05-02", "2026-05-03"), ("the day before", "2026-05-01", "2026-05-02")]
    assert turn["periods"][0]["first"] == point("day", offset=-1)
    fake = FakeClaude()  # asked again the same day: its saved plan, no Claude
    monkeypatch.setattr(llm, "_create", fake)
    again = answering.ask("bookings and sales by agency yesterday vs the day before, in one chart")
    assert again.result["periods"] == turn["periods"] and "periods" not in again.spec and fake.requests == []


def test_adding_from_chat_asks_nothing_and_runs_nothing(asked, monkeypatch):
    turn, _ = asked
    fake = FakeClaude()  # any call fails the test
    monkeypatch.setattr(llm, "_create", fake)
    runs = counting_runs(monkeypatch)
    board = dashboards.create_dashboard("Desk")
    began = time.perf_counter()
    chart = dashboards.add_from_answer(board, turn, "own", as_of={cubes.LOCAL: "3 May 2026, 06:00"})
    assert time.perf_counter() - began < 1
    assert runs == [] and fake.requests == [] and fake.rewrites == []
    query = chart["plan"]["steps"][0]["query"]
    assert '"Booking Date" >= @P2_START AND "Booking Date" < @P1_END' in query and "2026-05" not in query
    # what you saw is what you get: the chart as drawn in Chat, its title without the periods
    assert {k: chart[k] for k in ("chart_type", "x", "y", "color", "style")} == {
        k: turn["spec"][k] for k in ("chart_type", "x", "y", "color", "style")}
    assert chart["style"]["measures"] == "one_chart"
    assert chart["title"] == "Bookings and sales by agency" and chart["question"] == turn["standalone"]
    assert chart["period_mode"] == "own" and chart["date_column"] == '"Booking Date"'
    assert dashboards.get_chart(board, chart["id"])["periods"] == turn["periods"]
    # the dashboard opens with the chat's numbers, whatever its own period and comparison
    res, updating = dashboards.results_for([chart], date(2026, 1, 1), date(2026, 5, 4),
                                           (date(2025, 1, 1), date(2025, 5, 4)), {cubes.LOCAL: "3 May 2026, 06:00"})
    assert runs == [] and updating == [] and res[chart["id"]]["prev"] is None
    pd.testing.assert_frame_equal(res[chart["id"]]["df"], turn["df"])
    assert dashboards.period_text(chart) == "Own period: yesterday vs the day before (1–2 May)"


def test_own_periods_move_forward_and_fixed_ones_never_do(asked, monkeypatch):
    turn, _ = asked
    monkeypatch.setattr(llm, "_create", FakeClaude())
    own, fixed = dashboards.chart_from_answer(turn, "own"), dashboards.chart_from_answer(turn, "fixed")
    monkeypatch.setattr(dashboards, "_today", lambda: date(2026, 5, 21))  # 18 days later
    runs = counting_runs(monkeypatch)
    res = dashboards.run_all([own, fixed], date(2026, 1, 1), date(2026, 2, 1), (date(2025, 1, 1), date(2025, 2, 1)))
    assert "DATE '2026-05-19'" in runs[0].steps[0].query and "DATE '2026-05-21'" in runs[0].steps[0].query
    assert res[own["id"]]["df"].to_dict("records") == [
        {"Agency": "Lotus Travel House", "Day": date(2026, 5, 20), "Bookings": 1, "Sales": 220.0}]
    assert res[own["id"]]["prev"] is None and res[fixed["id"]]["prev"] is None  # no dashboard comparison
    pd.testing.assert_frame_equal(res[fixed["id"]]["df"], turn["df"])  # still 1-2 May
    assert dashboards.period_text(own) == "Own period: yesterday vs the day before (19–20 May)"
    assert dashboards.period_text(fixed) == "Fixed: 1–2 May 2026"
    assert not dashboards.compares(own) and not dashboards.compares({**fixed, "chart_type": "kpi", "y": []})


def test_saved_numbers_of_own_periods_dont_depend_on_the_dashboard(asked):
    turn, _ = asked
    own = dashboards.chart_from_answer(turn, "own")
    keys = {dashboards.saved_key(own, date(2026, m, 1), date(2026, m + 1, 1), c)
            for m in (1, 4) for c in (None, (date(2025, 1, 1), date(2025, 2, 1)))}
    assert len(keys) == 1  # any dashboard period, any comparison: the same saved numbers
    follows = {**own, "period_mode": "dashboard"}
    assert dashboards.saved_key(follows, date(2026, 1, 1), date(2026, 2, 1), None) != \
        dashboards.saved_key(follows, date(2026, 4, 1), date(2026, 5, 1), None)


def test_saved_numbers_of_own_periods_move_with_the_days(asked, monkeypatch):
    turn, _ = asked
    own = dashboards.chart_from_answer(turn, "own")
    today_key = dashboards.saved_key(own, date(2026, 1, 1), date(2026, 2, 1), None)
    monkeypatch.setattr(dashboards, "_today", lambda: date(2026, 5, 4))
    assert dashboards.saved_key(own, date(2026, 1, 1), date(2026, 2, 1), None) != today_key
    assert not dashboards.keep_answer_numbers(own, turn)  # yesterday's answer is not today's "yesterday"


def test_how_an_answer_can_go_on_a_dashboard(asked):
    turn, _ = asked
    choices = dashboards.period_choices(turn)
    assert [(c["mode"], c["instant"]) for c in choices] == [("own", True), ("fixed", True), ("dashboard", False)]
    assert choices[0]["label"] == "Own period: yesterday vs the day before (1–2 May)"
    assert choices[1]["label"] == "Fixed dates: 1–2 May 2026"
    with pytest.raises(dashboards.NeedsClaude):  # two periods can't follow the dashboard's one
        dashboards.chart_from_answer(turn, "dashboard")
    no_dates = {**turn, "periods": []}
    assert [(c["mode"], c["instant"]) for c in dashboards.period_choices(no_dates)] == [("dashboard", False), ("fixed", True)]
    all_dates = dashboards.chart_from_answer(no_dates, "fixed")
    assert dashboards.period_text(all_dates) == "All dates" and all_dates["plan"] == turn["plan"]
    by_month = {**turn, "plan": {"steps": [step('SELECT 1 AS "N" FROM bookings WHERE "Month" = \'May\'')], "combine_sql": ""}}
    assert [c["mode"] for c in dashboards.period_choices(by_month)] == ["dashboard", "fixed"]  # dates not in the query


def test_one_period_follows_the_dashboard_at_once(layer, monkeypatch):  # noqa: F811
    query = ('SELECT "Destination Country", COUNT(*) AS "Bookings" FROM bookings '
             'WHERE "Booking Date" >= DATE \'2026-03-01\' AND "Booking Date" <= DATE \'2026-03-31\' GROUP BY 1')
    march = item("March 2026", point("month", "calendar", year=2026, number=3))
    turn = {"question": "Bookings by country in March 2026", "plan": {"steps": [step(query)], "combine_sql": ""},
            "df": pd.DataFrame({"Destination Country": ["Spain", "France", "Italy"], "Bookings": [1, 1, 1]}),
            "spec": {"chart_type": "horizontal_bar", "x": "Destination Country", "y": ["Bookings"], "color": "",
                     "title": "Bookings by country, March 2026"},
            "periods": records(date(2026, 10, 16), march)}
    chart = dashboards.chart_from_answer(turn, "dashboard")
    assert chart["plan"]["steps"][0]["query"].endswith('"Booking Date" >= @START AND "Booking Date" <= @LAST GROUP BY 1')
    assert chart["title"] == "Bookings by country" and dashboards.compares(chart) and dashboards.period_text(chart) == ""
    res = dashboards.run_all([chart], date(2026, 1, 1), date(2026, 6, 1), (date(2025, 1, 1), date(2025, 6, 1)))
    assert res[chart["id"]]["df"]["Bookings"].sum() == 12 and res[chart["id"]]["prev"].empty  # Jan-May; none in 2025
    # its first numbers are kept only for the dashboard's period that is the question's
    assert not dashboards.keep_answer_numbers(chart, turn, period=(date(2026, 1, 1), date(2026, 6, 1)))
    assert dashboards.keep_answer_numbers(chart, turn, period=(date(2026, 3, 1), date(2026, 4, 1)))


def test_old_charts_follow_the_dashboard_as_before(layer):  # noqa: F811
    query = 'SELECT COUNT(*) AS "Bookings" FROM bookings WHERE "Booking Date" >= @START AND "Booking Date" < @END'
    old = {"id": "k1", "chart_type": "kpi", "date_column": '"Booking Date"', "title": "Bookings", "question": "Bookings",
           "plan": {"steps": [step(query)], "combine_sql": ""}}
    assert dashboards.period_mode(old) == "dashboard" and dashboards.own_dates(old) is None
    assert dashboards.period_text(old) == "" and dashboards.compares(old)
    period, versus = (date(2026, 3, 1), date(2026, 6, 1)), (date(2026, 1, 1), date(2026, 3, 1))
    before = hashlib.sha256(json.dumps([dashboards.run_key(old), str(period[0]), str(period[1]),
                                        [str(d) for d in versus]]).encode()).hexdigest()[:24]
    assert dashboards.saved_key(old, *period, versus) == before  # saved numbers from before still found
    res = dashboards.run_all([old], *period, versus)["k1"]
    assert res["df"].iloc[0, 0] == 8 and res["prev"].iloc[0, 0] == 4


# ---------------------------------------------------------------- switching modes (Edit) --

def test_an_admin_switches_how_a_chart_picks_its_dates(asked):
    turn, _ = asked
    own = dashboards.chart_from_answer(turn, "own")
    fixed = dashboards.change_period_mode(own, "fixed", date(2026, 1, 1), date(2026, 5, 4), "This year")
    assert [(p["start"], p["end"]) for p in fixed["periods"]] == [("2026-05-02", "2026-05-03"), ("2026-05-01", "2026-05-02")]
    assert dashboards.change_period_mode(fixed, "own", date(2026, 1, 1), date(2026, 5, 4))["period_mode"] == "own"
    with pytest.raises(dashboards.NeedsClaude):  # two periods of its own can't follow the dashboard's one
        dashboards.change_period_mode(own, "dashboard", date(2026, 1, 1), date(2026, 5, 4))
    assert list(dashboards.mode_choices(own, date(2026, 1, 1), date(2026, 5, 4), "This year")) == ["dashboard", "own", "fixed"]
    assert "Claude" in dashboards.mode_choices(own, date(2026, 1, 1), date(2026, 5, 4))["dashboard"]

    built = {"id": "b1", "chart_type": "bar", "date_column": '"Booking Date"', "title": "Sales", "question": "Sales",
             "plan": {"steps": [step('SELECT 1 WHERE "Booking Date" >= @START AND "Booking Date" < @END')],
                      "combine_sql": ""}}
    mine = dashboards.change_period_mode(built, "own", date(2026, 5, 1), date(2026, 5, 4), "This month",
                                         today=date(2026, 5, 3))
    assert mine["plan"]["steps"][0]["query"].endswith('>= @P1_START AND "Booking Date" < @P1_END')
    assert dashboards.period_text(mine, date(2026, 5, 3)) == "Own period: this month (1–3 May)"
    back = dashboards.change_period_mode(mine, "dashboard", date(2026, 5, 1), date(2026, 5, 4))
    assert back["plan"] == built["plan"] and dashboards.period_mode(back) == "dashboard"
    calendar = dashboards.change_period_mode(built, "fixed", date(2026, 2, 2), date(2026, 2, 9), "")
    assert dashboards.period_text(calendar) == "Fixed: 2–8 Feb 2026"
    assert "own" not in dashboards.mode_choices(built, date(2026, 2, 2), date(2026, 2, 9), "")  # no quick choice


def test_titles_lose_the_questions_periods():
    recs = records(date(2026, 10, 16), YESTERDAY, DAY_BEFORE)
    for title, short in [("Bookings yesterday vs the day before by customer", "Bookings by customer"),
                         ("Requests, bookings and sales for each customer over yesterday and the day before",
                          "Requests, bookings and sales for each customer"),
                         ("Sales on 15 Oct 2026 vs 14 Oct 2026 by customer", "Sales by customer"),
                         ("Sales vs profit by month", "Sales vs profit by month")]:
        assert dashboards._title_without_periods(title, recs) == short


# ---------------------------------------------------------------- grain --

def by_day_chart(measure_sql, x="Day", color="", kind="line"):
    query = f'SELECT "Booking Date" AS "Day", "Agency", {measure_sql} AS "Bookings" FROM bookings GROUP BY 1, 2'
    return {"id": "g1", "chart_type": kind, "x": x, "y": ["Bookings"], "color": color, "date_column": '"Booking Date"',
            "plan": {"steps": [step(query)], "combine_sql": ""}}


def days(n, start=date(2026, 1, 1)):
    when = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({"Day": pd.to_datetime(when), "Agency": ["Desert Pearl Tours"] * n, "Bookings": [1] * n})


def test_long_periods_are_drawn_by_week_or_month_when_the_numbers_add_up(app_dirs):
    counts = by_day_chart("COUNT(*)")
    start = date(2026, 1, 1)
    df, grain = dashboards.display_grain(days(20), counts, start, start + timedelta(days=20))
    assert grain == "" and len(df) == 20  # a month or less: by day
    df, grain = dashboards.display_grain(days(90), counts, start, start + timedelta(days=90))
    assert grain == "week" and df["Bookings"].sum() == 90 and (df["Day"].dt.weekday == 0).all()
    assert len(df) == 14  # Mondays from 29 Dec 2025 to 30 Mar 2026
    as_read = days(90).assign(Day=lambda d: d["Day"].dt.date)  # dates as the local files return them
    assert dashboards.display_grain(as_read, counts, start, start + timedelta(days=90))[1] == "week"
    df, grain = dashboards.display_grain(days(250), counts, start, start + timedelta(days=250))
    assert grain == "month" and len(df) == 9 and df["Bookings"].sum() == 250
    across = by_day_chart("SUM(\"Sales USD\")", x="Agency", color="Day", kind="bar")  # days as colours
    assert dashboards.display_grain(days(90), across, start, start + timedelta(days=90))[1] == "week"
    for not_added in ("AVG(\"Sales USD\")", "COUNT(DISTINCT \"Agency\")", "SUM(\"Sales USD\") / COUNT(*)"):
        assert dashboards.display_grain(days(90), by_day_chart(not_added), start, start + timedelta(days=90))[1] == ""
    monthly = days(200).assign(Day=lambda d: d["Day"].dt.to_period("M").dt.to_timestamp()).drop_duplicates("Day")
    assert dashboards.display_grain(monthly, counts, start, start + timedelta(days=200))[1] == ""  # already by month
    own = {**counts, "period_mode": "own", "periods": records(date(2026, 4, 1), item("last 90 days", point("day", offset=-89), point("day")))}
    assert dashboards.display_grain(days(90), own, start, start + timedelta(days=90))[1] == ""  # its own dates, as asked


def test_the_meaning_layer_says_which_cube_measures_add_up(app_dirs, monkeypatch):
    import semantic
    meaning = {"measures": [
        {"name": "[Bookings]", "aggregation": "sum", "notes": "", "definition": "Bookings made."},
        {"name": "[Average Rate]", "aggregation": "average", "notes": "", "definition": ""},
        {"name": "[Rooms On Hand]", "aggregation": "sum", "notes": "A snapshot per day: never add it up across days.",
         "definition": ""}]}
    monkeypatch.setattr(semantic, "cube", lambda name: meaning if name == "Desert Cube" else None)

    def adds_up(expression, combine="", label="N"):
        query = f"EVALUATE SUMMARIZECOLUMNS('Day'[Date], \"{label}\", {expression})"
        return dashboards.additive({"plan": dax_plan(query, combine).to_dict()}, "N")
    assert adds_up("[Bookings]") and adds_up("CALCULATE([Bookings], 'Client'[Market] = \"UAE\")")
    assert adds_up("COUNTROWS('Bookings')") and adds_up("SUM('Bookings'[Amount])")
    assert not adds_up("[Average Rate]") and not adds_up("[Rooms On Hand]") and not adds_up("[Unknown Measure]")
    assert not adds_up("DIVIDE([Bookings], 7)") and not adds_up("DISTINCTCOUNT('Bookings'[Client])")
    defined = dax_plan("DEFINE MEASURE 'Bookings'[Share] = DIVIDE([Bookings], 3) "
                       "EVALUATE SUMMARIZECOLUMNS('Day'[Date], \"N\", [Share])")
    assert not dashboards.additive({"plan": defined.to_dict()}, "N")
    joined = plans.Plan([plans.Step("bk", "Desert Cube", "EVALUATE SUMMARIZECOLUMNS('Day'[Date], \"Bookings\", [Bookings])"),
                         plans.Step("rt", "Desert Cube", "EVALUATE SUMMARIZECOLUMNS('Day'[Date], \"Rate\", [Average Rate])")],
                        'SELECT bk."Date", bk."Bookings" AS "N", COALESCE(rt."Rate", 0) AS "R" FROM bk LEFT JOIN rt USING ("Date")')
    assert dashboards.additive({"plan": joined.to_dict()}, "N") and not dashboards.additive({"plan": joined.to_dict()}, "R")
    assert not adds_up("[Bookings]", label="Other")  # a column the query doesn't make: unsure, so no


# ---------------------------------------------------------------- the dashboard page --

def test_the_card_names_a_charts_own_period(asked, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import secrets_store
    from conftest import ROOT
    turn, _ = asked
    monkeypatch.setattr(secrets_store, "has_admin_password", lambda: True)
    monkeypatch.setattr(llm, "_create", FakeClaude())
    board = dashboards.list_dashboards()[0]["id"]
    dashboards.add_from_answer(board, turn, "own", as_of={})
    runs = counting_runs(monkeypatch)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert any(c.value.startswith("Own period: yesterday vs the day before (1–2 May)") for c in at.caption)
    assert at.get("plotly_chart") and runs == []  # shown from the chat's numbers


def test_chat_adds_an_answer_to_a_dashboard_at_once(asked, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import secrets_store
    from conftest import ROOT
    turn, _ = asked
    monkeypatch.setattr(secrets_store, "has_admin_password", lambda: True)
    fake = FakeClaude()
    monkeypatch.setattr(llm, "_create", fake)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["admin"] = True
    at.run()
    at.switch_page("views/chat.py").run()
    at.session_state["turns"] = [turn]
    at.run()
    at.button(key="addbtn_0").click().run()
    assert not at.exception
    assert at.radio(key="chat_add_mode_0").options == [
        "Own period: yesterday vs the day before (1–2 May)", "Fixed dates: 1–2 May 2026", "Follow the dashboard's period"]
    assert not any("follows the period picked there" in c.value for c in at.caption)
    runs = counting_runs(monkeypatch)
    at.button(key="addbtn_0").click()  # AppTest reruns the whole page: the dialog is opened again with the click
    at.button(key="chat_add_go_0").click().run()
    assert not at.exception
    assert any("Added **Bookings and sales by agency**" in s.value for s in at.success)
    added = dashboards.list_dashboards()[0]["charts"]
    assert [(c["period_mode"], c["title"]) for c in added] == [("own", "Bookings and sales by agency")]
    assert runs == [] and fake.requests == []  # no query, no Claude


def test_a_chart_asked_for_twice_at_once_runs_once(monkeypatch, tmp_path):
    import threading
    import time
    from datetime import date as d
    import pandas as pd
    runs = []

    def slow_run(chart, start, end, compare=None):
        runs.append(chart["id"])
        time.sleep(0.3)
        return {"df": pd.DataFrame({"x": [1]}), "prev": None, "error": "", "details": ""}
    monkeypatch.setattr(dashboards, "_run_one", slow_run)
    monkeypatch.setattr(dashboards, "_saved_dir", lambda: tmp_path)
    chart = {"id": "c1", "chart_type": "bar", "plan": {"steps": [{"name": "s", "cube": "C", "query": "EVALUATE X"}], "combine_sql": ""}}
    got = []
    visitors = [threading.Thread(target=lambda: got.append(dashboards._run_and_save(chart, d(2026, 1, 1), d(2026, 2, 1), None, {})))
                for _ in range(3)]
    for v in visitors:
        v.start()
    for v in visitors:
        v.join()
    assert runs == ["c1"] and len(got) == 3 and all(g["df"]["x"].iloc[0] == 1 for g in got)
