"""The app's pages, run headless with Streamlit's AppTest (local mode, temporary files)."""
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

import cubes
import data_layer
import llm
import period_picker
import periods
import secrets_store
from conftest import ROOT
from fakes import FakeClaude, chart, plan
from test_data_layer import build_local_layer

_real_structured_call = llm._structured_call


@pytest.fixture
def at(app_dirs, monkeypatch):
    monkeypatch.setattr(secrets_store, "has_admin_password", lambda: True)
    monkeypatch.setattr(secrets_store, "check_admin_password", lambda pw: pw == "right password")
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)


def texts(at) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info]
    return "\n".join(str(p) for p in parts)


def test_not_signed_in_is_obvious(at):
    at.run()
    assert not at.exception
    assert at.button(key="auth_signin").label == "View only · Sign in"  # amber pill, top right
    assert "sign in to open" in texts(at)  # next to Admin in the menu


def test_menu_has_a_plus_next_to_dashboards(at):
    at.run()
    plus = at.button(key="navadd_dashboards")
    assert plus.label == "" and plus.help == "New dashboard"
    plus.click().run()
    assert not at.exception
    assert any("adding a dashboard needs the admin password" in c.value for c in at.caption)


def test_plus_buttons_are_there_for_everyone_and_ask_to_sign_in(at):
    at.run()
    assert at.button(key="dash_add").label == "Add chart"
    assert at.button(key="addtile_btn_first").label == "Add your first chart"
    at.button(key="addtile_btn_first").click().run()
    assert not at.exception
    assert any("adding a chart needs the admin password" in c.value for c in at.caption)
    assert [t.label for t in at.text_input] == ["Admin password"]  # the dialog asks to sign in first
    assert at.checkbox[0].label == "Keep me signed in on this computer" and at.checkbox[0].value
    at.session_state["admin"] = True
    at.run()
    at.button(key="dash_add").click().run()
    assert not at.exception
    assert any(t.label == "What should the chart show?" for t in at.text_area)  # signed in: straight to the form


def test_sign_in_and_out(at):
    at.run()
    at.session_state["admin"] = True
    at.run()
    assert "**Signed in as admin**" in texts(at) and "sign in to open" not in texts(at)
    at.button(key="auth_signout").click().run()
    assert at.button(key="auth_signin").label == "View only · Sign in"


def test_admin_pages_are_locked_until_signed_in(at):
    at.run()
    at.switch_page("views/cubes_page.py").run()
    assert not at.exception
    assert "Admins only" in texts(at)
    sign_in = lambda: next(b for b in at.button if b.label == "Sign in")
    at.text_input[0].input("wrong").run()
    sign_in().click().run()
    assert "That password isn't right" in "".join(e.value for e in at.error)
    at.text_input[0].input("right password")
    sign_in().click().run()
    assert "**Signed in as admin**" in texts(at) and "Data layer" in [s.value for s in at.subheader]


def period_label(at) -> str:
    return next(p for p in at.get("popover") if p.proto.id.endswith("dash_period_popover")).proto.popover.label


def test_dashboard_period_button_and_calendar_choices(at):
    at.run()
    start, end = periods.preset_range("This year")
    assert period_label(at) == periods.label(start, end, "This year")  # e.g. This year · 1 Jan – 13 Oct 2026 · W1–42

    at.session_state["dash_period"] = {"start": "2026-10-05", "end": "2026-10-19"}  # weeks 41-42 on the calendar
    at.run()
    assert period_label(at) == "5 Oct – 18 Oct 2026 · W41–42"

    at.session_state["dash_period"] = {"preset": "Last week"}
    at.run()
    assert period_label(at).startswith("Last week · ")


def compare_label(at) -> str:
    labels = [p.proto.popover.label for p in at.get("popover")]
    return next(label for label in labels if label.startswith("vs ") or label == "Compare")


def test_compare_button_next_to_the_period(at):
    at.run()
    start, end = periods.preset_range("This year")
    assert compare_label(at) == "vs " + periods.dates_text(*periods.same_period_last_year(start, end))  # the default
    at.session_state["dash_period"] = {"preset": "Last month"}
    at.session_state["dash_compare"] = {"mode": "previous"}
    at.run()
    assert compare_label(at) == "vs " + periods.dates_text(*periods.previous_period(*periods.preset_range("Last month"), "Last month"))
    at.session_state["dash_compare"] = {"mode": "none"}
    at.run()
    assert compare_label(at) == "Compare" and not at.exception


def test_dashboard_numbers_and_charts_show_the_comparison(at):
    import json

    import dashboards
    at.run()
    board = dashboards.list_dashboards()[0]["id"]
    dated = 'FROM bookings WHERE "Booking Date" >= @START AND "Booking Date" < @END'
    for cid, kind, query, extra in [
            ("k1", "kpi", f'SELECT COUNT(*) AS "Bookings" {dated}', {}),
            ("b1", "bar", f'SELECT "Destination Country", COUNT(*) AS "Bookings" {dated} GROUP BY 1 ORDER BY 2 DESC',
             {"x": "Destination Country", "y": ["Bookings"]})]:
        dashboards.add_chart(board, {"id": cid, "title": kind, "question": kind, "chart_type": kind, "width": "half",
                                     "date_column": '"Booking Date"', "cube": cubes.LOCAL, "style": {}, "color": "",
                                     "plan": {"steps": [{"name": "result", "cube": cubes.LOCAL, "query": query}],
                                              "combine_sql": ""}, **{"x": "", "y": [], **extra}})
    at.session_state["dash_period"] = {"start": "2026-03-01", "end": "2026-06-01"}
    at.session_state["dash_compare"] = {"mode": "custom", "start": "2026-01-01", "end": "2026-03-01"}
    at.run()
    assert not at.exception
    assert compare_label(at) == "vs 1 Jan – 28 Feb 2026"
    assert at.metric[0].value == "8" and at.metric[0].delta == "+100.0% vs 1 Jan – 28 Feb 2026"  # 8 bookings vs 4
    figure = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert [t["name"] for t in figure["data"]] == ["1 Jan – 28 Feb 2026", "1 Mar – 31 May 2026"]  # grey, then colour


