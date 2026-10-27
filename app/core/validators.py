"""Shared input validation: strict schema base, email normalization, password policy, phone format."""

import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, StringConstraints

PASSWORD_MIN = 10
PASSWORD_MAX = 128
_PHONE_CHARS = re.compile(r"^\+?[\d\s()\-]+$")


class StrictModel(BaseModel):
    """Request schemas reject unknown fields (extra=forbid)."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_if_str(value: object) -> object:
    return normalize_email(value) if isinstance(value, str) else value


def check_password_policy(password: str, email: str | None = None) -> str:
    """10..128 chars, at least one letter and one digit, not equal to the email."""
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ValueError(f"Password must be {PASSWORD_MIN}..{PASSWORD_MAX} characters long")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one letter and one digit")
    if email is not None and password.strip().lower() == email.strip().lower():
        raise ValueError("Password must not be equal to the email")
    return password


def check_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    digits = sum(c.isdigit() for c in value)
    if not _PHONE_CHARS.match(value) or not 10 <= digits <= 15 or len(value) > 32:
        raise ValueError("Invalid phone number format")
    return value


NormalizedEmail = Annotated[EmailStr, BeforeValidator(_normalize_if_str)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Phone = Annotated[str, BeforeValidator(lambda v: check_phone(v) if isinstance(v, str) else v)]
