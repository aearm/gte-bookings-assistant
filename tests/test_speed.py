"""Steps 0-2 of making answers faster and cheaper: measuring, picking cubes from index cards, value
hits found up front, and remembering answers."""
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

import answer_memory
import answering
import cubes
import data_layer
import llm
import routing
import usage
import value_index
from fakes import FakeClaude, chart, plan
from test_data_layer import build_local_layer

_real_structured_call = llm._structured_call


# ---------------------------------------------------------------- measuring --

def test_usage_records_calls_stages_and_cost(app_dirs):
    response_usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=10_000,
                                     cache_creation_input_tokens=2000,
                                     cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=2000))
    with usage.track("question", "Sales by month", scope="all"):
        with usage.stage("plan"):
            usage.record_call("plan", "claude-sonnet-5-5", response_usage, 3.5)
        usage.note(outcome="data")
    entry = usage.load()[-1]
    # 1000 x $2 + 500 x $10 + 10,000 x $0.20 + 2,000 x $2 x 2 (1-hour cache write), per million
    assert entry["cost"] == pytest.approx((2000 + 5000 + 2000 + 8000) / 1e6)
    assert entry["claude_calls"] == 1 and entry["outcome"] == "data" and "plan" in entry["stages"]
    assert entry["cache_hit"] == pytest.approx(10_000 / 13_000, abs=0.001)


def test_usage_follows_work_into_threads(app_dirs):
    from concurrent.futures import ThreadPoolExecutor
    u = SimpleNamespace(input_tokens=10, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    with usage.track("layer_build"):
        work = usage.in_thread(lambda: usage.record_call("profile", "claude-opus-5-5", u, 1.0))
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda _: work(), range(4)))
    assert usage.load()[-1]["claude_calls"] == 4


# ---------------------------------------------------------------- cards, graph, value hits --

LAYER = {
    "built": "2026-10-14T10:00:00",
    "cubes": {
        "Bookings": {"label": "Bookings", "subject_area": "Sales", "description": "Booking lines. More text.",
                     "grain": "one booking line",
                     "measures": [{"name": "[Final Sales]", "label": "Sales", "synonyms": ["revenue"],
                                   "unit": "currency", "aggregation": "additive", "meaning": ""}],
                     "dates": [{"column": "'Calendar'[Date]", "meaning": "booking made"}],
                     "default_date": "'Calendar'[Date]",
                     "dimensions": [{"table": "Customers", "entity": "customer", "key_column": "'Customers'[Code]",
                                     "name_column": ""}]},
        "Payments": {"label": "Payments", "subject_area": "Payments", "description": "Payments.", "grain": "one payment",
                     "measures": [{"name": "[Payments]", "label": "Payments", "synonyms": [], "unit": "currency",
                                   "aggregation": "additive", "meaning": ""}],
                     "dates": [], "dimensions": [{"table": "Customers", "entity": "customer",
                                                  "key_column": "'Customers'[Code]", "name_column": ""}]},
        "Tickets": {"label": "Tickets", "description": "Tours.", "grain": "one ticket", "measures": [],
                    "dates": [], "dimensions": []},
    },
    "entities": [{"label": "Customer", "join_notes": "upper(trim)", "members": [
        {"cube": "Bookings", "join_column": "'Customers'[Code]", "match": "high"},
        {"cube": "Payments", "join_column": "'Customers'[Code]", "match": "high"}]}],
    "routing": [{"topic": "Sales and profit", "cube": "Bookings", "why": "main"}],
}


@pytest.fixture
def layer3(app_dirs, monkeypatch):
    monkeypatch.setattr(data_layer, "load", lambda: LAYER)
    monkeypatch.setattr(data_layer, "layer_cubes", lambda: ["Bookings", "Payments", "Tickets"])
    routing._cache["key"] = None
    for cube, values in {"Bookings": [["UAE", 120], ["Spain", 80], ["UNITED ARAB EMIRATES", 5]],
                         "Payments": [["UAE", 40]], "Tickets": [["Desert Safari", 9]]}.items():
        value_index.for_cube(cube).save({"'Customers'[Market]": {"group_with": [], "values": values}}, "")
    return LAYER


def test_cards_are_short_and_name_every_cube(layer3):
    cards = routing.cards_text()
    assert all(f'cube "{c}"' in cards for c in ("Bookings", "Payments", "Tickets"))
    assert "Measures: Sales" in cards and "- Sales and profit: Bookings" in cards
    assert "- Customer: Bookings, Payments" in cards
    assert len(cards) < 2500


def test_join_path_between_picked_cubes(layer3):
    path = routing.join_path(["Bookings", "Payments"])
    assert "Bookings 'Customers'[Code] = Payments 'Customers'[Code] (Customer, match: high)" in path
    assert "share no dimension" in routing.join_path(["Bookings", "Tickets"])
    assert routing.join_path(["Bookings"]) == ""


