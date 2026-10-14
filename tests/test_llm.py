import pandas as pd
import pytest

import llm
from fakes import FakeClaude, chart, plan

STEP = {"name": "bookings", "cube": "Bookings", "query": "EVALUATE SUMMARIZECOLUMNS('C'[Code], \"Sales\", [Sales])"}


def ask(fake, monkeypatch, **kwargs):
    monkeypatch.setattr(llm, "_create", fake)
    args = dict(question="Sales by customer", cards="# The data\nCARDS", details=[("Bookings", "BOOKINGS DETAILS")],
                today="2026-10-13", language="DAX", hits='- "UAE": Bookings Market = "UAE" (12)',
                join="", examples=[{"question": "Sales by agency", "understanding": "Sales", "plan": {"steps": []}}])
    args.update(kwargs)
    return llm.question_to_plan(**args)


def test_plan_after_checking_values(monkeypatch):
    fake = FakeClaude([("find_values", {"text": "UAE", "cube": "", "column": ""})], plan([STEP]))
    ran = []
    result = ask(fake, monkeypatch, tools=[{"name": "find_values"}],
                 run_tool=lambda name, args: ran.append((name, args)) or "UAE found")
    assert ran == [("find_values", {"text": "UAE", "cube": "", "column": ""})]
    assert result["steps"] == [STEP] and result["needs_clarification"] is False
    system = fake.system_text()
    assert "CARDS" in system and "Joining cubes" in system and "2026-10-13" in system
    assert "Rules for DAX queries" in system and "TODAY_DATE" not in system and "MAX_ROWS" not in system
    assert fake.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert fake.requests[0]["output_config"]["effort"] == "medium"
    first = fake.requests[0]["messages"][0]["content"]
    assert first[0]["text"].startswith('# Full details of the cube "Bookings"') and first[0]["cache_control"] == {"type": "ephemeral"}
    user = fake.user_text()
    assert "Values of the question found in the data" in user and '"UAE"' in user
    assert "A similar question answered correctly before" in user and "Check the data with your tools" in user
    assert fake.requests[1]["messages"][-1]["content"][0]["content"] == "UAE found"


def test_clarifying_question_has_no_steps(monkeypatch):
    fake = FakeClaude({**plan([STEP]), "needs_clarification": True, "clarifying_question": "Which date?",
                       "options": ["Booking date", "Travel date"]})
    result = ask(fake, monkeypatch)
    assert result["steps"] == [] and result["clarifying_question"] == "Which date?"


def test_reuse_previous_only_with_context(monkeypatch):
    reuse = {**plan([]), "reuse_previous": True, "chart_request": "as a pie"}
    context = [{"question": "Sales by channel", "query": "EVALUATE X"}]
    assert ask(FakeClaude(reuse), monkeypatch, context=context)["reuse_previous"] is True
    # without an earlier answer there is nothing to reuse: Claude is asked again for a plan
    result = ask(FakeClaude(reuse, plan([STEP])), monkeypatch)
    assert result["steps"] == [STEP] and result["reuse_previous"] is False


def test_failed_plan_is_sent_back_with_the_error(monkeypatch):
    fake = FakeClaude(plan([STEP]))
    ask(fake, monkeypatch, failed_plan="EVALUATE BAD", error="Column X not found")
    assert "Your previous plan failed" in fake.user_text() and "Column X not found" in fake.user_text()


def test_queries_must_be_read_only(monkeypatch):
    bad = plan([{**STEP, "query": "DELETE FROM x"}])
    with pytest.raises(ValueError, match="EVALUATE"):
        ask(FakeClaude(bad), monkeypatch)


def test_dashboard_instructions():
    text = llm.dashboard_instructions("DAX", "auto", kpi=True)
    assert "In every step" in text and "@START" in text and "exactly one row" in text
    assert "Do not filter by date" in llm.dashboard_instructions("DAX", "", kpi=False)
    assert "'D'[Date] >= @START" in llm.dashboard_instructions("DAX", "'D'[Date]", kpi=False)


DF = pd.DataFrame({"Month": ["Jan", "Feb", "Mar"], "Sales": [10.0, 20.0, 15.0], "Profit %": [0.1, 0.2, 0.15]})
COMBO = ('{"traces": [{"type": "bar", "x": {"col": "Month"}, "y": {"col": "Sales"}},'
         ' {"type": "scatter", "x": {"col": "Month"}, "y": {"col": "Profit %"}, "yaxis": "y2"}],'
         ' "layout": {"yaxis2": {"overlaying": "y", "side": "right"}}}')


def test_described_chart_becomes_a_custom_spec(monkeypatch):
    fake = FakeClaude(chart("custom", custom_chart=COMBO))
    monkeypatch.setattr(llm, "_create", fake)
    spec = llm.describe_result("Sales and profit %", DF, chart_request="bars for sales, line for profit % on the right")
    assert spec["chart_type"] == "custom" and len(spec["custom"]["traces"]) == 2
    assert spec["chart_request"].startswith("bars for sales")
    assert "Plotly traces" in fake.system_text() and "The user asked for this chart" in fake.user_text()


def test_a_broken_custom_chart_is_retried_then_replaced(monkeypatch):
    broken = chart("custom", custom_chart='{"traces": [{"type": "bar", "x": {"col": "Nope"}}]}')
    fake = FakeClaude(broken, chart("custom", custom_chart=COMBO))
    monkeypatch.setattr(llm, "_create", fake)
    assert llm.describe_result("q", DF, chart_request="combo")["chart_type"] == "custom"
    assert "Column 'Nope' is not in the result" in fake.user_text(1)

    monkeypatch.setattr(llm, "_create", FakeClaude(broken, broken))
    spec = llm.describe_result("q", DF, chart_request="combo")
    assert spec["chart_type"] != "custom" and "couldn't be drawn" in spec["note"]


def test_standard_chart_without_a_request(monkeypatch):
    fake = FakeClaude(chart("line", x="Month", y=["Sales"]))
    monkeypatch.setattr(llm, "_create", fake)
    spec = llm.describe_result("Sales by month", DF)
    assert spec["chart_type"] == "line" and "custom" not in spec
    assert fake.requests[0]["model"] == llm.config.CLAUDE_FAST_MODEL  # a standard chart: the fast model
    assert "Plotly traces" not in fake.system_text()


def test_requests_are_streamed_with_refusal_fallback(monkeypatch):
    sent = {}

    class Stream:
        def __init__(self, kwargs):
            sent.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return "message"

    class Client:
        class beta:
            class messages:
                stream = staticmethod(lambda **kw: Stream(kw))
    monkeypatch.setattr(llm, "_get_client", lambda: Client)
    monkeypatch.setattr(llm, "_fallbacks_ok", True)
    assert llm._create(model="claude-sonnet-5-5", max_tokens=10, messages=[]) == "message"
    assert sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]
