"""Admin sign-in for the Settings page and glossary editing. The admin password is stored
only as a salted hash in Windows Credential Manager. Whether you are signed in is shown at the
top of every page (ui.auth_bar)."""
import time

import streamlit as st

import secrets_store


def signed_in() -> bool:
    return st.session_state.get("admin", False)


def sign_out() -> None:
    st.session_state.admin = False


def sign_in_form(scope: str = "app") -> bool:
    """Shows the admin sign-in form (or first-time setup). Returns True when signed in.
    Use scope="fragment" inside a dialog so it stays open after signing in."""
    if signed_in():
        return True

    if not secrets_store.has_admin_password():
        st.info("First, create an admin password. Only people who know it can change keys "
                "and the glossary. **Do this before you share the app link with others.**", icon="🔐")
        with st.form("create_admin"):
            pw = st.text_input("New admin password", type="password")
            pw2 = st.text_input("Type it again", type="password")
            if st.form_submit_button("Create admin password", type="primary"):
                if len(pw) < 8:
                    st.error("Use at least 8 characters.")
                elif pw != pw2:
                    st.error("The two passwords don't match.")
                else:
                    secrets_store.set_admin_password(pw)
                    st.session_state.admin = True
                    st.rerun(scope=scope)
        return False

    with st.form("admin_sign_in"):
        pw = st.text_input("Admin password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            if secrets_store.check_admin_password(pw):
                st.session_state.admin = True
                st.rerun(scope=scope)
            time.sleep(1)  # slows down guessing
            st.error("That password isn't right. (Forgotten it? Run reset_admin_password.py on the server.)")
    return False


@st.dialog("Sign in as admin")
def sign_in_dialog():
    if sign_in_form(scope="fragment"):
        st.success("You're signed in as admin.", icon=":material/verified_user:")
        if st.button("Continue", type="primary"):
            st.rerun()


def locked_page(what: str) -> None:
    """The panel an admin page shows when nobody is signed in, then stops the page."""
    with st.container(key="panel_locked"):
        st.markdown("#### :material/lock: You're not signed in")
        st.caption(f"{what} is for admins. Sign in with the admin password to continue.")
        sign_in_form()
    st.stop()
