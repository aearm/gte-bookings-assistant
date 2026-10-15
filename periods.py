"""Dashboard periods: a quick choice (this month, last week...), any days or weeks on the calendar
(period_picker.py). Weeks follow ISO 8601: they start on Monday, and week 1 is the week with the
year's first Thursday (so 29 Dec 2025 is in week 1 of 2026, and 2026 has 53 weeks).
Every period is (start, end) with end exclusive: the day after the last day."""
from datetime import date, timedelta

PRESETS = ["Today", "Yesterday", "This week", "Last week", "Last 7 days", "Last 30 days", "This month",
           "Last month", "This quarter", "Last quarter", "This year", "Last year", "Last 12 months"]
DEFAULT_PRESET = "This year"


def add_months(d: date, months: int) -> date:
    years, month0 = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + years, month=month0 + 1)


def preset_range(name: str, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    tomorrow, first = today + timedelta(days=1), today.replace(day=1)
    monday = today - timedelta(days=today.weekday())
    quarter = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
    if name == "Today":
        return today, tomorrow
    if name == "Yesterday":
        return today - timedelta(days=1), today
    if name == "Last 7 days":
        return today - timedelta(days=6), tomorrow
    if name == "Last 30 days":
        return today - timedelta(days=29), tomorrow
    if name == "This quarter":
        return quarter, tomorrow
    if name == "Last quarter":
        return add_months(quarter, -3), quarter
    if name == "Last year":
        return date(today.year - 1, 1, 1), date(today.year, 1, 1)
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


def dates_text(start: date, end: date) -> str:
    """'1 Jan – 13 Oct 2026', '5 Oct 2026', '29 Dec 2025 – 4 Jan 2026'"""
    last = end - timedelta(days=1)
    if start == last:
        return f"{start.day} {start:%b %Y}"
    first = f"{start.day} {start:%b}" + ("" if start.year == last.year else f" {start.year}")
    return f"{first} – {last.day} {last:%b %Y}"


def label(start: date, end: date, preset: str = "") -> str:
    """The period button: 'This year · 1 Jan – 13 Oct 2026 · W1–42'."""
    last = end - timedelta(days=1)
    (y1, w1, _), (y2, w2, _) = start.isocalendar(), last.isocalendar()
    if (y1, w1) == (y2, w2):
        weeks = f"W{w1}"
    elif y1 == y2:
        weeks = f"W{w1}–{w2}"
    else:  # across a new year: only short periods, where the numbers still help
        weeks = f"W{w1}–W{w2} {y2}" if (end - start).days <= 92 else ""
    return " · ".join(x for x in (preset, dates_text(start, end), weeks) if x)


def whole_weeks(start: date, end: date) -> bool:
    return start.weekday() == 0 and (end - start).days % 7 == 0


def describe(start: date, end: date) -> str:
    """'06 Oct 2026 – 12 Oct 2026 · week 41'"""
    return f"{start:%d %b %Y} – {end - timedelta(days=1):%d %b %Y} · {weeks_of(start, end)}"


# ---------------------------------------------------------------- comparisons --

_DATE_WORDS = (r"(?:\b(?:on|for|in|during|since|from|as of)\s+)?(?:"
               r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]{3,9}\.?\s+\d{4}"      # 13 Oct 2026, 12 of oct 2026
               r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"               # Oct 13, 2026
               r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"                            # 2026-10-13, 13/10/2026
               r"|(?:Q[1-4]\s+)?(?:19|20)\d{2}(?:\s+(?:so far|to date|YTD))?(?=\s*(?:$|[,;)(]))"  # 2026 at a phrase end
               r"|(?:this|last|previous|next)\s+(?:year|month|quarter|week)|yesterday|today"
               r"|(?:year|month)\s+to\s+date|YTD|MTD)\b")


def without_dates(title: str) -> str:
    """A title without the dates of the question it came from ("Sales by month, 2026" -> "Sales by
    month"): on a dashboard the chart follows the period picked there."""
    import re
    text = re.sub(_DATE_WORDS, "", title, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*[,;:]?\s*\)", "", text)                     # empty brackets left behind
    text = re.sub(r"[,;:]\s*\(", " (", text)                          # "customer, (top 25)" -> "customer (top 25)"
    text = re.sub(r"\s+([,;:)])", r"\1", re.sub(r"\s{2,}", " ", text))
    text = re.sub(r"[\s,;:\-–—·|]+$", "", text).strip()
    return text or title


