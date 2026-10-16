"""One dashboard page: its charts for the period you pick on the calendar (period_picker.py) - a
quick choice, days, or week numbers - compared with another period if you like (previous period, the
same period last year or other dates: the period in colour, the comparison in grey). Everyone can view dashboards; adding, editing, restyling,
reordering, copying/moving and deleting charts and dashboards asks for the admin password (the +
buttons are always there; the dialog asks to sign in first). Each dashboard is a page in the menu
(app.py builds one with page_for)."""
from datetime import date, datetime

import pandas as pd
import streamlit as st

import admin
import config
import cubes
import dashboards
import data_layer
import period_picker
import plans
import periods
import ui
from backends import get_backend
import charts
from charts import build_figure, suggest, trim


@st.fragment(run_every=3)
def wait_for_update(keys: list[str]) -> None:
    """While charts are brought up to date in the background: a note, then the page again with the new numbers."""
    if dashboards.still_updating(keys):
        st.caption(":material/sync: Showing the last numbers while the latest load...")
    else:
        st.rerun()


@st.cache_data(ttl=300, show_spinner=False)
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


def headline(c: dict, df) -> str:
    """A headline number written the way Claude chose for it (AED 4.5M, 12.3%), else plainly."""
    nums = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])] if df is not None else []
    value = first_number(df)
    d3, prefix, suffix = charts.number_format(c, nums[0]) if nums else ("", "", "")
    if not (d3 or prefix or suffix):
        d3, prefix, suffix = next(((f.get("d3_format", ""), f.get("prefix", ""), f.get("suffix", ""))
                                   for f in (c.get("style") or {}).get("formats", [])), ("", "", ""))
    return charts.format_number(value, d3, prefix, suffix) if (d3 or prefix or suffix) else fmt(value)


def chart_cubes(c: dict) -> list[str]:
    return plans.Plan.from_chart(c).cubes


def _target_dashboard(choice: str, name: str) -> str:
    return dashboards.create_dashboard(name or "New dashboard") if choice == "new" else choice


def updated_text(cubes_used: list[str]) -> tuple[str, str]:
    """('Data updated 13 Oct, 18:24', one line per cube for the tooltip) from the server times."""
    times = {cb: t for cb in cubes_used if (t := data_as_of(cb))}
    if not times:
        return "", ""
    parsed = {}
    for cb, t in times.items():
        try:
            parsed[cb] = datetime.strptime(t, "%d %b %Y, %H:%M")
        except ValueError:
            pass
    latest = max(parsed.values()) if parsed else None
    head = f"Data updated {latest.day} {latest:%b, %H:%M}" if latest else "Data updated " + next(iter(times.values()))
    return head, "  \n".join(f"{data_layer.cube_label(cb)}: {t}" for cb, t in times.items())


def needs_admin(what: str) -> bool:
    """Inside a dialog: True once signed in as admin, else shows the sign-in form."""
    if admin.signed_in():
        return True
    st.caption(f":material/lock: Dashboards are shared with everyone, so {what} needs the admin password.")
    admin.sign_in_form(scope="fragment")
    return False


# ---------------------------------------------------------------- dialogs --

@st.dialog("Add a chart", width="large")
def add_dialog(dashboard_id: str, start: date, end: date):
    if not needs_admin("adding a chart"):
        return
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
    show_compare = st.toggle("Show the comparison picked at the top of the dashboard", value=c.get("compare", True),
                             key=f"edit_compare_{chart_id}", disabled=not date_col,
                             help="Headline numbers show the change; columns, bars and lines of one measure show the "
                                  "other period in grey; tables get a change column. Needs dates that follow the "
                                  "dashboard.")
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
        c.pop("compare", None)
        if not show_compare:
            c["compare"] = False
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
    if not needs_admin("adding a dashboard"):
        return
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

def kpi_card(dashboard_id: str, c: dict, res: dict, start: date, end: date, is_admin: bool,
             versus: period_picker.Comparison | None) -> None:
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
            delta = f"{(value - prev) / abs(prev):+.1%} vs {versus.name}" if versus and value is not None and prev else None
            source = " + ".join(data_layer.cube_label(x) for x in chart_cubes(c))
            was = (f"  \n{versus.dates}: {headline(c, res['prev'])}"
                   if versus and res.get("prev") is not None and prev is not None else "")
            st.metric(c["title"], headline(c, res["df"]), delta=delta, help=f"{c['question']} · {source}{was}")


def chart_card(dashboard_id: str, c: dict, res: dict, start: date, end: date, is_admin: bool,
               several_cubes: bool, versus: period_picker.Comparison | None = None) -> None:
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
        prev = res.get("prev") if versus else None
        compare = {"df": prev, "current": periods.dates_text(start, end), "name": versus.dates} if prev is not None else None
        fig = build_figure(df, c, dark=ui.is_dark(), height=height, show_title=False, compare=compare)
        if fig is not None:
            st.plotly_chart(fig, key=f"fig_{c['id']}", config={"displayModeBar": False})
            note = trim(df, c)[1] if c.get("chart_type") != "custom" else ""
            if note:
                st.caption(note.split(" (")[0] + ".")
        else:
            shown, spec = charts.with_changes(df, prev, c) if prev is not None else (df, c)
            ui.table(shown, spec, height=min(330, 38 + 35 * len(df)))
            if shown is not df:
                st.caption(f"Change vs {versus.dates}.")


