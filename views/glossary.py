"""Glossary: what our numbers mean. Everyone can read it, admins can edit it, Claude follows it."""
import pandas as pd
import streamlit as st

import admin
import glossary

st.title("📖 Glossary")
st.caption("What our numbers mean. Claude follows these definitions in every answer, "
           "so everyone in the company gets the same numbers for the same question.")

rows, updated = glossary.load()
drafts = [r for r in rows if r.get("Status") != "Agreed"]
if drafts:
    st.warning(f"**{len(drafts)} of {len(rows)} definitions are drafts.** Agree them with the owner "
               "of the numbers (Finance or BI), then mark them *Agreed*. Until then Claude picks "
               "the most likely option and says which one it used under each answer.", icon="📝")
elif rows:
    st.success("All definitions are agreed.", icon="✅")

for i, r in enumerate(rows):
    if i % 2 == 0:
        cols = st.columns(2)  # a new row every two cards keeps them lined up
    with cols[i % 2].container(border=True):
        badge = ":green-badge[Agreed]" if r.get("Status") == "Agreed" else ":orange-badge[Draft]"
        st.markdown(f"#### {r['Term']} {badge}")
        if r.get("Meaning"):
            st.markdown(r["Meaning"])
        if r.get("Measure"):
            st.markdown(f"**Measure:** {r['Measure']}")
        if r.get("Date to use"):
            st.markdown(f"**Date:** {r['Date to use']}")
        if r.get("Agreed by"):
            st.caption(f"Agreed by {r['Agreed by']}")
if updated:
    st.caption(f"Last updated {updated}")

with st.expander("How to agree the glossary"):
    st.markdown(
        "1. Book 30 minutes with the owner of the numbers (Finance or BI).\n"
        "2. For each term, pick the measure and the date. The options available in the "
        "data are listed on each card.\n"
        "3. Check one number together against a report you already trust (e.g. last month's "
        "sales in Power BI).\n"
        "4. An admin edits the term below, sets **Status** to *Agreed* and fills in **Agreed by**.\n"
        "5. Add new terms whenever people use a word the data doesn't know (e.g. *market*, *channel*).")

st.divider()
st.subheader("Edit the glossary")
if admin.sign_in_form():
    edited = st.data_editor(
        pd.DataFrame(rows, columns=glossary.COLUMNS),
        num_rows="dynamic", hide_index=True,
        column_config={
            "Term": st.column_config.TextColumn(required=True),
            "Meaning": st.column_config.TextColumn(width="large"),
            "Measure": st.column_config.TextColumn(help="Exact measure name(s) from the data, e.g. [Final Sales]"),
            "Date to use": st.column_config.TextColumn(help="e.g. 'Create Date' (when the booking was made)"),
            "Status": st.column_config.SelectboxColumn(options=glossary.STATUSES, required=True, default="Draft"),
            "Agreed by": st.column_config.TextColumn(help="Who confirmed it, e.g. Finance - J. Smith"),
        },
    )
    if st.button("Save glossary", type="primary"):
        glossary.save(edited.to_dict("records"))
        st.success("Saved. Claude uses the new definitions from the next question.")
        st.rerun()