def test_calendar_choices_are_kept(monkeypatch):
    state = {}
    monkeypatch.setattr(period_picker.st, "session_state", state)
    period_picker.choose({"start": "2026-03-02", "end": "2026-03-09", "preset": ""})
    assert period_picker.current() == (date(2026, 3, 2), date(2026, 3, 9), "")
    period_picker.choose({"start": "x", "end": "y", "preset": "This month"})
    assert period_picker.current()[2] == "This month"
    state[period_picker.PICKER_KEY] = {"selection": {"start": "2026-01-05", "end": "2026-01-19", "preset": ""}}
    state[period_picker.POPOVER_KEY] = True
    period_picker._on_pick()
    assert state[period_picker.POPOVER_KEY] is False  # the calendar closes
    assert period_picker.current()[:2] == periods.week_range(2026, 2, 3)
    state[period_picker.STATE_KEY] = {"start": "broken"}
    assert period_picker.current()[2] == periods.DEFAULT_PRESET


def test_chat_with_all_the_data(at, monkeypatch):
    build_local_layer(monkeypatch)
    monkeypatch.setattr(llm, "_structured_call", _real_structured_call)
    at.run()
    at.switch_page("views/chat.py").run()
    assert not at.exception
    assert at.sidebar.selectbox[0].value == "__all__"  # All data is the default once the layer is built
    assert "Sales by account manager" in [b.label for b in at.button]

    query = ('SELECT a."Account Manager" AS "Manager", SUM(b."Sales USD") AS "Sales" FROM bookings b '
             'JOIN agencies a ON b."Agency" = a."Agency" GROUP BY 1 ORDER BY 2 DESC')
    donut = '{"traces": [{"type": "pie", "labels": {"col": "Manager"}, "values": {"col": "Sales"}, "hole": 0.5}]}'
    monkeypatch.setattr(llm, "_create", FakeClaude(
        plan([{"name": "result", "cube": cubes.LOCAL, "query": query}], chart_request="as a donut",
             understanding="Sales by account manager, all dates"),
        chart("custom", custom_chart=donut, summary="Sara leads with 1,005.5.")))
    at.chat_input[0].set_value("Sales by account manager as a donut").run()
    assert not at.exception
    assert "Sales by account manager, all dates" in at.info[0].value
    assert "Sara leads with 1,005.5." in texts(at)
    assert at.get("plotly_chart")  # the described chart was drawn
    assert any(b.label == "Change chart" for b in at.button)


def test_chat_makes_a_dashboard_from_the_conversation(at, monkeypatch):
    build_local_layer(monkeypatch)
    monkeypatch.setattr(llm, "_structured_call", _real_structured_call)
    at.session_state["admin"] = True
    at.run()
    at.switch_page("views/chat.py").run()
    asked = [("Sales by agency in 2026", 'SELECT "Agency", SUM("Sales USD") AS "Sales" FROM bookings GROUP BY 1',
              "Agency", "Sales", "Sales by agency, 2026"),
             ("Bookings by status this year", 'SELECT "Status", COUNT(*) AS "Bookings" FROM bookings GROUP BY 1',
              "Status", "Bookings", "Bookings by status this year")]
    for question, query, x, y, title in asked:
        monkeypatch.setattr(llm, "_create", FakeClaude(
            plan([{"name": "result", "cube": cubes.LOCAL, "query": query}]), {**chart("bar", x=x, y=[y]), "title": title}))
        at.chat_input[0].set_value(question).run()
        assert not at.exception
    assert [b.label for b in at.button if b.label == "Add to dashboard"] == ["Add to dashboard"] * 2
    assert at.button(key="add_all_charts").label == "Make a dashboard from this conversation"
    at.button(key="add_all_charts").click().run()
    assert not at.exception
    assert at.text_input(key="chat_board_name").value.startswith("From chat · ")  # always a new dashboard
    picks = [c for c in at.checkbox if c.key.startswith("chat_board_pick_")]
    assert [c.label for c in picks] == ["Sales by agency", "Bookings by status"] and all(c.value for c in picks)
    assert at.button(key="chat_board_go").label == "Create dashboard with 2 charts"


def test_settings_show_what_claude_costs(at, monkeypatch):
    import usage
    from datetime import datetime
    monkeypatch.setattr(secrets_store, "api_key_status", lambda: "saved")
    for kind, cost in [("question", 0.25), ("dashboard_chart", 0.5)]:
        usage.save({"time": datetime.now().isoformat(timespec="seconds"), "kind": kind, "label": "x", "cost": cost,
                    "calls": []})
    at.session_state["admin"] = True
    at.run()
    at.switch_page("views/settings.py").run()
    assert not at.exception
    assert "Claude cost" in [s.value for s in at.subheader]
    assert [m.value for m in at.metric] == ["$0.75"] * 4  # today, 7 days, this month, since measuring began


def test_chat_explains_what_is_missing(at, monkeypatch):
    monkeypatch.setattr(data_layer, "is_built", lambda: False)
    at.run()
    at.switch_page("views/chat.py").run()
    assert not at.exception
    assert [o for o in at.sidebar.selectbox[0].options] == [cubes.LOCAL]  # no "All data" without the layer
