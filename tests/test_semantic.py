"""The meaning layer: shipped files that agree with the cubes, one measure per business term, and the code
rules built on it (no empty cubes, helper columns added, hidden measures refused, admins' decisions win)."""
import json
import re

import pytest

import plans
import semantic

BOOKINGS = "GlobalTravelEngine - Bookings"
ZONE = "GlobalTravelEngine - Statistics Zone"


def test_shipped_files_agree_with_the_cubes():
    if not semantic.FACTS_DIR.exists():
        pytest.skip("cube facts are read on the installation (python semantic.py facts)")
    problems, clashes = semantic.check_all()
    assert {c: p for c, p in problems.items() if p} == {}
    assert clashes == {}  # every business term means exactly one measure


def test_nothing_private_ships():
    text = "\n".join(p.read_text(encoding="utf-8") for p in (semantic.SEMANTIC_DIR / "cubes").glob("*.json"))
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)  # no e-mail addresses
    for path in (semantic.SEMANTIC_DIR / "cubes").glob("*.json"):
        for b in json.loads(path.read_text(encoding="utf-8"))["breakdowns"]:
            assert not b.get("sample_values") or b.get("kind") == "enum", (path.name, b["column"])


def test_business_words_mean_one_measure():
    hits = {h["text"]: h for h in semantic.term_hits("Hotel searches, bookings, sales and cancellations by customer")}
    assert (hits["hotel searches"]["cube"], hits["hotel searches"]["measure"]) == (ZONE, "[Total Requests]")
    assert (hits["bookings"]["cube"], hits["bookings"]["measure"]) == (BOOKINGS, "[Reservations Count]")
    assert hits["sales"]["measure"] == "[Sale]" and hits["cancellations"]["filter"] == "cancelled bookings"
    assert "searches" not in hits  # inside "hotel searches": the longest phrase wins
    assert 'means Searches: measure [Total Requests] of cube "GlobalTravelEngine - Statistics Zone"' in \
        semantic.hits_text([hits["hotel searches"]])


def test_empty_cubes_are_never_picked():
    empty = "GlobalTravelEngine - Statistics History 3"
    assert not semantic.usable(empty) and semantic.usable(BOOKINGS)
    assert "NO DATA" in semantic.card(empty)
    assert "Data: 2014-" in semantic.card(BOOKINGS)
    details = semantic.details_text(BOOKINGS)
    assert "'Calendar'[Date]: Booking date (DEFAULT)" in details and "Never use these measures" in details


def test_helper_columns_are_added_to_grouped_columns():
    needs = {"'Booking Date'[Year]": ["'Booking Date'[Year.UniqueName]"], "'Hotels'[Hotel]": ["'Hotels'[Hotel.Key0]"]}
    query = ("EVALUATE SUMMARIZECOLUMNS('Booking Date'[Year], 'Hotels'[Hotel], "
             "KEEPFILTERS(FILTER(ALL('Booking Date'[Year]), 'Booking Date'[Year] = \"2026\")), \"Sales\", [Sale])")
    fixed = semantic.add_needed_columns(query, needs)
    assert fixed.startswith("EVALUATE SUMMARIZECOLUMNS('Booking Date'[Year], 'Hotels'[Hotel], "
                            "'Booking Date'[Year.UniqueName], 'Hotels'[Hotel.Key0], KEEPFILTERS(")
    assert semantic.add_needed_columns(fixed, needs) == fixed  # already there: unchanged


def test_hidden_measures_are_refused():
    hidden = next(iter(semantic.hidden(BOOKINGS)))
    plan = plans.Plan([plans.Step("result", BOOKINGS, f'EVALUATE ROW("x", {hidden})')])
    with pytest.raises(ValueError, match="must not be used"):
        plans.validate(plan)
    plans.validate(plans.Plan([plans.Step("result", BOOKINGS, 'EVALUATE ROW("x", [Sale])')]))


def test_an_admins_decision_overrides_the_proposed_one():
    item = semantic.decisions(BOOKINGS)[0]
    assert item["status"] == "proposed" and len(semantic.decisions()) > len(semantic.decisions(BOOKINGS))
    semantic.save_decision(item["id"], "Agreed answer")  # what the Agree button on the Glossary page does
    assert json.loads(semantic.overrides_file().read_text(encoding="utf-8"))["decisions"][item["id"]]["by"] == "admin"
    agreed = next(r for r in semantic.decisions(BOOKINGS) if r["id"] == item["id"])
    assert (agreed["status"], agreed["answer"]) == ("agreed", "Agreed answer")
    assert "(agreed)" in semantic.details_text(BOOKINGS)


def test_filters_on_composite_key_columns_get_their_helpers_too(monkeypatch):
    needs = {"'Channels'[Channel]": ["'Channels'[Channel.UniqueName]"]}
    query = ("EVALUATE SUMMARIZECOLUMNS(KEEPFILTERS(TREATAS({\"WEB\", \"XML\"}, 'Channels'[Channel])), "
             "KEEPFILTERS(FILTER(ALL('Channels'[Channel]), 'Channels'[Channel] <> \"B2C\")), \"r\", [Total Requests])")
    fixed = semantic.add_needed_columns(query, needs)
    assert ("FILTER(ALL('Channels'[Channel], 'Channels'[Channel.UniqueName]), 'Channels'[Channel] IN {\"WEB\", \"XML\"})"
            in fixed)  # TREATAS on such a column is rejected by the server; this is the same filter
    assert "FILTER(ALL('Channels'[Channel], 'Channels'[Channel.UniqueName]), 'Channels'[Channel] <> \"B2C\")" in fixed
    assert semantic.add_needed_columns(fixed, needs) == fixed and "ALL('Calendar')" in semantic.add_needed_columns(
        "EVALUATE CALCULATETABLE(ROW(\"x\", 1), ALL('Calendar'))", needs)  # a whole table: as it is
    monkeypatch.setattr(semantic, "needed_columns", lambda cube: needs)
    hint = semantic.composite_key_hint("Zone", "Query (1, 39) Column [Channel] is part of composite key, but not all ...")
    assert "'Channels'[Channel] must always be used together with 'Channels'[Channel.UniqueName]" in hint
    assert semantic.composite_key_hint("Zone", "Some other error") == ""
