"""Admin sign-in. The admin password is stored only as a salted hash in Windows Credential
Manager. A pill at the top right of every page shows whether you're signed in (ui.auth_bar).
"Keep me signed in on this computer" stores a signed token in the browser (30 days, ended by
signing out or by changing the admin password), so reloading the page doesn't sign you out."""
import time

import streamlit as st

import secrets_store
from inline_component import InlineComponent

KEEP_DAYS = 30
_ACTION = "_admin_memory_action"   # what the browser should do with its token on the next run
_TRIED = "_admin_memory_tried"     # the token last checked, so a bad one is only tried once

_MEMORY_JS = r"""
export default function (component) {
  const { data, setStateValue } = component;
  const KEY = "bookings-assistant:admin";
  try {
    if (data.store) localStorage.setItem(KEY, data.store);
    if (data.clear) localStorage.removeItem(KEY);
    const token = localStorage.getItem(KEY) || "";
    if (token && !data.signed_in && data.tried !== token) setStateValue("token", token);
  } catch (e) { /* storage blocked: just no "keep me signed in" */ }
}
"""
_memory = InlineComponent("admin_memory", js=_MEMORY_JS)


def signed_in() -> bool:
    return st.session_state.get("admin", False)


def sign_in(keep: bool) -> None:
    st.session_state.admin = True
    if keep:
        st.session_state[_ACTION] = {"store": secrets_store.make_login_token(KEEP_DAYS)}


def sign_out() -> None:
    st.session_state.admin = False
    st.session_state[_ACTION] = {"clear": True}


def _on_token() -> None:
    value = st.session_state.get("admin_memory")
    token = (value.get("token") if hasattr(value, "get") else getattr(value, "token", "")) or ""
    st.session_state[_TRIED] = token
    if secrets_store.check_login_token(token):
        st.session_state.admin = True
    else:  # expired, or the admin password changed: forget it
        st.session_state[_ACTION] = {"clear": True}


def remember_me() -> None:
    """Keeps the browser's "keep me signed in" token in step (invisible; call once per run)."""
    action = st.session_state.pop(_ACTION, None) or {}
    _memory(key="admin_memory", on_token_change=_on_token,
            data={**action, "signed_in": signed_in(), "tried": st.session_state.get(_TRIED, "")})


def sign_in_form(scope: str = "app", name: str = "") -> bool:
    """The admin sign-in form (or first-time setup). Returns True when signed in.
    Use scope="fragment" inside a dialog that should stay open after signing in. name keeps forms
    apart when a page and a dialog both show one (defaults to the scope)."""
    name = name or scope
    if signed_in():
        return True

    if not secrets_store.has_admin_password():
        st.info("First, create an admin password. Only people who know it can change dashboards, keys "
                "and the glossary. **Do this before you share the app link with others.**", icon="🔐")
        with st.form(f"create_admin_{name}", border=False):
            pw = st.text_input("New admin password", type="password")
            pw2 = st.text_input("Type it again", type="password")
            if st.form_submit_button("Create admin password", type="primary", width="stretch"):
                if len(pw) < 8:
                    st.error("Use at least 8 characters.")
                elif pw != pw2:
                    st.error("The two passwords don't match.")
                else:
                    secrets_store.set_admin_password(pw)
                    sign_in(keep=True)
                    st.rerun(scope=scope)
        return False

    with st.form(f"admin_sign_in_{name}", border=False):
        pw = st.text_input("Admin password", type="password", placeholder="Admin password",
                           label_visibility="collapsed")
        keep = st.checkbox("Keep me signed in on this computer", value=True,
                           help=f"For {KEEP_DAYS} days, or until you sign out or the admin password changes.")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            if secrets_store.check_admin_password(pw):
                sign_in(keep)
                st.rerun(scope=scope)
            time.sleep(1)  # slows down guessing
            st.error("That password isn't right. (Forgotten it? Run reset_admin_password.py on the server.)")
    return False


@st.dialog("Sign in as admin", width="small")
def sign_in_dialog():
    st.caption("Admins can add and change dashboards, connect cubes and change settings. "
               "Everyone can use the dashboards and Chat.")
    sign_in_form(scope="app", name="dialog")  # signing in reloads the page, which closes this


def locked_page(what: str) -> None:
    """What an admin page shows when nobody is signed in, then stops the page."""
    _, middle, _ = st.columns([1, 2, 1])
    with middle, st.container(key="panel_locked"):
        st.markdown("#### :material/lock: Admins only")
        st.caption(f"{what} is for admins. Sign in with the admin password to continue.")
        sign_in_form()
    st.stop()
