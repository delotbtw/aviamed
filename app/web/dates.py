"""Dates on pages are typed as дд.мм.гггг whatever the browser locale is; the JSON API keeps ISO."""

import re
from datetime import date, datetime, time

from app.core.config import get_settings
from app.core.local_time import LocalCalendar

DATE_FIELDS = ("birth_date", "consent_signed_at")
DATE_FORMAT_ERROR = "Введите существующую дату в формате дд.мм.гггг"
TIME_FORMAT_ERROR = "Введите время в формате чч:мм"

_RU = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TIME = re.compile(r"(\d{2}):(\d{2})")


def parse_page_date(text: str) -> date | None:
    """дд.мм.гггг (or ISO, for compatibility) -> date; None when the text is not a real calendar date."""
    text = text.strip()
    if m := _RU.fullmatch(text):
        day, month, year = (int(g) for g in m.groups())
    elif m := _ISO.fullmatch(text):
        year, month, day = (int(g) for g in m.groups())
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_page_time(text: str) -> time | None:
    """чч:мм with two digits each (00:00..23:59) -> time; None for anything else."""
    if not (m := _TIME.fullmatch(text.strip())):
        return None
    hour, minute = (int(g) for g in m.groups())
    return time(hour, minute) if hour < 24 and minute < 60 else None


def page_date(day: date) -> str:
    """date -> дд.мм.гггг, the format of every date field on pages."""
    return day.strftime("%d.%m.%Y")


def normalize_dates(payload: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Payload with the date fields turned into ISO, and field -> message for the ones that could not be read."""
    out, errors = dict(payload), {}
    for field in DATE_FIELDS:
        if field not in out:
            continue
        parsed = parse_page_date(out[field])
        if parsed is None:
            del out[field]
            errors[field] = DATE_FORMAT_ERROR
        else:
            out[field] = parsed.isoformat()
    return out, errors


def show_dates(values: dict[str, str]) -> dict[str, str]:
    """Entered values for the form again: readable dates as дд.мм.гггг, anything else as typed."""
    out = dict(values)
    for field in DATE_FIELDS:
        if field in out and (parsed := parse_page_date(out[field])) is not None:
            out[field] = page_date(parsed)
    return out


# --------------------------------------------------------------------------- showing moments of the schedule


def _calendar() -> LocalCalendar:
    return LocalCalendar(get_settings().schedule_timezone)  # read per call: the zone is a setting, not a constant


def local_date(moment: datetime) -> str:
    """UTC moment -> дд.мм.гггг in the schedule time zone (template filter)."""
    return _calendar().to_local(moment).strftime("%d.%m.%Y")


def local_time(moment: datetime) -> str:
    """UTC moment -> чч:мм in the schedule time zone (template filter)."""
    return _calendar().to_local(moment).strftime("%H:%M")
