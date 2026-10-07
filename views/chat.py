"""Chat with the data: ask a question, check Claude's understanding of it, get a chart, a short
answer and the data. Any chart can be added to the dashboard (hover over it)."""
from datetime import date

import streamlit as st

import admin
import config
import dashboards
import glossary
import llm
import storage
import ui
from backends import get_backend
from charts import build_figure
from errors import details, friendly

backend = get_backend()

st.markdown("""<style>
[class*="st-key-answer_"] [class*="st-key-addbtn_"] { opacity: 0; transition: opacity .15s ease; }
[class*="st-key-answer_"]:hover [class*="st-key-addbtn_"],
[class*="st-key-answer_"]:focus-within [class*="st-key-addbtn_"] { opacity: 1; }
@media (hover: none) { [class*="st-key-addbtn_"] { opacity: 1 !important; } }
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers --

def refresh_schema() -> str:
    text, a, b = backend.build_schema()
    backend.schema_file.write_text(text, encoding="utf-8")
    return backend.schema_summary(a, b)


def answer(question: str, context: list[dict], clarification: tuple[str, str] | None = None,
           shown_as: str = "") -> dict:
    """Question -> understanding (or a clarifying question) -> query -> data -> chart.
    Retries once if the query fails."""
    schema = ui.schema_text()
    notes = glossary.notes_for_claude()
    today = date.today().isoformat()
    lang = backend.language
    turn = {"question": shown_as or question}

    with st.status("Working on it...", expanded=False) as status:
        status.write("Understanding the question")
        result = llm.question_to_query(question, schema, notes, today, lang, context, clarification=clarification)
        turn["understanding"] = result.get("understanding", "")
        if result.get("needs_clarification"):
            turn["clarify"] = {"original": question, "question": result["clarifying_question"],
                               "options": result.get("options", [])[:4]}
            status.update(label="I need a bit more detail", state="complete")
            return turn
        try:
            status.write("Pulling the data")
            df = backend.run(result["query"], config.MAX_ROWS)
        except Exception as first_error:
            status.write("Query failed, asking Claude to fix it")
            result = llm.question_to_query(question, schema, notes, today, lang, context,
                                           failed_query=result["query"], error=str(first_error)[:1500],
                                           clarification=clarification)
            df = backend.run(result["query"], config.MAX_ROWS)

        turn.update(query=result["query"], explanation=result.get("explanation", ""), df=df)
        if df.empty:
            turn["spec"] = {"chart_type": "table", "title": "No results",
                            "summary": "The query ran but returned no rows. Try widening the filters or dates."}
        else:
            status.write("Choosing a chart")
            turn["spec"] = llm.describe_result(question, df)
        turn["file"] = storage.save_result(turn["question"], turn["query"], df, turn["spec"])
        status.update(label="Done", state="complete")
    return turn


@st.dialog("Add to dashboard", width="large")
def add_to_dashboard(i: int):
    turn = st.session_state.turns[i]
    if not admin.sign_in_form(scope="fragment"):
        st.caption("Only admins can change the shared dashboard.")
        return
    title = st.text_input("Title", value=turn["spec"].get("title") or turn["question"])
    used = next((c for c in dashboards.date_columns(ui.schema_text()) if c in turn["query"]), None)
    date_col = ui.date_column_picker(used, f"chat_add_date_{i}")
    chart_type = ui.chart_type_picker(turn["spec"].get("chart_type", "auto"), f"chat_add_type_{i}")
    width = ui.width_picker("half", f"chat_add_width_{i}")
    st.caption("On the dashboard the chart follows the period picked there, not the dates in your question.")
    if st.button("Add to dashboard", type="primary"):
        start, end = ui.dashboard_period()
        with st.spinner("Preparing the chart for the dashboard and testing it..."):
            try:
                chart = dashboards.build_chart(turn["question"], title, chart_type, width, date_col, start, end,
                                               base_query=turn["query"], base_spec=turn["spec"])
            except Exception as exc:
                ui.show_exception(exc)
                return
        dashboards.add(chart)
        st.success(f"Added **{chart['title']}** to the dashboard.")
        st.page_link("views/dashboard.py", label="Open the dashboard", icon="📊")


def show_turn(i: int, turn: dict) -> None:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        if "error" in turn:
            ui.show_error(turn["error"], turn.get("details", ""))
            return
        if turn.get("understanding"):
            st.info(f"**I understood your question as:** {turn['understanding']}", icon="🧭")
        if "clarify" in turn:
            cl = turn["clarify"]
            st.markdown(f"**{cl['question']}**")
            cols = st.columns(max(len(cl["options"]), 1))
            for j, option in enumerate(cl["options"]):
                if cols[j].button(option, key=f"opt_{i}_{j}", width="stretch", disabled=turn.get("answered", False)):
                    st.session_state.pending_reply = option
                    st.rerun()
            if not turn.get("answered"):
                st.caption("Pick an answer, or type your own below.")
            return
        spec, df = turn["spec"], turn["df"]
        st.markdown(spec.get("summary", ""))
        with st.container(key=f"answer_{i}"):
            fig = build_figure(df, spec, dark=ui.is_dark())
            if fig is not None:
                st.plotly_chart(fig, key=f"chart_{i}")
            else:
                st.dataframe(df, hide_index=True)
            if not df.empty and st.button("➕ Add to dashboard", key=f"addbtn_{i}"):
                add_to_dashboard(i)
        with st.expander(f"Data ({len(df)} rows)"):
            st.dataframe(df, hide_index=True)
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
        refresh_schema()
    except Exception as exc:
        st.session_state.schema_error = friendly(exc)

with st.sidebar:
    st.header("📊 Bookings Assistant")
    st.caption(backend.label)

    if backend.schema_file.exists():
        st.success("Data structure loaded")
    else:
        st.warning(st.session_state.get("schema_error", "Data structure not read yet"))
    if st.button("Refresh data structure"):
        with st.spinner("Reading tables and columns..."):
            try:
                st.success(refresh_schema())
            except Exception as exc:
                ui.show_error(f"Could not read the data structure. {friendly(exc)}", details(exc))

    if backend.schema_file.exists():
        with st.expander("What Claude can see"):
            st.markdown(ui.schema_text())

    if st.button("Clear conversation"):
        st.session_state.turns = []

    history = storage.load_history()
    if history:
        st.subheader("Recent questions")
        for j, h in enumerate(history):
            if st.button(h["question"][:60], key=f"hist_{j}"):
                st.session_state.pending = h["question"]


# ---------------------------------------------------------------- main --

st.title("💬 Chat with your data")
st.caption("Ask in plain English, e.g. *Bookings by month this year*, "
           "*Top 10 destinations by revenue in 2026*, *Compare this month with the same month last year*. "
           "Hover over a chart to add it to the dashboard.")
st.page_link("views/glossary.py", label="What do sales, revenue and profit mean here? See the Glossary", icon="📖")
if not config.ANTHROPIC_API_KEY:
    st.warning("No Claude API key is set yet, so questions can't be answered.", icon="🔑")
    st.page_link("views/settings.py", label="Add it on the Settings page", icon="⚙️")
if backend.key == "ssas" and not config.SSAS_SERVER:
    st.warning("No bookings server is set yet.", icon="🖥️")
    st.page_link("views/settings.py", label="Add it on the Settings page", icon="⚙️")
if backend.key == "local":
    st.info("Local mode: answering from the files in **data/local** (sample data unless you add your own).",
            icon="💻")

if "turns" not in st.session_state:
    st.session_state.turns = []

for i, t in enumerate(st.session_state.turns):
    show_turn(i, t)

typed = st.chat_input("Ask a question about the bookings data")
reply = st.session_state.pop("pending_reply", None)
from_history = st.session_state.pop("pending", None)
turns = st.session_state.turns
open_question = turns[-1] if turns and "clarify" in turns[-1] and not turns[-1].get("answered") else None
if typed and open_question and not reply:
    reply, typed = typed, None  # typed text answers the clarifying question

if (typed or from_history or reply) and not backend.schema_file.exists():
    st.error("Click **Refresh data structure** in the sidebar first.")
elif reply and open_question:
    open_question["answered"] = True
    cl = open_question["clarify"]
    context = [t for t in turns if "query" in t]
    try:
        turn = answer(cl["original"], context, clarification=(cl["question"], reply),
                      shown_as=f"{cl['original']} → {reply}")
    except Exception as exc:
        turn = {"question": f"{cl['original']} → {reply}", "error": friendly(exc), "details": details(exc)}
    turns.append(turn)
    st.rerun()
elif typed or from_history:
    question = typed or from_history
    context = [t for t in turns if "query" in t]
    try:
        turn = answer(question, context)
    except Exception as exc:
        turn = {"question": question, "error": friendly(exc), "details": details(exc)}
    turns.append(turn)
    st.rerun()
