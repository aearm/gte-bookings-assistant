"""Picking the cubes a question needs, so Claude reads only those cubes' details.

The data layer is turned into
- index cards: a few lines per cube (what it's for, its main measures, dates and entities) - all 27
  together are a few thousand tokens, given to Claude with every question instead of the full layer;
- a graph: cubes are nodes, and two cubes are linked when they share a business entity (customer,
  supplier, hotel...), with the join column on each side and how well the values match;
- value hits: words of the question found as exact values in the data ("UAE" -> Market = "UAE").

pick() asks Claude Haiku (fast and cheap) which cubes answer the question, from the cards and the value
hits; the planner then gets those cubes' full details, the join path between them and the value hits
up front, so it rarely needs extra rounds to look things up."""
import re
import threading
from dataclasses import dataclass, field

import config
import cubes
import data_layer
import llm
import semantic
import value_index

MAX_CUBES = 5  # as many as a plan may join (plans.MAX_STEPS), so none has to be read in an extra round
_STOP = set("""a an and are as at be between both by can compare compared did do does each for from had has have
how i in into is it its last many me month months much my next no not of on or our per show shown sort than that
the their them then there these this those to top total totals up versus vs was we week weeks were what when where
which who with year years yesterday today day days quarter all any one two give list by also only""".split())

_cache = {"key": None, "cards": "", "graph": {}}
_lock = threading.Lock()


# ---------------------------------------------------------------- cards and graph --

def _card(cube: str, p: dict) -> str:
    from_meaning = semantic.card(cube)  # the meaning layer's card, with real coverage, when it has the cube
    if from_meaning:
        return from_meaning
    ms = ", ".join(dict.fromkeys(m["label"] for m in p.get("measures", [])))  # exact names come with the details
    dates = " · ".join(d["meaning"].split(".")[0][:60] + (" (default)" if d["column"] == p.get("default_date") else "")
                       for d in p.get("dates", [])[:3])
    entities = ", ".join(dict.fromkeys(d["entity"] for d in p.get("dimensions", []) if d["entity"] != "other"))
    first = (p.get("description") or "").split(". ")[0].rstrip(".")
    lines = [f"### {p.get('label') or cubes.label(cube)} - cube \"{cube}\" ({p.get('subject_area', '')})",
             f"{first}. Grain: {p.get('grain', '')}"]
    if ms:
        lines.append(f"Measures: {ms}")
    if dates:
        lines.append(f"Dates: {dates}")
    if p.get("default_date"):
        lines.append(f"Default date: {p['default_date']}")
    if entities:
        lines.append(f"By: {entities}")
    return "\n".join(lines)


def _build(layer: dict) -> tuple[str, dict]:
    names = data_layer.layer_cubes()
    profiles = layer.get("cubes", {})
    lines = [f"# The data: {len(names)} cubes (index cards)",
             "Each cube is a separate Analysis Services database; one query reads one cube. Cubes are joined on "
             "the shared dimensions below. The full details of the cubes most likely needed are given with the "
             "question; read any other cube's details with get_cube_details."]
    routing = [r for r in layer.get("routing", []) if r["cube"] in names]
    if routing:
        lines += ["", "## Which cube for what"] + [f"- {r['topic']}: {cubes.label(r['cube'])}" for r in routing]
    lines += ["", "## Cubes"]
    lines += [_card(c, profiles[c]) + "\n" for c in names]
    graph: dict[str, list[dict]] = {c: [] for c in names}
    shared = []
    for e in layer.get("entities", []):
        members = [m for m in e["members"] if m["cube"] in graph]
        if len({m["cube"] for m in members}) < 2:
            continue
        shared.append(f"- {e['label']}: " + ", ".join(dict.fromkeys(cubes.label(m["cube"]) for m in members)))
        for a in members:
            for b in members:
                if a["cube"] != b["cube"]:
                    graph[a["cube"]].append({"to": b["cube"], "entity": e["label"], "from_column": a["join_column"],
                                             "to_column": b["join_column"], "match": b["match"],
                                             "notes": e.get("join_notes", "")})
    if shared:
        lines += ["## Shared dimensions (which cubes can be joined)"] + shared
    return "\n".join(lines) + "\n", graph


def _state() -> dict:
    layer = data_layer.load()
    key = (layer.get("built"), tuple(data_layer.layer_cubes()))
    with _lock:
        if _cache["key"] != key:
            _cache["cards"], _cache["graph"] = _build(layer) if layer.get("cubes") else ("", {})
            _cache["key"] = key
        return _cache


def cards_text() -> str:
    """All the cubes' index cards and shared dimensions: what Claude always reads (a few thousand tokens)."""
    return _state()["cards"]


def planner_cards() -> str:
    """The cards for the planner, who gets the picked cubes in full anyway: every cube in one line (what
    it is), with which cube for what and the shared dimensions - about a fifth of the full cards."""
    text = cards_text()
    head, _, rest = text.partition("\n## Cubes\n")
    if not rest:
        return text
    body, _, shared = rest.partition("\n## Shared dimensions")
    lines = []
    for card in re.split(r"^### ", body, flags=re.MULTILINE)[1:]:
        title, _, desc = card.partition("\n")
        first = desc.strip().split("\n")[0]
        lines.append(f"- {title.strip()}: {first[:220]}")
    return (head + "\n## Cubes (one line each; read a cube's details with get_cube_details)\n" + "\n".join(lines)
            + ("\n\n## Shared dimensions" + shared if shared else ""))


