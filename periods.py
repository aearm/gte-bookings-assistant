"""Dashboard periods: a quick choice (this month, last week...), any dates on a calendar, or week
numbers of a year. Weeks follow ISO 8601: they start on Monday, and week 1 is the week with the
year's first Thursday (so 29 Dec 2025 is in week 1 of 2026, and 2026 has 53 weeks).
Every period is (start, end) with end exclusive: the day after the last day."""
from datetime import date, timedelta

PRESETS = ["Last 7 days", "This week", "Last week", "This month", "Last month", "This year", "Last 12 months"]
DEFAULT_PRESET = "This year"
MODES = ["Quick", "Calendar", "Week"]  # how the period is picked on a dashboard


def add_months(d: date, months: int) -> date:
    years, month0 = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + years, month=month0 + 1)


def preset_range(name: str, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    tomorrow, first = today + timedelta(days=1), today.replace(day=1)
    monday = today - timedelta(days=today.weekday())
    if name == "Last 7 days":
        return today - timedelta(days=6), tomorrow
    if name == "This week":
        return monday, tomorrow
    if name == "Last week":
        return monday - timedelta(days=7), monday
    if name == "This month":
        return first, tomorrow
    if name == "Last month":
        return add_months(first, -1), first
    if name == "Last 12 months":
        return add_months(first, -11), tomorrow
    return today.replace(month=1, day=1), tomorrow  # This year


def calendar_range(first_day: date, last_day: date) -> tuple[date, date]:
    first_day, last_day = min(first_day, last_day), max(first_day, last_day)
    return first_day, last_day + timedelta(days=1)


# ---------------------------------------------------------------- ISO weeks --

def weeks_in_year(year: int) -> int:
    """52 or 53: 28 December is always in the year's last week."""
    return date(year, 12, 28).isocalendar().week


def week_start(year: int, week: int) -> date:
    return date.fromisocalendar(year, week, 1)


def week_range(year: int, first_week: int, last_week: int | None = None) -> tuple[date, date]:
    """Monday of the first week to the Monday after the last week."""
    last_week = first_week if last_week is None else last_week
    first_week, last_week = sorted((first_week, last_week))
    top = weeks_in_year(year)
    first_week, last_week = max(1, min(first_week, top)), max(1, min(last_week, top))
    return week_start(year, first_week), week_start(year, last_week) + timedelta(days=7)


def week_label(year: int, week: int) -> str:
    """'W41 · 5 Oct – 11 Oct'"""
    start = week_start(year, week)
    end = start + timedelta(days=6)
    return f"W{week} · {start.day} {start:%b} – {end.day} {end:%b}"


def current_week(today: date | None = None) -> tuple[int, int]:
    """(ISO year, week number) of today."""
    iso = (today or date.today()).isocalendar()
    return iso.year, iso.week


def weeks_of(start: date, end: date) -> str:
    """The ISO weeks a period covers, e.g. 'week 41', 'weeks 1–42' or 'weeks 52 (2025) – 3 (2026)'."""
    last = end - timedelta(days=1)
    (y1, w1, _), (y2, w2, _) = start.isocalendar(), last.isocalendar()
    if (y1, w1) == (y2, w2):
        return f"week {w1}"
    if y1 == y2:
        return f"weeks {w1}–{w2}"
    return f"weeks {w1} ({y1}) – {w2} ({y2})"


def describe(start: date, end: date) -> str:
    """'06 Oct 2026 – 12 Oct 2026 · week 41'"""
    return f"{start:%d %b %Y} – {end - timedelta(days=1):%d %b %Y} · {weeks_of(start, end)}"


# ---------------------------------------------------------------- comparisons --

def same_period_last_year(start: date, end: date, weekly: bool = False) -> tuple[date, date]:
    """The period a year earlier. Weekly periods move back 52 weeks, so Monday stays Monday
    (week 41 is compared with week 41); other periods keep their dates."""
    if weekly:
        return start - timedelta(weeks=52), end - timedelta(weeks=52)

    def shift(d: date) -> date:
        return d.replace(year=d.year - 1, day=28) if (d.month == 2 and d.day == 29) else d.replace(year=d.year - 1)
    return shift(start), shift(end)


def is_weekly(mode: str, preset: str = "") -> bool:
    return mode == "Week" or (mode == "Quick" and preset in ("This week", "Last week"))
