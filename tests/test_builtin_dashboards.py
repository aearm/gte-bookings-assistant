"""The dashboards the app ships with (builtin_dashboards.py), dashboard filters (a client, a market) and how the
built-in dashboards reach every installation. No cube and no Claude: the queries themselves are run on the
cubes by hand when they change (their checks here are on their shape)."""
import json
import re
from datetime import date

import pandas as pd
import pytest

import builtin_dashboards as bd
import config
import cubes
import dashboards
import plans

BOARDS = bd.all_dashboards()
CHARTS = [(b, c) for b in BOARDS for c in b["charts"]]


# ---------------------------------------------------------------- the definitions --

IDS = ["overview", "market", "destination", "client", "supplier"]


def test_five_dashboards_overview_first():
    assert [b["id"] for b in BOARDS] == IDS
    assert [b["name"] for b in BOARDS] == ["Business overview", "Market view", "Destination view", "Client view",
                                           "Supplier view"]
    assert [f["key"] for b in BOARDS for f in b["filters"]] == IDS[1:]


def test_every_chart_is_complete_and_follows_the_dashboard():
    ids = [c["id"] for _, c in CHARTS]
    assert len(ids) == len(set(ids))  # unique across all of them (results are saved by chart id)
    for board, c in CHARTS:
        assert c["chart_type"] in dashboards.TYPE_LABELS and c["width"] in ("half", "full"), c["id"]
        assert c["title"] and c["question"] and c["period_mode"] == "dashboard" and c["builtin"], c["id"]
        plan = plans.Plan.from_chart(c)
        assert plans.Plan.from_dict(c["plan"]) == plan  # survives being saved
        assert all("@START" in s.query and "@END" in s.query for s in plan.steps), c["id"]
        assert plan.single or plan.combine_sql, c["id"]  # several steps are joined
        if c["chart_type"] != "kpi":
            assert c["x"] and c["y"], c["id"]
        assert {f["column"] for f in c["style"]["formats"]} <= set(c["y"]) | {c["title"]}, c["id"]
        marks = set(re.findall(r"@F_[A-Z]+", json.dumps(c["plan"])))
        assert marks <= {f["placeholder"] for f in board["filters"]}, c["id"]  # only the dashboard's own filters


def test_business_numbers_leave_out_the_test_agencies():
    for _, c in CHARTS:
        for s in plans.Plan.from_chart(c).steps:
            assert "Market for Testing Purposes" in s.query, c["id"]


def test_headline_numbers_come_first_then_the_trend():
    for b in BOARDS:
        kinds = [c["chart_type"] for c in b["charts"]]
        first_chart = kinds.index(next(k for k in kinds if k != "kpi"))
        assert kinds[:first_chart] == ["kpi"] * 8 and "kpi" not in kinds[first_chart:]
        assert b["charts"][first_chart]["title"] == "Sales" and b["charts"][first_chart]["width"] == "full"


def test_the_filters_list_values_from_the_last_year():
    for b in BOARDS:
        for f in b["filters"]:
            assert f["placeholder"] == "@F_" + f["key"].upper()
            assert "@START" in f["options"]["query"] and f["options"]["value"]
            assert all(f["placeholder"] in json.dumps(c["plan"]) for c in b["charts"]), b["id"]  # all follow it


# ---------------------------------------------------------------- filters --

CLIENT_BOARD = {"id": "b1", "name": "Client", "filters": [{
    "key": "client", "label": "Client", "placeholder": "@F_CLIENT",
    "options": {"cube": "Cube", "query": "options @START @END", "value": "Code", "label": "{Name} - {Code}"}}],
    "charts": [{"id": "k", "chart_type": "kpi", "plan": {"steps": [
        {"name": "result", "cube": "Cube", "query": "EVALUATE x = @F_CLIENT AND @START"}], "combine_sql": ""}},
        {"id": "n", "chart_type": "kpi", "plan": {"steps": [{"name": "result", "cube": "Cube", "query": "plain"}],
                                                   "combine_sql": ""}}]}


@pytest.fixture
def options(monkeypatch):
    """The options query answers with three clients (biggest first); the cube speaks DAX."""
    ran = []

    def run(plan, max_rows=None):
        ran.append(plan.steps[0].query)
        return pd.DataFrame({"Code": ["7", "12", 'O"Hara'], "Name": ["Atlas", "Coral Bay", None], "Sales": [9, 5, 1]})
    monkeypatch.setattr(dashboards.plans, "run", run)
    monkeypatch.setattr(dashboards, "get_backend", lambda cube: type("B", (), {"language": "DAX"})())
    dashboards._options_cache.clear()
    return ran