def join_path(chosen: list[str]) -> str:
    """How the chosen cubes join: the shared dimensions between each pair, best (code, high match) first."""
    if len(chosen) < 2:
        return ""
    graph, lines = _state()["graph"], []
    rank = {"high": 0, "partial": 1, "names_only": 2, "unknown": 3}
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            links = sorted((x for x in graph.get(a, []) if x["to"] == b), key=lambda x: rank.get(x["match"], 9))
            if not links:
                lines.append(f"- {cubes.label(a)} and {cubes.label(b)} share no dimension: answer them as separate "
                             "results side by side only if they have the same breakdown, else ask.")
            for x in links[:4]:
                lines.append(f"- {cubes.label(a)} {x['from_column']} = {cubes.label(b)} {x['to_column']} "
                             f"({x['entity']}, match: {x['match']})" + (f". {x['notes']}" if x["notes"] else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------- value hits --

def _phrases(question: str) -> list[str]:
    """Words and 2-3 word phrases of the question that could be values ("UAE", "RateHawk", "Abu Dhabi")."""
    words = re.findall(r"[^\W_][\w&'.-]*", question)
    out = []
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            chunk = words[i:i + n]
            if all(w.lower() in _STOP for w in chunk) or (n == 1 and (chunk[0].lower() in _STOP or len(chunk[0]) < 2)):
                continue
            if chunk[0].lower() in _STOP or chunk[-1].lower() in _STOP:
                continue
            out.append(" ".join(chunk))
    return list(dict.fromkeys(out))


def value_hits(question: str, names: list[str], limit: int = 24) -> list[dict]:
    """Exact values (or initials) of the data found in the question: [{text, cube, column, value, count}]."""
    phrases = [p for p in _phrases(question) if not data_layer.is_measure_word(p)]  # "sales" is a number
    hits = []
    for cube in names:
        hits += [{"cube": cube, **h} for h in value_index.for_cube(cube).exact_many(phrases)] if phrases else []
    hits.sort(key=lambda h: (-len(h["text"]), -(h["count"] or 0)))
    return hits[:limit]


def hits_text(hits: list[dict], chosen: list[str] | None = None) -> str:
    if not hits:
        return ""
    terms = [h for h in hits if h.get("kind") == "term"]  # business words: always shown, they name the measure
    lines = [semantic.hits_text(terms)] if terms else []
    for h in hits:
        if h.get("kind") == "term" or (chosen and h["cube"] not in chosen):
            continue
        amount = f"{h['count']:,.0f}" if h["count"] else "no data"
        lines.append(f'- "{h["text"]}": {cubes.label(h["cube"])} {h["column"]} = "{h["value"]}" ({amount})')
    return "\n".join(lines)


# ---------------------------------------------------------------- picking --

def _route_tool(names: list[str]) -> dict:
    """The answer format: only exact cube names can be given."""
    return {"name": "submit_cubes", "input_schema": {
        "type": "object",
        "properties": {
            "cubes": {"type": "array", "items": {"type": "string", "enum": names},
                      "description": f"1 to {MAX_CUBES} exact cube names, most important first."},
            "reason": {"type": "string", "description": "One short sentence."},
        },
        "required": ["cubes", "reason"],
    }}


def _exact(name: str, names: list[str]) -> str | None:
    """The cube meant by a name, a short label ("Bookings") or a profile label."""
    plain = lambda t: " ".join(str(t).lower().split())
    for cube in names:
        if plain(name) in (plain(cube), plain(cubes.label(cube)), plain(data_layer.cube_label(cube))):
            return cube
    return None
ROUTE_RULES = """Pick the cube(s) whose data answers the question, from the index cards below.
- One cube when it has every number asked for (prefer the cube "Which cube for what" names for the topic).
- Several cubes only when the numbers asked for live in different cubes (e.g. sales and payments); they must
  share a dimension to be combined.
- Use the values found in the data to tell cubes apart (a market, a customer, an API...).
- For a follow-up question, keep the earlier question's cubes unless it asks for something they don't have.
Answer with exact cube names."""


@dataclass
class Pick:
    cubes: list[str]
    reason: str = ""
    hits: list[dict] = field(default_factory=list)


def pick(question: str, names: list[str], context: list[dict] | None = None) -> Pick:
    """The cubes to give the planner in full (a quick Haiku request when there is a choice)."""
    hits = semantic.term_hits(question) + value_hits(question, names)
    names = [c for c in names if semantic.usable(c)] or names  # cubes with no data are never picked
    if len(names) <= 1:
        return Pick(list(names), "the cube picked", hits)
    parts = [f"Question: {question}"]
    for prev in (context or [])[-2:]:
        used = prev.get("cubes") or []
        parts.insert(0, f"Earlier question: {prev.get('question', '')} (answered from: {', '.join(used) or '?'})")
    if hits:
        parts.append("Business terms and values found in the question:\n" + hits_text(hits))
    system = [{"type": "text", "text": ROUTE_RULES + "\n\n" + cards_text(),
               "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    try:
        out = llm._structured_call(system, _route_tool(names), "\n\n".join(parts), model=config.CLAUDE_FAST_MODEL,
                                   effort="low", max_tokens=4000, purpose="route")
    except Exception:
        return Pick([], "could not pick", hits)  # the planner still has every card and can read any cube
    chosen = [c for c in dict.fromkeys(_exact(x, names) for x in out.get("cubes", [])) if c][:MAX_CUBES]
    return Pick(chosen, out.get("reason", ""), hits)
