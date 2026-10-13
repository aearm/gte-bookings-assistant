"""The app's pages, run headless with Streamlit's AppTest (local mode, temporary files)."""
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

import cubes
import data_layer
import llm
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
    assert "**Not signed in** · view only" in texts(at)
    assert at.button(key="authbar_signin").label == "Sign in"
    assert "View only. Sign in as admin" in texts(at)


def test_sign_in_and_out(at):
    at.run()
    at.session_state["admin"] = True
    at.run()
    assert "**Signed in as admin**" in texts(at)
    at.button(key="authbar_signout").click().run()
    assert "**Not signed in**" in texts(at)


def test_admin_pages_are_locked_until_signed_in(at):
    at.run()
    at.switch_page("views/cubes_page.py").run()
    assert not at.exception
    assert "You're not signed in" in texts(at)
    at.text_input[0].input("wrong").run()
    at.button[-1].click().run()
    assert "That password isn't right" in "".join(e.value for e in at.error)
    at.text_input[0].input("right password")
    at.button[-1].click().run()
    assert "**Signed in as admin**" in texts(at) and "Data layer" in [s.value for s in at.subheader]


def test_dashboard_period_by_calendar_and_week_numbers(at):
    at.run()
    picker = at.segmented_control(key="dash_mode")
    assert picker.options == periods.MODES and picker.value == "Quick"
    start, end = periods.preset_range("This year")
    assert any(periods.describe(start, end) in c.value for c in at.caption)

    picker.set_value("Week").run()
    iso_year, iso_week = periods.current_week()
    week_from = at.selectbox(key=f"dash_week_from_{iso_year}")
    assert week_from.value == iso_week and week_from.format_func(iso_week).startswith(f"From W{iso_week} ·")
    week_from.set_value(1).run()
    at.selectbox(key=f"dash_week_to_{iso_year}").set_value(3).run()
    assert at.session_state["dash_range"] == periods.week_range(iso_year, 1, 3)
    assert any("weeks 1–3" in c.value for c in at.caption)
    at.selectbox(key="dash_week_year").set_value(2025).run()
    assert len(at.selectbox(key="dash_week_from_2025").options) == 52

    at.segmented_control(key="dash_mode").set_value("Calendar").run()
    at.date_input(key="dash_calendar").set_value((date(2026, 3, 2), date(2026, 3, 8))).run()
    assert at.session_state["dash_range"] == (date(2026, 3, 2), date(2026, 3, 9))
    assert any("02 Mar 2026 – 08 Mar 2026 · week 10" in c.value for c in at.caption)


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


def test_chat_explains_what_is_missing(at, monkeypatch):
    monkeypatch.setattr(data_layer, "is_built", lambda: False)
    at.run()
    at.switch_page("views/chat.py").run()
    assert not at.exception
    assert [o for o in at.sidebar.selectbox[0].options] == [cubes.LOCAL]  # no "All data" without the layer
