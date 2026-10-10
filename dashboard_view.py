"""One dashboard page: its charts for the period you pick. Everyone can view dashboards; admins
create, rename and delete them, and add, edit, reorder, copy/move and delete charts. Each dashboard
is a page in the menu (app.py builds one with page_for)."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import admin
import config
import cubes
import dashboards
import ui
from backends import get_backend
from charts import build_figure, suggest, trim


@st.cache_data(ttl=900, show_spinner=False)
def run_cached(items: tuple, start: date, end: date) -> dict:
    charts = [dict(zip(("id", "cube", "query", "date_column", "chart_type"), item)) for item in items]
    return dashboards.run_all(charts, start, end)


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


def _target_dashboard(choice: str, name: str) -> str:
    return dashboards.create_dashboard(name or "New dashboard") if choice == "new" else choice


# ---------------------------------------------------------------- dialogs --

@st.dialog("Add a chart", width="large")
def add_dialog(dashboard_id: str, start: date, end: date):
    cube = ui.cube_picker("add_cube", label="Data")
    question = st.text_area("What should the chart show?", placeholder="e.g. Top 10 destination countries by sales")
    title = st.text_input("Title", placeholder="Optional - Claude suggests one")
    chart_type = ui.chart_type_picker("auto", "add_type")
    date_col = ui.date_column_picker(cube, None, f"add_date_{cubes.slug(cube)}")
    width = ui.width_picker("half", "add_width")
    if st.button("Create chart", type="primary", disabled=not question.strip()):
        with st.spinner("Claude is checking the data, writing the query and testing it..."):
            try:
                chart = dashboards.build_chart(cube, question.strip(), title, chart_type, width, date_col, start, end)
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
    cube = c.get("cube") or cubes.default()
    st.caption(f"Data: {cubes.label(cube)}")
    title = st.text_input("Title", value=c["title"])
    question = st.text_area("What the chart shows", value=c["question"],
                            help="Changing this asks Claude to write a new query.")
    chart_type = ui.chart_type_picker(c["chart_type"], f"edit_type_{chart_id}", allow_auto=False)
    date_col = ui.date_column_picker(cube, c.get("date_column", ""), f"edit_date_{chart_id}")
    width = ui.width_picker(c.get("width", "half"), f"edit_width_{chart_id}")
    with st.expander("Query (advanced)"):
        query = st.text_area("Query", value=c["query"], height=220, label_visibility="collapsed",
                             help="@START and @END are replaced with the dashboard's dates.")

    if st.button("Save changes", type="primary"):
        kpi_changed = (chart_type == "kpi") != (c["chart_type"] == "kpi")
        try:
            if question.strip() != c["question"] or date_col != c.get("date_column", "") or kpi_changed:
                with st.spinner("Claude is writing a new query and testing it..."):
                    new = dashboards.build_chart(cube, question.strip(), title, chart_type, width, date_col,
                                                 start, end)
                c = {**new, "id": c["id"]}
            else:
                if query.strip() != c["query"].strip() or (chart_type not in ("kpi", "table") and not c.get("x")):
                    backend = get_backend(cube)
                    df = backend.run(dashboards.fill_dates(query, start, end, backend), config.MAX_ROWS)
                    if c.get("x") not in df.columns:
                        c.update({k: v for k, v in suggest(df).items() if k in ("x", "y", "color")})
                c.update(title=title.strip() or c["title"], chart_type=chart_type, width=width, query=query)
        except Exception as exc:
            ui.show_exception(exc)
            return
        dashboards.update_chart(dashboard_id, c)
        st.rerun()


@st.dialog("Send to another dashboard")
def send_dialog(dashboard_id: str, chart_id: str):
    c = dashboards.get_chart(dashboard_id, chart_id)
    if c is None:
        return
    st.write(f"**{c['title']}**")
    target = ui.dashboard_picker(f"send_to_{chart_id}", exclude=dashboard_id)
    name = st.text_input("Name of the new dashboard") if target == "new" else ""
    action = st.radio("", ["Copy (keep it here too)", "Move (remove it from here)"], key=f"send_how_{chart_id}",
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

def kpi_card(dashboard_id: str, c: dict, res: dict, start: date, end: date, is_admin: bool) -> None:
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
            delta = f"{(value - prev) / abs(prev):+.1%} vs last year" if value is not None and prev else None
            st.metric(c["title"], fmt(value), delta=delta, help=f"{c['question']} · {cubes.label(c.get('cube', ''))}")


def chart_card(dashboard_id: str, c: dict, res: dict, start: date, end: date, is_admin: bool,
               several_cubes: bool) -> None:
    with st.container(border=True, key=f"card_{c['id']}"):
        head, menu = st.columns([12, 1], vertical_alignment="top") if is_admin else (st.container(), None)
        with head:
            st.markdown(f"**{c['title']}**")
            source = f"{cubes.label(c.get('cube', ''))} · " if several_cubes else ""
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
            note = trim(df, c)[1]
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
    board_cubes = list(dict.fromkeys(c.get("cube", "") for c in charts if c.get("cube")))

    top_left, top_right = st.columns([3, 2], vertical_alignment="bottom")
    with top_left:
        st.title(board["name"])
        times = [f"{cubes.label(cb)} {t}" if len(board_cubes) > 1 else t
                 for cb in board_cubes if (t := data_as_of(cb))]
        if times:
            st.caption("Live data · last refreshed on the server " + " · ".join(times))
    with top_right:
        period_col, refresh_col, more_col = st.columns([3, 2, 1] if is_admin else [3, 2, 0.01],
                                                       vertical_alignment="bottom")
        period = period_col.selectbox("Period", dashboards.PERIODS, index=3, key="dash_period")
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

    custom = None
    if period == "Custom":
        today = date.today()
        picked = st.date_input("Dates", value=(today.replace(month=1, day=1), today), format="DD/MM/YYYY",
                               key="dash_custom")
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            custom = (picked[0], picked[1])
            st.session_state.dash_custom_range = custom
        else:
            st.info("Pick an end date.")
            return
    start, end = dashboards.period_range(period, custom)
    st.caption(f"{start:%d %b %Y} – {end - timedelta(days=1):%d %b %Y}")

    if not charts:
        with st.container(key="panel_empty"):
            st.markdown("#### This dashboard is empty")
            if is_admin:
                st.caption("Add a chart with ⋯ › Add chart, send one from Chat, or start with suggested charts.")
                ready = [cb for cb in cubes.enabled() if cubes.is_ready(cb)]
                if ready:
                    cube = st.selectbox("Suggested charts from", ready, format_func=cubes.label, key="starter_cube")
                    if st.button("Create suggested charts", icon=":material/auto_awesome:", type="primary"):
                        with st.status("Claude is creating the charts...", expanded=True) as status:
                            failed = dashboards.create_starter(dashboard_id, cube, start, end,
                                                               on_done=lambda t: status.write(f"✓ {t}"))
                            status.update(label="Charts created", state="complete")
                        if failed:
                            st.warning("These charts could not be created: " + ", ".join(failed))
                        st.rerun()
                else:
                    st.info("Set up a cube on the Cubes page first.")
            else:
                st.caption("An admin can add charts here, or send any chart from Chat.")
    else:
        with st.spinner("Loading the latest numbers..."):
            items = tuple((c["id"], c.get("cube", ""), c["query"], c.get("date_column", ""), c["chart_type"])
                          for c in charts)
            results = run_cached(items, start, end)

        kpis = [c for c in charts if c["chart_type"] == "kpi"]
        for i in range(0, len(kpis), 4):
            row = kpis[i:i + 4]
            for col, c in zip(st.columns(len(row)), row):
                with col:
                    kpi_card(dashboard_id, c, results.get(c["id"], {}), start, end, is_admin)

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

    if not is_admin:
        with st.expander("Edit dashboards (admins)", icon=":material/lock:"):
            admin.sign_in_form()


def page_for(board: dict):
    """A page function for the menu (each dashboard needs its own function name)."""
    def page():
        render(board["id"])
    page.__name__ = f"dashboard_{board['id']}"
    return page
