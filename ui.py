"""Small pieces of UI shared by the pages, and the Apple-like styling."""
import re

import streamlit as st

import admin
import cubes
import dashboards
import data_layer
from backends import get_backend
from errors import details, friendly


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def show_error(message: str, technical: str = "") -> None:
    st.error(message)
    if technical:
        with st.expander("Technical details (for support)"):
            st.code(technical, language=None)


def show_exception(exc: Exception) -> None:
    show_error(friendly(exc), details(exc))


def schema_text(cube: str) -> str:
    return get_backend(cube).schema_text()


def table(df, spec: dict | None = None, height=None) -> None:
    """A results table with readable numbers, formatted like the chart (percent, the currency in the
    column name, thousands separators)."""
    import pandas as pd

    import charts
    numbers = {}
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        d3, prefix, suffix = charts.number_format(spec or {}, c)
        unit = (prefix or suffix).strip()
        label = f"{c} ({unit})" if unit and unit != "%" else None
        if d3.endswith("%"):
            numbers[c] = st.column_config.NumberColumn(label, format="percent")
        elif suffix.strip() == "%":
            numbers[c] = st.column_config.NumberColumn(label, format="%.1f%%")
        else:
            numbers[c] = st.column_config.NumberColumn(label, format="localized")
    st.dataframe(df.round(4), hide_index=True, column_config=numbers, height=height or "auto")


# ---------------------------------------------------------------- pickers --

ALL_DATA = "__all__"  # picker value for "All data": Claude picks the cubes from the data layer


def cube_picker(key: str = "cube", label: str = "Data", container=None, allow_all: bool = False) -> str:
    """Pick one of the connected cubes, or (allow_all) all the data. The choice is shared by Chat
    and the Glossary. Returns the cube, "" for all the data, or None when nothing is connected."""
    names = cubes.enabled()
    if not names:
        return None
    options = ([ALL_DATA] if allow_all and data_layer.is_built() else []) + names
    current = st.session_state.get("cube")
    if current not in options:
        current = options[0]
    where = container or st
    chosen = where.selectbox(label, options, index=options.index(current), key=f"pick_{key}",
                             format_func=lambda c: "All data (Claude picks the cubes)" if c == ALL_DATA
                             else data_layer.cube_label(c))
    st.session_state.cube = chosen
    return "" if chosen == ALL_DATA else chosen


def dashboard_picker(key: str, exclude: str = "") -> str:
    """Pick a dashboard, or "new" to create one (the caller asks for its name)."""
    boards = [d for d in dashboards.list_dashboards() if d["id"] != exclude]
    ids = [d["id"] for d in boards] + ["new"]
    names = {d["id"]: d["name"] for d in boards} | {"new": "➕ New dashboard…"}
    return st.selectbox("Dashboard", ids, format_func=names.get, key=key)


def dashboard_link(board_id: str) -> None:
    """A link to a dashboard page (a dashboard created a moment ago shows in the menu after a refresh)."""
    page = st.session_state.get("board_pages", {}).get(board_id)
    if page:
        st.page_link(page, label="Open the dashboard", icon=":material/space_dashboard:")
    else:
        st.caption("You'll find it under **Dashboards** in the menu.")


def date_column_picker(cube: str, value: str | None, key: str) -> str:
    """Which date the dashboard's period filters. cube "" = a chart that may combine cubes."""
    cols = dashboards.date_columns(schema_text(cube)) if cube else [dashboards.AUTO_DATE]
    options = cols + [""]
    if value not in options:
        value = dashboards.default_date_column(cols, cube)
    return st.selectbox(
        "The dashboard's dates apply to", options, index=options.index(value), key=key,
        format_func=lambda c: dashboards.date_label(c) if c else "Nothing (always show all dates)",
        help="Which date the period picked on the dashboard filters, e.g. when the booking was made. "
             "A chart that combines cubes uses each cube's main date.")


def chart_type_picker(value: str, key: str, allow_auto: bool = True) -> str:
    options = [t for t in dashboards.TYPE_LABELS if allow_auto or t != "auto"]
    value = "donut" if value == "pie" else value
    return st.selectbox("Chart type", options, index=options.index(value) if value in options else 0,
                        format_func=dashboards.TYPE_LABELS.get, key=key)


