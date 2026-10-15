"""Settings (admins only): Claude API key and cost, bookings server login, admin password."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import admin
import config
import llm
import secrets_store
import usage
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


# ---------------------------------------------------------------- Claude cost --

st.divider()
st.subheader("Claude cost")
report = usage.cost_report()
if report["since"] is None:
    st.info("Nothing measured yet. The cost of each question, chart and setup step appears here.")
else:
    a, b, c, d = st.columns(4)
    a.metric("Today", f"${report['today']:,.2f}")
    b.metric("Last 7 days", f"${report['week']:,.2f}")
    c.metric("This month", f"${report['month']:,.2f}")
    d.metric(f"Since {report['since']:%d %b %Y}", f"${report['total']:,.2f}")
    daily = pd.DataFrame([d for d in report["daily"] if d["Day"] >= report["since"]])  # from the first measured day
    fig = go.Figure(go.Bar(x=pd.to_datetime(daily["Day"]), y=daily["Cost ($)"], marker_color="#0a84ff",
                           hovertemplate="%{x|%d %b %Y}: $%{y:.2f}<extra></extra>"))
    fig.update_layout(height=190, margin=dict(l=12, r=0, t=10, b=0), bargap=0.35,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(tickformat="%d %b", dtick=86_400_000 if len(daily) <= 14 else None)
    fig.update_yaxes(tickprefix="$", rangemode="tozero")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    money = st.column_config.NumberColumn(format="$%.2f")
    st.dataframe(pd.DataFrame(report["activities"]), hide_index=True, width="stretch",
                 column_config={"This month ($)": money, "Total ($)": money})
    with st.expander("By model"):
        st.dataframe(pd.DataFrame(report["models"]), hide_index=True, width="stretch",
                     column_config={"Total ($)": money,
                                    "Tokens read": st.column_config.NumberColumn(format="localized"),
                                    "Tokens written": st.column_config.NumberColumn(format="localized")})
    st.caption(f"Estimated from Claude's list prices for every call this app has made since "
               f"{report['since']:%d %b %Y}, when measuring started. Questions answered from memory (asked "
               "again the same day) cost nothing. The exact bill, including anything before that date, is at "
               "[platform.claude.com](https://platform.claude.com/settings/billing). Per-question details "
               "are on the **Usage** page.")


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
