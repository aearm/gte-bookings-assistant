"""Before planning, Haiku prepares the message: a follow-up ("and by market?") becomes a standalone
question with everything it depends on from earlier turns, how to draw it is set apart from what to
fetch, and each period is described in a small grammar that code turns into exact dates (so "last
month" or "week 41" is never miscounted). A message that only asks to show the previous answer
differently needs no new data, so it skips planning.

The planner then gets the standalone question and the dates, not the conversation."""
from dataclasses import dataclass, field
from datetime import date, timedelta

import config
import llm
import periods
import usage

UNITS = ["day", "week", "month", "quarter", "half", "year"]
MONTHS_IN = {"month": 1, "quarter": 3, "half": 6, "year": 12}

RULES = """You prepare a business user's message about a travel company's data for the analyst who
answers it. You don't answer it.

Return:
- standalone_question: the question to answer, complete on its own. When the message follows up earlier
  turns ("and by market?", "same for hotels", "what about last year?", "only UAE"), carry over everything
  it still depends on: the numbers, breakdowns, filters, periods and exact names. Keep the user's own
  business words (never swap "bookings" or "sales" for another word), and every name, code and value
  exactly as written. Keep everything that changes which numbers are needed: measures, breakdowns and
  their grain (by day, by month), filters, top-N, ranking order, comparisons, and which date a number is
  counted on (booking date, stay date...). Leave out how to draw it. A follow-up that adds something
  ("and the sales", "the success rate for each", "X too", "as well", "also", "add X") keeps everything
  the earlier question asked for and adds the new numbers; only "instead", "only X" or "just X" replace.
- chart_request: only how to show it, in the user's words: chart type, one chart or one panel per
  measure, bars side by side, colours, labels, axes, "as a table". Empty when nothing was said. For a
  chart-only message, its instructions plus earlier ones that still apply.
- kind: "chart_only" when the message only asks to show the previous answer differently and needs no
  new numbers; "follow_up" when it builds on earlier turns; otherwise "new".
- periods: every period the question means (in a follow-up, the ones carried over too), each with the
  user's phrase and its first and last point. Code computes the dates from these points:
    unit: day, week, month, quarter, half or year, and one way to place it:
    relative: offset from the current unit (0 = this, -1 = last, -2 = the one before; +1 = next)
    calendar: year (0 when the user gave none) and number (month 1-12, quarter 1-4, half 1-2, ISO week
      1-53; 0 for a whole year)
    date: an exact day, YYYY-MM-DD (unit day)
  Fill the fields of the way you use and leave the others 0 or empty.
  Examples: "last month" = month relative -1 to month relative -1. "July to September 2026" = month
  calendar 2026/7 to month calendar 2026/9. "this year" = year relative 0 to year relative 0 with
  to_date. "since March" = month calendar 0/3 to day relative 0. "last 7 days" = day relative -6 to day
  relative 0. "week 41" = week calendar 0/41 to the same. "H1 2019" = half calendar 2019/1 to the same.
  "yesterday" = day relative -1 to the same. "next month" = month relative 1 to the same.
  to_date: true when the period runs up to today ("this month", "so far", "year to date").
  A comparison has one period per side ("September 2026 vs September 2025" = two periods). No period in
  the question: an empty list (never invent one)."""

_POINT = {
    "type": "object",
    "properties": {
        "unit": {"type": "string", "enum": UNITS},
        "way": {"type": "string", "enum": ["relative", "calendar", "date"]},
        "offset": {"type": "integer"},
        "year": {"type": "integer"},
        "number": {"type": "integer"},
        "date": {"type": "string", "description": "YYYY-MM-DD for way date, else empty."},
    },
    "required": ["unit", "way", "offset", "year", "number", "date"],
    "additionalProperties": False,
}
TOOL = {
    "name": "submit_question",
    "description": "The prepared question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "standalone_question": {"type": "string"},
            "chart_request": {"type": "string"},
            "kind": {"type": "string", "enum": ["new", "follow_up", "chart_only"]},
            "periods": {"type": "array", "items": {
                "type": "object",
                "properties": {"phrase": {"type": "string"}, "first": _POINT, "last": _POINT,
                               "to_date": {"type": "boolean"}},
                "required": ["phrase", "first", "last", "to_date"],
                "additionalProperties": False,
            }},
        },
        "required": ["standalone_question", "chart_request", "kind", "periods"],
    },
}


@dataclass
class Period:
    phrase: str
    start: date
    end: date  # exclusive: the day after the last day

    def text(self) -> str:
        last = self.end - timedelta(days=1)
        return f'"{self.phrase}" = {self.start.isoformat()} to {last.isoformat()} ({periods.dates_text(self.start, self.end)})'


@dataclass
class Rewrite:
    question: str
    kind: str = "new"
    chart_request: str = ""
    periods: list[Period] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)  # each period as Haiku described it (the grammar), in order

    def periods_text(self) -> str:
        return "\n".join(f"- {p.text()}" for p in self.periods)

    def records(self) -> list[dict]:
        """The periods as they are kept with an answer (see record)."""
        return [record(item, p) for item, p in zip(self.items, self.periods)]


def record(item: dict, period: Period) -> dict:
    """A period as it is kept with an answer or a dashboard chart: the user's phrase, its first and last
    point in the grammar (so it can be worked out again on another day: "yesterday" moves forward) and
    the dates it meant when it was asked (end exclusive)."""
    return {"phrase": period.phrase, "first": dict(item["first"]), "last": dict(item["last"]),
            "to_date": bool(item.get("to_date")), "start": period.start.isoformat(), "end": period.end.isoformat()}


