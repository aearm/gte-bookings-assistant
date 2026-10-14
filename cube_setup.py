"""Setting up a cube (once, by an admin): Claude reads its structure and real values and drafts a
plain-language map of the business words people will use - which number "bookings" is, which date
"bookings in March" uses, which statuses count as valid, what "destination" means.

Items the data makes clear are listed for the admin to confirm in one click; unclear ones become
short questions with plain options (no column names). Answers become agreed glossary terms
(glossary.py), which Claude follows for every question about that cube. Saved in setup.json."""
import json
from datetime import date, datetime

import charts
import cubes
import glossary
import llm
from backends import get_backend

MAX_QUESTIONS = 8

_OPTION = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "The answer in plain words, no column or measure names."},
        "meaning": {"type": "string", "description": "What choosing it means, in plain words."},
        "in_data": {"type": "string", "description": "Exact technical mapping: measure, column or filter."},
        "date_to_use": {"type": "string", "description": "Exact date column if relevant, else empty."},
    },
    "required": ["label", "meaning", "in_data", "date_to_use"],
    "additionalProperties": False,
}
MAP_TOOL = {
    "name": "submit_map",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "2-3 plain sentences: what this cube contains."},
            "items": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "The business word, e.g. Bookings, Booking date"},
                    "kind": {"type": "string", "enum": ["number", "date", "filter", "breakdown"]},
                    "clear": {"type": "boolean"},
                    "meaning": {"type": "string", "description": "Plain meaning when clear, else empty."},
                    "in_data": {"type": "string", "description": "Exact technical mapping when clear, else empty."},
                    "date_to_use": {"type": "string", "description": "Exact date column when relevant, else empty."},
                    "question": {"type": "string", "description": "When not clear: one short plain question."},
                    "options": {"type": "array", "items": _OPTION},
                },
                "required": ["term", "kind", "clear", "meaning", "in_data", "date_to_use", "question", "options"],
                "additionalProperties": False,
            }},
            "suggested_charts": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "question": {"type": "string"},
                    "chart_type": {"type": "string", "enum": ["kpi"] + charts.CHART_TYPES},
                    "width": {"type": "string", "enum": ["half", "full"]},
                },
                "required": ["title", "question", "chart_type", "width"],
                "additionalProperties": False,
            }},
            "example_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "items", "suggested_charts", "example_questions"],
    },
}

INSTRUCTIONS = f"""You help a non-technical admin set up an assistant that answers questions about an
Analysis Services cube. Staff will ask in plain English, e.g. "bookings in March by destination".
Map the business words they will use to the data, using the schema below: measures, columns, and
each column's real values with how much data they have.

List the 10-20 most important business words, most important first:
- numbers (kind=number): e.g. bookings, sales, revenue, cost, profit, and the other key measures.
- dates (kind=date): the default date for "... in March" questions, and other dates people mean.
- filters (kind=filter): groups people mean, e.g. valid, confirmed or cancelled bookings, using
  exact values.
- breakdowns (kind=breakdown): e.g. destination, agency or customer, supplier, market, channel.

Set clear=true only when the data leaves one sensible reading (a single obvious measure or column,
or names that make it unambiguous); then fill meaning (plain words) and in_data (exact mapping).
Set clear=false when there are several candidates that would give different numbers (several date
columns, several "sales" measures, several country columns, statuses whose grouping is a business
decision). Then write ONE short, friendly question a non-technical person understands, e.g.
"When you ask for bookings in March, which date do you mean?", with 2-4 options. Option labels are
plain words ("The day the booking was made"), never column or measure names; put the exact mapping
in each option's in_data and date_to_use. Ask at most {MAX_QUESTIONS} questions; settle the rest
yourself as clear items.

Use only measures, columns and values that exist in the schema. Write in_data with exact names,
e.g. [Booking Count]; 'Countries'[Country]; 'Order Status'[Status Name] in {{"Paid", "Confirmed"}}.
Prefer values that have data. Skip words that are already agreed (listed below).

Also suggest 6-9 dashboard charts for this cube (2-3 headline numbers as kpi, then charts: map for
countries, line for months, donut for a few parts, horizontal_bar for top 10s; width full for maps
and long trends), and 6 example questions staff could ask."""


# ---------------------------------------------------------------- state --

