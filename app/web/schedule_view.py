"""Presentation rules of the schedule pages: reading filters and forms, labels, which buttons a row gets.

Pure functions, no I/O and no HTTP. The business rules stay in the services; what is repeated here (the moment a
button disappears) only decides what to show, the service still checks the rule when the button is pressed.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.core.local_time import LocalCalendar
from app.core.rbac import Role
from app.models.enums import AppointmentStatus, SlotStatus
from app.schedule.schemas import (
    AppointmentListItem,
    Id,
    Offset,
    QueryDate,
    SlotBatchCreate,
    SlotCreate,
    SlotManageItem,
)
from app.web import schedule_messages as texts
from app.web.dates import DATE_FORMAT_ERROR, TIME_FORMAT_ERROR, page_date, parse_page_date, parse_page_time

PAGE_SIZE = 50  # rows of the free-slot table per request
QUEUE_LIMIT = 200  # rows of a day queue / a day of slots (the API maximum)
HISTORY_DAYS = 365  # how far back "Моя запись" looks for past appointments

APPOINTMENT_LABELS: dict[AppointmentStatus, str] = {
    AppointmentStatus.BOOKED: "Записан",
    AppointmentStatus.ARRIVED: "Пришёл",
    AppointmentStatus.DONE: "Приём завершён",
    AppointmentStatus.CANCELLED: "Отменена",
    AppointmentStatus.NO_SHOW: "Не пришёл",
}
STATUS_OPTIONS = [(status.value, label) for status, label in APPOINTMENT_LABELS.items()]  # for the status select
SLOT_LABELS: dict[SlotStatus, str] = {
    SlotStatus.FREE: "Свободен",
    SlotStatus.BOOKED: "Занят",
    SlotStatus.CLOSED: "Закрыт",
}
STATUS_ERROR = "Выберите статус из списка"
DATE_RANGE_ERROR = "Введите дату с 2000 по 2100 год"
_DIGITS = re.compile(r"[0-9]{1,10}")
_MINUTES = re.compile(r"[0-9]{1,4}")


# The bounds are the API's own (app.schedule.schemas), so a page can never send what the API would refuse.
_ID = TypeAdapter(Id)
_OFFSET = TypeAdapter(Offset)
_DAY = TypeAdapter(QueryDate)


def parse_id(text: str | None) -> int | None:
    """A database id written with ASCII digits; anything else (letters, signs, huge numbers) is None."""
    if text is None or not _DIGITS.fullmatch(text.strip()):
        return None
    try:
        return _ID.validate_python(int(text))
    except ValidationError:
        return None


def parse_offset(text: str | None) -> int:
    if text is None or not _DIGITS.fullmatch(text.strip()):
        return 0
    try:
        return _OFFSET.validate_python(int(text))
    except ValidationError:
        return 0


def read_day(text: str) -> tuple[date | None, str | None]:
    """(day, None) for a real date inside the API's range, otherwise (None, message)."""
    day = parse_page_date(text)
    if day is None:
        return None, DATE_FORMAT_ERROR
    try:
        return _DAY.validate_python(day), None
    except ValidationError:
        return None, DATE_RANGE_ERROR


@dataclass(frozen=True, slots=True)
class Filters:
    """What the user typed (for the form again), the message per bad field and the parsed query parameters."""

    values: dict[str, str]
    errors: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)


