"""Ask questions about your cubes in plain English, and keep the useful answers on dashboards.

Run:  streamlit run app.py   (or run_app.bat on Windows, ./run_app.sh on Mac)
Pages: dashboards (dashboard_view.py) and views/ (Chat, Glossary, Cubes, Settings).
"""
import streamlit as st

import admin
import cubes
import dashboard_view
import dashboards
import ui

st.set_page_config(page_title="Bookings Assistant", page_icon=":material/insights:", layout="wide")
cubes.migrate()  # one-time move of files from the single-cube layout
ui.apply_style()

boards = dashboards.list_dashboards()
board_pages = {b["id"]: st.Page(dashboard_view.page_for(b), title=b["name"], icon=":material/space_dashboard:",
                                url_path=f"dashboard-{b['id']}", default=(i == 0))
               for i, b in enumerate(boards)}
locked = "" if admin.signed_in() else " (admin)"  # admin pages say they need signing in
nav = st.navigation({
    "Dashboards": list(board_pages.values()),
    "Ask": [st.Page("views/chat.py", title="Chat", icon=":material/chat_bubble:", url_path="chat"),
            st.Page("views/glossary_page.py", title="Glossary", icon=":material/menu_book:", url_path="glossary")],
    "Admin": [st.Page("views/cubes_page.py", title="Cubes" + locked, url_path="cubes",
                      icon=":material/deployed_code:" if admin.signed_in() else ":material/lock:"),
              st.Page("views/settings.py", title="Settings" + locked, url_path="settings",
                      icon=":material/settings:" if admin.signed_in() else ":material/lock:")],
})
st.session_state.board_pages = board_pages  # for links to a dashboard from other pages
go_to = st.session_state.pop("go_to_dashboard", None)  # just created a dashboard: open it
if go_to in board_pages:
    st.switch_page(board_pages[go_to])
ui.auth_bar()
nav.run()
