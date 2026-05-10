from datetime import date

from app.date_ranges import DATE_RANGE_PRESET_GROUPS, resolve_date_range_preset


def test_date_range_preset_groups_cover_all_periods_and_modes():
    preset_keys = {
        preset_key
        for _, group_options in DATE_RANGE_PRESET_GROUPS
        for preset_key, _ in group_options
    }

    assert preset_keys == {
        "all_dates",
        "today",
        "yesterday",
        "tomorrow",
        "this_week",
        "last_week",
        "next_week",
        "this_week_to_date",
        "last_week_to_date",
        "this_month",
        "last_month",
        "next_month",
        "this_month_to_date",
        "last_month_to_date",
        "this_quarter",
        "last_quarter",
        "next_quarter",
        "this_quarter_to_date",
        "last_quarter_to_date",
        "this_year",
        "last_year",
        "next_year",
        "this_year_to_date",
        "last_year_to_date",
    }


def test_resolve_date_range_preset_handles_human_day_labels_and_legacy_aliases():
    anchor_date = date(2026, 5, 10)

    all_dates = resolve_date_range_preset("all_dates", reference_date=anchor_date)
    today = resolve_date_range_preset("today", reference_date=anchor_date)
    yesterday = resolve_date_range_preset("last_day", reference_date=anchor_date)
    tomorrow = resolve_date_range_preset("next_day", reference_date=anchor_date)
    legacy_week_to_date = resolve_date_range_preset("week_to_date", reference_date=anchor_date)

    assert all_dates.label == "All Dates"
    assert all_dates.start_date is None
    assert all_dates.end_date is None

    assert today.label == "Today"
    assert today.start_date == anchor_date
    assert today.end_date == anchor_date

    assert yesterday.label == "Yesterday"
    assert yesterday.start_date == date(2026, 5, 9)
    assert yesterday.end_date == date(2026, 5, 9)

    assert tomorrow.label == "Tomorrow"
    assert tomorrow.start_date == date(2026, 5, 11)
    assert tomorrow.end_date == date(2026, 5, 11)

    assert legacy_week_to_date.key == "this_week_to_date"
    assert legacy_week_to_date.label == "This Week to Date"


def test_resolve_date_range_preset_handles_last_and_this_to_date_windows():
    anchor_date = date(2026, 5, 10)

    last_quarter = resolve_date_range_preset("last_quarter", reference_date=anchor_date)
    this_quarter_to_date = resolve_date_range_preset("this_quarter_to_date", reference_date=anchor_date)
    last_month_to_date = resolve_date_range_preset("last_month_to_date", reference_date=anchor_date)
    next_year = resolve_date_range_preset("next_year", reference_date=anchor_date)

    assert last_quarter.label == "Last Quarter"
    assert last_quarter.start_date == date(2026, 1, 1)
    assert last_quarter.end_date == date(2026, 3, 31)

    assert this_quarter_to_date.label == "This Quarter to Date"
    assert this_quarter_to_date.start_date == date(2026, 4, 1)
    assert this_quarter_to_date.end_date == anchor_date

    assert last_month_to_date.label == "Last Month to Date"
    assert last_month_to_date.start_date == date(2026, 4, 1)
    assert last_month_to_date.end_date == date(2026, 4, 10)

    assert next_year.label == "Next Year"
    assert next_year.start_date == date(2027, 1, 1)
    assert next_year.end_date == date(2027, 12, 31)

    assert resolve_date_range_preset("next_month_to_date", reference_date=anchor_date) is None