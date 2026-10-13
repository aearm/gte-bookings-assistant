"""Settings (admins only): Claude API key, bookings server login, admin password."""
import streamlit as st

import admin
import config
import llm
import secrets_store
from backends import resolve_source
from errors import details, friendly

st.title("⚙️ Settings")
st.caption("Keys and passwords are saved in Windows Credential Manager on the computer running "
           "the app, never in a text file. They are never shown again after saving.")

if not admin.signed_in():
    admin.locked_page("The Settings page")


def show_error(exc: Exception) -> None:
    st.error(friendly(exc))
    with st.expander("Technical details (for support)"):
        st.code(details(exc), language=None)


# ---------------------------------------------------------------- Claude --

st.subheader("Claude API key")
status = secrets_store.api_key_status()
if status == "saved":
    st.success("A key is saved securely.", icon="✅")
elif status == "env":
    st.warning("The key is currently read from the .env file as plain text. Save it here to store "
               "it securely; the copy in .env is then removed.", icon="⚠️")
else:
    st.error("No key is saved. Questions can't be answered until you add one.", icon="🔑")

with st.form("api_key", clear_on_submit=True):
    key = st.text_input("New API key", type="password", placeholder="sk-ant-...",
                        help="Create one at https://platform.claude.com/settings/keys")
    if st.form_submit_button("Save key", type="primary"):
        key = key.strip()
        if not key.startswith("sk-ant-"):
            st.error("That doesn't look like a Claude API key. They start with sk-ant-.")
        else:
            secrets_store.save_api_key(key)
            st.success("Saved. Use **Test Claude** below to check it works.")

if st.button("Test Claude"):
    with st.spinner("Checking the key..."):
        try:
            llm.check_connection()
            st.success(f"The key works (model: {config.CLAUDE_MODEL}).")
        except Exception as exc:
            show_error(exc)


# ---------------------------------------------------------------- bookings server --

st.divider()
st.subheader("Server")
if resolve_source() != "ssas":
    st.info("The app is using local data files, so no server is needed.")
else:
    if not config.SSAS_SERVER:
        st.error("No server set yet.", icon="🖥️")
    elif not config.SSAS_USERNAME:
        st.info("No username set: the app signs in with this computer's Windows login.")
    elif secrets_store.server_password_saved():
        st.success(f"Signed in as **{config.SSAS_USERNAME}**. Password saved securely.", icon="✅")
    else:
        st.error(f"No password saved for **{config.SSAS_USERNAME}**.", icon="🔑")

    with st.form("server_login", clear_on_submit=True):
        server = st.text_input("Server", value=config.SSAS_SERVER, placeholder="bi.company.com:2383",
                               help="The Analysis Services server, as shown in Power BI > Data source settings.")
        username = st.text_input("Username", value=config.SSAS_USERNAME,
                                 help="Exactly as you type it in Excel or Power BI (often name@domain "
                                      "or DOMAIN\\name). Leave blank to use this computer's Windows login.")
        password = st.text_input("Password", type="password",
                                 placeholder="Leave blank to keep the saved password")
        if st.form_submit_button("Save", type="primary"):
            server, username = server.strip(), username.strip()
            if not server:
                st.error("Enter the server.")
            elif username and username != config.SSAS_USERNAME and not password:
                st.error("Enter the password for the new username too.")
            else:
                secrets_store.save_server_address(server, config.SSAS_DATABASE)
                secrets_store.save_server_login(username, password)
                st.success("Saved. Use **Test server** below to check it works, then choose the cubes "
                           "to use on the **Cubes** page.")

    if st.button("Test server"):
        import ssas
        with st.spinner("Connecting to the server..."):
            try:
                found = ssas.list_databases()
                st.success(f"Connected. {len(found)} cubes available - choose them on the Cubes page.")
            except Exception as exc:
                show_error(exc)


# ---------------------------------------------------------------- admin --

st.divider()
st.subheader("Admin password")
with st.form("change_admin", clear_on_submit=True):
    new = st.text_input("New admin password", type="password")
    new2 = st.text_input("Type it again", type="password")
    if st.form_submit_button("Change admin password"):
        if len(new) < 8:
            st.error("Use at least 8 characters.")
        elif new != new2:
            st.error("The two passwords don't match.")
        else:
            secrets_store.set_admin_password(new)
            st.success("Admin password changed.")

if st.button("Sign out of admin", icon=":material/logout:"):
    admin.sign_out()
    st.rerun()
