"""Glossary: what the business words mean in a cube (its map). Everyone can read it, admins can
edit it, and Claude follows it for every question about that cube."""
import pandas as pd
import streamlit as st

import admin
import cube_setup
import cubes
import glossary
import semantic
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

# decisions from the meaning layer (semantic/): only a person can make them; until then the proposed answer is used
made = semantic.decisions(cube)
waiting = [r for r in semantic.decisions() if r["status"] == "proposed"]
if made:
    st.subheader("Decisions")
    st.caption(f"Questions only a person can answer. Until someone agrees, Claude uses the proposed answer. "
               f"{len(waiting)} decision{'s' if len(waiting) != 1 else ''} still open across all cubes.")
    is_admin = admin.signed_in()
    for r in made:
        with st.container(border=True, key=f"decision_{r['id']}"):
            badge = ":green-badge[Agreed]" if r["status"] == "agreed" else ":orange-badge[Proposed]"
            st.markdown(f"**{r['question']}** {badge}")
            if r.get("why"):
                st.caption(r["why"])
            current = r.get("answer", r["proposed"])
            if is_admin:
                options = list(dict.fromkeys([*r.get("options", []), r["proposed"], current]))
                choice = st.radio("Answer", options, index=options.index(current), key=f"decide_{r['id']}",
                                  label_visibility="collapsed")
                if st.button("Agree", key=f"agree_{r['id']}", type="primary" if r["status"] != "agreed" else "secondary"):
                    semantic.save_decision(r["id"], choice)
                    st.rerun()
            else:
                st.caption(f"Answer used: {current}")
    if not is_admin:
        st.caption(":material/lock: Agreeing to decisions needs the admin password.")
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
