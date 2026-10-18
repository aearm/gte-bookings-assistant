"""Chat: a conversation's questions answered as a stream of events (progress, the data, the chart),
follow-ups that build on earlier answers, clarifying questions, "as a pie" redraws, CSV downloads,
marking answers correct, and the recent questions. Same steps as views/chat.py, without the page."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Depends, Response

import answer_memory
import answering
import cubes
import dashboards
import data_layer
import llm
import storage
import usage
from backends import get_backend
from errors import details, friendly
from server import conversations, convert
from server.auth import require_admin
from server.replies import ApiError, event, not_found, stream
from server.schemas import Ask, ChartOut, ChartRequest, ConversationOut, HistoryEntry, NewConversation, Ok, Verify

router = APIRouter(tags=["chat"])
_answering = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ask")  # questions being answered


def conversation(conversation_id: str) -> conversations.Conversation:
    conv = conversations.get(conversation_id)
    if conv is None:
        raise not_found("This conversation")
    return conv


def turn_of(conv: conversations.Conversation, turn_id: str) -> dict:
    turn = conv.turn(turn_id)
    if turn is None:
        raise not_found("This answer")
    return turn


# ---------------------------------------------------------------- a turn as JSON --

def has_chart(turn: dict) -> bool:
    """An answer with numbers (it can be redrawn, downloaded and put on a dashboard)."""
    return "query" in turn and turn.get("df") is not None and not turn["df"].empty


def turn_chart(turn: dict) -> dict | None:
    if turn.get("df") is None:
        return None
    if "_chart" not in turn:
        turn["_chart"] = convert.chart(turn["df"], turn.get("spec") or {})
    return turn["_chart"]


def dashboard_modes(turn: dict) -> list[dict]:
    """How the answer can go on a dashboard, the suggested way first (instant = no Claude, no query)."""
    if not has_chart(turn) or not turn.get("plan"):
        return []
    if "_modes" not in turn:
        try:
            turn["_modes"] = dashboards.period_choices(turn)
        except Exception:
            turn["_modes"] = []
    return turn["_modes"]


def turn_json(turn: dict) -> dict:
    used = turn.get("cubes") or []
    clarify = turn.get("clarify")
    return {
        "id": turn["id"], "question": turn["question"], "understanding": turn.get("understanding", ""),
        "query": turn.get("query", ""), "cubes": used, "explanation": turn.get("explanation", ""),
        "notes": turn.get("notes", []) if turn.get("df") is not None and not turn["df"].empty else [],
        "periods": [{"phrase": p.get("phrase", ""), "start": p.get("start", ""), "end": p.get("end", "")}
                    for p in turn.get("periods") or []],
        "table": convert.table(turn.get("df"), turn.get("spec")), "chart": turn_chart(turn),
        "clarify": {"question": clarify["question"], "options": clarify["options"],
                    "answered": bool(turn.get("answered"))} if clarify else None,
        "error": turn.get("error"), "details": turn.get("details"), "answer_id": turn.get("answer_id"),
        "language": get_backend(used[0]).language if used else "", "verified": bool(turn.get("verified")),
        "asked": turn.get("asked", ""), "dashboard_modes": dashboard_modes(turn),
    }


# ---------------------------------------------------------------- answering --

def answer(conv: conversations.Conversation, question: str, context: list[dict],
           clarification: tuple[str, str] | None, shown_as: str, emit) -> dict:
    """Question -> understanding (or a clarifying question) -> plan -> data -> chart, as views/chat.py."""
    turn = {"id": conversations.new_id(), "question": shown_as or question, "scope": conv.scope}
    outcome = answering.ask(question, conv.scope, context, clarification,
                            on_step=lambda text: emit("step", {"text": text}),
                            on_data=lambda df: emit("data", {"table": convert.table(df)}))
    turn["understanding"] = outcome.result.get("understanding", "")
    if outcome.kind == "clarify":
        turn["clarify"] = {"original": question, "question": outcome.question, "options": outcome.options}
        return turn
    if outcome.kind == "reuse":  # same data, shown differently
        previous = context[-1]
        turn.update({k: previous[k] for k in ("query", "plan", "cubes", "explanation", "notes", "periods",
                                              "standalone", "asked") if k in previous})
    else:  # periods: the question's own, kept so the chart can go on a dashboard as it is
        turn.update(query=outcome.plan.text(), plan=outcome.plan.to_dict(), cubes=outcome.plan.cubes,
                    explanation=outcome.result.get("explanation", ""), notes=outcome.notes,
                    periods=outcome.result.get("periods", []),
                    standalone=outcome.result.get("standalone_question", ""))
    turn.update(df=outcome.df, spec=outcome.spec, answer_id=outcome.answer_id)
    turn.setdefault("asked", datetime.now().isoformat(timespec="seconds"))  # when its numbers were read
    if outcome.kind == "data":
        turn["file"] = storage.save_result(turn["question"], turn["query"], outcome.df, turn["spec"])
    return turn


def run_question(conv: conversations.Conversation, body: Ask, emit) -> None:
    """The work of one question, in a worker thread: emit(event, data) sends the stream's events."""
    with conv.lock:
        turns = conv.turns
        open_question = turns[-1] if turns and "clarify" in turns[-1] and not turns[-1].get("answered") else None
        clarification, shown_as, question = None, "", body.question.strip()
        if body.clarification:  # the answer to the clarifying question: the original question is asked again
            reply = body.clarification.answer.strip()
            original = open_question["clarify"]["original"] if open_question else question
            asked = body.clarification.question or (open_question["clarify"]["question"] if open_question else "")
            clarification, shown_as, question = (asked, reply), f"{original} → {reply}", original
            if open_question:
                open_question["answered"] = True
        elif open_question:
            open_question["answered"] = True  # a new question instead of an answer
        context = [t for t in turns if "query" in t]
        pending = conv.pending = {"question": shown_as or question, "steps": []}

        def noted(name, data):  # the progress, also for a page that opens the conversation meanwhile
            if name == "step":
                pending["steps"].append(str((data or {}).get("text", "")))
            emit(name, data)
        try:
            if not question:
                raise ApiError(400, "Type a question first.")
            turn = answer(conv, question, context, clarification, shown_as, noted)
        except Exception as exc:
            message = exc.detail if isinstance(exc, ApiError) else friendly(exc)
            turn = {"id": conversations.new_id(), "question": shown_as or question, "scope": conv.scope,
                    "error": message, "details": "" if isinstance(exc, ApiError) else details(exc)}
            turns.append(turn)
            conv.pending = None
            emit("error", {"message": turn["error"], "details": turn["details"], "turn": turn_json(turn)})
            return
        turns.append(turn)
        conv.pending = None
    if "clarify" in turn:
        emit("clarify", {"question": turn["clarify"]["question"], "options": turn["clarify"]["options"]})
    else:
        if turn.get("df") is not None and turn["df"].empty:
            emit("data", {"table": convert.table(turn["df"])})  # no rows: answering.ask doesn't send them
        emit("chart", {"chart": turn_chart(turn)})
    emit("done", {"turn": turn_json(turn)})


