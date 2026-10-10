"""Chat with the data: pick a cube, ask a question, check Claude's understanding of it, and get a
chart, a short answer and the data. Any chart can be sent to any dashboard (hover over it)."""
from datetime import date

import streamlit as st

import admin
import config
import cube_setup
import cubes
import dashboards
import data_tools
import glossary
import llm
import storage
import ui
import value_check
from backends import get_backend
from charts import build_figure, trim
from errors import details, friendly

st.markdown("""<style>
[class*="st-key-answer_"] [class*="st-key-addbtn_"] { opacity: 0; transition: opacity .15s ease; }
[class*="st-key-answer_"]:hover [class*="st-key-addbtn_"],
[class*="st-key-answer_"]:focus-within [class*="st-key-addbtn_"] { opacity: 1; }
@media (hover: none) { [class*="st-key-addbtn_"] { opacity: 1 !important; } }
</style>""", unsafe_allow_html=True)

with st.sidebar:
    cube = ui.cube_picker("chat")
if not cube:
    st.title("Chat")
    st.info("No cube is connected yet. An admin connects cubes on the Cubes page.", icon=":material/deployed_code:")
    st.stop()
backend = get_backend(cube)


# ---------------------------------------------------------------- helpers --

def answer(question: str, context: list[dict], clarification: tuple[str, str] | None = None,
           shown_as: str = "") -> dict:
    """Question -> understanding (or a clarifying question) -> query -> data -> chart.
    Retries once if the query fails."""
    schema = backend.schema_text()
    notes = glossary.notes_for_claude(cube)
    today = date.today().isoformat()
    lang = backend.language
    turn = {"question": shown_as or question, "cube": cube}

    with st.status("Working on it...", expanded=False) as status:
        status.write("Understanding the question")
        checks = data_tools.checks(backend, on_step=status.write)
        result = llm.question_to_query(question, schema, notes, today, lang, context, clarification=clarification,
                                       **checks)
        turn["understanding"] = result.get("understanding", "")
        if result.get("needs_clarification"):
            turn["clarify"] = {"original": question, "question": result["clarifying_question"],
                               "options": result.get("options", [])[:4]}
            status.update(label="I need a bit more detail", state="complete")
            return turn
        query = result["query"]
        for attempt in (1, 2):
            status.write("Checking the values it filters on")
            checked = value_check.check(query, lang, schema, backend)
            if checked.problems:  # a value that isn't in the data: ask instead of returning nothing
                problem = checked.problems[0]
                turn["clarify"] = {"original": turn["question"], "question": problem.question(),
                                   "options": problem.suggestions}
                status.update(label="I need a bit more detail", state="complete")
                return turn
            query = checked.query
            try:
                status.write("Pulling the data")
                df = backend.run(query, config.MAX_ROWS)
                break
            except Exception as error:
                if attempt == 2:
                    raise
                status.write("Query failed, asking Claude to fix it")
                result = llm.question_to_query(question, schema, notes, today, lang, context,
                                               failed_query=query, error=str(error)[:1500],
                                               clarification=clarification, **checks)
                query = result["query"]

        turn.update(query=query, explanation=result.get("explanation", ""), df=df, notes=checked.notes)
        if df.empty:
            turn["spec"] = {"chart_type": "table", "title": "No results",
                            "summary": "The query ran but returned no rows. " + (
                                " ".join(checked.notes) or "Try widening the filters or dates.")}
        else:
            status.write("Choosing the best chart")
            turn["spec"] = llm.describe_result(question, df)
        turn["file"] = storage.save_result(turn["question"], turn["query"], df, turn["spec"])
        status.update(label="Done", state="complete")
    return turn