# ---------------------------------------------------------------- page --

def add_tile(dashboard_id: str, start: date, end: date, first: bool = False) -> None:
    """The dashed "+ Add chart" tile at the end of the charts."""
    with st.container(key="addtile_first" if first else "addtile"):
        label = "Add your first chart" if first else "Add chart"
        if st.button(label, icon=":material/add:", key=f"addtile_btn_{'first' if first else 'more'}", width="stretch",
                     help="Describe a chart in plain English; Claude builds it from the data"):
            add_dialog(dashboard_id, start, end)


def render(dashboard_id: str) -> None:
    board = dashboards.get_dashboard(dashboard_id)
    if board is None:
        st.warning("This dashboard was deleted.")
        return
    is_admin = admin.signed_in()
    charts = board["charts"]
    board_cubes = list(dict.fromkeys(x for c in charts for x in chart_cubes(c) if x))

    # title on the left; + Add chart and the dashboard menu on the right
    title_col, actions_col = st.columns([3, 2], vertical_alignment="center")
    with title_col:
        st.title(board["name"], anchor=False)
    with actions_col, st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                                   key="dash_actions"):
        start, end = period_picker.current()[:2]
        if st.button("Add chart", icon=":material/add:", type="primary", key="dash_add"):
            add_dialog(dashboard_id, start, end)
        with st.popover("", icon=":material/more_horiz:", help="Dashboard options"):
            if st.button("New dashboard", icon=":material/dashboard_customize:", key="dash_new", width="stretch"):
                new_dashboard_dialog()
            if st.button("Rename", icon=":material/edit:", key="dash_rename", width="stretch", disabled=not is_admin):
                rename_dialog(board)
            if st.button("Delete dashboard", icon=":material/delete:", key="dash_delete", width="stretch",
                         disabled=not is_admin):
                delete_dashboard_dialog(board)
            if not is_admin:
                st.caption("Renaming and deleting need the admin sign-in (top of the page).")

    # one row of filters above the charts: the period, refresh, and when the data was updated
    with st.container(horizontal=True, vertical_alignment="center", key="dash_filters"):
        start, end, _ = period_picker.picker()
        versus = period_picker.compare_picker()
        force = st.button("", icon=":material/refresh:", type="tertiary", key="dash_refresh",
                          help="Get the latest numbers from the server")
        if force:
            data_as_of.clear()
        updated, per_cube = updated_text(board_cubes)
        if updated:
            st.caption(updated, help=per_cube if len(board_cubes) > 1 else None)

    if not charts:
        with st.container(key="panel_empty"):
            st.markdown("#### Nothing on this dashboard yet")
            st.caption("Add a chart by describing it in plain English, send one from Chat, or start with suggested "
                       "charts.")
            add_tile(dashboard_id, start, end, first=True)
            ready = [cb for cb in cubes.enabled() if cubes.is_ready(cb)]
            if is_admin and ready:
                left, right = st.columns([2, 1], vertical_alignment="bottom")
                cube = left.selectbox("Or create suggested charts from", ready, format_func=data_layer.cube_label,
                                      key="starter_cube")
                if right.button("Create suggested charts", icon=":material/auto_awesome:", width="stretch"):
                    with st.status("Claude is creating the charts...", expanded=True) as status:
                        failed = dashboards.create_starter(dashboard_id, cube, start, end,
                                                           on_done=lambda t: status.write(f"✓ {t}"))
                        status.update(label="Charts created", state="complete")
                    if failed:
                        st.warning("These charts could not be created: " + ", ".join(failed))
                    st.rerun()
        return

    with st.spinner("Loading the latest numbers..."):
        results, updating = dashboards.results_for(charts, start, end, (versus.start, versus.end) if versus else None,
                                                   {cb: data_as_of(cb) for cb in board_cubes}, force=force)
    if updating:
        wait_for_update(updating)

    kpis = [c for c in charts if c["chart_type"] == "kpi"]
    for i in range(0, len(kpis), 4):
        row = kpis[i:i + 4]
        for col, c in zip(st.columns(len(row)), row):
            with col:
                kpi_card(dashboard_id, c, results.get(c["id"], {}), start, end, is_admin, versus)

    several = len(board_cubes) > 1
    draw = lambda c: chart_card(dashboard_id, c, results.get(c["id"], {}), start, end, is_admin, several, versus)
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
        left, right = st.columns(2)
        with left:
            draw(pending)
        with right:
            add_tile(dashboard_id, start, end)
    else:
        add_tile(dashboard_id, start, end)


def page_for(board: dict):
    """A page function for the menu (each dashboard needs its own function name)."""
    def page():
        render(board["id"])
    page.__name__ = f"dashboard_{board['id']}"
    return page