def chart_request_input(value: str, key: str) -> str:
    return st.text_area("Describe the chart", value=value, key=key,
                        placeholder="e.g. bars for sales by month with a line for profit % on a second axis",
                        help="Any chart Plotly can draw: combos, two axes, stacked percentages, funnels, "
                             "sunbursts, waterfalls... Claude draws it from the chart's data.")


def width_picker(value: str, key: str) -> str:
    return st.radio("Size", ["half", "full"], index=1 if value == "full" else 0, horizontal=True, key=key,
                    format_func=lambda w: "Half width" if w == "half" else "Full width")


def dashboard_period() -> tuple:
    """The period currently picked on the dashboards (this year if none has been picked)."""
    import period_picker
    return period_picker.current()[:2]


# ---------------------------------------------------------------- the menu --

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def nav_section(title: str, add: tuple | None = None, note: str = "") -> None:
    """A heading in the menu; add = (help text, function) puts a + next to it."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"navhead_{_slug(title)}"):
        st.markdown(f"{title} <span class='navnote'>· {note}</span>" if note else title, width="stretch",
                    unsafe_allow_html=True)
        if add and st.button("", icon=":material/add:", type="tertiary", key=f"navadd_{_slug(title)}", help=add[0]):
            add[1]()


def nav_link(page, current) -> None:
    """A page in the menu, highlighted when it's the page you're on."""
    page_id = getattr(page, "_script_hash", None) or page.title
    on = page_id == (getattr(current, "_script_hash", None) or current.title)
    with st.container(key=f"navlink_{'on' if on else 'off'}_{_slug(str(page_id))}"):
        st.page_link(page, label=page.title, icon=page.icon)


# ---------------------------------------------------------------- signed in or not --

def auth_bar() -> None:
    """Top right of every page: an amber "View only · Sign in" pill, or "Admin" with Sign out."""
    with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", key="authrow"):
        if admin.signed_in():
            with st.popover("Admin", icon=":material/verified_user:", key="auth_menu"):
                st.markdown("**Signed in as admin**")
                st.caption("You can add and change dashboards, cubes, the glossary and settings.")
                if st.button("Sign out", icon=":material/logout:", key="auth_signout", width="stretch"):
                    admin.sign_out()
                    st.rerun()
        elif st.button("View only · Sign in", icon=":material/lock:", key="auth_signin",
                       help="Dashboards and Chat work for everyone. Sign in as admin to add or change things."):
            admin.sign_in_dialog()


# ---------------------------------------------------------------- Apple-like styling --

def apply_style() -> None:
    """Rounded white cards with soft shadows, pill buttons, tight headings (colours and the Inter
    font come from .streamlit/config.toml)."""
    dark = is_dark()
    card = "#1c1c1e" if dark else "#ffffff"
    shadow = ("0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35)" if dark
              else "0 1px 2px rgba(0,0,0,.04), 0 6px 20px rgba(0,0,0,.06)")
    lift = ("0 2px 4px rgba(0,0,0,.5), 0 12px 32px rgba(0,0,0,.45)" if dark
            else "0 2px 4px rgba(0,0,0,.05), 0 12px 32px rgba(0,0,0,.10)")
    header = "rgba(0,0,0,.72)" if dark else "rgba(245,245,247,.72)"
    st.markdown(f"""<style>
h1, h2, h3, h4 {{ letter-spacing: -0.022em; }}
h1 {{ font-weight: 700 !important; }}
[data-testid="stMetricValue"] {{ font-weight: 600; letter-spacing: -0.025em; }}
[data-testid="stMetricLabel"] p {{ font-weight: 500; }}
[class*="st-key-card_"], [class*="st-key-panel_"], [data-testid="stChatMessage"] {{
    background: {card}; border: none !important; border-radius: 18px !important;
    box-shadow: {shadow}; transition: box-shadow .2s ease; }}
