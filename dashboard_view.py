"""One dashboard page: its charts for the period you pick - a quick choice (this week, last month...),
any dates on the calendar, or week numbers of a year. Everyone can view dashboards; admins create,
rename and delete them, and add, edit, restyle, reorder, copy/move and delete charts. Each dashboard
is a page in the menu (app.py builds one with page_for)."""
from datetime import date

import pandas as pd
import streamlit as st

import admin
import config
import cubes
import dashboards
import data_layer
import periods
import plans
import ui
from backends import get_backend
from charts import build_figure, suggest, trim


@st.cache_data(ttl=900, show_spinner=False)
def run_cached(keys: tuple, start: date, end: date, weekly: bool) -> dict:
    return dashboards.run_all([dashboards.chart_from_key(k) for k in keys], start, end, weekly)


@st.cache_data(ttl=900, show_spinner=False)
def data_as_of(cube: str) -> str:
    try:
        return get_backend(cube).data_as_of()
    except Exception:
        return ""


def fmt(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    return f"{value:,.0f}" if abs(value) >= 1000 or float(value).is_integer() else f"{value:,.2f}"


def first_number(df) -> float | None:
    if df is None or df.empty:
        return None
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    return df[nums[0]].iloc[0] if nums else None


def chart_cubes(c: dict) -> list[str]:
    return plans.Plan.from_chart(c).cubes


def _target_dashboard(choice: str, name: str) -> str:
    return dashboards.create_dashboard(name or "New dashboard") if choice == "new" else choice


# ---------------------------------------------------------------- the period --

def period_picker() -> tuple[date, date, bool]:
    """The period picked on the dashboard: (start, end exclusive, weekly). The choice is kept for
    every dashboard and for charts added from Chat."""
    mode_col, pick_col = st.columns([2, 5], vertical_alignment="center")
    mode = mode_col.segmented_control("Pick the period by", periods.MODES, default="Quick", key="dash_mode",
                                      label_visibility="collapsed",
                                      help="Quick: this week, last month... · Calendar: any dates · "
                                           "Week: ISO week numbers of a year (weeks start on Monday)") or "Quick"
    with pick_col:
        start, end, preset = _pick(mode, date.today())
    st.session_state.dash_range = (start, end)
    return start, end, periods.is_weekly(mode, preset)


def _pick(mode: str, today: date) -> tuple[date, date, str]:
    preset = ""
    if mode == "Quick":
        preset = st.selectbox("Period", periods.PRESETS, index=periods.PRESETS.index(periods.DEFAULT_PRESET),
                              key="dash_period", label_visibility="collapsed")
        start, end = periods.preset_range(preset)
    elif mode == "Calendar":
        picked = st.date_input("Dates", value=(today.replace(month=1, day=1), today), format="DD/MM/YYYY",
                               key="dash_calendar", label_visibility="collapsed")
        if not (isinstance(picked, (tuple, list)) and len(picked) == 2):
            st.caption("Pick the last day too.")
            st.stop()
        start, end = periods.calendar_range(picked[0], picked[1])
    else:
        iso_year, iso_week = periods.current_week(today)
        years = list(range(iso_year + 1, iso_year - 6, -1))
        year_col, from_col, to_col = st.columns([1, 2, 2])
        year = year_col.selectbox("Year", years, index=years.index(iso_year), key="dash_week_year",
                                  label_visibility="collapsed")
        weeks = list(range(1, periods.weeks_in_year(year) + 1))
        default = iso_week if year == iso_year else 1
        first = from_col.selectbox("From week", weeks, index=default - 1, key=f"dash_week_from_{year}",
                                   format_func=lambda w: "From " + periods.week_label(year, w),
                                   label_visibility="collapsed")
        last = to_col.selectbox("To week", weeks, index=max(first, default) - 1, key=f"dash_week_to_{year}",
                                format_func=lambda w: "to " + periods.week_label(year, w),
                                label_visibility="collapsed")
        start, end = periods.week_range(year, first, last)
    return start, end, preset


# ---------------------------------------------------------------- dialogs --

@st.dialog("Add a chart", width="large")
def add_dialog(dashboard_id: str, start: date, end: date):
    cube = ui.cube_picker("add_cube", label="Data", allow_all=True)
    question = st.text_area("What should the chart show?", placeholder="e.g. Top 10 destination countries by sales"
                            + (", or sales and payments by customer" if cube == "" else ""))
    title = st.text_input("Title", placeholder="Optional - Claude suggests one")
    chart_type = ui.chart_type_picker("auto", "add_type")
    request = ui.chart_request_input("", "add_request") if chart_type == "custom" else ""
    date_col = ui.date_column_picker(cube or "", None, f"add_date_{cubes.slug(cube or 'all')}")
    width = ui.width_picker("full" if chart_type == "custom" else "half", "add_width")
    if st.button("Create chart", type="primary",
                 disabled=not question.strip() or (chart_type == "custom" and not request.strip())):
        with st.spinner("Claude is checking the data, writing the query and testing it..."):
            try:
                chart = dashboards.build_chart(cube or "", question.strip(), title, chart_type, width, date_col,
                                               start, end, chart_request=request.strip())
            except Exception as exc:
                ui.show_exception(exc)
                return
        dashboards.add_chart(dashboard_id, chart)
        st.rerun()


@st.dialog("Edit chart", width="large")
def edit_dialog(dashboard_id: str, chart_id: str, start: date, end: date):
    c = dashboards.get_chart(dashboard_id, chart_id)
    if c is None:
        st.warning("This chart no longer exists.")
        return
    plan = plans.Plan.from_chart(c)
    cube = c.get("cube", "") if plan.single else ""
    st.caption("Data: " + " + ".join(data_layer.cube_label(x) for x in plan.cubes))
    title = st.text_input("Title", value=c["title"])
    question = st.text_area("What the chart shows", value=c["question"],
                            help="Changing this asks Claude to write a new query.")
    chart_type = ui.chart_type_picker(c["chart_type"], f"edit_type_{chart_id}", allow_auto=False)
    request = (ui.chart_request_input(c.get("chart_request", ""), f"edit_request_{chart_id}")
               if chart_type == "custom" else "")
    date_col = ui.date_column_picker(cube, c.get("date_column", ""), f"edit_date_{chart_id}")
    width = ui.width_picker(c.get("width", "half"), f"edit_width_{chart_id}")
    query = c.get("query", "")
    with st.expander("Query (advanced)"):
        if plan.single:
            query = st.text_area("Query", value=plan.steps[0].query, height=220, label_visibility="collapsed",
                                 help="@START and @END are replaced with the dashboard's dates.")
        else:
            st.caption("This chart combines several cubes. Change the question to change the queries.")
            st.code(plan.text(), language="sql")

    if st.button("Save changes", type="primary", disabled=chart_type == "custom" and not request.strip()):
        kpi_changed = (chart_type == "kpi") != (c["chart_type"] == "kpi")
        try:
            if question.strip() != c["question"] or date_col != c.get("date_column", "") or kpi_changed:
                with st.spinner("Claude is writing a new query and testing it..."):
                    new = dashboards.build_chart(cube, question.strip(), title, chart_type, width, date_col,
                                                 start, end, chart_request=request.strip())
                c = {**new, "id": c["id"]}
            elif chart_type == "custom" and request.strip() != c.get("chart_request", ""):
                with st.spinner("Claude is drawing the chart you described..."):
                    c = dashboards.restyle_chart(c, request.strip(), start, end)
                c.update(title=title.strip() or c["title"], width=width)
            else:
                query_changed = plan.single and query.strip() != plan.steps[0].query.strip()
                if query_changed:
                    plan = plans.Plan([plans.Step(plan.steps[0].name, plan.steps[0].cube, query)])
                    c.update(plan=plan.to_dict(), query=plan.text())
                if plan.single and (query_changed or
                                    (chart_type not in ("kpi", "table", "custom") and not c.get("x"))):
                    df = plans.run(plan.with_dates(start, end), config.MAX_ROWS)
                    if c.get("x") not in df.columns:
                        c.update({k: v for k, v in suggest(df).items() if k in ("x", "y", "color")})
                if chart_type != "custom":
                    c.pop("custom", None)
                    c.pop("chart_request", None)
                c.update(title=title.strip() or c["title"], chart_type=chart_type, width=width)
        except Exception as exc:
            ui.show_exception(exc)
            return
        dashboards.update_chart(dashboard_id, c)
        st.rerun()


@st.dialog("Change how the chart looks", width="large")
def restyle_dialog(dashboard_id: str, chart_id: str, start: date, end: date):
    c = dashboards.get_chart(dashboard_id, chart_id)
    if c is None:
        return
    st.write(f"**{c['title']}** · same numbers, drawn the way you describe.")
    request = ui.chart_request_input(c.get("chart_request", ""), f"restyle_{chart_id}")
    if st.button("Draw it", type="primary", disabled=not request.strip()):
        with st.spinner("Claude is drawing the chart you described..."):
            try:
                new = dashboards.restyle_chart(c, request.strip(), start, end)
            except Exception as exc:
                ui.show_exception(exc)
                return
        dashboards.update_chart(dashboard_id, new)
        st.rerun()


@st.dialog("Send to another dashboard")
def send_dialog(dashboard_id: str, chart_id: str):
    c = dashboards.get_chart(dashboard_id, chart_id)
    if c is None:
        return
    st.write(f"**{c['title']}**")
    target = ui.dashboard_picker(f"send_to_{chart_id}", exclude=dashboard_id)
    name = st.text_input("Name of the new dashboard") if target == "new" else ""
    action = st.radio("How", ["Copy (keep it here too)", "Move (remove it from here)"], key=f"send_how_{chart_id}",
                      label_visibility="collapsed")
    if st.button("Send", type="primary", disabled=target == "new" and not name.strip()):
        dashboards.send_chart(c, _target_dashboard(target, name),
                              remove_from=dashboard_id if action.startswith("Move") else "")
        st.rerun()


@st.dialog("Delete chart")
def delete_dialog(dashboard_id: str, chart_id: str):
    c = dashboards.get_chart(dashboard_id, chart_id)
    st.write(f"Delete **{c['title'] if c else 'this chart'}** from the dashboard for everyone?")
    if st.button("Delete", type="primary"):
        dashboards.delete_chart(dashboard_id, chart_id)
        st.rerun()


@st.dialog("New dashboard")
def new_dashboard_dialog():
    name = st.text_input("Name", placeholder="e.g. Sales overview")
    if st.button("Create", type="primary", disabled=not name.strip()):
        st.session_state.go_to_dashboard = dashboards.create_dashboard(name)
        st.rerun()


@st.dialog("Rename dashboard")
def rename_dialog(board: dict):
    name = st.text_input("Name", value=board["name"])
    if st.button("Save", type="primary", disabled=not name.strip()):
        dashboards.rename_dashboard(board["id"], name)
        st.rerun()


@st.dialog("Delete dashboard")
def delete_dashboard_dialog(board: dict):
    st.write(f"Delete **{board['name']}** and its {len(board['charts'])} chart(s) for everyone?")
    if st.button("Delete dashboard", type="primary"):
        dashboards.delete_dashboard(board["id"])
        st.rerun()


def chart_menu(dashboard_id: str, c: dict, start: date, end: date) -> None:
    with st.popover("⋯", help="Edit this chart"):
        if st.button("Edit", icon=":material/edit:", key=f"edit_{c['id']}", width="stretch"):
            edit_dialog(dashboard_id, c["id"], start, end)
        if c["chart_type"] != "kpi" and st.button("Change how it looks", icon=":material/palette:",
                                                  key=f"restyle_{c['id']}", width="stretch"):
            restyle_dialog(dashboard_id, c["id"], start, end)
        if st.button("Send to another dashboard", icon=":material/send:", key=f"send_{c['id']}", width="stretch"):
            send_dialog(dashboard_id, c["id"])
        if st.button("Move earlier", icon=":material/arrow_upward:", key=f"up_{c['id']}", width="stretch"):
            dashboards.move_chart(dashboard_id, c["id"], -1)
            st.rerun()
        if st.button("Move later", icon=":material/arrow_downward:", key=f"down_{c['id']}", width="stretch"):
            dashboards.move_chart(dashboard_id, c["id"], 1)
            st.rerun()
        if st.button("Delete", icon=":material/delete:", key=f"del_{c['id']}", width="stretch"):
            delete_dialog(dashboard_id, c["id"])


# ---------------------------------------------------------------- cards --

def kpi_card(dashboard_id: str, c: dict, res: dict, start: date, end: date, is_admin: bool, weekly: bool) -> None:
    with st.container(border=True, key=f"card_{c['id']}"):
        if is_admin:
            left, right = st.columns([6, 1], vertical_alignment="top")
            with right:
                chart_menu(dashboard_id, c, start, end)
        else:
            left = st.container()
        with left:
            if res.get("error"):
                st.markdown(f"**{c['title']}**")
                ui.show_error(res["error"], res.get("details", ""))
                return
            value, prev = first_number(res["df"]), first_number(res.get("prev"))
            than = "same weeks last year" if weekly else "last year"
            delta = f"{(value - prev) / abs(prev):+.1%} vs {than}" if value is not None and prev else None
            source = " + ".join(data_layer.cube_label(x) for x in chart_cubes(c))
            st.metric(c["title"], fmt(value), delta=delta, help=f"{c['question']} · {source}")


def chart_card(dashboard_id: str, c: dict, res: dict, start: date, end: date, is_admin: bool,
               several_cubes: bool) -> None:
    with st.container(border=True, key=f"card_{c['id']}"):
        head, menu = st.columns([12, 1], vertical_alignment="top") if is_admin else (st.container(), None)
        with head:
            st.markdown(f"**{c['title']}**")
            used = chart_cubes(c)
            source = (" + ".join(data_layer.cube_label(x) for x in used) + " · ") if several_cubes or len(used) > 1 else ""
            st.caption(f"{source}Dates: {dashboards.date_label(c.get('date_column', ''))}", help=c["question"])
        if menu:
            with menu:
                chart_menu(dashboard_id, c, start, end)
        if res.get("error"):
            ui.show_error(res["error"], res.get("details", ""))
            return
        df = res["df"]
        if df is None or df.empty:
            st.info("No data for this period.")
            return
        height = 420 if c.get("chart_type") == "map" else 330
        fig = build_figure(df, c, dark=ui.is_dark(), height=height, show_title=False)
        if fig is not None:
            st.plotly_chart(fig, key=f"fig_{c['id']}", config={"displayModeBar": False})
            note = trim(df, c)[1] if c.get("chart_type") != "custom" else ""
            if note:
                st.caption(note.split(" (")[0] + ".")
        else:
            ui.table(df, height=min(330, 38 + 35 * len(df)))


# ---------------------------------------------------------------- page --

def render(dashboard_id: str) -> None:
    board = dashboards.get_dashboard(dashboard_id)
    if board is None:
        st.warning("This dashboard was deleted.")
        return
    is_admin = admin.signed_in()
    charts = board["charts"]
    board_cubes = list(dict.fromkeys(x for c in charts for x in chart_cubes(c) if x))

    top_left, top_right = st.columns([3, 2], vertical_alignment="bottom")
    with top_left:
        st.title(board["name"])
        times = [f"{cubes.label(cb)} {t}" if len(board_cubes) > 1 else t
                 for cb in board_cubes if (t := data_as_of(cb))]
        if times:
            st.caption("Live data · last refreshed on the server " + " · ".join(times))
    with top_right:
        _, refresh_col, more_col = st.columns([3, 2, 1] if is_admin else [3, 2, 0.01], vertical_alignment="bottom")
        if refresh_col.button("Refresh", icon=":material/refresh:", width="stretch",
                              help="Get the latest numbers from the server"):
            run_cached.clear()
            data_as_of.clear()
        if is_admin:
            with more_col.popover("⋯", help="Dashboard options"):
                if st.button("Add chart", icon=":material/add_chart:", key="dash_add", width="stretch"):
                    add_dialog(dashboard_id, *ui.dashboard_period())
                if st.button("New dashboard", icon=":material/dashboard_customize:", key="dash_new", width="stretch"):
                    new_dashboard_dialog()
                if st.button("Rename", icon=":material/edit:", key="dash_rename", width="stretch"):
                    rename_dialog(board)
                if st.button("Delete dashboard", icon=":material/delete:", key="dash_delete", width="stretch"):
                    delete_dashboard_dialog(board)

    with st.container(key="panel_period"):
        start, end, weekly = period_picker()
        st.caption(f":material/calendar_month: {periods.describe(start, end)}")

    if not is_admin:
        st.caption(":material/visibility: View only. Sign in as admin (top of the page) to add or change charts.")

    if not charts:
        with st.container(key="panel_empty"):
            st.markdown("#### This dashboard is empty")
            if is_admin:
                st.caption("Add a chart with ⋯ › Add chart, send one from Chat, or start with suggested charts.")
                ready = [cb for cb in cubes.enabled() if cubes.is_ready(cb)]
                if ready:
                    cube = st.selectbox("Suggested charts from", ready, format_func=data_layer.cube_label,
                                        key="starter_cube")
                    if st.button("Create suggested charts", icon=":material/auto_awesome:", type="primary"):
                        with st.status("Claude is creating the charts...", expanded=True) as status:
                            failed = dashboards.create_starter(dashboard_id, cube, start, end,
                                                               on_done=lambda t: status.write(f"✓ {t}"))
                            status.update(label="Charts created", state="complete")
                        if failed:
                            st.warning("These charts could not be created: " + ", ".join(failed))
                        st.rerun()
                else:
                    st.info("Build the data layer on the Cubes page first.")
            else:
                st.caption("An admin can add charts here, or send any chart from Chat.")
        return

    with st.spinner("Loading the latest numbers..."):
        results = run_cached(tuple(dashboards.run_key(c) for c in charts), start, end, weekly)

    kpis = [c for c in charts if c["chart_type"] == "kpi"]
    for i in range(0, len(kpis), 4):
        row = kpis[i:i + 4]
        for col, c in zip(st.columns(len(row)), row):
            with col:
                kpi_card(dashboard_id, c, results.get(c["id"], {}), start, end, is_admin, weekly)

    several = len(board_cubes) > 1
    draw = lambda c: chart_card(dashboard_id, c, results.get(c["id"], {}), start, end, is_admin, several)
    pending = None
    for c in [c for c in charts if c["chart_type"] != "kpi"]:
        if c.get("width") == "full":
            if pending:
                draw(pending)
                pending = None
            draw(c)
        elif pending:
            left, right = st.columns(2)
            with left:
                draw(pending)
            with right:
                draw(c)
            pending = None
        else:
            pending = c
    if pending:
        left, _ = st.columns(2)
        with left:
            draw(pending)


def page_for(board: dict):
    """A page function for the menu (each dashboard needs its own function name)."""
    def page():
        render(board["id"])
    page.__name__ = f"dashboard_{board['id']}"
    return page
