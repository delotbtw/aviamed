"""Access tokens: a generic JWT codec and the access-token policy built on top of it (both get config injected)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import Settings
from app.core.exceptions import AuthenticationFailed


class JwtCodec:
    def __init__(self, secret_key: str, algorithm: str) -> None:
        self.secret_key = secret_key
        self.algorithm = algorithm

    def encode(self, payload: dict[str, Any]) -> str:
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode(self, token: str) -> dict[str, Any]:
        """Raises jwt.PyJWTError on an invalid or expired token; `exp` and `sub` are mandatory."""
        return jwt.decode(token, self.secret_key, algorithms=[self.algorithm], options={"require": ["exp", "sub"]})


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    role: str


class AccessTokenService:
    TYPE = "access"

    def __init__(self, codec: JwtCodec, ttl: timedelta) -> None:
        self.codec = codec
        self.ttl = ttl

    def issue(self, user_id: int, role: str) -> str:
        now = datetime.now(UTC)
        return self.codec.encode(
            {"sub": str(user_id), "role": str(role), "type": self.TYPE, "iat": now, "exp": now + self.ttl}
        )

    def parse(self, token: str) -> AccessClaims:
        """Raises AuthenticationFailed for anything that is not a valid access token."""
        try:
            payload = self.codec.decode(token)
            if payload.get("type") != self.TYPE:
                raise ValueError("not an access token")
            return AccessClaims(user_id=int(payload["sub"]), role=str(payload.get("role", "")))
        except (jwt.PyJWTError, ValueError, TypeError):
            raise AuthenticationFailed("Not authenticated") from None


def build_access_tokens(settings: Settings) -> AccessTokenService:
    """The single place where the access-token service is assembled from settings."""
    return AccessTokenService(
        JwtCodec(settings.secret_key, settings.jwt_algorithm), timedelta(minutes=settings.access_token_ttl_min)
    )
