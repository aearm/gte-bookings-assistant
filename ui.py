"""Small pieces of UI shared by the pages, and the Apple-like styling."""
import streamlit as st

import cubes
import dashboards
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

def cube_picker(key: str = "cube", label: str = "Data", container=None) -> str:
    """Pick one of the connected cubes. The choice is shared by Chat and the Glossary."""
    names = cubes.enabled()
    if not names:
        return ""
    if st.session_state.get("cube") not in names:
        st.session_state.cube = names[0]
    where = container or st
    chosen = where.selectbox(label, names, index=names.index(st.session_state.cube), key=f"pick_{key}",
                             format_func=cubes.label)
    st.session_state.cube = chosen
    return chosen


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
    cols = dashboards.date_columns(schema_text(cube))
    options = cols + [""]
    if value not in options:
        value = dashboards.default_date_column(cols, cube)
    return st.selectbox(
        "The dashboard's dates apply to", options, index=options.index(value), key=key,
        format_func=lambda c: dashboards.date_label(c) if c else "Nothing (always show all dates)",
        help="Which date the period picked on the dashboard filters, e.g. when the booking was made.")


def chart_type_picker(value: str, key: str, allow_auto: bool = True) -> str:
    options = [t for t in dashboards.TYPE_LABELS if allow_auto or t != "auto"]
    value = "donut" if value == "pie" else value
    return st.selectbox("Chart type", options, index=options.index(value) if value in options else 0,
                        format_func=dashboards.TYPE_LABELS.get, key=key)


def width_picker(value: str, key: str) -> str:
    return st.radio("Size", ["half", "full"], index=1 if value == "full" else 0, horizontal=True, key=key,
                    format_func=lambda w: "Half width" if w == "half" else "Full width")


def dashboard_period() -> tuple:
    """The period currently picked on the dashboards (This year if none has been opened)."""
    return dashboards.period_range(st.session_state.get("dash_period", "This year"),
                                   st.session_state.get("dash_custom_range"))


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
</style>""", unsafe_allow_html=True)
