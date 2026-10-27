"""Small shared helpers (plain functions; fixtures live in conftest.py)."""

import hashlib
from datetime import date, timedelta
from urllib.parse import unquote

STRONG_PASSWORD = "Str0ng-Passw0rd"
GENERIC_LOGIN_ERROR = "Invalid email or password"
GENERIC_REFRESH_ERROR = "Invalid refresh token"


def sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def location(resp) -> str:
    """Redirect target with percent-encoding undone (so `?next=%2Fcabinet` == `?next=/cabinet`)."""
    return unquote(resp.headers["location"])


def set_cookie_headers(resp) -> dict[str, str]:
    """name -> raw Set-Cookie header value."""
    out = {}
    for raw in resp.headers.get_list("set-cookie"):
        out[raw.split("=", 1)[0].strip()] = raw
    return out


def cookie_attrs(raw: str) -> dict[str, str | bool]:
    """Parse a Set-Cookie value into lowercase attribute dict (flags map to True)."""
    parts = [p.strip() for p in raw.split(";")]
    attrs: dict[str, str | bool] = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        attrs[k.lower()] = v if _ else True
    return attrs


def staff_payload(role: str, **extra) -> dict:
    base = {
        "email": f"new-{role}@example.com",
        "password": STRONG_PASSWORD,
        "role": role,
        "last_name": "Петров",
        "first_name": "Пётр",
    }
    return {**base, **extra}


def athlete_payload(**extra) -> dict:
    base = {
        "email": "new-athlete1@example.com",
        "password": STRONG_PASSWORD,
        "last_name": "Сидоров",
        "first_name": "Сидор",
        "birth_date": "2004-03-12",
        "sex": "male",
        "consent_paper_number": "PD-0001",
        "consent_signed_at": date.today().isoformat(),
    }
    return {**base, **extra}


def tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()
