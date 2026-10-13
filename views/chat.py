"""Chat with the data: ask a question about all the data (Claude picks the cubes from the data
layer, and joins cubes when a question needs several) or about one cube, check Claude's
understanding of it, and get a chart, a short answer and the data. Describe any chart you want
("as a funnel", "sales as bars and profit % as a line on a second axis") and Claude draws it.
Any chart can be sent to any dashboard (hover over it)."""
import streamlit as st

import admin
import answering
import config
import cube_setup
import dashboards
import data_layer
import llm
import storage
import ui
from backends import get_backend
from charts import build_figure, trim
from errors import details, friendly

st.markdown("""<style>
[class*="st-key-answer_"] [class*="st-key-addbtn_"], [class*="st-key-answer_"] [class*="st-key-restyle_"] {
    opacity: 0; transition: opacity .15s ease; }
[class*="st-key-answer_"]:hover [class*="st-key-addbtn_"], [class*="st-key-answer_"]:hover [class*="st-key-restyle_"],
[class*="st-key-answer_"]:focus-within [class*="st-key-addbtn_"],
[class*="st-key-answer_"]:focus-within [class*="st-key-restyle_"] { opacity: 1; }
@media (hover: none) { [class*="st-key-addbtn_"], [class*="st-key-restyle_"] { opacity: 1 !important; } }
</style>""", unsafe_allow_html=True)

with st.sidebar:
    scope = ui.cube_picker("chat", allow_all=True)
if scope is None:
    st.title("Chat")
    st.info("No cube is connected yet. An admin connects cubes on the Cubes page.", icon=":material/deployed_code:")
    st.stop()
scope_key = scope or ui.ALL_DATA
scope_name = data_layer.cube_label(scope) if scope else "all the data"


# ---------------------------------------------------------------- helpers --

def answer(question: str, context: list[dict], clarification: tuple[str, str] | None = None,
           shown_as: str = "") -> dict:
    """Question -> understanding (or a clarifying question) -> plan -> data -> chart."""
    turn = {"question": shown_as or question, "scope": scope_key}
    with st.status("Working on it...", expanded=False) as status:
        outcome = answering.answer(question, scope, context, clarification, on_step=status.write)
        turn["understanding"] = outcome.result.get("understanding", "")
        if outcome.kind == "clarify":
            turn["clarify"] = {"original": question, "question": outcome.question, "options": outcome.options}
            status.update(label="I need a bit more detail", state="complete")
            return turn
        request = outcome.result.get("chart_request", "")
        if outcome.kind == "reuse":  # same data, shown differently
            previous = context[-1]
            turn.update({k: previous[k] for k in ("query", "plan", "cubes", "explanation", "df", "notes")
                         if k in previous})
            status.write("Drawing the chart you asked for")
            turn["spec"] = llm.describe_result(question, turn["df"], chart_request=request or question,
                                               **chart_context(turn))
            status.update(label="Done", state="complete")
            return turn
        df = outcome.df
        turn.update(query=outcome.plan.text(), plan=outcome.plan.to_dict(), cubes=outcome.plan.cubes,
                    explanation=outcome.result.get("explanation", ""), df=df, notes=outcome.notes)
        if df.empty:
            turn["spec"] = {"chart_type": "table", "title": "No results",
                            "summary": "The query ran but returned no rows. " + (
                                " ".join(outcome.notes) or "Try widening the filters or dates.")}
        else:
            status.write("Drawing the chart you asked for" if request else "Choosing the best chart")
            turn["spec"] = llm.describe_result(question, df, chart_request=request, **chart_context(turn))
        turn["file"] = storage.save_result(turn["question"], turn["query"], df, turn["spec"])
        status.update(label="Done", state="complete")
    return turn


def chart_context(turn: dict) -> dict:
    """The query and what its numbers are, so Claude formats the chart for them (AED, %, counts)."""
    return {"query": turn.get("query", ""), "measures": data_layer.measure_notes(turn.get("cubes", []),
                                                                                 turn.get("query", ""))}


