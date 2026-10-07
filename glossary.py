"""The glossary: what each number means, agreed with the owner of the numbers (Finance/BI).
Shown on the Glossary page and given to Claude with every question."""
import json
import re
from datetime import date

import config

COLUMNS = ["Term", "Meaning", "Measure", "Date to use", "Status", "Agreed by"]
STATUSES = ["Draft", "Agreed"]

# Starting point for the conversation with Finance/BI: the questions to settle and the
# options that exist in the model. Nothing here is agreed yet.
STARTER = [
    {"Term": "Bookings", "Meaning": "Number of reservations. To agree: include cancelled ones or not?",
     "Measure": "[Reservations Count]",
     "Date to use": "To agree: 'Create Date' (when booked) or 'Travel Date Start' (when travel starts)",
     "Status": "Draft", "Agreed by": ""},
    {"Term": "Sales", "Meaning": "To agree: with or without tax? Before or after final adjustments?",
     "Measure": "Options: [Sale], [Sale w/o Tax], [Final Sales]",
     "Date to use": "To agree", "Status": "Draft", "Agreed by": ""},
    {"Term": "Revenue", "Meaning": "To agree: the same as Sales, or something else?",
     "Measure": "Options: [Sale], [Final Sales], [Amount]",
     "Date to use": "To agree", "Status": "Draft", "Agreed by": ""},
    {"Term": "Profit", "Meaning": "To agree: which profit is the official one?",
     "Measure": "Options: [Profit], [Base Profit], [Final Profit]",
     "Date to use": "To agree", "Status": "Draft", "Agreed by": ""},
    {"Term": "Cost", "Meaning": "To agree: which cost is the official one?",
     "Measure": "Options: [Cost], [Base Cost], [Final Cost]",
     "Date to use": "To agree", "Status": "Draft", "Agreed by": ""},
    {"Term": "Destination",
     "Meaning": "To agree: is 'destination' the country or the city/area of the service? "
                "And is 'Countries' the destination country or another country (e.g. the customer's)?",
     "Measure": "Options: 'Countries'[Country] (country), 'Areas'[Area] (city/area)",
     "Date to use": "", "Status": "Draft", "Agreed by": ""},
    {"Term": "Default date",
     "Meaning": "The date to use when a question doesn't say (e.g. 'bookings in March').",
     "Measure": "",
     "Date to use": "To agree: 'Create Date', 'Travel Date Start', 'Cancelation Date' or 'Calendar' (ask BI what 'Calendar' is)",
     "Status": "Draft", "Agreed by": ""},
]


def load() -> tuple[list[dict], str]:
    """Returns (rows, last updated date)."""
    if not config.GLOSSARY_FILE.exists():
        return [dict(r) for r in STARTER], ""
    data = json.loads(config.GLOSSARY_FILE.read_text(encoding="utf-8"))
    return data.get("rows", []), data.get("updated", "")


def save(rows: list[dict]) -> None:
    clean = [{c: str(r.get(c) or "").strip() for c in COLUMNS} for r in rows]
    clean = [r for r in clean if r["Term"]]
    for r in clean:
        if r["Status"] not in STATUSES:
            r["Status"] = "Draft"
    data = {"updated": date.today().isoformat(), "rows": clean}
    config.GLOSSARY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def prompt_text(rows: list[dict]) -> str:
    """The glossary as instructions for Claude."""
    if not rows:
        return ""
    lines = ["## Glossary",
             "Agreed entries are confirmed by the owner of the numbers: always follow them.",
             "Draft entries are not confirmed yet. For which measure or date to use, pick the most likely "
             "option and say which in the understanding. For which values to filter on (e.g. which statuses), "
             "a draft does not decide: if the question depends on it, ask."]
    for r in rows:
        parts = [f"- {r['Term']} ({r.get('Status') or 'Draft'}): {r.get('Meaning', '')}"]
        if r.get("Measure"):
            parts.append(f"Measure: {r['Measure']}")
        if r.get("Date to use"):
            parts.append(f"Date: {r['Date to use']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def notes_for_claude() -> str:
    """Business notes plus the glossary, as given to Claude with every question."""
    notes = config.NOTES_FILE.read_text(encoding="utf-8") if config.NOTES_FILE.exists() else ""
    notes = re.sub(r"<!--.*?-->", "", notes, flags=re.DOTALL)
    return (notes.strip() + "\n\n" + prompt_text(load()[0])).strip()
