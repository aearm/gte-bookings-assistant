"""Small Streamlit components written inline (HTML, CSS and JavaScript as strings, no build step):
the dashboards' calendar (period_picker.py) and "keep me signed in" (admin.py)."""
import streamlit as st


class InlineComponent:
    """Registers the component once, and again if Streamlit's runtime was replaced (a restarted
    server, or each test) while this module stayed imported."""

    def __init__(self, name: str, **definition):
        self.name, self.definition = name, definition
        self._mount = st.components.v2.component(name, **definition)

    def __call__(self, **kwargs):
        try:
            return self._mount(**kwargs)
        except Exception as exc:
            if "not registered" not in str(exc):
                raise
            self._mount = st.components.v2.component(self.name, **self.definition)
            return self._mount(**kwargs)
