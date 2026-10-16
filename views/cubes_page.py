"""Cubes (admins only): connect the cubes people can ask about, build the data layer once (Claude
reads every cube, learns what each is for and how they join), and optionally set each cube up -
let Claude draft a map of the business words, answer the few questions that aren't clear, and
confirm the rest."""
import pandas as pd
import streamlit as st

import admin
import config
import cube_setup
import cubes
import data_layer
import semantic
import ui
from backends import get_backend

st.title("Cubes")
st.caption("Choose which cubes people can ask about, build the data layer once so Claude understands all of "
           "them, and set up each cube's business words.")
if not admin.signed_in():
    admin.locked_page("The Cubes page")


@st.cache_data(ttl=600, show_spinner=False)
def server_cubes() -> pd.DataFrame:
    import ssas
    df = ssas.list_databases()
    return df.sort_values("CATALOG_NAME").reset_index(drop=True)


# ---------------------------------------------------------------- 1. which cubes --

st.subheader("Connected cubes")
if config.resolve_source() != "ssas":
    st.info("Local mode: the only data source is the files in data/local.", icon=":material/folder:")
    connected = cubes.enabled()
else:
    try:
        available = server_cubes()
    except Exception as exc:
        ui.show_exception(exc)
        st.stop()
    current = cubes.enabled()
    with st.form("connected_cubes", border=False):
        st.caption(f"{len(available)} cubes on `{config.SSAS_SERVER}`. Tick the ones to use.")
        picked = []
        cols = st.columns(3)
        for i, row in available.iterrows():
            name = row["CATALOG_NAME"]
            refreshed = pd.to_datetime(row["DATE_MODIFIED"], errors="coerce")
            note = f"updated {refreshed:%d %b %H:%M}" if pd.notna(refreshed) else ""
            if cols[i % 3].checkbox(cubes.label(name), value=name in current, key=f"use_{cubes.slug(name)}",
                                    help=f"{name} · {note}"):
                picked.append(name)
        save_col, all_col, _ = st.columns([1, 1, 3])
        if save_col.form_submit_button("Save", type="primary", width="stretch"):
            # keep the admin's existing order, add new ones at the end
            cubes.set_enabled([c for c in current if c in picked] + [c for c in picked if c not in current])
            st.rerun()
        if all_col.form_submit_button("Use all cubes", width="stretch"):
            names = available["CATALOG_NAME"].tolist()
            cubes.set_enabled([c for c in current if c in names] + [c for c in names if c not in current])
            st.rerun()
    connected = cubes.enabled()

if not connected:
    st.info("Tick at least one cube above.")
    st.stop()

layer = data_layer.status()
with st.container(key="panel_status"):
    rows = [{"Cube": cubes.label(c), "In the data layer": "Yes" if c in layer["cubes"] else "Not yet",
             "Business words": cube_setup.status_label(c)} for c in connected]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---------------------------------------------------------------- 2. the data layer --

st.subheader("Data layer")
with st.container(key="panel_layer"):
    if layer["built"]:
        st.markdown(f":material/check_circle: **Built** {layer['built'].replace('T', ' ')[:16]} with "
                    f"`{layer['model']}` · {len(layer['cubes'])} cube(s) · {layer['entities']} shared dimension(s)")
        if layer["missing"]:
            st.warning(f"{len(layer['missing'])} connected cube(s) are not in the data layer yet: "
                       + ", ".join(cubes.label(c) for c in layer["missing"]) + ". Update it to add them.",
                       icon=":material/add_circle:")
        if layer["changed"]:
            st.warning(f"{len(layer['changed'])} cube(s) changed since the layer was built: "
                       + ", ".join(cubes.label(c) for c in layer["changed"]) + ". Update it.",
                       icon=":material/sync_problem:")
        moved = semantic.drift()
        if moved:
            st.warning(f"The meaning layer (semantic/) was built for an earlier structure of {len(moved)} cube(s): "
                       + ", ".join(cubes.label(c) for c in moved) + ". Answers still work; ask for the meaning layer "
                       "to be checked for these cubes (python semantic.py facts, then check).",
                       icon=":material/rule:")
        else:
            st.caption(f":material/verified: Meaning layer: {len(semantic.decisions())} decisions, "
                       f"{sum(r['status'] == 'agreed' for r in semantic.decisions())} agreed (Glossary › Decisions).")
    else:
        st.markdown("**Build it once after installing.** Claude reads every connected cube (structure and every "
                    "value), learns what each one is for, what its numbers and dates mean, and which customers, "
                    "suppliers, hotels... are the same across cubes, so it can pick the right cube and join cubes "
                    "in one answer. Chat and the dashboards then work from it.")
    for cube, problem in st.session_state.get("layer_errors", {}).items():
        st.warning(f"Left out of the data layer - {cubes.label(cube)}: {problem}")
    st.caption(f"Reading takes about a minute per cube; then Claude ({config.CLAUDE_LAYER_MODEL}) studies them. "
               "Run it again after cubes change.")
    build_col, update_col, _ = st.columns([1.2, 1.4, 2])
    full = build_col.button("Rebuild the data layer" if layer["built"] else "Build the data layer",
                            icon=":material/hub:", type="secondary" if layer["built"] else "primary", width="stretch")
    update = layer["built"] and update_col.button(
        "Update new and changed cubes", icon=":material/sync:", width="stretch",
        type="primary" if layer["missing"] or layer["changed"] else "secondary",
        help="Reads every cube again, and asks Claude only about the cubes that are new or changed.")
    if full or update:
        with st.status("Building the data layer...", expanded=True) as status:
            try:
                built = data_layer.build(only_changed=bool(update), on_progress=status.write)
                status.update(label=f"Data layer ready: {len(built['cubes'])} cube(s), "
                                    f"{len(built['entities'])} shared dimension(s)", state="complete")
                st.session_state.layer_errors = built.get("errors", {})  # shown after the page reloads
            except Exception as exc:
                status.update(label="The data layer could not be built", state="error")
                ui.show_exception(exc)
                st.stop()
        st.rerun()
    if layer["built"]:
        with st.expander("What Claude knows (the data layer)"):
            built = data_layer.load()
            shared = [{"Shared dimension": e["label"],
                       "Cubes and join columns": " · ".join(f"{cubes.label(m['cube'])}: {m['join_column']}"
                                                            for m in e["members"]),
                       "How to join": e.get("join_notes", "")} for e in built.get("entities", [])]
            if shared:
                st.markdown("**Shared dimensions** - how cubes join")
                st.dataframe(pd.DataFrame(shared), hide_index=True, width="stretch")
            routing = [{"Topic": r["topic"], "Cube": cubes.label(r["cube"]), "Why": r["why"]}
                       for r in built.get("routing", [])]
            if routing:
                st.markdown("**Which cube for what**")
                st.dataframe(pd.DataFrame(routing), hide_index=True, width="stretch")
            st.markdown("**Catalog** (given to Claude with every question)")
            st.markdown(data_layer.catalog_text())


