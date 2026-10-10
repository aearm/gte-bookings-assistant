"""The glossary (the cube's "map"): what each business word means in the data, e.g. which date
"bookings in March" uses or which statuses count as valid. One per cube, mostly filled in by the
admin's setup answers (see cube_setup.py). Shown on the Glossary page and given to Claude with
every question about that cube."""
import json
import re
from datetime import date

import cubes

COLUMNS = ["Term", "Meaning", "Measure", "Date to use", "Status", "Agreed by"]
STATUSES = ["Draft", "Agreed"]


def load(cube: str) -> tuple[list[dict], str]:
    """Returns (rows, last updated date)."""
    path = cubes.glossary_file(cube)
    if not path.exists():
        return [], ""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("rows", []), data.get("updated", "")


def save(cube: str, rows: list[dict]) -> None:
    clean = [{c: str(r.get(c) or "").strip() for c in COLUMNS} for r in rows]
    clean = [r for r in clean if r["Term"]]
    for r in clean:
        if r["Status"] not in STATUSES:
            r["Status"] = "Draft"
    data = {"updated": date.today().isoformat(), "rows": clean}
    cubes.glossary_file(cube).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def upsert(cube: str, row: dict) -> None:
    """Add a term, or replace the one with the same name."""
    rows, _ = load(cube)
    rows = [r for r in rows if r["Term"].lower() != row["Term"].lower()] + [row]
    save(cube, rows)


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
            parts.append(f"In the data: {r['Measure']}")
        if r.get("Date to use"):
            parts.append(f"Date: {r['Date to use']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def notes_for_claude(cube: str) -> str:
    """The cube's business notes plus its glossary, as given to Claude with every question."""
    path = cubes.notes_file(cube)
    notes = path.read_text(encoding="utf-8") if path.exists() else ""
    notes = re.sub(r"<!--.*?-->", "", notes, flags=re.DOTALL)
    return (notes.strip() + "\n\n" + prompt_text(load(cube)[0])).strip()