async def events(conv: conversations.Conversation, body: Ask):
    """The stream: run_question in a worker thread, its events passed on as they come. If the browser
    goes away, the question still finishes and its answer stays in the conversation."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(name, data):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (name, data))
        except RuntimeError:
            pass  # the server is stopping

    def work():
        try:
            run_question(conv, body, emit)
        except Exception as exc:  # never leave the stream hanging
            emit("error", {"message": friendly(exc), "details": details(exc)})
        finally:
            emit(None, None)

    loop.run_in_executor(_answering, work)
    while True:
        name, data = await queue.get()
        if name is None:
            return
        yield event(name, data)


# ---------------------------------------------------------------- routes --

@router.post("/conversations")
def new_conversation(body: NewConversation) -> dict:
    if body.scope and body.scope not in cubes.enabled():
        raise ApiError(400, "That cube isn't connected. Pick another one, or All data.")
    return {"id": conversations.create(body.scope).id}


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def read_conversation(conversation_id: str) -> dict:
    conv = conversation(conversation_id)
    pending = conv.pending
    return {"id": conv.id, "scope": conv.scope, "turns": [turn_json(t) for t in list(conv.turns)],
            "pending": {"question": pending["question"], "steps": list(pending["steps"])} if pending else None}


@router.post("/conversations/{conversation_id}/ask")
def ask(conversation_id: str, body: Ask):
    """SSE: step* -> clarify | data -> chart -> done; error on failure (see docs/api.md)."""
    return stream(events(conversation(conversation_id), body))


def chart_context(turn: dict) -> dict:
    """The query and what its numbers are, so Claude formats the chart for them (AED, %, counts)."""
    return {"query": turn.get("query", ""), "measures": data_layer.measure_notes(turn.get("cubes", []),
                                                                                 turn.get("query", ""))}


@router.post("/conversations/{conversation_id}/turns/{turn_id}/chart", response_model=ChartOut)
def change_chart(conversation_id: str, turn_id: str, body: ChartRequest) -> dict:
    """The same numbers drawn the way the request describes: one Claude call, no new query."""
    turn = turn_of(conversation(conversation_id), turn_id)
    if not has_chart(turn):
        raise ApiError(400, "This answer has no numbers to draw.")
    request = body.request.strip()
    if not request:
        raise ApiError(400, "Describe the chart you want.")
    try:
        with usage.track("chart_restyle", turn["question"]):
            spec = llm.describe_result(turn["question"], turn["df"], chart_request=request, **chart_context(turn))
    except Exception as exc:
        raise ApiError(502, friendly(exc), details(exc)) from exc
    turn["spec"] = {**spec, "summary": (turn.get("spec") or {}).get("summary", spec.get("summary", ""))}
    turn.pop("_chart", None)
    turn.pop("_modes", None)
    return {"chart": turn_chart(turn)}


@router.get("/conversations/{conversation_id}/turns/{turn_id}/csv")
def download_csv(conversation_id: str, turn_id: str) -> Response:
    turn = turn_of(conversation(conversation_id), turn_id)
    if turn.get("df") is None:
        raise ApiError(400, "This answer has no data to download.")
    name = storage.slugify((turn.get("spec") or {}).get("title") or turn["question"])[:60] or "result"
    return Response(turn["df"].to_csv(index=False).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.post("/answers/{answer_id}/verify", response_model=Ok, dependencies=[Depends(require_admin)])
def verify(answer_id: int, body: Verify) -> dict:
    """Marked correct: Claude follows it as an example for similar questions."""
    answer_memory.verify(answer_id, body.verified)
    for turn in conversations.all_turns():
        if turn.get("answer_id") == answer_id:
            turn["verified"] = body.verified
    return {"ok": True}


@router.get("/history", response_model=list[HistoryEntry])
def history() -> list[dict]:
    return [{"time": h.get("time", ""), "question": h.get("question", ""), "rows": h.get("rows", 0),
             "title": h.get("title", "")} for h in storage.load_history()]

