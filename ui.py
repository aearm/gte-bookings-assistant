"""Small pieces of UI shared by the Dashboard and Chat pages."""
import streamlit as st

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


def schema_text() -> str:
    backend = get_backend()
    return backend.schema_file.read_text(encoding="utf-8") if backend.schema_file.exists() else ""


def date_column_picker(value: str | None, key: str) -> str:
    cols = dashboards.date_columns(schema_text())
    options = cols + [""]
    if value not in options:
        value = dashboards.default_date_column(cols)
    return st.selectbox(
        "The dashboard's dates apply to", options, index=options.index(value), key=key,
        format_func=lambda c: dashboards.date_label(c) if c else "Nothing (always show all dates)",
        help="Which date the period picked on the dashboard filters, e.g. when the booking was made.")


def chart_type_picker(value: str, key: str, allow_auto: bool = True) -> str:
    options = [t for t in dashboards.TYPE_LABELS if allow_auto or t != "auto"]
    return st.selectbox("Chart type", options, index=options.index(value) if value in options else 0,
                        format_func=dashboards.TYPE_LABELS.get, key=key)


def width_picker(value: str, key: str) -> str:
    return st.radio("Size", ["half", "full"], index=1 if value == "full" else 0, horizontal=True, key=key,
                    format_func=lambda w: "Half width" if w == "half" else "Full width")


def dashboard_period() -> tuple:
    """The period currently picked on the Dashboard page (This year if it hasn't been opened)."""
    return dashboards.period_range(st.session_state.get("dash_period", "This year"),
                                   st.session_state.get("dash_custom_range"))