def test_filter_options_come_from_the_last_year_and_are_kept(options):
    got = dashboards.filter_options(CLIENT_BOARD, today=date(2026, 10, 18))
    assert got == [{"key": "client", "label": "Client", "default": "7", "error": "", "options": [
        {"value": "7", "label": "Atlas - 7"}, {"value": "12", "label": "Coral Bay - 12"},
        {"value": 'O"Hara', "label": 'O"Hara'}]}]
    assert "DATE(2025,10,18)" in options[0] or "2025-10-18" in options[0]
    dashboards.filter_options(CLIENT_BOARD, today=date(2026, 10, 18))
    assert len(options) == 1  # asked once


def test_the_value_picked_goes_into_the_queries_quoted(options):
    filled = dashboards.apply_filters(CLIENT_BOARD, CLIENT_BOARD["charts"], {"client": "12"})
    assert filled[0]["plan"]["steps"][0]["query"] == 'EVALUATE x = "12" AND @START'
    assert filled[1] is CLIENT_BOARD["charts"][1]  # a chart without the filter: as it is
    assert CLIENT_BOARD["charts"][0]["plan"]["steps"][0]["query"].endswith("@F_CLIENT AND @START")  # not changed
    quoted = dashboards.apply_filters(CLIENT_BOARD, CLIENT_BOARD["charts"], {"client": 'O"Hara'})
    assert 'x = "O""Hara"' in quoted[0]["plan"]["steps"][0]["query"]  # a quote can't end the text early


def test_no_value_or_one_not_in_the_list_means_the_default(options):
    for asked in (None, {}, {"client": "999"}, {"client": '" || 1=1 || "'}):
        assert dashboards.filter_values(CLIENT_BOARD, asked) == {"client": "7"}


def test_each_value_has_numbers_of_its_own(options):
    one, other = (dashboards.apply_filters(CLIENT_BOARD, CLIENT_BOARD["charts"], {"client": v})[0] for v in ("7", "12"))
    span = (date(2026, 10, 11), date(2026, 10, 18))
    assert dashboards.saved_key(one, *span, None) != dashboards.saved_key(other, *span, None)


def test_a_chart_away_from_its_filter_says_so(app_dirs, options, monkeypatch):
    lonely = {**CLIENT_BOARD["charts"][0], "id": "moved"}
    monkeypatch.setattr(dashboards, "_read", lambda: {"dashboards": [{"id": "x", "charts": [lonely]}]})
    with pytest.raises(RuntimeError, match="needs a filter its dashboard doesn't have \\(client\\)"):
        dashboards.runnable(lonely, date(2026, 10, 11), date(2026, 10, 18))
    monkeypatch.setattr(dashboards, "_read", lambda: {"dashboards": [CLIENT_BOARD]})
    alone = dashboards._plan_of(CLIENT_BOARD["charts"][0])  # run on its own (editing it): the default
    assert alone.steps[0].query == 'EVALUATE x = "7" AND @START'


# ---------------------------------------------------------------- reaching every installation --


@pytest.fixture
def gte_cubes(app_dirs, monkeypatch):
    """Live mode on a fresh install: no cube picked, no cube server asked (the dashboards don't wait for either)."""
    monkeypatch.setattr(config, "BUILTIN_DASHBOARDS", True)
    monkeypatch.setattr(config, "DATA_SOURCE", "ssas")
    monkeypatch.setattr(cubes, "server_names", lambda wait=0: pytest.fail("the server was asked"))
    dashboards._builtin_checked["time"] = 0.0
    yield
    dashboards._builtin_checked["time"] = 0.0


def test_added_first_at_once_on_a_new_install(gte_cubes):
    mine = dashboards.create_dashboard("My numbers")
    dashboards.ensure_builtin(force=True)
    names = [d["name"] for d in dashboards.list_dashboards()]
    assert names == ["Business overview", "Market view", "Destination view", "Client view", "Supplier view",
                     "My numbers"]
    assert json.loads(config.DASHBOARDS_FILE.read_text(encoding="utf-8"))["builtin"] == {b: bd.VERSION for b in IDS}
    assert dashboards.get_dashboard(mine)["charts"] == []


def test_not_added_again_once_deleted_and_renaming_stays(gte_cubes):
    dashboards.ensure_builtin(force=True)
    dashboards.delete_dashboard("market")
    dashboards.rename_dashboard("overview", "Our business")
    dashboards.ensure_builtin(force=True)
    assert [d["id"] for d in dashboards.list_dashboards()] == ["overview", "destination", "client", "supplier"]
    assert dashboards.get_dashboard("overview")["name"] == "Our business"