def _typed(params: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    return {name: value for name in names if (value := params.get(name, "").strip())}


def _read_ids(values: dict[str, str], names: Iterable[str], errors: dict[str, str], query: dict[str, Any]) -> None:
    for name in names:
        if name in values:
            if (number := parse_id(values[name])) is None:
                errors[name] = texts.NOT_A_NUMBER
            else:
                query[name] = number


def _read_dates(values: dict[str, str], names: Iterable[str], errors: dict[str, str], query: dict[str, Any]) -> None:
    for name in names:
        if name in values:
            day, error = read_day(values[name])
            if day is None:
                errors[name] = error or DATE_FORMAT_ERROR
            else:
                query[name] = day
                values[name] = page_date(day)  # an ISO date comes back as дд.мм.гггг


def free_slot_filters(params: Mapping[str, str]) -> Filters:
    """Filters of /cabinet/schedule: doctor, specialty and a range of days (дд.мм.гггг)."""
    values = _typed(params, ("doctor_id", "specialty_id", "date_from", "date_to"))
    errors: dict[str, str] = {}
    query: dict[str, Any] = {}
    _read_ids(values, ("doctor_id", "specialty_id"), errors, query)
    _read_dates(values, ("date_from", "date_to"), errors, query)
    first, last = query.get("date_from"), query.get("date_to")
    if first and last and first > last:
        errors["date_from"] = texts.DATES_REVERSED
    return Filters(values, errors, query)


def queue_filters(params: Mapping[str, str], today: date) -> Filters:
    """Filters of the appointment queue; the day defaults to today."""
    values = _typed(params, ("date", "doctor_id", "status", "athlete_id"))
    values.setdefault("date", page_date(today))
    errors: dict[str, str] = {}
    query: dict[str, Any] = {}
    _read_ids(values, ("doctor_id",), errors, query)
    if (athlete_id := parse_id(values.get("athlete_id"))) is None:
        values.pop("athlete_id", None)  # a stale or hand-made athlete is simply no filter
    else:
        query["athlete_id"] = athlete_id
    _read_dates(values, ("date",), errors, query)
    if (chosen := values.get("status")) is not None:
        if chosen in AppointmentStatus:
            query["status"] = AppointmentStatus(chosen)
        else:
            errors["status"] = STATUS_ERROR
    if "date" in query:
        query["date_from"] = query["date_to"] = query.pop("date")
    return Filters(values, errors, query)


def slots_filters(params: Mapping[str, str], today: date, *, by_doctor: bool) -> Filters:
    """Filters of /cabinet/slots: one day, and for the admin one doctor."""
    values = _typed(params, ("date", "doctor_id") if by_doctor else ("date",))
    values.setdefault("date", page_date(today))
    errors: dict[str, str] = {}
    query: dict[str, Any] = {}
    _read_ids(values, ("doctor_id",), errors, query)
    _read_dates(values, ("date",), errors, query)
    if "date" in query:
        query["date_from"] = query["date_to"] = query.pop("date")
    return Filters(values, errors, query)


# --------------------------------------------------------------------------- the slot form


@dataclass(frozen=True, slots=True)
class SlotForm:
    values: dict[str, str]
    errors: dict[str, str]
    day: date | None = None
    start: datetime | None = None
    end: datetime | None = None
    slot_minutes: int | None = None
    doctor_id: int | None = None


def parse_slot_form(payload: Mapping[str, str], calendar: LocalCalendar, *, admin: bool) -> SlotForm:
    """Date and times are Moscow wall-clock text; the result carries them as aware UTC moments."""
    values = dict(payload)
    errors: dict[str, str] = {}
    day, day_error = read_day(values.get("slot_date", ""))
    if day is None:
        errors["slot_date"] = day_error or DATE_FORMAT_ERROR
    else:
        values["slot_date"] = page_date(day)
    times = {name: parse_page_time(values.get(name, "")) for name in ("start_time", "end_time")}
    for name, parsed in times.items():
        if parsed is None:
            errors[name] = TIME_FORMAT_ERROR
    minutes = None
    if "slot_minutes" in values:
        if _MINUTES.fullmatch(values["slot_minutes"]):
            minutes = int(values["slot_minutes"])
        else:
            errors["slot_minutes"] = "Введите длину слота в минутах (целое число)"
    doctor_id = parse_id(values.get("slot_doctor_id"))
    if admin and doctor_id is None:
        errors["slot_doctor_id"] = texts.CHOOSE_DOCTOR
    elif "slot_doctor_id" in values and doctor_id is None:
        errors["slot_doctor_id"] = texts.NOT_A_NUMBER
    start = end = None
    if not errors and day is not None and times["start_time"] and times["end_time"]:
        start, end = calendar.at(day, times["start_time"]), calendar.at(day, times["end_time"])
    return SlotForm(values, errors, day, start, end, minutes, doctor_id)


# --------------------------------------------------------------------------- rows and their buttons


@dataclass(frozen=True, slots=True)
class AppointmentRow:
    item: AppointmentListItem
    actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SlotRow:
    item: SlotManageItem
    actions: tuple[str, ...]


def appointment_actions(
    item: AppointmentListItem, role: Role, now: datetime, calendar: LocalCalendar
) -> tuple[str, ...]:
    """Buttons of an appointment row, in display order: arrive, no-show (registrar), cancel."""
    if item.status is not AppointmentStatus.BOOKED:
        return ()
    actions = []
    if role is Role.REGISTRAR:
        if calendar.day_of(now) == calendar.day_of(item.start_at):
            actions.append("arrive")
        if now >= item.end_at:
            actions.append("no-show")
    if now < (item.start_at if role is Role.ATHLETE else item.end_at):
        actions.append("cancel")
    return tuple(actions)


def appointment_row(item: AppointmentListItem, role: Role, now: datetime, calendar: LocalCalendar) -> AppointmentRow:
    return AppointmentRow(item, appointment_actions(item, role, now, calendar))


def slot_actions(item: SlotManageItem, now: datetime) -> tuple[str, ...]:
    if item.status is SlotStatus.FREE:
        return ("close",)
    if item.status is SlotStatus.CLOSED and item.start_at > now:
        return ("reopen",)
    return ()


def slot_row(item: SlotManageItem, now: datetime, *, manage: bool = True) -> SlotRow:
    """A read-only viewer (the doctor) gets no buttons."""
    return SlotRow(item, slot_actions(item, now) if manage else ())


def split_appointments(
    items: Iterable[AppointmentListItem], now: datetime
) -> tuple[list[AppointmentListItem], list[AppointmentListItem]]:
    """(upcoming, history): upcoming are active appointments not yet over, oldest first; history newest first."""
    upcoming, history = [], []
    for item in items:
        active = item.status in (AppointmentStatus.BOOKED, AppointmentStatus.ARRIVED) and item.end_at >= now
        (upcoming if active else history).append(item)
    return upcoming, sorted(history, key=lambda i: i.start_at, reverse=True)


def slot_request(form: SlotForm) -> SlotCreate | SlotBatchCreate:
    """One slot when the length is empty, otherwise the window cut into slots of that length. The form must be valid."""
    assert form.start is not None and form.end is not None
    if form.slot_minutes is None:
        return SlotCreate(doctor_id=form.doctor_id, start_at=form.start, end_at=form.end)
    return SlotBatchCreate(
        doctor_id=form.doctor_id, start_at=form.start, end_at=form.end, slot_minutes=form.slot_minutes
    )


def board_filters_after_create(form: SlotForm, *, admin: bool) -> Filters:
    """Filters that show the day (and for the admin the doctor) the slots were just made for."""
    assert form.day is not None
    shown: dict[str, Any] = {"doctor_id": form.doctor_id} if admin and form.doctor_id else {}
    return Filters(
        {"date": page_date(form.day), **{k: str(v) for k, v in shown.items()}}, {}, {"date_from": form.day, **shown}
    )
