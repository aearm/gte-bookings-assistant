"""Ask questions about bookings data in plain English.

Run:  streamlit run app.py   (or run_app.bat on Windows, ./run_app.sh on Mac)
Pages are in the views folder.
"""
import streamlit as st

st.set_page_config(page_title="Bookings Assistant", page_icon="📊", layout="wide")

st.navigation([
    st.Page("views/ask.py", title="Ask", icon="💬", default=True),
    st.Page("views/glossary.py", title="Glossary", icon="📖"),
    st.Page("views/settings.py", title="Settings", icon="⚙️"),
]).run()
