from datetime import date

import periods

TUESDAY = date(2026, 10, 13)  # in ISO week 42 of 2026


def test_presets():
    assert periods.preset_range("Last 7 days", TUESDAY) == (date(2026, 10, 7), date(2026, 10, 14))
    assert periods.preset_range("This week", TUESDAY) == (date(2026, 10, 12), date(2026, 10, 14))
    assert periods.preset_range("Last week", TUESDAY) == (date(2026, 10, 5), date(2026, 10, 12))
    assert periods.preset_range("This month", TUESDAY) == (date(2026, 10, 1), date(2026, 10, 14))
    assert periods.preset_range("Last month", TUESDAY) == (date(2026, 9, 1), date(2026, 10, 1))
    assert periods.preset_range("This year", TUESDAY) == (date(2026, 1, 1), date(2026, 10, 14))
    assert periods.preset_range("Last 12 months", TUESDAY) == (date(2025, 11, 1), date(2026, 10, 14))
    assert periods.preset_range("Last month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2026, 1, 1))


def test_calendar_range_is_inclusive_and_ordered():
    assert periods.calendar_range(date(2026, 3, 9), date(2026, 3, 1)) == (date(2026, 3, 1), date(2026, 3, 10))


def test_iso_weeks():
    assert periods.current_week(TUESDAY) == (2026, 42)
    assert periods.weeks_in_year(2026) == 53  # 1 Jan 2026 is a Thursday
    assert periods.weeks_in_year(2025) == 52
    assert periods.week_start(2026, 1) == date(2025, 12, 29)  # week 1 starts in the previous year
    assert periods.week_range(2026, 42) == (date(2026, 10, 12), date(2026, 10, 19))
    assert periods.week_range(2026, 1, 3) == (date(2025, 12, 29), date(2026, 1, 19))
    assert periods.week_range(2026, 5, 2) == periods.week_range(2026, 2, 5)  # either order
    assert periods.week_range(2025, 53) == periods.week_range(2025, 52)  # no week 53 in 2025
    assert periods.week_label(2026, 42) == "W42 · 12 Oct – 18 Oct"


def test_describe_names_the_weeks():
    assert periods.describe(*periods.week_range(2026, 42)) == "12 Oct 2026 – 18 Oct 2026 · week 42"
    assert periods.describe(date(2026, 1, 1), date(2026, 10, 14)).endswith("weeks 1–42")
    assert periods.weeks_of(date(2025, 12, 22), date(2026, 1, 12)) == "weeks 52 (2025) – 2 (2026)"


def test_same_period_last_year():
    start, end = periods.week_range(2026, 42)
    prev = periods.same_period_last_year(start, end, weekly=True)
    assert prev == (date(2025, 10, 13), date(2025, 10, 20))
    assert prev[0].weekday() == 0 and prev[0].isocalendar().week == 42  # Monday of week 42 last year
    assert periods.same_period_last_year(date(2024, 2, 29), date(2024, 3, 1)) == (date(2023, 2, 28), date(2023, 3, 1))
    assert periods.is_weekly(*periods.week_range(2026, 41, 42))  # whole weeks picked on the calendar
    assert periods.is_weekly(date(2026, 10, 12), date(2026, 10, 14), "This week")
    assert not periods.is_weekly(*periods.preset_range("This month", TUESDAY), "This month")
    assert not periods.is_weekly(date(2026, 10, 6), date(2026, 10, 13))  # 7 days, but not Monday to Sunday


def test_more_presets():
    assert periods.preset_range("Today", TUESDAY) == (TUESDAY, date(2026, 10, 14))
    assert periods.preset_range("Yesterday", TUESDAY) == (date(2026, 10, 12), TUESDAY)
    assert periods.preset_range("Last 30 days", TUESDAY) == (date(2026, 9, 14), date(2026, 10, 14))
    assert periods.preset_range("This quarter", TUESDAY) == (date(2026, 10, 1), date(2026, 10, 14))
    assert periods.preset_range("Last quarter", TUESDAY) == (date(2026, 7, 1), date(2026, 10, 1))
    assert periods.preset_range("Last quarter", date(2026, 2, 1)) == (date(2025, 10, 1), date(2026, 1, 1))
    assert periods.preset_range("Last year", TUESDAY) == (date(2025, 1, 1), date(2026, 1, 1))
    assert all(periods.preset_range(n, TUESDAY)[0] < periods.preset_range(n, TUESDAY)[1] for n in periods.PRESETS)


def test_labels():
    year = periods.preset_range("This year", TUESDAY)
    assert periods.label(*year, "This year") == "This year · 1 Jan – 13 Oct 2026 · W1–42"
    assert periods.label(*periods.week_range(2026, 42)) == "12 Oct – 18 Oct 2026 · W42"
    assert periods.label(TUESDAY, date(2026, 10, 14), "Today") == "Today · 13 Oct 2026 · W42"
    assert periods.label(date(2025, 12, 22), date(2026, 1, 12)) == "22 Dec 2025 – 11 Jan 2026 · W52–W2 2026"
    assert periods.label(*periods.preset_range("Last 12 months", TUESDAY)) == "1 Nov 2025 – 13 Oct 2026"
