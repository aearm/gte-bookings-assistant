"""Ask questions about your cubes in plain English, and keep the useful answers on dashboards.

Run:  streamlit run app.py   (or run_app.bat on Windows, ./run_app.sh on Mac)
Pages: dashboards (dashboard_view.py) and views/ (Chat, Glossary, Cubes, Settings). The menu is
drawn here (not Streamlit's own) so "Dashboards" can have a + for a new dashboard.
"""
import sys

import streamlit as st
import streamlit.delta_generator

import admin
import cubes
import dashboard_view
import dashboards
import ui
import warm_up

# The server's threads take turns on Python's lock every 5 ms by default; a thread that makes many small
# calls (reading rows through the .NET connector, file system calls) waits that long after each one
# while a page is being drawn, and crawls. 1 ms keeps them moving.
sys.setswitchinterval(0.001)
# Streamlit checks once per server start whether it runs in a Python prompt, by reading the source of
# every frame (inspect.stack): on a busy server that took minutes and slowed every page meanwhile. The
# app always runs with `streamlit run`, so the check is marked done.
streamlit.delta_generator._use_warning_has_been_displayed = True

st.set_page_config(page_title="Bookings Assistant", page_icon=":material/insights:", layout="wide")
cubes.migrate()  # one-time move of files from the single-cube layout
ui.apply_style()
warm_up.start()  # once per server start: connector, server connection and value indexes, in the background

boards = dashboards.list_dashboards()
board_pages = {b["id"]: st.Page(dashboard_view.page_for(b), title=b["name"], icon=":material/space_dashboard:",
                                url_path=f"dashboard-{b['id']}", default=(i == 0))
               for i, b in enumerate(boards)}
locked = not admin.signed_in()
ask_pages = [st.Page("views/chat.py", title="Chat", icon=":material/chat_bubble:", url_path="chat"),
             st.Page("views/glossary_page.py", title="Glossary", icon=":material/menu_book:", url_path="glossary")]
admin_pages = [st.Page("views/cubes_page.py", title="Cubes", url_path="cubes",
                       icon=":material/lock:" if locked else ":material/deployed_code:"),
               st.Page("views/settings.py", title="Settings", url_path="settings",
                       icon=":material/lock:" if locked else ":material/settings:"),
               st.Page("views/usage_page.py", title="Usage", url_path="usage",
                       icon=":material/lock:" if locked else ":material/monitoring:")]
current = st.navigation(list(board_pages.values()) + ask_pages + admin_pages, position="hidden")
st.session_state.board_pages = board_pages  # for links to a dashboard from other pages
go_to = st.session_state.pop("go_to_dashboard", None)  # just created a dashboard: open it
if go_to in board_pages:
    st.switch_page(board_pages[go_to])

with st.sidebar:
    ui.nav_section("Dashboards", add=("New dashboard", dashboard_view.new_dashboard_dialog))
    for page in board_pages.values():
        ui.nav_link(page, current)
    ui.nav_section("Ask")
    for page in ask_pages:
        ui.nav_link(page, current)
    ui.nav_section("Admin", note="sign in to open" if locked else "")
    for page in admin_pages:
        ui.nav_link(page, current)
    admin.remember_me()  # signs in again on a computer where "keep me signed in" was ticked

ui.auth_bar()
current.run()
