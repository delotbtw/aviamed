"""Dates on pages are typed as дд.мм.гггг whatever the browser locale is; the JSON API keeps ISO."""

import re
from datetime import date

DATE_FIELDS = ("birth_date", "consent_signed_at")
DATE_FORMAT_ERROR = "Введите существующую дату в формате дд.мм.гггг"

_RU = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


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
            out[field] = parsed.strftime("%d.%m.%Y")
    return out
