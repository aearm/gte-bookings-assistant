"""Glossary: what the business words mean in a cube (its map). Everyone can read it, admins can
edit it, and Claude follows it for every question about that cube."""
import pandas as pd
import streamlit as st

import admin
import cube_setup
import cubes
import glossary
import ui

with st.sidebar:
    cube = ui.cube_picker("glossary")
st.title("Glossary")
if cube is None:
    st.info("No cube is connected yet. An admin connects cubes on the Cubes page.")
    st.stop()
st.caption(f"What the words mean in **{cubes.label(cube)}**. Claude follows these definitions in every answer, "
           "so everyone gets the same numbers for the same question.")

rows, updated = glossary.load(cube)
summary = cube_setup.load(cube).get("summary")
if summary:
    st.markdown(summary)
drafts = [r for r in rows if r.get("Status") != "Agreed"]
if not rows:
    st.info("Nothing here yet. An admin sets up this cube on the Cubes page, which fills in the glossary.",
            icon=":material/info:")
    st.page_link("views/cubes_page.py", label="Open the Cubes page", icon=":material/deployed_code:")
elif drafts:
    st.warning(f"**{len(drafts)} of {len(rows)} definitions are drafts.** When a question depends on one, "
               "Claude asks or says which option it used.", icon=":material/edit_note:")

for i, r in enumerate(rows):
    if i % 2 == 0:
        cols = st.columns(2)  # a new row every two cards keeps them lined up
    with cols[i % 2].container(border=True, key=f"card_term_{i}"):
        badge = ":green-badge[Agreed]" if r.get("Status") == "Agreed" else ":orange-badge[Draft]"
        st.markdown(f"#### {r['Term']} {badge}")
        if r.get("Meaning"):
            st.markdown(r["Meaning"])
        details = " · ".join(x for x in (r.get("Measure"), r.get("Date to use") and f"Date: {r['Date to use']}") if x)
        if details:
            st.caption(details)
        if r.get("Agreed by"):
            st.caption(f"Agreed by {r['Agreed by']}")
if updated:
    st.caption(f"Last updated {updated}")

st.divider()
st.subheader("Edit")
if not admin.signed_in():
    st.caption(":material/lock: You're not signed in. Editing the glossary needs the admin password.")
if admin.sign_in_form():
    edited = st.data_editor(
        pd.DataFrame(rows, columns=glossary.COLUMNS),
        num_rows="dynamic", hide_index=True, key=f"edit_glossary_{cubes.slug(cube)}",
        column_config={
            "Term": st.column_config.TextColumn(required=True),
            "Meaning": st.column_config.TextColumn(width="large"),
            "Measure": st.column_config.TextColumn("In the data", help="Exact measure, column or filter, e.g. [Final Sales]"),
            "Date to use": st.column_config.TextColumn(help="e.g. 'Create Date'[Create Date]"),
            "Status": st.column_config.SelectboxColumn(options=glossary.STATUSES, required=True, default="Draft"),
            "Agreed by": st.column_config.TextColumn(help="Who confirmed it, e.g. Finance - J. Smith"),
        },
    )
    if st.button("Save glossary", type="primary"):
        glossary.save(cube, edited.to_dict("records"))
        st.success("Saved. Claude uses the new definitions from the next question.")
        st.rerun()
