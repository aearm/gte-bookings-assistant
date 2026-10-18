"""The API (server/) end to end in local mode: sessions and the CSRF guard, chat streams (data,
clarifying questions, errors, follow-ups, redraws), dashboards (changes, results for a period, chat
answers added at once), periods, glossary and decisions, jobs, settings, usage and the cube worker
pool. Claude is scripted (tests/fakes.py): the real Claude API is never called."""
import json
import os
import pickle
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

import keyring
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import config
import cubes
import dashboards
import data_layer
import llm
import periods
import plans
import rewrite
import secrets_store
import semantic
import updates
import usage
from fakes import FakeClaude, chart, plan
from server import background, conversations, convert, jobs, pool
from server.main import app
from server.routes import dashboards as dashboard_routes
from server.routes import settings as settings_routes
from test_answering import layer, step  # noqa: F401 (fixture)
from test_chart_periods import BY_AGENCY_AND_DAY, DAY_BEFORE, ONE_CHART, YESTERDAY, FixedDay

APP_HEADER = {"X-Requested-With": "bookings-assistant"}
PASSWORD = "correct horse battery"
BY_AGENCY = 'SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings GROUP BY 1 ORDER BY 2 DESC'
DATED_BY_AGENCY = ('SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings '
                   'WHERE "Booking Date" >= @START AND "Booking Date" < @END GROUP BY 1 ORDER BY 2 DESC')
COUNT = 'SELECT COUNT(*) AS "Bookings" FROM bookings WHERE "Booking Date" >= @START AND "Booking Date" < @END'


@pytest.fixture
def vault(monkeypatch):
    """Windows Credential Manager replaced by a dict (the API key, server passwords, the admin hash)."""
    store = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: store.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: store.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: store.pop((service, name), None))
    return store


@pytest.fixture
def api(layer, vault, monkeypatch, tmp_path):  # noqa: F811
    """A client of the app (the browser), in local mode with the data layer built. No start-up work
    (worker processes, warm-up, nightly runs): those are tested on their own below."""
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    conversations.clear()
    jobs.clear()
    dashboard_routes._as_of.clear()
    settings_routes._latest.update(time=0.0, release=None, error="")
    return TestClient(app, headers=APP_HEADER)


def rows_of(result: dict) -> list:
    """A dashboard result's rows: in its chart (dataset) when it is drawn, else in its table."""
    option = (result.get("chart") or {}).get("option")
    return option["dataset"][0]["source"] if option else result["table"]["rows"]


def sign_in(client, keep=True):
    if not secrets_store.has_admin_password():
        secrets_store.set_admin_password(PASSWORD)
    r = client.post("/api/session", json={"password": PASSWORD, "keep": keep})
    assert r.status_code == 200, r.text
    return r


def events(response) -> list[tuple[str, dict]]:
    """The Server-Sent Events of a response: [(event, data)]."""
    out = []
    for block in response.text.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if name:
            out.append((name, data))
    return out


def new_conversation(client, scope="") -> str:
    r = client.post("/api/conversations", json={"scope": scope})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def ask(client, cid, question, clarification=None):
    body = {"question": question, **({"clarification": clarification} if clarification else {})}
    return events(client.post(f"/api/conversations/{cid}/ask", json=body))


def counting_runs(monkeypatch) -> list:
    runs, real_run = [], plans.run
    monkeypatch.setattr(plans, "run", lambda p, *a, **k: runs.append(p) or real_run(p, *a, **k))
    return runs


@pytest.fixture
def by_agency(api, monkeypatch):
    """A conversation with one answer, "Sales by agency" (no dates): (conversation id, turn)."""
    fake = FakeClaude(plan([step(BY_AGENCY)]), chart("horizontal_bar", x="Agency", y=["Sales"], summary="Lotus leads."))
    monkeypatch.setattr(llm, "_create", fake)
    cid = new_conversation(api)
    got = ask(api, cid, "Sales by agency")
    return cid, dict(got)["done"]["turn"]


@pytest.fixture
def yesterday(api, monkeypatch):
    """A conversation with an answer to "yesterday vs the day before", asked on 3 May 2026."""
    monkeypatch.setattr(rewrite, "date", FixedDay)
    monkeypatch.setattr(dashboards, "_today", lambda: date(2026, 5, 3))
    fake = FakeClaude(plan([step(BY_AGENCY_AND_DAY)]), ONE_CHART,
                      rewrite={"standalone_question": "Bookings and sales by agency yesterday vs the day before",
                               "chart_request": "one chart", "kind": "new", "periods": [YESTERDAY, DAY_BEFORE]})
    monkeypatch.setattr(llm, "_create", fake)
    cid = new_conversation(api)
    got = ask(api, cid, "bookings and sales by agency yesterday vs the day before, in one chart")
    return cid, dict(got)["done"]["turn"]


# ---------------------------------------------------------------- session, CSRF, admin --

def test_signing_in_sets_a_strict_http_only_cookie(api):
    assert api.get("/api/session").json() == {"admin": False, "has_admin_password": False}
    assert api.post("/api/session", json={"password": PASSWORD}).status_code == 409  # none created yet
    assert api.post("/api/session/first-password", json={"password": "short"}).status_code == 400
    r = api.post("/api/session/first-password", json={"password": PASSWORD})
    assert r.json() == {"admin": True, "has_admin_password": True}
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("ba_session=") and "httponly" in cookie and "samesite=strict" in cookie
    assert api.post("/api/session/first-password", json={"password": PASSWORD}).status_code == 409
    assert api.delete("/api/session").json()["admin"] is False
    assert api.get("/api/session").json()["admin"] is False

    began = time.perf_counter()
    r = api.post("/api/session", json={"password": "not it at all", "keep": True})
    assert r.status_code == 401 and "isn't right" in r.json()["detail"] and time.perf_counter() - began >= 1
    kept = sign_in(api, keep=True).headers["set-cookie"].lower()
    assert "max-age=2592000" in kept  # 30 days
    session_only = sign_in(api, keep=False).headers["set-cookie"].lower()
    assert "max-age" not in session_only and "expires" not in session_only  # ends with the browser session
    assert api.get("/api/session").json()["admin"] is True
    assert TestClient(app).get("/api/session").json()["admin"] is False  # another browser: not signed in


