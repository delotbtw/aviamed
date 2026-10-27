"""Password hashing and JWT helpers. Token storage/revocation lives in auth service."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_ttl_min),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on invalid or expired token."""
    s = get_settings()
    return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for the client, sha256 hash for the DB)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
