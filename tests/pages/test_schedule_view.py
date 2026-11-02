"""Pure helpers of the schedule pages: filter and form reading, row buttons, messages, template filters, menu gating."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.core.exceptions import Conflict, InvalidInput
from app.core.local_time import LocalCalendar
from app.core.rbac import Role, roles_for
from app.models.enums import AppointmentStatus, SlotStatus
from app.models.user import User
from app.schedule import planning
from app.schedule.schemas import AppointmentListItem, SlotBatchCreate, SlotCreate, SlotManageItem
from app.web import schedule_messages as texts
from app.web.dates import local_date, local_time, page_date
from app.web.nav import PAGE_ACTIONS, nav_links
from app.web.schedule_view import (
    appointment_actions,
    board_filters_after_create,
    free_slot_filters,
    parse_id,
    parse_offset,
    parse_slot_form,
    queue_filters,
    read_day,
    slot_actions,
    slot_request,
    slots_filters,
    split_appointments,
)

CAL = LocalCalendar("Europe/Moscow")
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)  # 09:00 in Moscow
TODAY = date(2026, 11, 2)


def appointment(status=AppointmentStatus.BOOKED, start=NOW + timedelta(hours=3), minutes=30):
    return AppointmentListItem(
        id=1,
        status=status,
        slot_id=1,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        doctor_name="A",
        specialty="S",
        cabinet=None,
        athlete_id=2,
        athlete_name="B",
        case_id=None,
        cancelled_at=None,
        doctor_active=True,
    )


def slot(status, start=NOW + timedelta(hours=3)):
    return SlotManageItem(
        id=1,
        doctor_id=1,
        doctor_name="A",
        specialty="S",
        cabinet=None,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=status,
        appointment=None,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5", 5),
        (" 12 ", 12),
        ("0", None),
        ("-1", None),
        ("abc", None),
        ("٣", None),
        ("99999999999", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_id(text, expected):
    assert parse_id(text) == expected


def test_free_slot_filters_read_ids_and_dates():
    f = free_slot_filters({"doctor_id": "3", "date_from": "03.11.2026", "date_to": "2026-11-05"})

    assert f.errors == {} and f.query == {"doctor_id": 3, "date_from": date(2026, 11, 3), "date_to": date(2026, 11, 5)}


def test_free_slot_filters_report_every_bad_field_and_the_reversed_range():
    bad = free_slot_filters({"doctor_id": "x", "date_to": "31.02.2026"})
    reversed_ = free_slot_filters({"date_from": "05.11.2026", "date_to": "04.11.2026"})

    assert set(bad.errors) == {"doctor_id", "date_to"} and bad.values["date_to"] == "31.02.2026"
    assert reversed_.errors == {"date_from": texts.DATES_REVERSED}


def test_queue_filters_default_to_today_and_validate_status():
    f = queue_filters({}, TODAY)
    bad = queue_filters({"status": "nope"}, TODAY)

    assert f.values["date"] == "02.11.2026" and f.query == {"date_from": TODAY, "date_to": TODAY}
    assert "status" in bad.errors
    assert queue_filters({"status": "booked"}, TODAY).query["status"] is AppointmentStatus.BOOKED


def test_slots_filters_take_the_doctor_only_for_the_admin():
    assert "doctor_id" in slots_filters({"doctor_id": "2"}, TODAY, by_doctor=True).query
    assert "doctor_id" not in slots_filters({"doctor_id": "2"}, TODAY, by_doctor=False).query


def test_slot_form_converts_moscow_text_to_utc():
    form = parse_slot_form(
        {"slot_date": "03.11.2026", "start_time": "10:30", "end_time": "11:00", "slot_minutes": "15"}, CAL, admin=False
    )

    assert form.errors == {} and form.start == datetime(2026, 11, 3, 7, 30, tzinfo=UTC) and form.slot_minutes == 15


def test_slot_form_collects_errors_per_field():
    form = parse_slot_form({"slot_date": "3.11.2026", "start_time": "9:00", "slot_minutes": "x"}, CAL, admin=True)

    assert set(form.errors) == {"slot_date", "start_time", "end_time", "slot_minutes", "slot_doctor_id"}
    assert form.start is None


@pytest.mark.parametrize(
    ("role", "start", "expected"),
    [
        (Role.ATHLETE, NOW + timedelta(hours=1), ["cancel"]),
        (Role.ATHLETE, NOW - timedelta(minutes=1), []),
        (Role.REGISTRAR, NOW + timedelta(hours=1), ["arrive", "cancel"]),
        (Role.REGISTRAR, NOW - timedelta(hours=2), ["arrive", "no-show"]),
        (Role.REGISTRAR, NOW + timedelta(days=1), ["cancel"]),
        (Role.ADMIN, NOW + timedelta(hours=1), ["cancel"]),
    ],
)
def test_appointment_actions_follow_role_and_time(role, start, expected):
    assert list(appointment_actions(appointment(start=start), role, NOW, CAL)) == expected


def test_appointment_actions_are_empty_unless_booked():
    for status in set(AppointmentStatus) - {AppointmentStatus.BOOKED}:
        assert appointment_actions(appointment(status), Role.REGISTRAR, NOW, CAL) == ()


def test_slot_actions():
    assert slot_actions(slot(SlotStatus.FREE), NOW) == ("close",)
    assert slot_actions(slot(SlotStatus.BOOKED), NOW) == ()
    assert slot_actions(slot(SlotStatus.CLOSED), NOW) == ("reopen",)
    assert slot_actions(slot(SlotStatus.CLOSED, NOW - timedelta(hours=1)), NOW) == ()


def test_split_appointments_puts_cancelled_and_past_into_history_newest_first():
    live = appointment()
    cancelled = appointment(AppointmentStatus.CANCELLED)
    old = appointment(AppointmentStatus.DONE, start=NOW - timedelta(days=3))
    older = appointment(AppointmentStatus.DONE, start=NOW - timedelta(days=9))

    upcoming, history = split_appointments([older, live, old, cancelled], NOW)

    assert upcoming == [live] and history == [cancelled, old, older]


def test_action_message_uses_the_table_of_the_action():
    assert texts.action_message(Conflict("Slot has already started"), texts.BOOKING) == (
        "Приём уже начался, запись невозможна"
    )
    assert texts.action_message(Conflict("Slot has already started"), texts.CANCEL) == (
        "Приём уже начался, отмена невозможна"
    )
    assert texts.action_message(Conflict("Slots overlap: 2026-11-03T07:30:00Z"), texts.SLOT_CREATE) == texts.OVERLAP


@pytest.mark.parametrize(
    ("detail", "batch", "field"),
    [
        (planning.SLOT_IN_PAST, False, "start_time"),
        (planning.END_NOT_AFTER_START, True, "end_time"),
        (planning.WINDOW_NOT_DIVISIBLE, True, "slot_minutes"),
        ("Slot length must be between 10 and 240 minutes", False, "end_time"),
        ("Slot length must be between 10 and 240 minutes", True, "slot_minutes"),
        ("something new", False, "_general"),
    ],
)
def test_slot_form_error_picks_the_field(detail, batch, field):
    assert texts.slot_form_error(InvalidInput(detail), get_settings(), batch=batch)[0] == field


def test_template_filters_show_the_schedule_time_zone_and_page_date():
    assert (local_date(NOW), local_time(NOW)) == ("02.11.2026", "09:00")
    assert page_date(date(2026, 1, 5)) == "05.01.2026"


@pytest.mark.parametrize("role", list(Role))
def test_schedule_links_never_lead_to_a_forbidden_page(role):
    for link in nav_links(User(role=role)):
        if link.href in PAGE_ACTIONS:
            assert role in roles_for(PAGE_ACTIONS[link.href])


@pytest.mark.parametrize(("text", "expected"), [("5", 5), ("100000", 100000), ("100001", 0), ("x", 0), (None, 0)])
def test_parse_offset_uses_the_api_bound(text, expected):
    assert parse_offset(text) == expected


@pytest.mark.parametrize(
    ("text", "ok"), [("01.01.2000", True), ("01.01.1999", False), ("01.01.2100", True), ("02.01.2100", False)]
)
def test_read_day_uses_the_api_range(text, ok):
    day, error = read_day(text)

    assert (day is not None) is ok and (error is None) is ok


def test_iso_dates_come_back_as_russian_dates():
    assert free_slot_filters({"date_from": "2026-11-03"}).values["date_from"] == "03.11.2026"


def test_queue_filter_drops_a_broken_athlete_silently():
    f = queue_filters({"athlete_id": "x"}, TODAY)

    assert f.errors == {} and "athlete_id" not in f.values and "athlete_id" not in f.query


def test_slot_request_is_a_batch_only_with_a_length():
    base = {"slot_date": "03.11.2026", "start_time": "09:00", "end_time": "10:00"}
    single = slot_request(parse_slot_form(base, CAL, admin=False))
    batch = slot_request(parse_slot_form({**base, "slot_minutes": "30"}, CAL, admin=False))

    assert isinstance(single, SlotCreate) and isinstance(batch, SlotBatchCreate) and batch.slot_minutes == 30


def test_board_after_create_shows_the_day_and_for_the_admin_the_doctor():
    form = parse_slot_form(
        {"slot_date": "03.11.2026", "start_time": "09:00", "end_time": "10:00", "slot_doctor_id": "7"}, CAL, admin=True
    )

    admin = board_filters_after_create(form, admin=True)
    doctor = board_filters_after_create(form, admin=False)

    assert admin.values == {"date": "03.11.2026", "doctor_id": "7"} and admin.query["doctor_id"] == 7
    assert "doctor_id" not in doctor.values