def test_value_hits_find_exact_values_and_initials(layer3, monkeypatch):
    monkeypatch.setattr(data_layer, "is_measure_word", lambda phrase: phrase.lower() in ("sales", "bookings"))
    hits = routing.value_hits("Sales in the UAE market and desert safari bookings", ["Bookings", "Payments", "Tickets"])
    found = {(h["cube"], h["value"]) for h in hits}
    assert {("Bookings", "UAE"), ("Payments", "UAE"), ("Tickets", "Desert Safari")} <= found
    assert not any(h["text"].lower() == "sales" for h in hits)
    assert value_index.for_cube("Bookings").exact("uae")[0]["value"] == "UAE"
    text = routing.hits_text(hits, ["Bookings"])
    assert '"UAE": Bookings' in text and "Payments" not in text


def test_pick_asks_haiku_with_the_cards(layer3, monkeypatch):
    seen = {}

    def fake(system, tool, user, **kwargs):
        seen.update(system=system[0]["text"], user=user, **kwargs)
        return {"cubes": ["Bookings", "Payments", "Nowhere"], "reason": "sales and payments"}
    monkeypatch.setattr(llm, "_structured_call", fake)
    picked = routing.pick("Sales and payments by customer", ["Bookings", "Payments", "Tickets"],
                          context=[{"question": "Sales by month", "cubes": ["Bookings"]}])
    assert picked.cubes == ["Bookings", "Payments"]  # made-up names are dropped
    assert seen["model"] == llm.config.CLAUDE_FAST_MODEL and seen["effort"] == "low"
    assert 'cube "Tickets"' in seen["system"] and "answered from: Bookings" in seen["user"]


# ---------------------------------------------------------------- remembering answers --

def test_same_question_today_reruns_its_plan_without_claude(app_dirs, monkeypatch):
    build_local_layer(monkeypatch)
    monkeypatch.setattr(llm, "_structured_call", _real_structured_call)
    query = 'SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings GROUP BY 1 ORDER BY 2 DESC'
    fake = FakeClaude(plan([{"name": "result", "cube": cubes.LOCAL, "query": query}]),
                      chart("horizontal_bar", x="Agency", y=["Sales"], summary="Coral Bay leads."))
    monkeypatch.setattr(llm, "_create", fake)
    first = answering.ask("Sales by agency")
    assert first.kind == "data" and first.answer_id and len(fake.requests) == 2
    again = answering.ask("sales by agency?")  # same question, other capitals and punctuation
    assert len(fake.requests) == 2  # no Claude call at all
    assert again.answer_id == first.answer_id and again.spec["summary"] == "Coral Bay leads."
    assert again.df.equals(first.df)
    entries = usage.load(kind="question")
    assert entries[-1]["memory"] == "same_day" and entries[-1]["claude_calls"] == 0


def test_verified_answers_become_examples(app_dirs, monkeypatch):
    monkeypatch.setattr(answer_memory, "_layer_key", lambda: "layer-1")
    df = pd.DataFrame({"x": [1]})
    a = answer_memory.remember("Top 10 customers by sales this year", "", {"steps": []}, {"understanding": "Top 10"},
                               {}, df)
    answer_memory.remember("Bookings by channel", "", {"steps": []}, {}, {}, df)
    assert answer_memory.examples("Top 10 customers by sales last year", "") == []  # not verified yet
    answer_memory.verify(a)
    found = answer_memory.examples("Top 10 customers by sales last year", "")
    assert [e["question"] for e in found] == ["Top 10 customers by sales this year"]
    assert answer_memory.examples("Hotel allotment usage", "") == []
    assert answer_memory.same_day("top 10 customers by SALES this year", "")["id"] == a
    assert answer_memory.same_day("Top 10 customers by sales this year", "Bookings") is None  # another scope
    monkeypatch.setattr(answer_memory, "date", SimpleNamespace(today=lambda: date(2030, 1, 1)))
    assert answer_memory.same_day("Top 10 customers by sales this year", "") is None  # another day


def test_short_cube_labels_are_matched_to_exact_names(layer3, monkeypatch):
    """Haiku sometimes answers "Bookings" for "GlobalTravelEngine - Bookings": that used to be dropped."""
    names = ["GlobalTravelEngine - Bookings", "GlobalTravelEngine - Booking Payments"]
    assert routing._exact("Bookings", names) == names[0]
    assert routing._exact("booking payments", names) == names[1]
    assert routing._exact("Tickets", names) is None
    assert routing._route_tool(names)["input_schema"]["properties"]["cubes"]["items"]["enum"] == names