def load(cube: str) -> dict:
    path = cubes.setup_file(cube)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(cube: str, data: dict) -> None:
    cubes.setup_file(cube).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def draft(cube: str) -> dict:
    """Ask Claude for the cube's map. Replaces any earlier draft (answered terms stay agreed)."""
    backend = get_backend(cube)
    schema = backend.schema_text()
    if not schema:
        raise RuntimeError("Read the cube's structure first.")
    agreed = [r for r in glossary.load(cube)[0] if r.get("Status") == "Agreed"]
    known = "\n".join(f"- {r['Term']}: {r['Meaning']} ({r['Measure']})" for r in agreed) or "(none yet)"
    system = [{"type": "text", "text": INSTRUCTIONS}]
    user = f"Already agreed (don't ask again):\n{known}\n\n{schema}"
    result = llm._structured_call(system, MAP_TOOL, user, purpose="setup")

    items, questions = [], 0
    for item in result.get("items", []):
        is_question = not item["clear"] and item["question"] and len(item["options"]) >= 2
        if is_question and questions >= MAX_QUESTIONS:
            is_question = False
        questions += is_question
        items.append({**item, "state": "question" if is_question else "proposal", "done": ""})
    data = {"drafted": datetime.now().isoformat(timespec="seconds"), "summary": result.get("summary", ""),
            "items": items, "suggested_charts": result.get("suggested_charts", []),
            "example_questions": result.get("example_questions", [])}
    _save(cube, data)
    return data


# ---------------------------------------------------------------- answers --

def _row(item: dict, meaning: str, in_data: str, date_to_use: str, status: str) -> dict:
    by = f"Admin setup, {date.today():%d %b %Y}" if status == "Agreed" else ""
    return {"Term": item["term"], "Meaning": meaning, "Measure": in_data, "Date to use": date_to_use,
            "Status": status, "Agreed by": by}


def _mark(cube: str, index: int, done: str) -> None:
    data = load(cube)
    data["items"][index]["done"] = done
    _save(cube, data)


def answer(cube: str, index: int, option: int | None = None, custom: str = "") -> None:
    """Save the admin's answer to a question as an agreed term."""
    item = load(cube)["items"][index]
    if option is not None:
        o = item["options"][option]
        glossary.upsert(cube, _row(item, o["meaning"] or o["label"], o["in_data"], o["date_to_use"], "Agreed"))
    else:  # their own words: Claude reads it as an agreed definition
        glossary.upsert(cube, _row(item, custom.strip(), "", "", "Agreed"))
    _mark(cube, index, "answered")


def skip(cube: str, index: int) -> None:
    """Not sure yet: keep it as a draft listing the options, so Chat asks when it matters."""
    item = load(cube)["items"][index]
    options = " / ".join(f"{o['label']}: {o['in_data']}" for o in item["options"])
    glossary.upsert(cube, _row(item, f"Not decided yet. {item['question']}", f"Options: {options}", "", "Draft"))
    _mark(cube, index, "skipped")


def confirm(cube: str, indexes: list[int], rejected: list[int]) -> None:
    """Confirmed proposals become agreed terms; rejected ones are kept as drafts."""
    data = load(cube)
    for i in indexes + rejected:
        item = data["items"][i]
        status = "Agreed" if i in indexes else "Draft"
        glossary.upsert(cube, _row(item, item["meaning"], item["in_data"], item["date_to_use"], status))
        item["done"] = "confirmed" if i in indexes else "rejected"
    _save(cube, data)


# ---------------------------------------------------------------- progress --

def open_items(data: dict, state: str) -> list[tuple[int, dict]]:
    return [(i, it) for i, it in enumerate(data.get("items", [])) if it["state"] == state and not it["done"]]


def progress(cube: str) -> dict:
    data = load(cube)
    questions, proposals = open_items(data, "question"), open_items(data, "proposal")
    return {"structure": cubes.is_ready(cube), "drafted": bool(data), "questions": len(questions),
            "proposals": len(proposals),
            "ready": cubes.is_ready(cube) and bool(data) and not questions and not proposals}


def status_label(cube: str) -> str:
    p = progress(cube)
    if not p["structure"]:
        return "Not set up"
    if not p["drafted"]:
        return "Structure read · map not drafted"
    if p["questions"] or p["proposals"]:
        waiting = p["questions"] + (1 if p["proposals"] else 0)
        return f"{waiting} step{'s' if waiting > 1 else ''} waiting"
    return "Ready"


def suggested_charts(cube: str) -> list[dict]:
    return load(cube).get("suggested_charts", [])


def example_questions(cube: str) -> list[str]:
    return load(cube).get("example_questions", [])
