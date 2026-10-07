"""Main page: ask a question, get a chart, a short answer and the data."""
import re
from datetime import date

import streamlit as st

import config
import glossary
import llm
import storage
from backends import get_backend
from charts import build_figure
from errors import details, friendly

backend = get_backend()


# ---------------------------------------------------------------- helpers --

def load_text(path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def refresh_schema() -> str:
    text, a, b = backend.build_schema()
    backend.schema_file.write_text(text, encoding="utf-8")
    return backend.schema_summary(a, b)


def answer(question: str, context: list[dict]) -> dict:
    """Question -> query -> data -> chart. Retries once if the query fails."""
    schema = load_text(backend.schema_file)
    notes = re.sub(r"<!--.*?-->", "", load_text(config.NOTES_FILE), flags=re.DOTALL)
    notes = (notes.strip() + "\n\n" + glossary.prompt_text(glossary.load()[0])).strip()
    today = date.today().isoformat()
    lang = backend.language
    turn = {"question": question}

    with st.status("Working on it...", expanded=False) as status:
        status.write("Writing the query")
        result = llm.question_to_query(question, schema, notes, today, lang, context)
        try:
            status.write("Pulling the data")
            df = backend.run(result["query"], config.MAX_ROWS)
        except Exception as first_error:
            status.write("Query failed, asking Claude to fix it")
            result = llm.question_to_query(question, schema, notes, today, lang, context,
                                           failed_query=result["query"], error=str(first_error)[:1500])
            df = backend.run(result["query"], config.MAX_ROWS)

        turn.update(query=result["query"], explanation=result.get("explanation", ""), df=df)
        if df.empty:
            turn["spec"] = {"chart_type": "table", "title": "No results",
                            "summary": "The query ran but returned no rows. Try widening the filters or dates."}
        else:
            status.write("Choosing a chart")
            turn["spec"] = llm.describe_result(question, df)
        turn["file"] = storage.save_result(question, turn["query"], df, turn["spec"])
        status.update(label="Done", state="complete")
    return turn


def show_error(message: str, technical: str = "") -> None:
    st.error(message)
    if technical:
        with st.expander("Technical details (for support)"):
            st.code(technical, language=None)


def show_turn(i: int, turn: dict) -> None:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        if "error" in turn:
            show_error(turn["error"], turn.get("details", ""))
            return
        spec, df = turn["spec"], turn["df"]
        st.markdown(spec.get("summary", ""))
        fig = build_figure(df, spec)
        if fig is not None:
            st.plotly_chart(fig, key=f"chart_{i}")
        else:
            st.dataframe(df, hide_index=True)
        if turn.get("explanation"):
            st.caption(turn["explanation"])
        with st.expander(f"Data ({len(df)} rows)"):
            st.dataframe(df, hide_index=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name="result.csv", mime="text/csv", key=f"dl_{i}")
        with st.expander(f"{backend.language} query"):
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
                show_error(f"Could not read the data structure. {friendly(exc)}", details(exc))

    if backend.schema_file.exists():
        with st.expander("What Claude can see"):
            st.markdown(load_text(backend.schema_file))

    if st.button("Clear conversation"):
        st.session_state.turns = []

    history = storage.load_history()
    if history:
        st.subheader("Recent questions")
        for j, h in enumerate(history):
            if st.button(h["question"][:60], key=f"hist_{j}"):
                st.session_state.pending = h["question"]


# ---------------------------------------------------------------- main --

st.title("Ask about bookings")
st.caption("Ask in plain English, e.g. *Bookings by month this year*, "
           "*Top 10 destinations by revenue in 2026*, *Compare this month with the same month last year*.")
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
question = typed or st.session_state.pop("pending", None)

if question:
    if not backend.schema_file.exists():
        st.error("Click **Refresh data structure** in the sidebar first.")
    else:
        context = [t for t in st.session_state.turns if "query" in t]
        try:
            turn = answer(question, context)
        except Exception as exc:
            turn = {"question": question, "error": friendly(exc), "details": details(exc)}
        st.session_state.turns.append(turn)
        show_turn(len(st.session_state.turns) - 1, turn)