@st.dialog("Add to a dashboard", width="large")
def add_to_dashboard(i: int):
    turn = st.session_state.turns[i]
    if not admin.sign_in_form(scope="fragment"):
        st.caption("Only admins can change the shared dashboards.")
        return
    used = turn.get("cubes") or []
    chart_cube = used[0] if len(used) == 1 else ""
    target = ui.dashboard_picker(f"chat_add_board_{i}")
    name = st.text_input("Name of the new dashboard", key=f"chat_add_name_{i}") if target == "new" else ""
    title = st.text_input("Title", value=turn["spec"].get("title") or turn["question"])
    date_used = next((c for c in dashboards.date_columns(ui.schema_text(chart_cube)) if c in turn["query"]),
                     None) if chart_cube else None
    date_col = ui.date_column_picker(chart_cube, date_used, f"chat_add_date_{i}")
    chart_type = ui.chart_type_picker(turn["spec"].get("chart_type", "auto"), f"chat_add_type_{i}")
    request = (ui.chart_request_input(turn["spec"].get("chart_request", ""), f"chat_add_request_{i}")
               if chart_type == "custom" else "")
    width = ui.width_picker("full" if chart_type in ("map", "custom") else "half", f"chat_add_width_{i}")
    st.caption("On the dashboard the chart follows the period picked there, not the dates in your question.")
    if st.button("Add to dashboard", type="primary", disabled=target == "new" and not name.strip()):
        start, end = ui.dashboard_period()
        with st.spinner("Preparing the chart for the dashboard and testing it..."):
            try:
                chart = dashboards.build_chart(chart_cube, turn["question"], title, chart_type, width, date_col,
                                               start, end, base_query=turn["query"], base_spec=turn["spec"],
                                               chart_request=request.strip())
            except Exception as exc:
                ui.show_exception(exc)
                return
        board_id = dashboards.create_dashboard(name) if target == "new" else target
        dashboards.add_chart(board_id, chart)
        st.success(f"Added **{chart['title']}** to **{dashboards.get_dashboard(board_id)['name']}**.")
        ui.dashboard_link(board_id)


@st.dialog("Change the chart", width="large")
def restyle(i: int):
    turn = st.session_state.turns[i]
    st.caption("Same numbers, drawn the way you describe.")
    request = ui.chart_request_input(turn["spec"].get("chart_request", ""), f"restyle_text_{i}")
    if st.button("Draw it", type="primary", disabled=not request.strip()):
        with st.spinner("Claude is drawing the chart you described..."):
            try:
                spec = llm.describe_result(turn["question"], turn["df"], chart_request=request.strip(),
                                           **chart_context(turn))
            except Exception as exc:
                ui.show_exception(exc)
                return
        turn["spec"] = {**spec, "summary": turn["spec"].get("summary", spec.get("summary", ""))}
        st.rerun()


def show_turn(i: int, turn: dict) -> None:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        if "error" in turn:
            ui.show_error(turn["error"], turn.get("details", ""))
            return
        if turn.get("understanding"):
            st.info(f"**I understood your question as:** {turn['understanding']}", icon=":material/explore:")
        if "clarify" in turn:
            cl = turn["clarify"]
            st.markdown(f"**{cl['question']}**")
            for row in range(0, len(cl["options"]), 3):
                cols = st.columns(3)
                for j, option in enumerate(cl["options"][row:row + 3], start=row):
                    if cols[j - row].button(option, key=f"opt_{i}_{j}", width="stretch",
                                            disabled=turn.get("answered", False)):
                        st.session_state.pending_reply = option
                        st.rerun()
            if not turn.get("answered"):
                st.caption("Pick an answer, or type your own below.")
            return
        spec, df = turn["spec"], turn["df"]
        st.markdown(spec.get("summary", ""))
        if len(turn.get("cubes", [])) > 1:
            st.caption(":material/join: Combined from " + " + ".join(data_layer.cube_label(c) for c in turn["cubes"]))
        if spec.get("note"):
            st.caption(f"ℹ️ {spec['note']}")
        if not df.empty:
            for note in turn.get("notes", []):
                st.caption(f"ℹ️ {note}")
        with st.container(key=f"answer_{i}"):
            fig = build_figure(df, spec, dark=ui.is_dark(), height=440 if spec.get("chart_type") in ("map", "custom") else None)
            if fig is not None:
                st.plotly_chart(fig, key=f"chart_{i}", config={"displaylogo": False})
                note = trim(df, spec)[1] if spec.get("chart_type") != "custom" else ""
                if note:
                    st.caption(note)
            else:
                ui.table(df, spec)
            if not df.empty:
                add_col, restyle_col, _ = st.columns([1, 1, 3])
                if add_col.button("Add to dashboard", icon=":material/add_chart:", key=f"addbtn_{i}"):
                    add_to_dashboard(i)
                if restyle_col.button("Change chart", icon=":material/palette:", key=f"restyle_{i}"):
                    restyle(i)
        with st.expander(f"Data ({len(df)} rows)"):
            ui.table(df, spec)
            st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name="result.csv", mime="text/csv", key=f"dl_{i}")
        used = turn.get("cubes") or []
        language = get_backend(used[0]).language if used else "DAX"
        with st.expander(f"{language} query" + (f" ({len(used)} cubes, joined)" if len(used) > 1 else "")):
            if turn.get("explanation"):
                st.caption(turn["explanation"])
            st.code(turn["query"], language="sql")
            if (len(used) == 1 and get_backend(used[0]).supports_schedule
                    and st.button("Save this query for scheduled pulls", key=f"save_{i}")):
                name = storage.save_query_for_schedule(spec.get("title") or turn["question"], turn["query"])
                st.success(f"Saved as queries/{name}. pull.py will refresh it on schedule.")


