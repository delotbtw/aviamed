"""Names the stage 2 implementation must provide (spec sections 3, 7.2, 7.4 and the contract in section 12)."""

import importlib
from datetime import UTC, datetime

import pytest

from app.core.exceptions import Conflict


def test_clock_dependency_exists():
    clock = importlib.import_module("app.core.clock")

    assert callable(clock.get_clock)
    now = clock.get_clock().now()
    assert now.tzinfo is not None and now.utcoffset().total_seconds() == 0
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5  # the default clock is the real one


@pytest.mark.parametrize("name", ["SlotTaken", "SlotUnavailable", "SlotOverlap", "AppointmentConflict"])
def test_domain_errors_are_conflicts(name):
    errors = importlib.import_module("app.schedule.service")

    assert issubclass(getattr(errors, name), Conflict)


def test_settings_defaults():
    from app.core.config import Settings

    s = Settings(_env_file=None)

    assert s.schedule_timezone == "Europe/Moscow"
    assert (s.schedule_horizon_days, s.slot_min_minutes, s.slot_max_minutes) == (60, 10, 240)
    assert (s.batch_max_slots, s.max_active_appointments, s.schedule_lock_timeout_ms) == (50, 20, 5000)


def test_timezone_database_is_available():
    from zoneinfo import ZoneInfo

    from app.core.config import get_settings

    assert ZoneInfo(get_settings().schedule_timezone).key == "Europe/Moscow"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("09:05", (9, 5)), ("00:00", (0, 0)), ("23:59", (23, 59)), (" 10:30 ", (10, 30))],
)
def test_Q3_parse_page_time_accepts(text, expected):
    from app.web.dates import parse_page_time

    parsed = parse_page_time(text)

    assert parsed is not None and (parsed.hour, parsed.minute, parsed.second) == (*expected, 0)


@pytest.mark.parametrize(
    "text", ["9:5", "9:05", "09:5", "24:00", "12:60", "10-30", "", "10:30:00", "1030", "ab:cd", "10.30"]
)
def test_Q3_parse_page_time_rejects(text):
    from app.web.dates import parse_page_time

    assert parse_page_time(text) is None


def test_Q3_page_date_accepts_iso_and_rejects_bad_forms():
    from datetime import date

    from app.web.dates import parse_page_date

    assert parse_page_date("2026-11-03") == date(2026, 11, 3)
    assert parse_page_date("03.11.2026") == date(2026, 11, 3)
    for bad in ("31.02.2026", "3.11.2026", "03.11.26", "2026.11.03", ""):
        assert parse_page_date(bad) is None


def test_Q3_time_error_message_is_the_spec_text():
    from app.web import dates

    assert dates.TIME_FORMAT_ERROR == "Введите время в формате чч:мм"
    assert dates.DATE_FORMAT_ERROR == "Введите существующую дату в формате дд.мм.гггг"