# ---------------------------------------------------------------- 3. business words of a cube --

st.subheader("Business words of a cube")
st.caption("Optional, per cube: agree what words like *bookings* or *valid* mean, so everyone gets the same numbers.")
cube = st.selectbox("Cube", connected, format_func=lambda c: f"{cubes.label(c)}  ·  {cube_setup.status_label(c)}",
                    key="setup_cube")
backend = get_backend(cube)
progress = cube_setup.progress(cube)

# Step 1: structure and values
with st.container(key="panel_step1"):
    st.markdown("**1 · Read the structure and values**")
    if progress["structure"]:
        modified = pd.Timestamp(backend.schema_file.stat().st_mtime, unit="s")
        st.caption(f":material/check_circle: Done ({modified:%d %b %H:%M}). Read again after the cube changes "
                   "(new measures, columns or values).")
    else:
        st.caption("Reads every table, measure, column and value (with how much data each has). "
                   "About a minute for a large cube.")
    if st.button("Read again" if progress["structure"] else "Read structure and values",
                 icon=":material/sync:", type="secondary" if progress["structure"] else "primary"):
        with st.spinner(f"Reading {cubes.label(cube)}..."):
            try:
                st.success(backend.refresh_schema())
            except Exception as exc:
                ui.show_exception(exc)
                st.stop()
        st.rerun()

if not progress["structure"]:
    st.stop()

# Step 2: Claude drafts the map
data = cube_setup.load(cube)
with st.container(key="panel_step2"):
    st.markdown("**2 · Let Claude map your business words**")
    if data:
        st.caption(f":material/check_circle: {data.get('summary', '')}")
    else:
        st.caption("Claude reads the structure and values and works out what words like *bookings*, *sales* "
                   "or *destination* mean in this cube. About a minute.")
    if st.button("Map again" if data else "Map the business words", icon=":material/auto_awesome:",
                 type="secondary" if data else "primary"):
        with st.spinner("Claude is reading the cube and drafting the map..."):
            try:
                data = cube_setup.draft(cube)
            except Exception as exc:
                ui.show_exception(exc)
                st.stop()
        st.rerun()

if not data:
    st.stop()

# Step 3: questions
questions = cube_setup.open_items(data, "question")
if questions:
    st.markdown(f"**3 · A few questions** ({len(questions)})")
    st.caption("Your answers become the agreed meaning everyone's questions use. Not sure? Skip it - "
               "Chat will ask whoever needs it.")
for i, item in questions:
    with st.container(key=f"panel_q_{i}"):
        st.markdown(f"##### {item['question']}")
        labels = [o["label"] for o in item["options"]] + ["Something else…"]
        choice = st.radio(item["term"], labels, key=f"q_{i}", label_visibility="collapsed", index=None)
        custom = st.text_input("In your words", key=f"q_custom_{i}") if choice == "Something else…" else ""
        save_col, skip_col, _ = st.columns([1, 1, 3])
        if save_col.button("Save", type="primary", key=f"q_save_{i}",
                           disabled=choice is None or (choice == "Something else…" and not custom.strip())):
            if choice == "Something else…":
                cube_setup.answer(cube, i, custom=custom)
            else:
                cube_setup.answer(cube, i, option=labels.index(choice))
            st.rerun()
        if skip_col.button("Not sure", key=f"q_skip_{i}"):
            cube_setup.skip(cube, i)
            st.rerun()

# Step 4: confirm the rest
proposals = cube_setup.open_items(data, "proposal")
if proposals:
    with st.container(key="panel_step4"):
        st.markdown(f"**{4 if questions else 3} · Check what Claude understood** ({len(proposals)})")
        st.caption("Untick anything that's wrong; it stays as a draft you can fix on the Glossary page.")
        keep = []
        for i, item in proposals:
            if st.checkbox(f"**{item['term']}** — {item['meaning']}", value=True, key=f"p_{i}",
                           help=item["in_data"]):
                keep.append(i)
        if st.button("Confirm", type="primary", icon=":material/done_all:"):
            cube_setup.confirm(cube, keep, [i for i, _ in proposals if i not in keep])
            st.rerun()

if not questions and not proposals:
    st.success(f"**{cubes.label(cube)} is ready.** People can ask about it in Chat; the agreed meanings are on "
               "the Glossary page.", icon=":material/verified:")
    left, right = st.columns(2)
    left.page_link("views/chat.py", label="Ask a question", icon=":material/chat_bubble:")
    right.page_link("views/glossary_page.py", label="See the Glossary", icon=":material/menu_book:")
