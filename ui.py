"""Small pieces of UI shared by the pages, and the Apple-like styling."""
import streamlit as st

import admin
import cubes
import dashboards
import data_layer
import periods
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


def table(df, height=None) -> None:
    """A results table with readable numbers (thousands separators, no long decimals)."""
    import pandas as pd
    numbers = {c: st.column_config.NumberColumn(format="localized") for c in df.columns
               if pd.api.types.is_numeric_dtype(df[c])}
    st.dataframe(df.round(2), hide_index=True, column_config=numbers, height=height or "auto")


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
    return st.session_state.get("dash_range") or periods.preset_range(periods.DEFAULT_PRESET)


# ---------------------------------------------------------------- signed in or not --

def auth_bar() -> None:
    """A bar at the top of every page that says plainly whether you are signed in as admin."""
    with st.container(key="authbar_in" if admin.signed_in() else "authbar_out"):
        text_col, button_col = st.columns([5, 1], vertical_alignment="center")
        if admin.signed_in():
            text_col.markdown(":material/verified_user: **Signed in as admin** · you can edit dashboards, "
                              "cubes, the glossary and settings")
            if button_col.button("Sign out", icon=":material/logout:", key="authbar_signout", width="stretch"):
                admin.sign_out()
                st.rerun()
        else:
            text_col.markdown(":material/lock: **Not signed in** · view only. Dashboards and Chat work; "
                              "editing needs the admin password")
            if button_col.button("Sign in", icon=":material/login:", key="authbar_signin", type="primary",
                                 width="stretch"):
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
.st-key-authbar_out, .st-key-authbar_in {{ border-radius: 14px; padding: 6px 10px 6px 16px; }}
.st-key-authbar_out {{ background: {"rgba(255,159,10,.16)" if dark else "#fff4e0"};
    border: 1px solid {"rgba(255,159,10,.45)" if dark else "#ffd391"}; }}
.st-key-authbar_in {{ background: {"rgba(48,209,88,.14)" if dark else "#e9f8ee"};
    border: 1px solid {"rgba(48,209,88,.40)" if dark else "#a6e3b8"}; }}
.st-key-authbar_out p, .st-key-authbar_in p {{ margin: 0; }}
</style>""", unsafe_allow_html=True)
