"""Unit tests for the business priority matrix and SLA calendar (Issue #30)."""

from __future__ import annotations

from datetime import UTC, datetime

import testrunner

from eventflow_work_management.services.business_calendar import (
    CalendarError,
    add_working_minutes,
    parse_business_hours,
    parse_holidays,
    warning_at,
)
from eventflow_work_management.services.priority import (
    calculate_priority,
    higher_priority,
    priority_rank,
)
from eventflow_work_management.services.sla import _warning_at


def test_priority_matrix_is_exhaustive_and_centralized():
    impacts = ("critical", "high", "moderate", "low")
    urgencies = ("immediate", "elevated", "normal", "low")
    values = {
        calculate_priority(impact, urgency)
        for impact in impacts
        for urgency in urgencies
    }
    assert values == {"critical", "high", "medium", "low"}
    assert calculate_priority("critical", "immediate") == "critical"
    assert calculate_priority("critical", "low") == "medium"
    assert calculate_priority("moderate", "elevated") == "medium"
    assert calculate_priority("low", "immediate") == "medium"
    assert calculate_priority("low", "low") == "low"


def test_priority_matrix_rejects_unknown_values():
    with testrunner.raises(Exception) as error:
        calculate_priority("catastrophic", "immediate")
    assert getattr(error.value, "status_code", None) == 400
    with testrunner.raises(Exception) as error:
        calculate_priority("low", "someday")
    assert getattr(error.value, "status_code", None) == 400


def test_priority_ordering_helpers():
    assert priority_rank("critical") < priority_rank("high")
    assert priority_rank("high") < priority_rank("medium")
    assert priority_rank("medium") < priority_rank("low")
    assert priority_rank("unknown") > priority_rank("low")
    assert higher_priority("low", "critical") == "critical"
    assert higher_priority("high", "high") == "high"


def test_business_calendar_skips_weekends_and_holidays():
    start = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)  # Friday 15:00 UTC
    due = add_working_minutes(
        start,
        180,
        timezone="UTC",
        business_hours={"monday": [["09:00", "17:00"]]},
        holidays=[],
    )
    assert due == datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    holiday_due = add_working_minutes(
        start,
        120,
        timezone="UTC",
        business_hours={"monday": [["09:00", "17:00"]]},
        holidays=["2026-10-19"],
    )
    assert holiday_due == datetime(2026, 10, 26, 11, 0, tzinfo=UTC)


def test_business_calendar_empty_hours_mean_24x7():
    start = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    due = add_working_minutes(
        start,
        60,
        timezone="UTC",
        business_hours={},
        holidays=[],
    )
    assert due == datetime(2026, 10, 19, 0, 30, tzinfo=UTC)


def test_business_calendar_respects_timezone():
    start = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)  # 09:00 Europe/Berlin (CEST)
    due = add_working_minutes(
        start,
        60,
        timezone="Europe/Berlin",
        business_hours={"monday": [["09:00", "10:00"]]},
        holidays=[],
    )
    assert due == datetime(2026, 10, 19, 8, 0, tzinfo=UTC)


def test_business_calendar_validation():
    with testrunner.raises(CalendarError):
        parse_business_hours({"funday": [["09:00", "10:00"]]})
    with testrunner.raises(CalendarError):
        parse_business_hours({"monday": [["10:00", "09:00"]]})
    with testrunner.raises(CalendarError):
        parse_holidays(["2026-13-01"])
    with testrunner.raises(CalendarError):
        add_working_minutes(
            datetime(2026, 10, 19, 9, 0),
            60,
            timezone="UTC",
            business_hours={},
            holidays=[],
        )
    with testrunner.raises(CalendarError):
        add_working_minutes(
            datetime(2026, 10, 19, 9, 0, tzinfo=UTC),
            60,
            timezone="Mars/Olympus",
            business_hours={},
            holidays=[],
        )


def test_sla_warning_uses_elapsed_business_time_across_weekends():
    start = datetime(2026, 10, 16, 16, 0, tzinfo=UTC)  # Friday 16:00 UTC
    warning = warning_at(
        start,
        120,
        75,
        timezone="UTC",
        business_hours={
            "friday": [["09:00", "17:00"]],
            "monday": [["09:00", "17:00"]],
        },
        holidays=[],
    )
    assert warning == datetime(2026, 10, 19, 9, 30, tzinfo=UTC)


def test_sla_warning_skips_excluded_hours_within_a_day():
    start = datetime(2026, 10, 19, 11, 30, tzinfo=UTC)  # Monday
    warning = warning_at(
        start,
        120,
        50,
        timezone="UTC",
        business_hours={
            "monday": [["09:00", "12:00"], ["13:00", "17:00"]],
        },
        holidays=[],
    )
    assert warning == datetime(2026, 10, 19, 13, 30, tzinfo=UTC)


def test_sla_warning_respects_timezone_boundaries_and_pause_shift():
    start = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)  # Sunday 22:00 New York
    warning = warning_at(
        start,
        120,
        50,
        timezone="America/New_York",
        business_hours={"monday": [["09:00", "17:00"]]},
        holidays=[],
        paused_seconds=3600,
    )
    assert warning == datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def test_sla_scheduler_uses_business_warning_helper():
    snapshot = {
        "timezone": "UTC",
        "business_hours": {
            "friday": [["09:00", "17:00"]],
            "monday": [["09:00", "17:00"]],
        },
        "holidays": [],
        "warning_threshold_percent": 75,
        "response_minutes": 120,
    }
    start = datetime(2026, 10, 16, 16, 0, tzinfo=UTC)
    assert _warning_at(start, 120, snapshot) == datetime(
        2026, 10, 19, 9, 30, tzinfo=UTC
    )
    assert _warning_at(start, 120, snapshot, paused_seconds=3600) == datetime(
        2026, 10, 19, 10, 30, tzinfo=UTC
    )