def test_writes_need_the_apps_header(api):
    plain_browser = TestClient(app)  # e.g. a form on another site
    r = plain_browser.post("/api/session", json={"password": PASSWORD})
    assert r.status_code == 403 and "didn't come from the app" in r.json()["detail"]
    assert plain_browser.get("/api/session").status_code == 200  # reading needs no header


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/dashboards", {"name": "X"}),
    ("put", "/api/glossary/Local files", {"rows": []}),
    ("post", "/api/decisions/any", {"answer": "x"}),
    ("post", "/api/answers/1/verify", {"verified": True}),
    ("get", "/api/cubes", None),
    ("post", "/api/layer/build", {}),
    ("get", "/api/jobs/any", None),
    ("put", "/api/settings/api-key", {"key": "sk-ant-x"}),
    ("get", "/api/updates", None),
    ("get", "/api/usage", None),
])
def test_admin_pages_are_locked_when_signed_out(api, method, path, body):
    r = api.request(method.upper(), path, **({"json": body} if body is not None else {}))
    assert r.status_code == 401 and r.json() == {"detail": "Sign in as admin to do this."}


def test_errors_are_plain_english_with_technical_details(api, monkeypatch):
    r = api.get("/api/dashboards/nope")
    assert r.status_code == 404 and "wasn't found" in r.json()["detail"]
    sign_in(api)
    r = api.post("/api/dashboards", json={})
    assert r.status_code == 422 and "isn't valid" in r.json()["detail"] and "name" in r.json()["details"]
    monkeypatch.setattr(dashboards, "list_dashboards", lambda: (_ for _ in ()).throw(RuntimeError("The disk is full.")))
    r = TestClient(app, raise_server_exceptions=False).get("/api/dashboards")
    assert r.status_code == 500 and r.json() == {"detail": "The disk is full.", "details": "RuntimeError: The disk is full."}


# ---------------------------------------------------------------- app --

def test_info_and_health(api):
    info = api.get("/api/info").json()
    assert info["version"] == updates.current_version()
    assert info["data_source"] == "local" and info["ready"] is True and info["why"] == ""
    assert info["scopes"] == [{"value": "", "label": "All data"}, {"value": cubes.LOCAL, "label": data_layer.cube_label(cubes.LOCAL)}]
    assert info["example_questions"] == ["Sales by account manager"]
    assert info["defaults"] == {"preset": "Last 7 days", "compare": "previous"}
    assert {"value": "kpi", "label": "Headline number"} in info["chart_types"]
    health = api.get("/api/health").json()
    assert health["ok"] is True and health["workers"]["mode"] == "in-process" and health["data_source"] == "local"


def test_periods_default_to_the_last_7_days_against_the_7_days_before(api):
    body = api.get("/api/periods").json()
    today = date.today()
    assert body["period"] == {"start": str(today - timedelta(days=6)), "end": str(today + timedelta(days=1)),
                              "label": periods.label(today - timedelta(days=6), today + timedelta(days=1), "Last 7 days"),
                              "preset": "Last 7 days"}
    assert (body["compare"]["mode"], body["compare"]["start"], body["compare"]["end"]) == (
        "previous", str(today - timedelta(days=13)), str(today - timedelta(days=6)))
    assert body["compare"]["name"] == "the 7 days before"
    assert [p["name"] for p in body["presets"]] == periods.PRESETS
    assert [m["mode"] for m in body["compare_modes"]] == ["none", "previous", "last_year", "custom"]
    march = api.get("/api/periods", params={"start": "2026-03-01", "end": "2026-04-01", "compare": "none"}).json()
    assert march["period"]["label"].startswith("1 Mar – 31 Mar 2026") and march["compare"] is None
    other = api.get("/api/periods", params={"preset": "This month", "compare": "custom", "cstart": "2025-01-01",
                                            "cend": "2025-01-08"}).json()
    assert other["period"]["preset"] == "This month" and other["compare"]["label"] == "1 Jan – 7 Jan 2025"


# ---------------------------------------------------------------- chat --

