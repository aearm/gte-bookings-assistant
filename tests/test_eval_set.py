"""The test-set runner's checks: an answer passes only when its numbers match the references and its
chart is drawn the way the question asked."""
import pandas as pd

import eval_set

ANSWER = pd.DataFrame({"Customer": ["A", "B", "C"], "Sales": [300.0, 200.0, 100.0], "Bookings": [3, 2, 1],
                       "Month": ["2026-07", "2026-08", "2026-09"]})


def test_reference_queries():
    check = {"cube": "c", "measure": "[Sale]", "date": "'Calendar'[Date]", "from": "2026-09-01", "to": "2026-09-30",
             "kind": "total"}
    query = eval_set.reference_query(check)
    assert query.startswith("EVALUATE SUMMARIZECOLUMNS(KEEPFILTERS(FILTER(ALL('Calendar'[Date])")
    assert "DATE(2026,9,1)" in query and "DATE(2026,9,30)" in query and '"v", [Sale]' in query


def test_numbers_must_match_the_references():
    total = {"kind": "total"}
    assert eval_set.check_data(ANSWER, total, 600.0)["ok"]                      # a column adds up to it
    assert eval_set.check_data(ANSWER, total, 600.4)["ok"]                      # within a tenth of a percent
    assert not eval_set.check_data(ANSWER, total, 601.0)["ok"]                  # half a percent off is another number
    missed = eval_set.check_data(ANSWER, total, 650.0)
    assert not missed["ok"] and missed["column"] == "Sales" and missed["found"] == 600.0  # the closest it came
    top = {"kind": "top", "n": 3}
    assert eval_set.check_data(ANSWER, top, [300.0, 200.0, 100.0, 50.0, 10.0])["ok"]
    assert not eval_set.check_data(ANSWER, top, [900.0, 800.0, 700.0])["ok"]
    assert not eval_set.check_data(None, total, 1.0)["ok"]


def test_charts_must_be_drawn_as_asked():
    months = ANSWER[["Month", "Sales", "Bookings"]]
    line = {"chart_type": "line", "x": "Month", "y": ["Sales", "Bookings"]}
    assert eval_set.check_chart(months, line, {"types": ["line"], "measures": 2})["ok"]
    two_panels = eval_set.check_chart(months, line, {"types": ["line"], "measures": 2, "layout": "panels"})
    assert two_panels["ok"]  # sales in hundreds, bookings in ones: one panel each
    dropped = eval_set.check_chart(months, {**line, "y": ["Sales"]}, {"types": ["line"], "measures": 2})
    assert not dropped["ok"] and "1 of 2 measures" in dropped["why"]
    wrong = eval_set.check_chart(months, {**line, "chart_type": "bar"}, {"types": ["line"], "measures": 1})
    assert not wrong["ok"] and "bar instead of line" in wrong["why"]
    table = {"chart_type": "table", "x": "", "y": []}
    assert eval_set.check_chart(ANSWER, table, {"types": ["table"]})["ok"]


def test_rates_are_ranges_and_changes_need_more_than_luck():
    low, high = eval_set.wilson(17, 21)
    assert 0.59 < low < 0.61 and 0.92 < high < 0.94  # 81% on 21 questions could really be anything from 60% to 93%
    assert eval_set.wilson(0, 0) == (0.0, 0.0)
    assert eval_set.sign_test(3, 0) == 0.25  # 3 questions better, none worse: a 1 in 4 chance by luck alone
    assert eval_set.sign_test(10, 1) < 0.05 and eval_set.sign_test(0, 0) == 1.0


def test_the_report_shows_trials_stages_and_groups():
    def r(qid, ok, stage="", tags=()):
        return {"id": qid, "pass": ok, "stage": stage, "tags": list(tags), "cubes_expected": ["a"], "error": "",
                "asked": "", "chart": {"ok": ok, "why": "" if ok else "bar instead of line"}, "cost": 0.1,
                "seconds": 10}
    data = {"label": "x", "model": "m", "time": "t", "repeat": 2, "version": {"git": "abc"},
            "results": [r("Q01", True), r("Q01", False, "chart"), r("Q02", True, tags=["paraphrase"]),
                        r("Q02", True, tags=["paraphrase"])]}
    text = eval_set.report(data)
    assert "| Q01 | 1 |  | 1/2 | chart (bar instead of line) |" in text
    assert "Passed 3/4 (75%" in text and "1 of 2 questions passed every trial" in text
    assert "Where they went wrong: chart 1" in text and "paraphrase 2/2" in text


def test_where_a_trial_went_wrong():
    base = {"pass": False, "expect": "data", "outcome": "data", "error": "", "cubes_ok": True, "data_ok": True}
    assert eval_set._stage({**base, "cubes_ok": False}) == "cubes"
    assert eval_set._stage({**base, "data_ok": False}) == "numbers"
    assert eval_set._stage(base) == "chart"
    assert eval_set._stage({**base, "outcome": "error", "error": "StepError: Step x failed"}) == "query"
    assert eval_set._stage({**base, "outcome": "clarify"}) == "asked instead of answering"
    assert eval_set._stage({**base, "expect": "clarify"}) == "answered instead of asking"


def test_relative_periods_are_worked_out_when_the_test_runs():
    first, last = eval_set.check_dates({"period": "Last month"})
    assert first.endswith("-01") and first < last
    assert eval_set.check_dates({"from": "2026-07-01", "to": "2026-09-30"}) == ("2026-07-01", "2026-09-30")