[class*="st-key-card_"] {{ padding: 4px 6px; }}
[class*="st-key-card_"]:hover {{ box-shadow: {lift}; }}
[data-testid="stChatMessage"] {{ padding: 14px 18px; }}
.stButton button, .stDownloadButton button, .stFormSubmitButton button,
[data-testid="stPopover"] > div > button {{ border-radius: 980px; font-weight: 500; }}
[data-testid="stSidebarNav"] a {{ border-radius: 10px; }}
[data-testid="stSidebarNavSeparator"] {{ display: none; }}
header[data-testid="stHeader"] {{ background: {header}; backdrop-filter: saturate(180%) blur(20px); }}
[data-testid="stExpander"] details {{ border-radius: 14px; }}
[class*="st-key-card_"] [data-testid="stPopover"] button {{ padding: 0 .55rem; min-height: 1.9rem; }}
[class*="st-key-card_"] [data-testid="stPopover"] button [data-testid="stIconMaterial"] {{ display: none; }}
/* the menu: headings with a +, tight links, the page you're on highlighted */
[data-testid="stSidebarHeader"] {{ height: 1.5rem; min-height: 1.5rem; }}
[class*="st-key-navhead_"] {{ margin-top: 1.15rem; margin-bottom: -.45rem; padding: 0 .25rem 0 .55rem; }}
.st-key-navhead_dashboards {{ margin-top: .2rem; }}
.navnote {{ font-weight: 400; font-size: .72rem; opacity: .85; }}
[class*="st-key-navhead_"] p {{ font-size: .78rem; font-weight: 600; margin: 0;
    color: {"#98989d" if dark else "#6e6e73"}; }}
[class*="st-key-navadd_"] button {{ min-height: 1.6rem; height: 1.6rem; width: 1.6rem; padding: 0;
    border-radius: 8px; color: {"#98989d" if dark else "#6e6e73"}; }}
[class*="st-key-navadd_"] button:hover {{ background: {"rgba(255,255,255,.08)" if dark else "rgba(0,0,0,.06)"};
    color: var(--st-primary-color, #0071e3); }}
[class*="st-key-navlink_"] {{ margin-bottom: -.85rem; }}
[class*="st-key-navlink_"] a {{ border-radius: 10px; padding: .32rem .55rem; }}
[class*="st-key-navlink_on_"] a {{ background: {"rgba(255,255,255,.09)" if dark else "rgba(0,0,0,.06)"}; }}
[class*="st-key-navlink_on_"] a p {{ font-weight: 600; }}
/* signed in or not: a pill at the top right of every page */
.st-key-authrow {{ margin: -3.2rem 0 .4rem; min-height: 2rem; }}
.st-key-auth_signin button {{ background: {"rgba(255,159,10,.16)" if dark else "#fff4e0"};
    border: 1px solid {"rgba(255,159,10,.5)" if dark else "#ffd08a"}; color: {"#ffb340" if dark else "#8a4b00"};
    min-height: 2rem; padding: 0 .9rem; font-size: .88rem; }}
.st-key-auth_signin button:hover {{ border-color: {"#ffb340" if dark else "#f5a524"}; }}
.st-key-auth_menu button {{ background: {"rgba(48,209,88,.14)" if dark else "#e9f8ee"};
    border: 1px solid {"rgba(48,209,88,.45)" if dark else "#a6e3b8"}; color: {"#30d158" if dark else "#1a7f37"};
    min-height: 2rem; padding: 0 .9rem; font-size: .88rem; }}
/* dashboards: a tight title, one row of filters, and dashed + tiles */
[class*="st-key-dash_filters"] {{ margin: -0.6rem 0 0.4rem; }}
[class*="st-key-dash_filters"] [data-testid="stCaptionContainer"] {{ margin-left: .25rem; }}
.st-key-addtile button, .st-key-addtile_first button {{
    border: 1.5px dashed {"#48484a" if dark else "#c7c7cc"} !important; background: transparent !important;
    border-radius: 18px !important; color: {"#98989d" if dark else "#6e6e73"}; font-weight: 500;
    transition: border-color .15s ease, color .15s ease, background .15s ease; }}
.st-key-addtile button {{ min-height: 120px; }}
.st-key-addtile_first button {{ min-height: 180px; font-size: 1.05rem; }}
.st-key-addtile button:hover, .st-key-addtile_first button:hover {{
    border-color: var(--st-primary-color, #0071e3) !important; color: var(--st-primary-color, #0071e3);
    background: {"rgba(10,132,255,.08)" if dark else "rgba(0,113,227,.05)"} !important; }}
</style>""", unsafe_allow_html=True)