# ---------------------------------------------------------------- sidebar --

if get_backend(scope or None).key == "local" and "schema_checked" not in st.session_state:
    # Local files can change between runs, so re-read their structure on start-up.
    st.session_state.schema_checked = True
    try:
        get_backend(scope or None).refresh_schema()
    except Exception as exc:
        st.session_state.schema_error = friendly(exc)

can_answer, why_not = answering.ready(scope)
with st.sidebar:
    if scope:
        backend = get_backend(scope)
        st.caption(backend.label)
        if backend.schema_file.exists():
            st.caption(f":material/check_circle: Ready · {cube_setup.status_label(scope)}")
            with st.expander("What Claude can see"):
                st.markdown(backend.schema_text())
        else:
            st.warning(st.session_state.get("schema_error", "This cube isn't set up yet."))
    elif can_answer:
        layer = data_layer.status()
        st.caption(f":material/hub: Data layer · {len(layer['cubes'])} cubes · built {layer['built'][:10]}")
        with st.expander("What Claude can see"):
            st.markdown(data_layer.catalog_text())
    if st.button("Clear conversation", icon=":material/delete_sweep:"):
        st.session_state.turns = []

    history = storage.load_history()
    if history:
        st.subheader("Recent questions")
        for j, h in enumerate(history):
            if st.button(h["question"][:60], key=f"hist_{j}", type="tertiary"):
                st.session_state.pending = h["question"]


# ---------------------------------------------------------------- main --

st.title("Chat")
st.caption(f"Ask about **{scope_name}** in plain English. Claude checks the data first, tells you how it "
           "understood the question, asks if something is unclear, and combines cubes when a question needs "
           "several. Ask for any chart you like. Hover over a chart to add it to a dashboard or change it.")
if not config.ANTHROPIC_API_KEY:
    st.warning("No Claude API key is set yet, so questions can't be answered.", icon=":material/key:")
    st.page_link("views/settings.py", label="Add it on the Settings page", icon=":material/settings:")
if config.resolve_source() == "ssas" and not config.SSAS_SERVER:
    st.warning("No server is set yet.", icon=":material/dns:")
    st.page_link("views/settings.py", label="Add it on the Settings page", icon=":material/settings:")
if not can_answer:
    st.info(why_not, icon=":material/info:")
    st.page_link("views/cubes_page.py", label="Open the Cubes page", icon=":material/deployed_code:")
    st.stop()

if "turns" not in st.session_state:
    st.session_state.turns = []
turns = [t for t in st.session_state.turns if t.get("scope", scope_key) == scope_key]  # this scope's conversation

if not turns:
    examples = (data_layer.example_questions() if not scope else
                cube_setup.example_questions(scope) or data_layer.profile(scope).get("example_questions", []))
    if examples:
        st.markdown("##### Try asking")
        cols = st.columns(2)
        for k, q in enumerate(examples[:6]):
            if cols[k % 2].button(q, key=f"example_{k}", width="stretch"):
                st.session_state.pending = q

for i, t in enumerate(st.session_state.turns):
    if t.get("scope", scope_key) == scope_key:
        show_turn(i, t)

typed = st.chat_input(f"Ask a question about {scope_name}")
reply = st.session_state.pop("pending_reply", None)
from_history = st.session_state.pop("pending", None)
open_question = turns[-1] if turns and "clarify" in turns[-1] and not turns[-1].get("answered") else None
if typed and open_question and not reply:
    reply, typed = typed, None  # typed text answers the clarifying question

if reply and open_question:
    open_question["answered"] = True
    cl = open_question["clarify"]
    context = [t for t in turns if "query" in t]
    try:
        turn = answer(cl["original"], context, clarification=(cl["question"], reply),
                      shown_as=f"{cl['original']} → {reply}")
    except Exception as exc:
        turn = {"question": f"{cl['original']} → {reply}", "scope": scope_key, "error": friendly(exc),
                "details": details(exc)}
    st.session_state.turns.append(turn)
    st.rerun()
elif typed or from_history:
    question = typed or from_history
    context = [t for t in turns if "query" in t]
    try:
        turn = answer(question, context)
    except Exception as exc:
        turn = {"question": question, "scope": scope_key, "error": friendly(exc), "details": details(exc)}
    st.session_state.turns.append(turn)
    st.rerun()