def test_a_newer_version_replaces_the_charts_unless_someone_changed_them(gte_cubes, monkeypatch):
    dashboards.ensure_builtin(force=True)
    dashboards.rename_dashboard("client", "Clients")  # a new name only: still updated
    dashboards.delete_chart("market", "mk-sales-trend")  # its charts changed: the market view is theirs now
    monkeypatch.setattr(bd, "VERSION", bd.VERSION + 1)
    dashboards.ensure_builtin(force=True)
    board = dashboards.get_dashboard("client")
    assert board["name"] == "Clients" and board["builtin"] == bd.VERSION
    market = dashboards.get_dashboard("market")
    assert market["customized"] and "mk-sales-trend" not in [c["id"] for c in market["charts"]]
    assert market["builtin"] == bd.VERSION - 1  # left as it was


def test_new_built_in_dashboards_take_their_place_among_the_others(gte_cubes, monkeypatch):
    """An installation with an older version (three of them, and one of its own) gets the new ones in their
    places in the list, after the overview and market views, not on top."""
    first = [b for b in BOARDS if b["id"] in ("overview", "market", "client")]
    config.DASHBOARDS_FILE.write_text(json.dumps({"dashboards": [*first, {"id": "mine", "name": "Mine", "charts": []}],
                                                  "builtin": {"overview": 2, "market": 2, "client": 2}}),
                                      encoding="utf-8")
    dashboards.ensure_builtin(force=True)
    assert [d["id"] for d in dashboards.list_dashboards()] == IDS + ["mine"]


def test_a_cube_server_not_set_up_is_one_note_for_the_page(gte_cubes, monkeypatch):
    import ssas
    monkeypatch.setattr(config, "SSAS_SERVER", "")
    assert "isn't set up yet" in dashboards.setup_problem()
    monkeypatch.setattr(config, "SSAS_SERVER", "cubes.example.test")
    monkeypatch.setattr(config, "SSAS_USERNAME", "reader")
    monkeypatch.setattr(ssas, "get_password", lambda: "")
    assert "password isn't saved yet" in dashboards.setup_problem()
    monkeypatch.setattr(ssas, "get_password", lambda: "secret")
    assert dashboards.setup_problem() == ""
    monkeypatch.setattr(config, "DATA_SOURCE", "local")
    monkeypatch.setattr(config, "SSAS_SERVER", "")
    assert dashboards.setup_problem({"id": "mine", "charts": []}) == ""  # local files need no server


def test_every_cube_on_the_server_is_connected_until_an_admin_picks(app_dirs, monkeypatch):
    import semantic
    monkeypatch.setattr(config, "DATA_SOURCE", "ssas")
    monkeypatch.setattr(config, "SSAS_SERVER", "cubes.example.test")
    monkeypatch.setattr(cubes, "server_names", lambda wait=5.0: ["A - Bookings", "A - Empty", "A - Sales"])
    monkeypatch.setattr(semantic, "usable", lambda c: c != "A - Empty")  # a cube without data is left out
    assert cubes.enabled() == ["A - Bookings", "A - Sales"]
    cubes.set_enabled(["A - Sales"])
    assert cubes.enabled() == ["A - Sales"]
    monkeypatch.setattr(config, "DATA_SOURCE", "local")
    assert cubes.enabled() == [cubes.LOCAL]


def test_the_server_is_asked_in_the_background_and_not_waited_for(monkeypatch):
    import threading
    import ssas
    asked, release = threading.Event(), threading.Event()

    def slow():
        asked.set()
        release.wait(5)
        return pd.DataFrame({"CATALOG_NAME": ["A - Sales", "A - Bookings"]})
    monkeypatch.setattr(config, "SSAS_SERVER", "cubes.example.test")
    monkeypatch.setattr(ssas, "list_databases", slow)
    monkeypatch.setattr(cubes, "_server", {"time": 0.0, "names": None, "thread": None})
    assert cubes.server_names(wait=0) == [] and asked.wait(5)  # still asking: nothing yet, nobody waits
    release.set()
    cubes._server["thread"].join(5)
    assert cubes.server_names(wait=0) == ["A - Bookings", "A - Sales"]


