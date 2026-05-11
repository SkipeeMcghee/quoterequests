from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


DATE_RANGE_PRESET_GROUPS = (
    (
        "All Dates",
        (
            ("all_dates", "All Dates"),
        ),
    ),
    (
        "Day",
        (
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("tomorrow", "Tomorrow"),
        ),
    ),
    (
        "Week",
        (
            ("this_week", "This Week"),
            ("last_week", "Last Week"),
            ("next_week", "Next Week"),
            ("this_week_to_date", "This Week to Date"),
            ("last_week_to_date", "Last Week to Date"),
        ),
    ),
    (
        "Month",
        (
            ("this_month", "This Month"),
            ("last_month", "Last Month"),
            ("next_month", "Next Month"),
            ("this_month_to_date", "This Month to Date"),
            ("last_month_to_date", "Last Month to Date"),
        ),
    ),
    (
        "Quarter",
        (
            ("this_quarter", "This Quarter"),
            ("last_quarter", "Last Quarter"),
            ("next_quarter", "Next Quarter"),
            ("this_quarter_to_date", "This Quarter to Date"),
            ("last_quarter_to_date", "Last Quarter to Date"),
        ),
    ),
    (
        "Year",
        (
            ("this_year", "This Year"),
            ("last_year", "Last Year"),
            ("next_year", "Next Year"),
            ("this_year_to_date", "This Year to Date"),
            ("last_year_to_date", "Last Year to Date"),
        ),
    ),
)


_PRESET_LABELS = {
    preset_key: preset_label
    for _, group_options in DATE_RANGE_PRESET_GROUPS
    for preset_key, preset_label in group_options
}

_PRESET_ALIASES = {
    "this_day": "today",
    "last_day": "yesterday",
    "next_day": "tomorrow",
    "day_to_date": "today",
    "week_to_date": "this_week_to_date",
    "month_to_date": "this_month_to_date",
    "quarter_to_date": "this_quarter_to_date",
    "year_to_date": "this_year_to_date",
}

_PERIOD_KEYS = {"day", "week", "month", "quarter", "year"}
_TO_DATE_PERIOD_KEYS = {"week", "month", "quarter", "year"}


@dataclass(frozen=True)
class ResolvedDateRangePreset:
    key: str
    label: str
    start_date: date | None
    end_date: date | None


def _shift_month(year_value: int, month_value: int, offset: int) -> tuple[int, int]:
    shifted_month_index = (year_value * 12 + (month_value - 1)) + offset
    return shifted_month_index // 12, (shifted_month_index % 12) + 1


def _month_bounds(year_value: int, month_value: int) -> tuple[date, date]:
    return (
        date(year_value, month_value, 1),
        date(year_value, month_value, monthrange(year_value, month_value)[1]),
    )


def _quarter_bounds(reference_date: date, offset: int = 0) -> tuple[date, date]:
    quarter_start_month = ((reference_date.month - 1) // 3) * 3 + 1
    start_year, start_month = _shift_month(reference_date.year, quarter_start_month, offset * 3)
    end_year, end_month = _shift_month(start_year, start_month, 2)
    _, end_date = _month_bounds(end_year, end_month)
    return date(start_year, start_month, 1), end_date


def _period_bounds(reference_date: date, period_key: str, offset: int = 0) -> tuple[date, date]:
    if period_key == "day":
        target_date = reference_date + timedelta(days=offset)
        return target_date, target_date

    if period_key == "week":
        start_date = reference_date - timedelta(days=reference_date.weekday()) + timedelta(days=offset * 7)
        return start_date, start_date + timedelta(days=6)

    if period_key == "month":
        target_year, target_month = _shift_month(reference_date.year, reference_date.month, offset)
        return _month_bounds(target_year, target_month)

    if period_key == "quarter":
        return _quarter_bounds(reference_date, offset)

    if period_key == "year":
        target_year = reference_date.year + offset
        return date(target_year, 1, 1), date(target_year, 12, 31)

    raise ValueError(f"Unsupported date range period: {period_key}")


def _period_to_date_bounds(reference_date: date, period_key: str, offset: int = 0) -> tuple[date, date]:
    if period_key not in _TO_DATE_PERIOD_KEYS:
        raise ValueError(f"Unsupported to-date period: {period_key}")

    if offset not in {0, -1}:
        raise ValueError(f"Unsupported to-date offset: {offset}")

    current_start_date, _ = _period_bounds(reference_date, period_key, 0)
    target_start_date, target_end_date = _period_bounds(reference_date, period_key, offset)

    if offset == 0:
        return target_start_date, reference_date

    elapsed_days = (reference_date - current_start_date).days
    return target_start_date, min(target_end_date, target_start_date + timedelta(days=elapsed_days))


def resolve_date_range_preset(
    preset_key: str | None,
    *,
    reference_date: date | None = None,
) -> ResolvedDateRangePreset | None:
    if not preset_key:
        return None

    normalized_key = _PRESET_ALIASES.get(preset_key.strip().lower(), preset_key.strip().lower())
    anchor_date = reference_date or date.today()

    if normalized_key == "all_dates":
        start_date = None
        end_date = None
    elif normalized_key in {"today", "yesterday", "tomorrow"}:
        day_offset = {
            "today": 0,
            "yesterday": -1,
            "tomorrow": 1,
        }[normalized_key]
        start_date, end_date = _period_bounds(anchor_date, "day", day_offset)
    elif normalized_key.endswith("_to_date"):
        base_key = normalized_key[: -len("_to_date")]
        if base_key.startswith("this_"):
            period_key = base_key[len("this_") :]
            offset = 0
        elif base_key.startswith("last_"):
            period_key = base_key[len("last_") :]
            offset = -1
        else:
            return None

        if period_key not in _TO_DATE_PERIOD_KEYS:
            return None

        start_date, end_date = _period_to_date_bounds(anchor_date, period_key, offset)
    elif normalized_key.startswith("this_"):
        period_key = normalized_key[len("this_") :]
        if period_key not in _PERIOD_KEYS:
            return None
        start_date, end_date = _period_bounds(anchor_date, period_key)
    elif normalized_key.startswith("last_"):
        period_key = normalized_key[len("last_") :]
        if period_key not in _PERIOD_KEYS:
            return None
        start_date, end_date = _period_bounds(anchor_date, period_key, -1)
    elif normalized_key.startswith("next_"):
        period_key = normalized_key[len("next_") :]
        if period_key not in _PERIOD_KEYS:
            return None
        start_date, end_date = _period_bounds(anchor_date, period_key, 1)
    else:
        return None

    return ResolvedDateRangePreset(
        key=normalized_key,
        label=_PRESET_LABELS[normalized_key],
        start_date=start_date,
        end_date=end_date,
    )