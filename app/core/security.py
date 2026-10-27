"""Password hashing and refresh-token primitives. Access (JWT) tokens live in core/access_tokens.py."""

import asyncio
import hashlib
import secrets
from typing import Protocol

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordHasher(Protocol):
    """Abstraction injected into services. Argon2 is CPU-bound: implementations must not block the event loop."""

    async def hash(self, password: str) -> str: ...

    async def verify(self, password: str, password_hash: str) -> bool: ...

    async def verify_dummy(self, password: str) -> None:
        """Spend the time of a real verification (hides whether an account exists)."""


class Argon2PasswordHasher:
    """Library-default argon2 parameters; the blocking work runs in a thread."""

    def __init__(self) -> None:
        self._argon2 = _Argon2()
        self._dummy_hash = self._argon2.hash("dummy-password-for-timing")

    def _verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._argon2.hash, password)

    async def verify(self, password: str, password_hash: str) -> bool:
        return await asyncio.to_thread(self._verify, password, password_hash)

    async def verify_dummy(self, password: str) -> None:
        await asyncio.to_thread(self._verify, password, self._dummy_hash)


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for the client, sha256 hash for the DB)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
