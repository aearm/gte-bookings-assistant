"""Dashboard: the company's saved charts for the period you pick. Everyone can view it;
admins add, edit, reorder and delete charts."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import admin
import config
import dashboards
import ui
from backends import get_backend
from charts import build_figure

backend = get_backend()
is_admin = admin.signed_in()
dark = ui.is_dark()

st.markdown("""<style>
[class*="st-key-card_"] { transition: box-shadow .15s ease; }
[class*="st-key-card_"]:hover { box-shadow: 0 2px 14px rgba(0, 0, 0, .08); }
[class*="st-key-card_"] [data-testid="stPopover"] button { padding: 0 .4rem; min-height: 1.8rem; }
[class*="st-key-card_"] [data-testid="stPopover"] button [data-testid="stIconMaterial"] { display: none; }
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner=False)
def run_cached(items: tuple, start: date, end: date) -> dict:
    charts = [dict(zip(("id", "query", "date_column", "chart_type"), item)) for item in items]
    return dashboards.run_all(charts, start, end)


@st.cache_data(ttl=900, show_spinner=False)
def data_as_of() -> str:
    try:
        return backend.data_as_of()
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


# ---------------------------------------------------------------- dialogs --

@st.dialog("Add a chart", width="large")
def add_dialog(start: date, end: date):
    question = st.text_area("What should the chart show?",
                            placeholder="e.g. Top 10 destination countries by sales")
    title = st.text_input("Title", placeholder="Optional - Claude suggests one")
    chart_type = ui.chart_type_picker("auto", "add_type")
    date_col = ui.date_column_picker(None, "add_date")
    width = ui.width_picker("half", "add_width")
    if st.button("Create chart", type="primary", disabled=not question.strip()):
        with st.spinner("Claude is writing the query and testing it on the data..."):
            try:
                chart = dashboards.build_chart(question.strip(), title, chart_type, width, date_col, start, end)
            except Exception as exc:
                ui.show_exception(exc)
                return
        dashboards.add(chart)
        run_cached.clear()
        st.rerun()


@st.dialog("Edit chart", width="large")
def edit_dialog(chart_id: str, start: date, end: date):
    c = dashboards.get(chart_id)
    if c is None:
        st.warning("This chart no longer exists.")
        return
    title = st.text_input("Title", value=c["title"])
    question = st.text_area("What the chart shows", value=c["question"],
                            help="Changing this asks Claude to write a new query.")
    chart_type = ui.chart_type_picker(c["chart_type"], f"edit_type_{chart_id}", allow_auto=False)
    date_col = ui.date_column_picker(c.get("date_column", ""), f"edit_date_{chart_id}")
    width = ui.width_picker(c.get("width", "half"), f"edit_width_{chart_id}")
    with st.expander("Query (advanced)"):
        query = st.text_area("Query", value=c["query"], height=220, label_visibility="collapsed",
                             help="@START and @END are replaced with the dashboard's dates.")

    if st.button("Save changes", type="primary"):
        kpi_changed = (chart_type == "kpi") != (c["chart_type"] == "kpi")
        try:
            if question.strip() != c["question"] or date_col != c.get("date_column", "") or kpi_changed:
                with st.spinner("Claude is writing a new query and testing it..."):
                    new = dashboards.build_chart(question.strip(), title, chart_type, width, date_col, start, end)
                c = {**new, "id": c["id"]}
            else:
                if query.strip() != c["query"].strip() or (chart_type not in ("kpi", "table") and not c.get("x")):
                    df = backend.run(dashboards.fill_dates(query, start, end, backend), config.MAX_ROWS)
                    if c.get("x") not in df.columns:
                        c.update(dashboards.guess_axes(df))
                c.update(title=title.strip() or c["title"], chart_type=chart_type, width=width, query=query)
        except Exception as exc:
            ui.show_exception(exc)
            return
        dashboards.update(c)
        run_cached.clear()
        st.rerun()


@st.dialog("Delete chart")
def delete_dialog(chart_id: str):
    c = dashboards.get(chart_id)
    st.write(f"Delete **{c['title'] if c else 'this chart'}** from the dashboard for everyone?")
    if st.button("Delete", type="primary"):
        dashboards.delete(chart_id)
        st.rerun()


def admin_menu(c: dict, start: date, end: date) -> None:
    with st.popover("⋮", help="Edit this chart"):
        if st.button("✏️ Edit", key=f"edit_{c['id']}", width="stretch"):
            edit_dialog(c["id"], start, end)
        if st.button("⬆️ Move earlier", key=f"up_{c['id']}", width="stretch"):
            dashboards.move(c["id"], -1)
            st.rerun()
        if st.button("⬇️ Move later", key=f"down_{c['id']}", width="stretch"):
            dashboards.move(c["id"], 1)
            st.rerun()
        if st.button("🗑️ Delete", key=f"del_{c['id']}", width="stretch"):
            delete_dialog(c["id"])


