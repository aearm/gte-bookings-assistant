"""Chat with the data: ask a question about all the data (Claude picks the cubes from the data
layer, and joins cubes when a question needs several) or about one cube, check Claude's
understanding of it, and get a chart, a short answer and the data. Describe any chart you want
("as a funnel", "sales as bars and profit % as a line on a second axis") and Claude draws it.
Any chart can be sent to any dashboard, or a conversation's charts can become a dashboard."""
from datetime import date

import streamlit as st

import admin
import answer_memory
import answering
import config
import cube_setup
import dashboards
import data_layer
import llm
import periods
import routing
import storage
import ui
from backends import get_backend
from charts import build_figure, trim
from errors import details, friendly

st.markdown("""<style>
[class*="st-key-answer_"] [class*="st-key-addbtn_"], [class*="st-key-answer_"] [class*="st-key-restyle_"] {
    opacity: .6; transition: opacity .15s ease; }
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
        def show_data(df):
            status.update(label="Got the data - drawing the chart...", expanded=True)
            status.dataframe(df.head(200), hide_index=True, height=min(300, 38 + 35 * min(len(df), 200)))

        outcome = answering.ask(question, scope, context, clarification, on_step=status.write, on_data=show_data)
        turn["understanding"] = outcome.result.get("understanding", "")
        if outcome.kind == "clarify":
            turn["clarify"] = {"original": question, "question": outcome.question, "options": outcome.options}
            status.update(label="I need a bit more detail", state="complete")
            return turn
        if outcome.kind == "reuse":  # same data, shown differently
            previous = context[-1]
            turn.update({k: previous[k] for k in ("query", "plan", "cubes", "explanation", "notes") if k in previous})
        else:
            turn.update(query=outcome.plan.text(), plan=outcome.plan.to_dict(), cubes=outcome.plan.cubes,
                        explanation=outcome.result.get("explanation", ""), notes=outcome.notes)
        turn.update(df=outcome.df, spec=outcome.spec, answer_id=outcome.answer_id)
        if outcome.kind == "data":
            turn["file"] = storage.save_result(turn["question"], turn["query"], outcome.df, turn["spec"])
        status.update(label="Done", state="complete")
    return turn


@st.dialog("What Claude can see", width="large")
def show_text(title: str, text: str):
    st.caption(title)
    st.markdown(text)


def chart_context(turn: dict) -> dict:
    """The query and what its numbers are, so Claude formats the chart for them (AED, %, counts)."""
    return {"query": turn.get("query", ""), "measures": data_layer.measure_notes(turn.get("cubes", []),
                                                                                 turn.get("query", ""))}


def chart_turns() -> list[int]:
    """This conversation's answers that have a chart (indexes into the turns)."""
    return [i for i, t in enumerate(st.session_state.get("turns", []))
            if t.get("scope", scope_key) == scope_key and "query" in t and t.get("df") is not None and not t["df"].empty]


def dashboard_defaults(turn: dict) -> dict:
    """How an answer goes on a dashboard unless the admin changes it: its cube (or several), the date
    the dashboard's period applies to, its chart, and its title without the question's dates."""
    used = turn.get("cubes") or []
    cube = used[0] if len(used) == 1 else ""
    cols = dashboards.date_columns(ui.schema_text(cube)) if cube else [dashboards.AUTO_DATE]
    used_date = next((c for c in cols if c in turn["query"]), None) if cube else None
    chart_type = {"pie": "donut"}.get(turn["spec"].get("chart_type", "auto"), turn["spec"].get("chart_type", "auto"))
    chart_type = chart_type if chart_type in dashboards.TYPE_LABELS else "auto"
    return {"cube": cube, "date_column": used_date or dashboards.default_date_column(cols, cube),
            "chart_type": chart_type, "title": periods.without_dates(turn["spec"].get("title") or turn["question"]),
            "request": turn["spec"].get("chart_request", "") if chart_type == "custom" else "",
            "width": "full" if chart_type in ("map", "custom") else "half"}


def dashboard_job(turn: dict, d: dict) -> dict:
    """dashboards.build_chart's arguments (all but the period) for an answer."""
    return {"cube": d["cube"], "question": turn["question"], "title": d["title"], "chart_type": d["chart_type"],
            "width": d["width"], "date_column": d["date_column"], "base_query": turn["query"],
            "base_spec": turn["spec"], "chart_request": d["request"]}


@st.dialog("Add to a dashboard", width="large")
def add_to_dashboard(i: int):
    turn = st.session_state.turns[i]
    if not admin.sign_in_form(scope="fragment"):
        st.caption("Only admins can change the shared dashboards.")
        return
    d = dashboard_defaults(turn)
    target = ui.dashboard_picker(f"chat_add_board_{i}")
    name = st.text_input("Name of the new dashboard", key=f"chat_add_name_{i}") if target == "new" else ""
    d["title"] = st.text_input("Title", value=d["title"], key=f"chat_add_title_{i}")
    d["date_column"] = ui.date_column_picker(d["cube"], d["date_column"], f"chat_add_date_{i}")
    d["chart_type"] = ui.chart_type_picker(d["chart_type"], f"chat_add_type_{i}")
    d["request"] = (ui.chart_request_input(turn["spec"].get("chart_request", ""), f"chat_add_request_{i}").strip()
                    if d["chart_type"] == "custom" else "")
    d["width"] = ui.width_picker("full" if d["chart_type"] in ("map", "custom") else "half", f"chat_add_width_{i}")
    st.caption("On the dashboard the chart follows the period picked there, not the dates in your question. "
               "To compare periods, use **Compare** next to the period.")
    if st.button("Add to dashboard", type="primary", key=f"chat_add_go_{i}",
                 disabled=target == "new" and not name.strip()):
        start, end = ui.dashboard_period()
        with st.spinner("Preparing the chart for the dashboard and testing it..."):
            try:
                chart = dashboards.build_chart(start=start, end=end, **dashboard_job(turn, d))
            except Exception as exc:
                ui.show_exception(exc)
                return
        board_id = dashboards.create_dashboard(name) if target == "new" else target
        dashboards.add_chart(board_id, chart)
        st.success(f"Added **{chart['title']}** to **{dashboards.get_dashboard(board_id)['name']}**.")
        ui.dashboard_link(board_id)


@st.dialog("New dashboard from this conversation", width="large")
def dashboard_from_conversation(indexes: list[int]):
    """The conversation's charts on a dashboard of their own, in the conversation's order, following its
    dates like every dashboard chart. Claude prepares them at the same time; one that can't be prepared
    is reported and the others are still added. Then the new dashboard opens."""
    if not admin.sign_in_form(scope="fragment"):
        st.caption("Only admins can change the shared dashboards.")
        return
    turns, today = st.session_state.turns, date.today()
    jobs = {i: dashboard_defaults(turns[i]) for i in indexes}
    name = st.text_input("Name", value=f"From chat · {today.day} {today:%b}", key="chat_board_name")
    st.markdown("**Charts**")
    chosen = [i for i in indexes if st.checkbox(jobs[i]["title"], value=True, key=f"chat_board_pick_{i}",
                                                 help=turns[i]["question"])]
    st.caption("Every chart follows the dashboard's dates. To compare periods, use **Compare** next to the period.")
    if not st.button(f"Create dashboard with {len(chosen)} chart{'s' if len(chosen) != 1 else ''}", type="primary",
                     key="chat_board_go", disabled=not chosen or not name.strip()):
        return
    start, end = ui.dashboard_period()
    built, failed = {}, {}
    with st.status(f"Preparing {len(chosen)} charts...", expanded=True) as status:
        for i, chart, exc in dashboards.build_many({i: dashboard_job(turns[i], jobs[i]) for i in chosen}, start, end):
            if chart:
                built[i] = chart
                status.write(f"✓ {chart['title']}")
            else:
                failed[i] = friendly(exc)
                status.write(f"✗ {jobs[i]['title']}: {failed[i]}")
        status.update(label=f"{len(built)} of {len(chosen)} charts ready",
                      state="complete" if not failed else "error", expanded=bool(failed))
    if not built:
        st.error("None of the charts could be prepared, so no dashboard was made.")
        return
    board_id = dashboards.create_dashboard(name)
    for i in chosen:  # in the conversation's order
        if i in built:
            dashboards.add_chart(board_id, built[i])
    if not failed:
        st.session_state.go_to_dashboard = board_id  # open it (app.py)
        st.rerun()
    st.warning("Not added: " + "; ".join(f"{jobs[i]['title']} ({failed[i]})" for i in failed))
    st.success(f"Made **{name.strip()}** with {len(built)} chart{'s' if len(built) != 1 else ''}.")
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
        if turn.get("answer_id") and admin.signed_in():
            if turn.get("verified"):
                st.caption(":material/verified: Marked as correct: Claude follows it for similar questions.")
            elif st.button("Mark as correct", icon=":material/verified:", key=f"verify_{i}", type="tertiary",
                           help="Claude uses answers marked correct as examples for similar questions"):
                answer_memory.verify(turn["answer_id"])
                turn["verified"] = True
                st.rerun()
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
            if st.button("What Claude can see", icon=":material/visibility:", type="tertiary", key="see_cube"):
                show_text("What Claude can see", backend.schema_text())
        else:
            st.warning(st.session_state.get("schema_error", "This cube isn't set up yet."))
    elif can_answer:
        built = data_layer.load()
        st.caption(f":material/hub: Data layer · {len(data_layer.layer_cubes())} cubes · built {built.get('built', '')[:10]}")
        if st.button("What Claude can see", icon=":material/visibility:", type="tertiary", key="see_layer"):
            show_text("What Claude reads with every question", routing.cards_text())
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
           "several. Ask for any chart you like. Add any chart to a dashboard, or make a dashboard from the "
           "whole conversation.")
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

with_charts = chart_turns()
if len(with_charts) >= 2 and st.button("Make a dashboard from this conversation", key="add_all_charts",
                                       icon=":material/dashboard_customize:", type="secondary",
                                       help=f"Its {len(with_charts)} charts on a new dashboard"):
    dashboard_from_conversation(with_charts)

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
