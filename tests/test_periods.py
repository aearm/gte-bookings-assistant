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


def test_titles_without_dates():
    assert periods.without_dates("Sales by month, 2026") == "Sales by month"
    assert periods.without_dates("Requests, bookings and sales by customer, 13 Oct 2026 (top 25 by sales)") == \
        "Requests, bookings and sales by customer (top 25 by sales)"
    assert periods.without_dates("Bookings by country this year") == "Bookings by country"
    assert periods.without_dates("Top 5 suppliers in Q3 2025") == "Top 5 suppliers"
    assert periods.without_dates("Sales on 2026-10-13 by channel") == "Sales by channel"
    assert periods.without_dates("Hotels with 2026 rates") == "Hotels with 2026 rates"  # a year inside a phrase stays
    assert periods.without_dates("2026") == "2026"  # never an empty title
    # ranges and comparisons go whole, not leaving "…, 14" behind
    assert periods.without_dates("Sales by day for the top 10 customers by bookings, 14–15 Oct 2026") == \
        "Sales by day for the top 10 customers by bookings"
    assert periods.without_dates("Sales by month, 1 Jan – 30 Sep 2026") == "Sales by month"
    assert periods.without_dates("Sales Oct 14–15, 2026 by channel") == "Sales by channel"
    assert periods.without_dates("Bookings 14 Oct 2026 vs 15 Oct 2026") == "Bookings"
    assert periods.without_dates("Bookings yesterday vs the day before by customer") == "Bookings by customer"
    assert periods.without_dates("Sales by customer over the last 7 days") == "Sales by customer"
    assert periods.without_dates("Top 10 customers 2026") == "Top 10 customers"  # not "Top": "customers" is no month
    assert periods.without_dates("Sales by domain") == "Sales by domain"
    assert periods.without_dates("Sales by month, Oct 2026") == "Sales by month"


def test_previous_period_is_the_same_kind_of_period():
    today = date(2026, 10, 15)
    previous = lambda name: periods.dates_text(*periods.previous_period(*periods.preset_range(name, today), name))
    assert previous("Today") == "14 Oct 2026"
    assert previous("This week") == "5 Oct – 8 Oct 2026"         # the same days of last week (Mon-Thu)
    assert previous("This month") == "1 Sep – 15 Sep 2026"       # the same days of last month
    assert previous("Last month") == "1 Aug – 31 Aug 2026"       # all of August, though September has 30 days
    assert previous("Last quarter") == "1 Apr – 30 Jun 2026"
    assert previous("Last 30 days") == "17 Aug – 15 Sep 2026"
    assert periods.previous_period(*periods.week_range(2026, 41, 42)) == periods.week_range(2026, 39, 40)
    assert periods.previous_period(date(2026, 3, 1), date(2026, 4, 1)) == (date(2026, 2, 1), date(2026, 3, 1))
    assert periods.shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)


def test_comparisons_and_their_names():
    start, end = periods.preset_range("This month", date(2026, 10, 15))
    assert periods.compare_range("none", start, end, "This month") is None
    assert periods.compare_range("last_year", start, end, "This month") == (date(2025, 10, 1), date(2025, 10, 16))
    assert periods.compare_name("last_year", start, end, "This month") == "last year"
    assert periods.compare_name("previous", start, end, "This month") == "last month"
    assert periods.compare_name("last_year", *periods.week_range(2026, 41)) == "same weeks last year"
    other = (date(2026, 10, 12), date(2026, 10, 13))
    assert periods.compare_range("custom", start, end, "", other) == other
    assert periods.compare_name("custom", start, end, "", other) == "12 Oct 2026"