def test_a_question_streams_progress_then_data_chart_and_the_answer(api, monkeypatch):
    fake = FakeClaude(plan([step(BY_AGENCY)]), chart("horizontal_bar", x="Agency", y=["Sales"], summary="Lotus leads."))
    monkeypatch.setattr(llm, "_create", fake)
    cid = new_conversation(api)
    r = api.post(f"/api/conversations/{cid}/ask", json={"question": "Sales by agency"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = events(r)
    names = [n for n, _ in got]
    assert names[0] == "step" and names[-1] == "done"
    assert names.index("data") < names.index("chart") < names.index("done") and "error" not in names
    assert "Pulling the data" in [d["text"] for n, d in got if n == "step"]
    table = dict(got)["data"]["table"]
    assert [(c["name"], c["type"]) for c in table["columns"]] == [("Agency", "text"), ("Sales", "number")]
    assert table["rows"][0] == ["Lotus Travel House", 710.0] and table["row_count"] == 4 and not table["truncated"]
    drawn = dict(got)["chart"]["chart"]
    assert drawn["kind"] == "horizontal_bar" and drawn["option"]["series"] and drawn["summary"] == "Lotus leads."
    turn = dict(got)["done"]["turn"]
    assert turn["question"] == "Sales by agency" and turn["query"] == BY_AGENCY and turn["cubes"] == [cubes.LOCAL]
    assert turn["language"] == "SQL" and isinstance(turn["answer_id"], int) and turn["error"] is None
    assert [(m["mode"], m["instant"]) for m in turn["dashboard_modes"]] == [("dashboard", False), ("fixed", True)]
    saved = api.get(f"/api/conversations/{cid}").json()
    assert saved["scope"] == "" and [t["id"] for t in saved["turns"]] == [turn["id"]]
    assert saved["turns"][0]["table"] == table
    latest = api.get("/api/history").json()[0]
    assert (latest["question"], latest["rows"], latest["title"]) == ("Sales by agency", 4, "Title")


def test_a_question_being_answered_shows_in_the_conversation_until_its_answer_is_there(api, monkeypatch):
    """A page opened while a question is answered (a reload, another tab) sees the question and its
    progress, then the answer."""
    from server.routes import chat as chat_routes
    monkeypatch.setattr(llm, "_create", FakeClaude(plan([step(BY_AGENCY)]), chart("table")))
    real, started, release = chat_routes.answer, threading.Event(), threading.Event()

    def slow(conv, question, context, clarification, shown_as, emit):
        emit("step", {"text": "Thinking it over"})
        started.set()
        release.wait(10)
        return real(conv, question, context, clarification, shown_as, emit)
    monkeypatch.setattr(chat_routes, "answer", slow)
    cid = new_conversation(api)
    streamed = []
    asking = threading.Thread(target=lambda: streamed.extend(ask(api, cid, "Sales by agency")))
    asking.start()
    try:
        assert started.wait(10)
        meanwhile = api.get(f"/api/conversations/{cid}").json()
        assert meanwhile["turns"] == []
        assert meanwhile["pending"] == {"question": "Sales by agency", "steps": ["Thinking it over"]}
    finally:
        release.set()
        asking.join(30)
    after = api.get(f"/api/conversations/{cid}").json()
    assert after["pending"] is None and [t["question"] for t in after["turns"]] == ["Sales by agency"]
    assert dict(streamed)["done"]["turn"]["id"] == after["turns"][0]["id"]


def test_a_clarifying_question_and_its_answer(api, monkeypatch):
    ask_back = {**plan([]), "needs_clarification": True, "clarifying_question": "Which date?",
                "options": ["Booking date", "Travel date"]}
    march = 'SELECT COUNT(*) AS "Bookings" FROM bookings WHERE strftime("Booking Date", \'%m\') = \'03\''
    fake = FakeClaude(ask_back, plan([step(march)]), chart("table"))
    monkeypatch.setattr(llm, "_create", fake)
    cid = new_conversation(api)
    got = ask(api, cid, "Bookings in March")
    assert [n for n, _ in got if n != "step"] == ["clarify", "done"]
    assert dict(got)["clarify"] == {"question": "Which date?", "options": ["Booking date", "Travel date"]}
    assert dict(got)["done"]["turn"]["clarify"]["answered"] is False
    got = ask(api, cid, "Bookings in March", clarification={"question": "Which date?", "answer": "Booking date"})
    turn = dict(got)["done"]["turn"]
    assert turn["question"] == "Bookings in March → Booking date" and turn["table"]["rows"] == [[3]]
    assert "The user answered: Booking date" in fake.rewrites[1]["messages"][0]["content"]
    first = api.get(f"/api/conversations/{cid}").json()["turns"][0]
    assert first["clarify"]["answered"] is True


def test_a_failing_question_ends_with_an_error_event(api, monkeypatch):
    broken = plan([step('SELECT "Nope" FROM bookings')])
    monkeypatch.setattr(llm, "_create", FakeClaude(broken, broken))
    cid = new_conversation(api)
    got = ask(api, cid, "Something odd")
    assert [n for n, _ in got][-1] == "error" and "done" not in dict(got)
    error = dict(got)["error"]
    assert error["message"].startswith("Claude couldn't write a query") and "Nope" in error["details"]
    assert api.get(f"/api/conversations/{cid}").json()["turns"][0]["error"] == error["message"]
    assert dict(ask(api, cid, "  "))["error"]["message"] == "Type a question first."
    assert api.post("/api/conversations/missing/ask", json={"question": "x"}).status_code == 404
    assert api.post("/api/conversations", json={"scope": "Not a cube"}).status_code == 400


def test_follow_ups_build_on_the_conversation(api, by_agency, monkeypatch):
    cid, first = by_agency

    def rewrite_reply(request):
        if "Message: as a donut" in request["messages"][0]["content"]:
            return {"standalone_question": "Sales by agency", "chart_request": "as a donut", "kind": "chart_only",
                    "periods": []}
        return None
    fake = FakeClaude(chart("donut", x="Agency", y=["Sales"]), rewrite=rewrite_reply)
    monkeypatch.setattr(llm, "_create", fake)
    runs = counting_runs(monkeypatch)
    got = ask(api, cid, "as a donut")
    turn = dict(got)["done"]["turn"]
    assert "Earlier question: Sales by agency" in fake.rewrites[0]["messages"][0]["content"]  # the context
    assert [r["purpose"] for r in fake.requests] == ["chart"] and runs == []  # same numbers: no plan, no query
    assert turn["query"] == first["query"] and turn["chart"]["kind"] == "donut"
    assert turn["table"]["rows"] == first["table"]["rows"]


def test_changing_the_chart_redraws_without_a_query(api, by_agency, monkeypatch):
    cid, turn = by_agency
    fake = FakeClaude(chart("donut", x="Agency", y=["Sales"], summary="ignored"))
    monkeypatch.setattr(llm, "_create", fake)
    runs = counting_runs(monkeypatch)
    r = api.post(f"/api/conversations/{cid}/turns/{turn['id']}/chart", json={"request": "as a donut"})
    assert r.status_code == 200 and r.json()["chart"]["kind"] == "donut"
    assert r.json()["chart"]["summary"] == "Lotus leads."  # the written answer stays
    assert len(fake.requests) == 1 and "as a donut" in fake.user_text(0) and runs == []
    again = api.get(f"/api/conversations/{cid}").json()["turns"][0]
    assert again["chart"]["kind"] == "donut"
    csv = api.get(f"/api/conversations/{cid}/turns/{turn['id']}/csv")
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0] == "Agency,Sales"
    assert "attachment" in csv.headers["content-disposition"]


def test_marking_an_answer_correct(api, by_agency):
    cid, turn = by_agency
    sign_in(api)
    assert api.post(f"/api/answers/{turn['answer_id']}/verify", json={"verified": True}).json() == {"ok": True}
    assert api.get(f"/api/conversations/{cid}").json()["turns"][0]["verified"] is True


# ---------------------------------------------------------------- dashboards --

def test_dashboards_are_created_renamed_and_deleted_by_admins(api):
    sign_in(api)
    board = api.post("/api/dashboards", json={"name": "Sales"}).json()
    assert board["name"] == "Sales" and board["charts"] == []
    assert {"id": board["id"], "name": "Sales", "charts": 0} in api.get("/api/dashboards").json()
    assert api.patch(f"/api/dashboards/{board['id']}", json={"name": "Revenue"}).json()["name"] == "Revenue"
    assert api.get(f"/api/dashboards/{board['id']}").json()["name"] == "Revenue"
    assert api.delete(f"/api/dashboards/{board['id']}").json() == {"ok": True}
    assert api.get(f"/api/dashboards/{board['id']}").status_code == 404


def test_an_answer_goes_on_a_dashboard_at_once_and_keeps_its_own_period(api, yesterday, monkeypatch):
    cid, turn = yesterday
    assert [(m["mode"], m["instant"]) for m in turn["dashboard_modes"]] == [("own", True), ("fixed", True), ("dashboard", False)]
    sign_in(api)
    board = api.post("/api/dashboards", json={"name": "Desk"}).json()["id"]
    fake = FakeClaude()  # any call to Claude fails the test
    monkeypatch.setattr(llm, "_create", fake)
    runs = counting_runs(monkeypatch)
    began = time.perf_counter()
    r = api.post(f"/api/dashboards/{board}/charts/from-answer",
                 json={"conversation_id": cid, "turn_id": turn["id"], "period_mode": "own"})
    assert r.status_code == 200, r.text
    assert time.perf_counter() - began < 1
    meta = r.json()
    assert fake.requests == [] and fake.rewrites == [] and runs == []  # no Claude, no query
    assert meta["period"] == {"mode": "own", "label": "Own period: yesterday vs the day before (1–2 May)"}
    assert meta["title"] == "Bookings and sales by agency" and meta["chart_type"] == "bar" and not meta["compares"]
    # its own dates whatever the dashboard's period and comparison: the chat's numbers, nothing run
    for params in ({}, {"preset": "This year", "compare": "last_year"}, {"start": "2026-01-01", "end": "2026-02-01"}):
        res = api.get(f"/api/dashboards/{board}/results", params=params).json()
        mine = res["charts"][meta["id"]]
        assert mine["error"] is None and rows_of(mine) == turn["table"]["rows"] and mine["prev_table"] is None
        assert mine["chart"]["kind"] == "bar" and mine["chart"]["option"] is not None
        assert mine["period_label"] == "Own period: yesterday vs the day before (1–2 May)"
    assert runs == [] and fake.requests == []
    wrong = api.post(f"/api/dashboards/{board}/charts/from-answer",
                     json={"conversation_id": cid, "turn_id": "nope", "period_mode": "own"})
    assert wrong.status_code == 404


def test_a_dashboard_from_a_whole_conversation(api, yesterday, monkeypatch):
    cid, first = yesterday
    monkeypatch.setattr(llm, "_create", FakeClaude(plan([step(BY_AGENCY)]), chart("horizontal_bar", x="Agency", y=["Sales"])))
    second = dict(ask(api, cid, "Sales by agency"))["done"]["turn"]
    sign_in(api)
    fake = FakeClaude(plan([step(DATED_BY_AGENCY)]))  # only the answer without dates needs a new plan
    monkeypatch.setattr(llm, "_create", fake)
    r = api.post("/api/dashboards/from-conversation", json={"conversation_id": cid, "name": "From chat"})
    assert r.status_code == 200, r.text
    board = r.json()
    assert board["name"] == "From chat" and board["failed"] == []
    assert [(c["title"], c["period"]["mode"]) for c in board["charts"]] == [
        ("Bookings and sales by agency", "own"), ("Title", "dashboard")]
    assert [q["purpose"] for q in fake.requests] == ["plan"] and fake.rewrites == []
    assert "@START" in board["charts"][1]["query"] and second["query"] == BY_AGENCY
    res = api.get(f"/api/dashboards/{board['id']}/results", params={"start": "2026-03-01", "end": "2026-06-01",
                                                                     "compare": "none"}).json()
    follows = res["charts"][board["charts"][1]["id"]]
    assert follows["error"] is None and sum(row[1] for row in rows_of(follows)) == 1200.5  # Mar-May sales


def test_results_follow_the_period_with_comparison_and_headline_numbers(api):
    kpi = {"id": "k1", "cube": cubes.LOCAL, "title": "Bookings", "question": "Bookings", "chart_type": "kpi",
           "date_column": '"Booking Date"', "plan": {"steps": [step(COUNT)], "combine_sql": ""}}
    by_country = {"id": "c1", "cube": cubes.LOCAL, "title": "Bookings by country", "question": "Bookings by country",
                  "chart_type": "bar", "x": "Destination Country", "y": ["Bookings"], "color": "",
                  "date_column": '"Booking Date"',
                  "plan": {"steps": [step(COUNT.replace('COUNT(*) AS "Bookings"', '"Destination Country", COUNT(*) AS "Bookings"')
                                          + " GROUP BY 1 ORDER BY 2 DESC")], "combine_sql": ""}}
    board = dashboards.create_dashboard("Overview")
    dashboards.add_chart(board, kpi)
    dashboards.add_chart(board, by_country)
    r = api.get(f"/api/dashboards/{board}/results", params={"start": "2026-03-01", "end": "2026-06-01", "compare": "custom",
                                                             "cstart": "2026-01-01", "cend": "2026-03-01"})
    assert r.headers["content-encoding"] == "gzip"  # results travel zipped
    res = r.json()
    assert res["period"] == {"start": "2026-03-01", "end": "2026-06-01", "preset": "",
                             "label": periods.label(date(2026, 3, 1), date(2026, 6, 1))}
    assert res["compare"]["label"] == "1 Jan – 28 Feb 2026" and res["updating"] is False
    headline = res["charts"]["k1"]["kpi"]
    assert (headline["value"], headline["text"], headline["change"]) == (8, "8", 1.0)  # 8 bookings vs 4
    assert headline["change_text"] == "+100.0% vs 1 Jan – 28 Feb 2026" and headline["prev_text"] == "4"
    assert res["charts"]["k1"]["chart"]["kind"] == "kpi"
    bars = res["charts"]["c1"]
    assert bars["chart"]["kind"] == "bar" and bars["chart"]["option"]["x-app"]["compare"] is not None
    assert sum(r[1] for r in rows_of(bars)) == 8 and bars["table"] is None  # the rows travel once, in the chart
    assert bars["chart"]["option"]["x-app"]["compare"] is not None  # with the comparison in grey
    default = api.get(f"/api/dashboards/{board}/results").json()  # the last 7 days vs the 7 days before
    assert default["period"]["preset"] == "Last 7 days" and default["compare"]["mode"] == "previous"
    assert default["charts"]["k1"]["kpi"]["value"] == 0
    empty = default["charts"]["c1"]
    assert empty["chart"]["kind"] == "table" and empty["chart"]["note"] == "No data for this period."


def test_a_dashboard_filter_lists_its_values_and_its_charts_follow_the_one_picked(api, monkeypatch):
    """A client (here: agency) dashboard: the agencies with bookings in the last year, biggest first; each
    chart's numbers are the picked agency's, the first agency's when none is picked."""
    dashboards._options_cache.clear()
    board = dashboards.create_dashboard("Agency")

    def put_filter(data):
        for d in data["dashboards"]:
            if d["id"] == board:
                d["filters"] = [{"key": "agency", "label": "Agency", "placeholder": "@F_AGENCY", "options": {
                    "cube": cubes.LOCAL, "value": "Agency", "label": "{Agency}",
                    "query": 'SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings WHERE "Booking Date" >= @START '
                             'AND "Booking Date" < @END GROUP BY 1 ORDER BY 2 DESC'}}]
    dashboards._change(put_filter)
    dashboards.add_chart(board, {"id": "k1", "cube": cubes.LOCAL, "title": "Bookings", "question": "Bookings",
                                 "chart_type": "kpi", "date_column": '"Booking Date"',
                                 "plan": {"steps": [step(COUNT + ' AND "Agency" = @F_AGENCY')], "combine_sql": ""}})
    meta = api.get(f"/api/dashboards/{board}").json()
    assert meta["filters"] == [{"key": "agency", "label": "Agency"}]
    monkeypatch.setattr(dashboards, "_today", lambda: date(2026, 6, 1))  # the options are the last year's
    choices = api.get(f"/api/dashboards/{board}/filters").json()
    assert [o["value"] for o in choices[0]["options"]] == ["Lotus Travel House", "Coral Bay Travel",
                                                           "Desert Pearl Tours", "Atlas Voyages"]  # by sales
    assert choices[0]["default"] == "Lotus Travel House"
    span = {"start": "2026-03-01", "end": "2026-06-01", "compare": "none"}
    first = api.get(f"/api/dashboards/{board}/results", params=span).json()
    picked = api.get(f"/api/dashboards/{board}/results", params={**span, "f_agency": "Atlas Voyages"}).json()
    unknown = api.get(f"/api/dashboards/{board}/results", params={**span, "f_agency": "Nobody"}).json()
    assert first["filters"] == {"agency": "Lotus Travel House"} and first["charts"]["k1"]["kpi"]["value"] == 2
    assert picked["filters"] == {"agency": "Atlas Voyages"} and picked["charts"]["k1"]["kpi"]["value"] == 3
    assert unknown["filters"] == {"agency": "Lotus Travel House"}  # not in the list: the default
    assert api.get("/api/dashboards/nope/filters").status_code == 404


def test_people_opening_the_same_dashboard_at_once_run_its_charts_once(api, monkeypatch):
    board = dashboards.create_dashboard("Busy")
    dashboards.add_chart(board, {"id": "k1", "cube": cubes.LOCAL, "title": "Bookings", "question": "Bookings",
                                 "chart_type": "kpi", "date_column": '"Booking Date"',
                                 "plan": {"steps": [step(COUNT)], "combine_sql": ""}})
    runs, real_run = [], plans.run

    def slow_run(p, *a, **k):
        runs.append(p)
        time.sleep(0.3)
        return real_run(p, *a, **k)
    monkeypatch.setattr(plans, "run", slow_run)
    answers = []
    visitors = [threading.Thread(target=lambda: answers.append(api.get(f"/api/dashboards/{board}/results").json()))
                for _ in range(3)]
    for v in visitors:
        v.start()
    for v in visitors:
        v.join(30)
    assert len(answers) == 3 and all(a["charts"]["k1"]["kpi"]["value"] == 0 for a in answers)
    assert len(runs) == 2  # the period and its comparison, once for everyone


def test_a_slow_cube_server_doesnt_hold_up_the_page(monkeypatch):
    gate = threading.Event()

    class SlowServer:
        def data_as_of(self):
            gate.wait(10)
            return "16 Oct 2026, 10:00"
    monkeypatch.setattr(dashboard_routes, "get_backend", lambda cube: SlowServer())
    dashboard_routes._as_of.clear()
    began = time.perf_counter()
    assert dashboard_routes.data_as_of("Sales Cube", wait=0.2) == ""  # not known yet: the page goes on
    assert time.perf_counter() - began < 1
    gate.set()
    dashboard_routes._asking["Sales Cube"].join(10)
    assert dashboard_routes.data_as_of("Sales Cube", wait=0.2) == "16 Oct 2026, 10:00"  # kept for next time
    dashboard_routes._as_of.clear()


def test_charts_are_edited_restyled_sent_moved_and_deleted(api, by_agency, monkeypatch):
    cid, turn = by_agency
    sign_in(api)
    first = api.post("/api/dashboards", json={"name": "First"}).json()["id"]
    second = api.post("/api/dashboards", json={"name": "Second"}).json()["id"]
    monkeypatch.setattr(llm, "_create", FakeClaude())
    add = lambda: api.post(f"/api/dashboards/{first}/charts/from-answer",  # noqa: E731
                           json={"conversation_id": cid, "turn_id": turn["id"], "period_mode": "fixed"}).json()
    one, two = add(), add()
    assert one["period"] == {"mode": "fixed", "label": "All dates"}
    edited = api.patch(f"/api/dashboards/{first}/charts/{one['id']}", json={"title": "Agencies", "width": "full"}).json()
    assert (edited["title"], edited["width"], edited["chart_type"]) == ("Agencies", "full", "horizontal_bar")
    no_compare = api.patch(f"/api/dashboards/{first}/charts/{one['id']}", json={"compare": False}).json()
    assert no_compare["compare_on"] is False
    monkeypatch.setattr(llm, "_create", FakeClaude(chart("donut", x="Agency", y=["Sales"])))
    restyled = api.post(f"/api/dashboards/{first}/charts/{one['id']}/restyle", json={"request": "a donut"}).json()
    assert restyled["chart_type"] == "donut" and restyled["title"] == "Agencies"
    moved = api.post(f"/api/dashboards/{first}/charts/{two['id']}/move", json={"step": -1}).json()
    assert [c["id"] for c in moved["charts"]] == [two["id"], one["id"]]
    assert api.post(f"/api/dashboards/{first}/charts/{one['id']}/send", json={"to": second}).json()["ok"] is True
    assert len(api.get(f"/api/dashboards/{second}").json()["charts"]) == 1
    sent = api.post(f"/api/dashboards/{first}/charts/{two['id']}/send", json={"to": "new", "name": "Third", "move": True}).json()
    assert len(api.get(f"/api/dashboards/{first}").json()["charts"]) == 1
    assert api.get(f"/api/dashboards/{sent['to']}").json()["name"] == "Third"
    assert api.delete(f"/api/dashboards/{first}/charts/{one['id']}").json() == {"ok": True}
    assert api.get(f"/api/dashboards/{first}").json()["charts"] == []
    modes = api.get(f"/api/dashboards/{second}/charts/{api.get(f'/api/dashboards/{second}').json()['charts'][0]['id']}/modes").json()
    assert modes["current"] == "fixed" and "dashboard" in modes["choices"]


def test_a_chart_from_a_question_is_planned_by_claude(api, monkeypatch):
    sign_in(api)
    board = api.post("/api/dashboards", json={"name": "Sales"}).json()["id"]
    fake = FakeClaude(plan([step(DATED_BY_AGENCY)]), chart("horizontal_bar", x="Agency", y=["Sales"]))
    monkeypatch.setattr(llm, "_create", fake)
    r = api.post(f"/api/dashboards/{board}/charts", json={"question": "Sales by agency", "cube": cubes.LOCAL,
                                                          "date_column": '"Booking Date"', "start": "2026-01-01",
                                                          "end": "2027-01-01"})
    assert r.status_code == 200, r.text
    assert r.json()["chart_type"] == "horizontal_bar" and r.json()["period"]["mode"] == "dashboard"
    assert [q["purpose"] for q in fake.requests] == ["plan", "chart"]
    columns = api.get("/api/date-columns", params={"cube": cubes.LOCAL}).json()
    assert columns["default"] == '"Booking Date"' and {"value": "", "label": "Nothing (always show all dates)"} in columns["options"]


def test_the_charts_of_the_day_are_run_before_the_first_visit(api, monkeypatch):
    board = dashboards.create_dashboard("Morning")
    dashboards.add_chart(board, {"id": "k1", "cube": cubes.LOCAL, "title": "Bookings", "question": "Bookings",
                                 "chart_type": "kpi", "date_column": '"Booking Date"',
                                 "plan": {"steps": [step(COUNT)], "combine_sql": ""}})
    runs = counting_runs(monkeypatch)
    assert background.prerun() >= 1 and len(runs) == 2  # the default period and its comparison
    api.get(f"/api/dashboards/{board}/results")
    assert len(runs) == 2  # the first visit: saved numbers
    assert background.seconds_until_next(datetime(2026, 10, 16, 0, 4)) == 60
    assert background.seconds_until_next(datetime(2026, 10, 16, 0, 5)) == 86400


# ---------------------------------------------------------------- glossary and decisions --

def test_glossary_is_read_by_everyone_and_edited_by_admins(api):
    empty = api.get(f"/api/glossary/{cubes.LOCAL}").json()
    assert empty["rows"] == [] and empty["cube"] == cubes.LOCAL
    assert api.get("/api/glossary/Not a cube").status_code == 404
    sign_in(api)
    rows = [{"Term": "Sales", "Meaning": "Final sales", "Measure": '"Sales USD"', "Status": "Agreed"},
            {"Term": "Bookings", "Meaning": "Rows", "Status": "Maybe"}]
    saved = api.put(f"/api/glossary/{cubes.LOCAL}", json={"rows": rows}).json()
    assert [(r["Term"], r["Status"]) for r in saved["rows"]] == [("Sales", "Agreed"), ("Bookings", "Draft")]
    assert saved["drafts"] == 1 and saved["updated"] == date.today().isoformat()


def test_decisions_are_agreed_by_admins(api):
    if not semantic.decisions():
        pytest.skip("no meaning layer decisions shipped")
    listed = api.get("/api/decisions").json()
    item = next(i for i in listed["items"] if i["status"] == "proposed")
    assert set(item) == {"id", "cube", "question", "why", "options", "proposed", "answer", "status"}
    sign_in(api)
    choice = item["options"][-1]
    agreed = api.post(f"/api/decisions/{item['id']}", json={"answer": choice}).json()
    assert (agreed["status"], agreed["answer"]) == ("agreed", choice)
    after = api.get("/api/decisions", params={"cube": item["cube"]}).json()
    assert after["open"] == listed["open"] - 1 and all(i["cube"] == item["cube"] for i in after["items"])
    assert api.post("/api/decisions/not-a-decision", json={"answer": "x"}).status_code == 404


# ---------------------------------------------------------------- cubes and jobs --

def test_jobs_report_their_progress_and_stream_it(api):
    sign_in(api)
    gate = threading.Event()

    def work(job):
        job.say("Reading the cubes")
        gate.wait(10)
        job.say("Done reading")
        return 42
    job = jobs.start("test", work, single=True)
    assert jobs.start("test", work, single=True) is job  # one at a time
    state = api.get(f"/api/jobs/{job.id}").json()
    assert (state["status"], state["lines"]) == ("running", ["Reading the cubes"])
    gate.set()
    streamed = events(api.get(f"/api/jobs/{job.id}/events"))
    assert streamed == [("line", {"text": "Reading the cubes"}), ("line", {"text": "Done reading"}),
                        ("done", {"status": "done"})]
    assert job.result == 42

    failing = jobs.start("test", lambda job: (_ for _ in ()).throw(RuntimeError("The cube is busy.")))
    streamed = events(api.get(f"/api/jobs/{failing.id}/events"))
    assert streamed[-1] == ("done", {"status": "failed", "error": "The cube is busy.",
                                     "details": "RuntimeError: The cube is busy."})
    assert api.get("/api/jobs/missing").status_code == 404


def test_the_data_layer_is_built_as_a_job(api, monkeypatch):
    sign_in(api)
    calls = []

    def fake_build(names, only_changed=False, on_progress=None):
        calls.append((names, only_changed))
        on_progress(f"✓ Read {cubes.LOCAL} (1/1)")
        return {"cubes": {cubes.LOCAL: {}}, "entities": [], "errors": {}}
    monkeypatch.setattr(data_layer, "build", fake_build)
    job = api.post("/api/layer/build", json={"only_changed": True}).json()["job"]
    streamed = events(api.get(f"/api/jobs/{job}/events"))
    assert streamed[-1] == ("done", {"status": "done"}) and calls == [(None, True)]
    assert ("line", {"text": "Data layer ready: 1 cube(s), 0 shared dimension(s)"}) in streamed
    state = api.get("/api/cubes").json()
    assert state["local"] is True and state["server_cubes"] == [] and state["enabled"] == [cubes.LOCAL]
    assert state["cubes"][0]["name"] == cubes.LOCAL and state["cubes"][0]["ready"] and state["layer"]["ready"]
    setup = api.get(f"/api/cubes/{cubes.LOCAL}/setup").json()
    assert setup["progress"]["structure"] is True and setup["questions"] == []
    assert api.put("/api/cubes/enabled", json={"names": []}).status_code == 400  # local mode: nothing to pick


def test_a_busy_cube_server_does_not_hold_up_the_cubes_page(monkeypatch):
    """While the server refreshes a cube it can hold new queries for minutes: the page waits a little,
    then shows the last list (or says the server is busy), and the answer is kept for next time."""
    import ssas
    from server.routes import cubes as cube_routes
    release = threading.Event()

    def slow_list():
        release.wait(10)
        return pd.DataFrame({"CATALOG_NAME": ["Sales"], "DATE_MODIFIED": ["2026-10-16 22:07:52"]})
    monkeypatch.setattr(config, "resolve_source", lambda: "ssas")
    monkeypatch.setattr(ssas, "list_databases", slow_list)
    monkeypatch.setattr(cube_routes, "_server_cubes", {"time": 0.0, "rows": [], "error": None})
    monkeypatch.setattr(cube_routes, "_listing", {"thread": None})
    began = time.perf_counter()
    with pytest.raises(RuntimeError, match="busy"):
        cube_routes.server_cubes(wait=0.2)
    assert time.perf_counter() - began < 2
    release.set()
    cube_routes._listing["thread"].join(5)
    assert [r["name"] for r in cube_routes.server_cubes(wait=0.2)] == ["Sales"]  # kept: no new question
    release.clear()
    rows = cube_routes.server_cubes(fresh=True, wait=0.2)  # asked again, still busy: the last list
    assert [r["name"] for r in rows] == ["Sales"]
    release.set()


# ---------------------------------------------------------------- settings, updates, usage --

def test_settings_say_what_is_set_but_never_the_secrets(api, vault, monkeypatch):
    for name in ("SSAS_SERVER", "SSAS_DATABASE", "SSAS_USERNAME"):
        monkeypatch.setattr(config, name, "")  # restored after the test (Settings changes them)
    sign_in(api)
    secret_key, server_password = "sk-ant-api03-VERY-SECRET-KEY", "SERVER-SECRET-PASSWORD"
    assert api.put("/api/settings/api-key", json={"key": "nonsense"}).status_code == 400
    status = api.put("/api/settings/api-key", json={"key": secret_key}).json()
    assert (status["api_key"], status["api_key_where"]) == ("set", "saved")
    assert api.put("/api/settings/server", json={"server": "cubes.example.com:2383", "username": "reader@example.com"}
                   ).status_code == 400  # a new username needs its password
    status = api.put("/api/settings/server", json={"server": "cubes.example.com:2383", "database": "",
                                                   "username": "reader@example.com", "password": server_password}).json()
    assert status["server"]["address"] == "cubes.example.com:2383" and status["server"]["login_saved"] is True
    assert status["server"]["username"] == "reader@example.com"  # shown to the admin
    hashed = vault[(config.APP_KEYRING_SERVICE, secrets_store.ADMIN_HASH_NAME)]
    for client in (api, TestClient(app)):  # signed in, and anyone
        text = client.get("/api/settings").text
        assert secret_key not in text and server_password not in text and hashed not in text and PASSWORD not in text
    assert "username" not in TestClient(app).get("/api/settings").json()["server"]

    monkeypatch.setattr(llm, "check_connection", lambda: (_ for _ in ()).throw(RuntimeError("No Claude API key is set.")))
    failed = api.post("/api/settings/api-key/test").json()
    assert failed["ok"] is False and "No Claude API key" in failed["detail"]
    monkeypatch.setattr(llm, "check_connection", lambda: None)
    assert api.post("/api/settings/api-key/test").json() == {"ok": True, "model": config.CLAUDE_MODEL}

    assert api.put("/api/settings/admin-password", json={"current": "wrong", "new": "a new password"}).status_code == 400
    elsewhere = TestClient(app, headers=APP_HEADER)
    sign_in(elsewhere)
    assert api.put("/api/settings/admin-password", json={"current": PASSWORD, "new": "a new password"}).json() == {"ok": True}
    assert api.get("/api/session").json()["admin"] is True  # this browser got a new cookie
    assert elsewhere.get("/api/session").json()["admin"] is False  # every other browser is signed out


def test_updates_are_checked_and_a_developer_copy_is_not_updated_from_the_app(api, monkeypatch):
    sign_in(api)
    release = updates.Release(version="9.9.9", tag="v9.9.9", published="1 Nov 2026", notes="New things",
                              zip_url="", page="https://example.com/release")
    monkeypatch.setattr(updates, "latest_release", lambda: release)
    monkeypatch.setattr(updates, "updating", lambda: False)
    found = api.get("/api/updates", params={"fresh": True}).json()
    assert (found["status"], found["latest"], found["notes"]) == ("available", "9.9.9", "New things")
    monkeypatch.setattr(updates, "is_developer_copy", lambda: True)
    launched = []
    monkeypatch.setattr(updates, "launch", lambda *a: launched.append(a))
    r = api.post("/api/updates/apply")
    assert r.status_code == 400 and "developer copy" in r.json()["detail"] and launched == []


def test_usage_shows_what_questions_cost(api):
    sign_in(api)
    usage.save({"time": datetime.now().isoformat(timespec="seconds"), "kind": "question", "label": "Sales by agency",
                "seconds": 12.5, "cost": 0.0421, "claude_calls": 3, "calls": []})
    body = api.get("/api/usage", params={"days": 7}).json()
    assert body["report"]["total"] == 0.0421 and body["report"]["today"] == 0.0421 and len(body["report"]["daily"]) == 7
    assert body["recent"][0]["label"] == "Sales by agency" and body["summary"]["questions_7d"] == 1


# ---------------------------------------------------------------- tables --

def test_tables_have_typed_columns_iso_dates_and_nulls():
    df = pd.DataFrame({"Day": pd.to_datetime(["2026-10-14", None]), "When": [datetime(2026, 10, 14, 9, 30), None],
                       "Sales": [1.5, np.nan], "Count": [Decimal("3"), None], "Name": ["A", None],
                       "Flag": [True, False]})
    t = convert.table(df)
    assert [(c["name"], c["type"]) for c in t["columns"]] == [
        ("Day", "date"), ("When", "date"), ("Sales", "number"), ("Count", "number"), ("Name", "text"), ("Flag", "text")]
    assert t["rows"] == [["2026-10-14", "2026-10-14T09:30:00", 1.5, 3.0, "A", "True"],
                         [None, None, None, None, None, "False"]]
    big = convert.table(pd.DataFrame({"n": range(5001)}))
    assert big["row_count"] == 5001 and len(big["rows"]) == 5000 and big["truncated"] is True
    assert convert.plain({"a": float("nan"), "b": np.int64(2), "c": date(2026, 1, 2)}) == {"a": None, "b": 2, "c": "2026-01-02"}


# ---------------------------------------------------------------- the cube worker processes --

class Unpicklable(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.connection = threading.Lock()  # like a .NET error holding a live object


def test_errors_from_workers_travel_back_in_plain_words():
    same = RuntimeError("No password saved for reader.")
    assert pool._portable(same) is same
    moved = pool._portable(Unpicklable("Query (1, 5) The column 'X' wasn't found."))
    assert isinstance(moved, pool.CubeError) and str(moved) == "Unpicklable: Query (1, 5) The column 'X' wasn't found."
    pickle.loads(pickle.dumps(moved))


def test_workers_end_when_the_server_is_ended():
    """Windows ends the server without warning (the task's End, a restart, an update): its workers must
    not stay behind."""
    import subprocess
    import sys
    from pathlib import Path
    app = str(Path(__file__).resolve().parents[1])
    server = subprocess.Popen([sys.executable, "-c",
                               f"import sys; sys.path.insert(0, {app!r}); from server import pool; "
                               "workers = pool.QueryPool(1, connect=False); print(workers.warm_up()[0], flush=True); "
                               "import time; time.sleep(60)"],
                              stdout=subprocess.PIPE, text=True, cwd=app)
    try:
        worker = int(server.stdout.readline())
        assert worker != server.pid and pool_alive(worker)
        server.kill()  # ended from outside, like the task's End: no shutdown code runs
        for _ in range(40):
            if not pool_alive(worker):
                break
            time.sleep(0.25)
        assert not pool_alive(worker)
    finally:
        server.kill()


def pool_alive(pid: int) -> bool:
    import updates
    return updates._alive(pid)


def test_a_worker_process_runs_calls_for_the_server_and_is_replaced_when_it_dies(monkeypatch):
    import sys
    import types
    from concurrent.futures.process import BrokenProcessPool
    # the Streamlit tests (AppTest) leave app.py as __main__, which a new worker process would run first
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))
    workers = pool.QueryPool(1, connect=False)
    try:
        first = workers.call(os.getpid)
        assert first != os.getpid()
        assert workers.warm_up() == [first] and workers.warm
        with pytest.raises(BrokenProcessPool):
            workers.call(os._exit, 3)  # a crash (e.g. inside .NET) takes the worker down
        assert workers.call(os.getpid) not in (first, os.getpid())  # a new worker took over
    finally:
        workers.shutdown()