@st.dialog("Add to a dashboard", width="large")
def add_to_dashboard(i: int):
    turn = st.session_state.turns[i]
    if not admin.sign_in_form(scope="fragment"):
        st.caption("Only admins can change the shared dashboards.")
        return
    turn_cube = turn.get("cube", cube)
    target = ui.dashboard_picker(f"chat_add_board_{i}")
    name = st.text_input("Name of the new dashboard", key=f"chat_add_name_{i}") if target == "new" else ""
    title = st.text_input("Title", value=turn["spec"].get("title") or turn["question"])
    used = next((c for c in dashboards.date_columns(ui.schema_text(turn_cube)) if c in turn["query"]), None)
    date_col = ui.date_column_picker(turn_cube, used, f"chat_add_date_{i}")
    chart_type = ui.chart_type_picker(turn["spec"].get("chart_type", "auto"), f"chat_add_type_{i}")
    width = ui.width_picker("full" if chart_type == "map" else "half", f"chat_add_width_{i}")
    st.caption("On the dashboard the chart follows the period picked there, not the dates in your question.")
    if st.button("Add to dashboard", type="primary", disabled=target == "new" and not name.strip()):
        start, end = ui.dashboard_period()
        with st.spinner("Preparing the chart for the dashboard and testing it..."):
            try:
                chart = dashboards.build_chart(turn_cube, turn["question"], title, chart_type, width, date_col,
                                               start, end, base_query=turn["query"], base_spec=turn["spec"])
            except Exception as exc:
                ui.show_exception(exc)
                return
        board_id = dashboards.create_dashboard(name) if target == "new" else target
        dashboards.add_chart(board_id, chart)
        st.success(f"Added **{chart['title']}** to **{dashboards.get_dashboard(board_id)['name']}**.")
        ui.dashboard_link(board_id)


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
        if not df.empty:
            for note in turn.get("notes", []):
                st.caption(f"ℹ️ {note}")
        with st.container(key=f"answer_{i}"):
            fig = build_figure(df, spec, dark=ui.is_dark(), height=440 if spec.get("chart_type") == "map" else None)
            if fig is not None:
                st.plotly_chart(fig, key=f"chart_{i}", config={"displaylogo": False})
                note = trim(df, spec)[1]
                if note:
                    st.caption(note)
            else:
                ui.table(df)
            if not df.empty and st.button("Add to dashboard", icon=":material/add_chart:", key=f"addbtn_{i}"):
                add_to_dashboard(i)
        with st.expander(f"Data ({len(df)} rows)"):
            ui.table(df)
            st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name="result.csv", mime="text/csv", key=f"dl_{i}")
        with st.expander(f"{backend.language} query"):
            if turn.get("explanation"):
                st.caption(turn["explanation"])
            st.code(turn["query"], language="sql")
            if backend.supports_schedule and st.button("Save this query for scheduled pulls", key=f"save_{i}"):
                name = storage.save_query_for_schedule(spec.get("title") or turn["question"], turn["query"])
                st.success(f"Saved as queries/{name}. pull.py will refresh it on schedule.")


# ---------------------------------------------------------------- sidebar --

if backend.key == "local" and "schema_checked" not in st.session_state:
    # Local files can change between runs, so re-read their structure on start-up.
    st.session_state.schema_checked = True
    try:
        backend.refresh_schema()
    except Exception as exc:
        st.session_state.schema_error = friendly(exc)

with st.sidebar:
    st.caption(backend.label)
    if backend.schema_file.exists():
        st.caption(f":material/check_circle: Ready · {cube_setup.status_label(cube)}")
        with st.expander("What Claude can see"):
            st.markdown(backend.schema_text())
    else:
        st.warning(st.session_state.get("schema_error", "This cube isn't set up yet."))
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
st.caption(f"Ask about **{cubes.label(cube)}** in plain English. Claude checks the data first, tells you how it "
           "understood the question, and asks if something is unclear. Hover over a chart to add it to a dashboard.")
if not config.ANTHROPIC_API_KEY:
    st.warning("No Claude API key is set yet, so questions can't be answered.", icon=":material/key:")
    st.page_link("views/settings.py", label="Add it on the Settings page", icon=":material/settings:")
if backend.key == "ssas" and not config.SSAS_SERVER:
    st.warning("No server is set yet.", icon=":material/dns:")
    st.page_link("views/settings.py", label="Add it on the Settings page", icon=":material/settings:")
if not backend.schema_file.exists():
    st.info("This cube isn't set up yet. An admin sets it up once on the Cubes page.", icon=":material/info:")
    st.page_link("views/cubes_page.py", label="Open the Cubes page", icon=":material/deployed_code:")
    st.stop()

if "turns" not in st.session_state:
    st.session_state.turns = []
turns = [t for t in st.session_state.turns if t.get("cube", cube) == cube]  # this cube's conversation

if not turns:
    examples = cube_setup.example_questions(cube)
    if examples:
        st.markdown("##### Try asking")
        cols = st.columns(2)
        for k, q in enumerate(examples[:6]):
            if cols[k % 2].button(q, key=f"example_{k}", width="stretch"):
                st.session_state.pending = q

for i, t in enumerate(st.session_state.turns):
    if t.get("cube", cube) == cube:
        show_turn(i, t)

typed = st.chat_input(f"Ask a question about {cubes.label(cube)}")
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
        turn = {"question": f"{cl['original']} → {reply}", "cube": cube, "error": friendly(exc),
                "details": details(exc)}
    st.session_state.turns.append(turn)
    st.rerun()
elif typed or from_history:
    question = typed or from_history
    context = [t for t in turns if "query" in t]
    try:
        turn = answer(question, context)
    except Exception as exc:
        turn = {"question": question, "cube": cube, "error": friendly(exc), "details": details(exc)}
    st.session_state.turns.append(turn)
    st.rerun()