def test_destination_is_the_hotels_country_and_countries_the_guests_nationality():
    """Checked on the data (2026-10-18): the Bookings and Hotel Sales cubes' 'Countries'[Country] is the guests'
    nationality (hotels in Dubai: UAE, China, Saudi Arabia, USA, India...), not where they go; the destination is
    the hotel's country, spelled alike in Hotel Sales and the hotel request and lock cubes."""
    for _, c in CHARTS:
        text = json.dumps(c["plan"])
        if "destination" in c["title"].lower():  # grouped by the hotel's country (it may filter a nationality)
            assert "SUMMARIZECOLUMNS('Hotels'[" in text and "SUMMARIZECOLUMNS('Countries'" not in text, c["id"]
        if "nationalit" in c["title"].lower():
            assert "'Countries'[Country]" in text, c["id"]
    where = {s["cube"]: s["query"] for c in bd.destination()["charts"] for s in c["plan"]["steps"]}
    assert set(where) == {bd.HOTEL_SALES, bd.HOTEL_REQUESTS, bd.LOCKS}  # hotel bookings, demand and supply there
    assert "'Hotels'[Hotel Country] = @F_DESTINATION" in where[bd.HOTEL_SALES]
    assert all("'Hotels'[Country] = @F_DESTINATION" in where[c] for c in (bd.HOTEL_REQUESTS, bd.LOCKS))
    # side by side in the destination and market views: who travels, where to, and who booked them
    titles = {c["id"]: c["title"] for b in (bd.destination(), bd.market()) for c in b["charts"]}
    assert titles["de-nationalities"] == "Who travels here: guest nationalities"
    assert titles["de-markets"] == "Booked from: agency countries"
    assert titles["mk-nationalities"] == "Who travels: guest nationalities"
    assert titles["mk-destinations"] == "Where they go: top 10 destinations"


def test_a_client_is_the_same_code_in_the_hotel_sales_cube():
    hotel = [s["query"] for c in bd.client()["charts"] for s in c["plan"]["steps"] if s["cube"] == bd.HOTEL_SALES]
    assert hotel and all("'Customers'[Id Cli] = \"GTE\" & @F_CLIENT" in q for q in hotel)


def test_the_supplier_list_holds_supplier_connections_only():
    options = bd.supplier()["filters"][0]["options"]
    assert options["value"] == "Module Code" and "'Product Type'[External] = \"Yes\"" in options["query"]
    steps = {s["cube"]: s["query"] for c in bd.supplier()["charts"] for s in c["plan"]["steps"]}
    assert "'Product Type'[Module Code] = @F_SUPPLIER" in steps[bd.BOOKINGS]
    assert "'Suppliers'[Supplier Code] = @F_SUPPLIER" in steps[bd.SUPPLIER_REQUESTS]
    assert "'Suppliers'[Supplier Code] = @F_SUPPLIER" in steps[bd.LOCKS]


def test_every_installation_has_them_even_on_local_files(app_dirs, monkeypatch):
    """Reading local files (a Mac, or DATA_SOURCE=local) the five are there too, each with a note that it reads the
    live cubes; the installation's own dashboards show their numbers as before."""
    dashboards._builtin_checked["time"] = 0.0
    monkeypatch.setattr(config, "BUILTIN_DASHBOARDS", True)
    assert [d["id"] for d in dashboards.list_dashboards()] == IDS
    assert "reads the live bookings cubes" in dashboards.setup_problem(dashboards.get_dashboard("overview"))
    mine = dashboards.get_dashboard(dashboards.create_dashboard("Mine"))
    assert dashboards.setup_problem(mine) == ""


def test_left_out_only_when_switched_off(app_dirs, monkeypatch):
    dashboards._builtin_checked["time"] = 0.0
    monkeypatch.setattr(config, "BUILTIN_DASHBOARDS", False)
    monkeypatch.setattr(config, "DATA_SOURCE", "ssas")
    dashboards.ensure_builtin(force=True)
    assert [d["name"] for d in dashboards.list_dashboards()] == ["Main dashboard"]


# ---------------------------------------------------------------- headline numbers --

def test_a_percentage_changes_in_points_and_look_to_book_is_better_lower():
    margin = next(c for c in bd.overview()["charts"] if c["id"] == "ov-margin")
    assert dashboards.headline_change(margin, 0.089, 0.057) == pytest.approx((0.032, "+3.2 pts"), abs=1e-9)
    sales = next(c for c in bd.overview()["charts"] if c["id"] == "ov-sales")
    assert dashboards.headline_change(sales, 288.0, 778.4)[1] == "-63.0%"
    assert dashboards.headline_change(sales, 5.0, 0.0) == (None, "")  # nothing before: no change to show
    assert dashboards.headline_change(sales, None, 3.0) == (None, "")
    lower = [c["id"] for _, c in CHARTS if c["style"].get("lower_is_better")]
    assert lower == ["ov-l2b", "mk-l2b", "cl-l2b", "su-l2b", "su-response", "su-locks"]