# ---------------------------------------------------------------- cards --

def kpi_card(c: dict, res: dict, start: date, end: date) -> None:
    with st.container(border=True, key=f"card_{c['id']}"):
        if is_admin:
            left, right = st.columns([6, 1], vertical_alignment="top")
            with right:
                admin_menu(c, start, end)
        else:
            left = st.container()
        with left:
            if res.get("error"):
                st.markdown(f"**{c['title']}**")
                ui.show_error(res["error"], res.get("details", ""))
                return
            value, prev = first_number(res["df"]), first_number(res.get("prev"))
            delta = None
            if value is not None and prev:
                delta = f"{(value - prev) / abs(prev):+.1%} vs last year"
            st.metric(c["title"], fmt(value), delta=delta, help=c["question"])


def chart_card(c: dict, res: dict, start: date, end: date) -> None:
    with st.container(border=True, key=f"card_{c['id']}"):
        head, menu = st.columns([12, 1], vertical_alignment="top") if is_admin else (st.container(), None)
        with head:
            st.markdown(f"**{c['title']}**")
            st.caption(f"Dates: {dashboards.date_label(c.get('date_column', ''))}", help=c["question"])
        if menu:
            with menu:
                admin_menu(c, start, end)
        if res.get("error"):
            ui.show_error(res["error"], res.get("details", ""))
            return
        df = res["df"]
        if df is None or df.empty:
            st.info("No data for this period.")
            return
        fig = build_figure(df, c, dark=dark, height=330, show_title=False)
        if fig is not None:
            st.plotly_chart(fig, key=f"fig_{c['id']}", config={"displayModeBar": False})
        else:
            st.dataframe(df, hide_index=True, height=min(330, 38 + 35 * len(df)))


# ---------------------------------------------------------------- page --

top_left, top_right = st.columns([3, 2], vertical_alignment="bottom")
with top_left:
    st.title("📊 Dashboard")
    as_of = data_as_of()
    if as_of:
        st.caption(f"Live data · last refreshed on the server {as_of} (server time)")
with top_right:
    period_col, refresh_col = st.columns([3, 2], vertical_alignment="bottom")
    period = period_col.selectbox("Period", dashboards.PERIODS, index=3, key="dash_period")
    if refresh_col.button("🔄 Refresh", width="stretch", help="Get the latest numbers from the server"):
        run_cached.clear()
        data_as_of.clear()

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
        st.stop()
start, end = dashboards.period_range(period, custom)
st.caption(f"{start:%d %b %Y} – {end - timedelta(days=1):%d %b %Y}")

charts = dashboards.load()
if is_admin:
    if st.button("➕ Add chart"):
        add_dialog(start, end)

if not charts:
    st.info("The dashboard has no charts yet.", icon="📊")
    if is_admin:
        if not backend.schema_file.exists():
            st.warning("Click **Refresh data structure** on the Chat page first.")
        elif st.button("✨ Create starter charts", type="primary",
                       help="Bookings, sales and profit, plus monthly trends and top 10s. Takes about a minute."):
            with st.status("Claude is creating the starter charts...", expanded=True) as status:
                failed = dashboards.create_starter(start, end, on_done=lambda t: status.write(f"✓ {t}"))
                status.update(label="Starter charts created", state="complete")
            if failed:
                st.warning("These charts could not be created: " + ", ".join(failed))
            st.rerun()
    else:
        st.caption("An admin can add charts, or add any chart from the Chat page.")
else:
    with st.spinner("Loading the latest numbers..."):
        items = tuple((c["id"], c["query"], c.get("date_column", ""), c["chart_type"]) for c in charts)
        results = run_cached(items, start, end)

    kpis = [c for c in charts if c["chart_type"] == "kpi"]
    for i in range(0, len(kpis), 4):
        row = kpis[i:i + 4]
        for col, c in zip(st.columns(len(row)), row):
            with col:
                kpi_card(c, results.get(c["id"], {}), start, end)

    pending = None
    for c in [c for c in charts if c["chart_type"] != "kpi"]:
        if c.get("width") == "full":
            if pending:
                chart_card(pending, results.get(pending["id"], {}), start, end)
                pending = None
            chart_card(c, results.get(c["id"], {}), start, end)
        elif pending:
            left, right = st.columns(2)
            with left:
                chart_card(pending, results.get(pending["id"], {}), start, end)
            with right:
                chart_card(c, results.get(c["id"], {}), start, end)
            pending = None
        else:
            pending = c
    if pending:
        left, _ = st.columns(2)
        with left:
            chart_card(pending, results.get(pending["id"], {}), start, end)

if not is_admin:
    with st.expander("✏️ Edit the dashboard (admins)"):
        admin.sign_in_form()