def same_period_last_year(start: date, end: date, weekly: bool = False) -> tuple[date, date]:
    """The period a year earlier. Weekly periods move back 52 weeks, so Monday stays Monday
    (week 41 is compared with week 41); other periods keep their dates."""
    if weekly:
        return start - timedelta(weeks=52), end - timedelta(weeks=52)

    def shift(d: date) -> date:
        return d.replace(year=d.year - 1, day=28) if (d.month == 2 and d.day == 29) else d.replace(year=d.year - 1)
    return shift(start), shift(end)


def is_weekly(start: date, end: date, preset: str = "") -> bool:
    """Compare with the same weeks last year: whole weeks picked on the calendar, or this/last week."""
    return preset in ("This week", "Last week") or (not preset and whole_weeks(start, end))


# What every dashboard chart can be compared with (one choice for the whole dashboard, next to the
# period). The default is what headline numbers have always shown: the same period last year.
COMPARE_MODES = {"none": "No comparison", "previous": "Previous period", "last_year": "Same period last year",
                 "custom": "Other dates"}
DEFAULT_COMPARE = "last_year"
# How far back "previous period" goes for each quick choice: the same days of the previous week,
# month, quarter or year ("This month" 1-15 Oct is compared with 1-15 Sep), or the days just before.
_PREVIOUS = {"Today": ("days", 1, "yesterday"), "Yesterday": ("days", 1, "the day before"),
             "This week": ("days", 7, "last week"), "Last week": ("days", 7, "the week before"),
             "Last 7 days": ("days", 7, "the 7 days before"), "Last 30 days": ("days", 30, "the 30 days before"),
             "This month": ("months", 1, "last month"), "Last month": ("months", 1, "the month before"),
             "This quarter": ("months", 3, "last quarter"), "Last quarter": ("months", 3, "the quarter before"),
             "This year": ("months", 12, "last year"), "Last year": ("months", 12, "the year before"),
             "Last 12 months": ("months", 12, "the 12 months before")}


def shift_months(d: date, months: int) -> date:
    """The same day some months later (negative: earlier); the month's last day if it is shorter."""
    years, month0 = divmod(d.month - 1 + months, 12)
    first = date(d.year + years, month0 + 1, 1)
    days = (add_months(first, 1) - first).days
    return first.replace(day=min(d.day, days))


def _previous_shift(start: date, end: date, preset: str = "") -> tuple[str, int, str]:
    if preset in _PREVIOUS:
        return _PREVIOUS[preset]
    if start.day == 1 and end.day == 1:  # whole months picked on the calendar
        months = (end.year - start.year) * 12 + end.month - start.month
        return "months", months, "the month before" if months == 1 else f"the {months} months before"
    days = (end - start).days
    if days == 1:
        return "days", 1, "the day before"
    if whole_weeks(start, end):
        weeks = days // 7
        return "days", days, "the week before" if weeks == 1 else f"the {weeks} weeks before"
    return "days", days, f"the {days} days before"


def previous_period(start: date, end: date, preset: str = "") -> tuple[date, date]:
    """The period just before this one, of the same kind (see _PREVIOUS); end exclusive."""
    unit, n, _ = _previous_shift(start, end, preset)
    if unit == "months":  # a period to the end of a month compares with whole months (all of August)
        last = shift_months(end, -n) if end.day == 1 else shift_months(end - timedelta(days=1), -n) + timedelta(days=1)
        return shift_months(start, -n), last
    return start - timedelta(days=n), end - timedelta(days=n)


def compare_range(mode: str, start: date, end: date, preset: str = "",
                  custom: tuple[date, date] | None = None) -> tuple[date, date] | None:
    """The dates a period is compared with (end exclusive), or None for no comparison."""
    if mode == "previous":
        return previous_period(start, end, preset)
    if mode == "last_year":
        return same_period_last_year(start, end, is_weekly(start, end, preset))
    if mode == "custom" and custom:
        return custom
    return None


def compare_name(mode: str, start: date, end: date, preset: str = "",
                 custom: tuple[date, date] | None = None) -> str:
    """The comparison in a few words, for "+12% vs ...": 'last year', 'same weeks last year',
    'yesterday', 'last month', or the dates."""
    if mode == "last_year":
        return "same weeks last year" if is_weekly(start, end, preset) else "last year"
    if mode == "previous":
        return _previous_shift(start, end, preset)[2]
    if mode == "custom" and custom:
        return dates_text(*custom)
    return ""
