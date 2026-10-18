"""Chat conversations, kept in the server's memory (as Streamlit kept them in the browser session): each
one's scope (a cube, or "" for all the data) and its turns, including each answer's numbers, so a
follow-up can build on them, "as a pie" can redraw them and "Add to dashboard" can keep them. The
least recently used conversations are forgotten beyond LIMIT; a restart forgets them all."""
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

LIMIT = 200


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Conversation:
    id: str
    scope: str
    turns: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)  # one question at a time per conversation
    # the question being answered right now, with its progress so far ({"question", "steps"}): a page
    # opened again meanwhile (a reload, another tab) shows it and picks up the answer when it's ready
    pending: dict | None = None

    def turn(self, turn_id: str) -> dict | None:
        return next((t for t in self.turns if t.get("id") == turn_id), None)


_store: "OrderedDict[str, Conversation]" = OrderedDict()
_lock = threading.Lock()


def create(scope: str) -> Conversation:
    conv = Conversation(new_id(), scope)
    with _lock:
        _store[conv.id] = conv
        while len(_store) > LIMIT:
            _store.popitem(last=False)
    return conv


def get(conversation_id: str) -> Conversation | None:
    with _lock:
        conv = _store.get(conversation_id)
        if conv is not None:
            _store.move_to_end(conversation_id)
        return conv


def all_turns():
    """Every turn of every conversation (to mark an answer verified wherever it shows)."""
    with _lock:
        convs = list(_store.values())
    return [t for c in convs for t in c.turns]


def clear() -> None:
    with _lock:
        _store.clear()
