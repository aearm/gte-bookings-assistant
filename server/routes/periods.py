"""The dashboards' periods: the quick choices with their dates, the comparisons, and the period a request
asks for (a quick choice, or dates; the defaults when it names neither)."""
from datetime import date

from fastapi import APIRouter

import periods

# What a dashboard shows before anyone picks a period: periods.py's defaults, so both apps agree (the
# React app reads them from /api/info, and the charts pre-run every night for them).
DEFAULTS = {"preset": periods.DEFAULT_PRESET, "compare": periods.DEFAULT_COMPARE}

router = APIRouter(tags=["periods"])


def pick(start: date | None, end: date | None, preset: str = "") -> tuple[date, date, str]:
    """(start, end exclusive, preset): a quick choice ("This month", as of today) wins; else the dates;
    else the default quick choice."""
    if preset in periods.PRESETS:
        return (*periods.preset_range(preset), preset)
    if start and end and end > start:
        return start, end, ""
    return (*periods.preset_range(DEFAULTS["preset"]), DEFAULTS["preset"])


def period_json(start: date, end: date, preset: str = "") -> dict:
    return {"start": start, "end": end, "label": periods.label(start, end, preset), "preset": preset}


def versus(mode: str, start: date, end: date, preset: str = "", cstart: date | None = None,
           cend: date | None = None) -> dict | None:
    """The comparison period ({"start", "end", "label", "preset", "mode", "name"}) or None for no comparison.
    "Other dates" without dates compares with the previous period (as the Streamlit picker did)."""
    mode = mode if mode in periods.COMPARE_MODES else DEFAULTS["compare"]
    custom = (cstart, cend) if cstart and cend and cend > cstart else periods.previous_period(start, end, preset)
    found = periods.compare_range(mode, start, end, preset, custom)
    if not found:
        return None
    return {"start": found[0], "end": found[1], "label": periods.dates_text(*found), "preset": "", "mode": mode,
            "name": periods.compare_name(mode, start, end, preset, custom)}


@router.get("/periods")
def list_periods(start: date | None = None, end: date | None = None, preset: str = "", compare: str = "",
                 cstart: date | None = None, cend: date | None = None) -> dict:
    """The quick choices and comparisons, and the period and comparison these parameters mean."""
    start, end, preset = pick(start, end, preset)
    mode = compare or DEFAULTS["compare"]
    custom = (cstart, cend) if cstart and cend and cend > cstart else periods.previous_period(start, end, preset)
    presets = []
    for name in periods.PRESETS:
        s, e = periods.preset_range(name)
        presets.append({"name": name, "start": s, "end": e, "label": periods.label(s, e, name)})
    modes = []
    for m, label in periods.COMPARE_MODES.items():
        dates = periods.compare_range(m, start, end, preset, custom)
        modes.append({"mode": m, "label": label, "dates": periods.dates_text(*dates) if dates else "Show this period only"})
    return {"presets": presets, "compare_modes": modes, "period": period_json(start, end, preset),
            "compare": versus(mode, start, end, preset, cstart, cend), "defaults": DEFAULTS}