def test_ssas_queries_go_through_the_pool_and_come_back(monkeypatch):
    import ssas
    calls = []

    class FakePool:
        def __init__(self, workers):
            self.workers = workers

        def call(self, fn, *args):
            calls.append((fn, args))
            return pd.DataFrame({"n": [1]})

        def shutdown(self):
            calls.append("stopped")
    real_query, real_refresh = ssas.run_query, dashboards._start_refresh
    monkeypatch.setattr(pool, "QueryPool", FakePool)
    monkeypatch.setattr(config, "SSAS_SERVER", "cubes.example.com:2383")
    try:
        pool.install(2)
        assert ssas.run_query is not real_query and dashboards._start_refresh is not real_refresh
        with ssas.using("Sales Cube"):
            out = ssas.run_query("EVALUATE ROW(\"n\", 1)", max_rows=10)
        assert out["n"].tolist() == [1]
        fn, (query, max_rows, conn_str, database, settings, extra) = calls[0]
        assert fn is pool._run_query and (query, max_rows, conn_str, database) == ('EVALUATE ROW("n", 1)', 10, None, "Sales Cube")
        assert settings["SSAS_SERVER"] == "cubes.example.com:2383"
    finally:
        pool.uninstall()
    assert ssas.run_query is real_query and dashboards._start_refresh is real_refresh and calls[-1] == "stopped"