# ---------------------------------------------------------------- dates, in code --

def _unit_start(unit: str, d: date) -> date:
    """The first day of the day / week / month ... that d is in."""
    if unit == "day":
        return d
    if unit == "week":
        return d - timedelta(days=d.weekday())
    months = MONTHS_IN[unit]
    return d.replace(month=(d.month - 1) // months * months + 1, day=1)


def _next(unit: str, start: date, count: int = 1) -> date:
    if unit == "day":
        return start + timedelta(days=count)
    if unit == "week":
        return start + timedelta(weeks=count)
    return periods.add_months(start, MONTHS_IN[unit] * count)


def _calendar(unit: str, year: int, number: int) -> date:
    if unit == "year":
        return date(year, 1, 1)
    if unit == "week":
        if not 1 <= number <= periods.weeks_in_year(year):
            raise ValueError(f"{year} has no week {number}")
        return periods.week_start(year, number)
    if unit == "day":
        raise ValueError("a day is given as a date")
    months = MONTHS_IN[unit]
    if not 1 <= number <= 12 // months:
        raise ValueError(f"there is no {unit} {number}")
    return date(year, (number - 1) * months + 1, 1)


def span(point: dict, today: date) -> tuple[date, date]:
    """(first day, day after the last) of one point of the grammar."""
    unit = point["unit"]
    if point["way"] == "date":
        start = _unit_start(unit, date.fromisoformat(point["date"]))
    elif point["way"] == "relative":
        start = _next(unit, _unit_start(unit, today), int(point["offset"]))
    else:
        year = int(point["year"])
        if not year:  # "in July", "week 41": the latest one that has started
            year = today.year if _calendar(unit, today.year, point["number"]) <= today else today.year - 1
        start = _calendar(unit, year, int(point["number"]))
    return start, _next(unit, start)


def _relative(unit: str, offset: int) -> dict:
    return {"unit": unit, "way": "relative", "offset": offset, "year": 0, "number": 0, "date": ""}


# The dashboard's quick choices (periods.PRESETS) in the grammar, so a chart can keep one as its own period.
PRESET_ITEMS = {
    "Today": ("day", 0, "day", 0, False), "Yesterday": ("day", -1, "day", -1, False),
    "This week": ("week", 0, "week", 0, True), "Last week": ("week", -1, "week", -1, False),
    "Last 7 days": ("day", -6, "day", 0, False), "Last 30 days": ("day", -29, "day", 0, False),
    "This month": ("month", 0, "month", 0, True), "Last month": ("month", -1, "month", -1, False),
    "This quarter": ("quarter", 0, "quarter", 0, True), "Last quarter": ("quarter", -1, "quarter", -1, False),
    "This year": ("year", 0, "year", 0, True), "Last year": ("year", -1, "year", -1, False),
    "Last 12 months": ("month", -11, "day", 0, False),
}


def preset_item(name: str) -> dict | None:
    """A quick choice of the dashboards ("This month") as a period of the grammar, or None."""
    if name not in PRESET_ITEMS:
        return None
    first_unit, first, last_unit, last, to_date = PRESET_ITEMS[name]
    return {"phrase": name.lower(), "first": _relative(first_unit, first), "last": _relative(last_unit, last),
            "to_date": to_date}


def resolve(item: dict, today: date) -> Period:
    start, end = span(item["first"], today)[0], span(item["last"], today)[1]
    if item.get("to_date"):
        end = min(end, today + timedelta(days=1))
    if end <= start:
        raise ValueError(f'"{item["phrase"]}" ends before it starts')
    return Period(item["phrase"], start, end)


# ---------------------------------------------------------------- the call --

def rewrite(question: str, context: list[dict] | None = None, clarification: tuple[str, str] | None = None,
            today: date | None = None) -> Rewrite | None:
    """The prepared question, or None if it couldn't be prepared (the planner then gets the message and
    the conversation, as before)."""
    today = today or date.today()
    parts = [f"Today is {today:%A} {today.isoformat()}."]
    for prev in (context or [])[-3:]:
        shown = (prev.get("spec") or {}).get("chart_type", "")
        parts.append(f"Earlier question: {prev.get('question', '')}"
                     + (f"\nUnderstood as: {prev['understanding']}" if prev.get("understanding") else "")
                     + (f"\nShown as: {shown}" if shown else ""))
    parts.append(f"Message: {question}")
    if clarification:
        parts.append(f"The analyst asked: {clarification[0]}\nThe user answered: {clarification[1]}\n"
                     "Make the answer part of the standalone question.")
    system = [{"type": "text", "text": RULES, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    try:
        out = llm._structured_call(system, TOOL, "\n\n".join(parts), model=config.CLAUDE_FAST_MODEL,
                                   effort="low", max_tokens=4000, purpose="rewrite")
    except Exception:
        return None
    standalone = (out.get("standalone_question") or "").strip()
    if not standalone:
        return None
    resolved, items, failed = [], [], []
    for item in out.get("periods", []):
        try:
            resolved.append(resolve(item, today))
            items.append(item)
        except (ValueError, KeyError, TypeError) as exc:
            failed.append(f"{item.get('phrase', '?')}: {exc}")
    kind = out.get("kind", "new") if context else "new"  # nothing earlier to show again or follow
    usage.note(rewritten=standalone, periods=[p.text() for p in resolved], **({"period_errors": failed} if failed else {}))
    return Rewrite(standalone, kind, (out.get("chart_request") or "").strip(), resolved, items)
