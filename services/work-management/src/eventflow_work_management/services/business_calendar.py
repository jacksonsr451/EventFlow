"""Business-calendar arithmetic for SLA targets (Issue #30).

SLA targets are business minutes, not wall-clock minutes. This module owns the
deterministic translation from a timezone, a weekly business-hours map, and a
holiday list to an absolute UTC due timestamp. It never uses naive datetimes:
every input and output is timezone-aware UTC, and local conversion goes through
``zoneinfo``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class CalendarError(ValueError):
    """Raised when a calendar definition cannot be interpreted."""


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarError(f"unknown timezone: {name}") from exc


def _parse_time(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except (ValueError, AttributeError) as exc:
        raise CalendarError(f"invalid business-hours time: {value!r}") from exc


def parse_business_hours(raw: dict | None) -> dict[str, list[tuple[time, time]]]:
    """Normalize a weekly business-hours document into weekday intervals.

    A ``None`` or empty document means 24x7 arithmetic. Each interval is a
    two-element ``[start, end]`` list of ``HH:MM`` strings and must not wrap past
    midnight.
    """
    if not raw:
        return {}
    parsed: dict[str, list[tuple[time, time]]] = {}
    for day, intervals in raw.items():
        if day not in WEEKDAYS:
            raise CalendarError(f"unknown weekday: {day!r}")
        if not isinstance(intervals, list):
            raise CalendarError(f"business hours for {day} must be a list")
        day_intervals: list[tuple[time, time]] = []
        for interval in intervals:
            if not isinstance(interval, list) or len(interval) != 2:
                raise CalendarError("each business-hours interval is [start, end]")
            start = _parse_time(interval[0])
            end = _parse_time(interval[1])
            if end <= start:
                raise CalendarError("business-hours intervals must not wrap midnight")
            day_intervals.append((start, end))
        parsed[day] = sorted(day_intervals)
    return parsed


def parse_holidays(raw: list | None) -> set[date]:
    holidays: set[date] = set()
    for item in raw or []:
        try:
            holidays.add(date.fromisoformat(str(item)))
        except ValueError as exc:
            raise CalendarError(f"invalid holiday date: {item!r}") from exc
    return holidays


def _working_intervals(
    target_date: date,
    business_hours: dict[str, list[tuple[time, time]]],
    holidays: set[date],
    tz: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    if target_date in holidays:
        return []
    if not business_hours:
        start = datetime.combine(target_date, time(0, 0), tzinfo=tz)
        end = datetime.combine(target_date, time(0, 0), tzinfo=tz) + timedelta(days=1)
        return [(start, end)]
    intervals = business_hours.get(WEEKDAYS[target_date.weekday()], [])
    result = []
    for start_time, end_time in intervals:
        result.append(
            (
                datetime.combine(target_date, start_time, tzinfo=tz),
                datetime.combine(target_date, end_time, tzinfo=tz),
            )
        )
    return result


def add_working_minutes(
    start: datetime,
    minutes: int,
    *,
    timezone: str,
    business_hours: dict | None,
    holidays: list | None,
) -> datetime:
    """Return ``start`` advanced by ``minutes`` business minutes.

    ``start`` may be any timezone-aware datetime; it is interpreted in the
    policy timezone. The result is timezone-aware UTC.
    """
    if start.tzinfo is None:
        raise CalendarError("start must be timezone-aware")
    if minutes < 0:
        raise CalendarError("minutes must not be negative")
    tz = resolve_timezone(timezone)
    parsed_hours = parse_business_hours(business_hours)
    holiday_set = parse_holidays(holidays)
    remaining = timedelta(minutes=minutes)
    cursor = start.astimezone(tz)
    # Safety bound: at most two years of calendar scanning.
    for _ in range(740):
        current_date = cursor.date()
        intervals = _working_intervals(current_date, parsed_hours, holiday_set, tz)
        for interval_start, interval_end in intervals:
            if cursor < interval_start:
                cursor = interval_start
            if cursor >= interval_end:
                continue
            available = interval_end - cursor
            if available >= remaining:
                cursor = cursor + remaining
                return cursor.astimezone(UTC)
            remaining -= available
            cursor = interval_end
        if cursor.date() <= current_date:
            cursor = datetime.combine(
                current_date + timedelta(days=1), time(0, 0), tzinfo=tz
            )
    raise CalendarError("business calendar did not contain enough working minutes")
