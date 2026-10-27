"""Refresh token storage and revocation: DB is the source of truth, Redis blacklist only speeds up checks."""

import logging
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.auth.schemas import TokenPair
from app.core.access_tokens import AccessTokenService
from app.core.redis import REDIS_ERRORS
from app.core.security import hash_token, new_refresh_token
from app.models.system import RefreshToken
from app.models.user import User
from app.repositories.system import RefreshTokenRepository

log = logging.getLogger(__name__)


class TokenBlacklist:
    PREFIX = "refresh_blacklist:"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def add(self, tokens: list[RefreshToken]) -> None:
        """TTL = remaining life of each token. Best effort."""
        now = datetime.now(UTC)
        try:
            for token in tokens:
                ttl = int((token.expires_at - now).total_seconds())
                if ttl > 0:
                    await self.redis.set(self.PREFIX + token.token_hash, "1", ex=ttl)
        except REDIS_ERRORS:
            log.warning("Redis unavailable: refresh blacklist not updated")

    async def contains(self, token_hash: str) -> bool:
        try:
            return bool(await self.redis.exists(self.PREFIX + token_hash))
        except REDIS_ERRORS:
            return False  # the DB check still applies


class TokenService:
    def __init__(
        self,
        repo: RefreshTokenRepository,
        blacklist: TokenBlacklist,
        access_tokens: AccessTokenService,
        *,
        refresh_ttl_days: int,
    ) -> None:
        self.repo = repo
        self.blacklist = blacklist
        self.access_tokens = access_tokens
        self.refresh_ttl = timedelta(days=refresh_ttl_days)

    async def issue(self, user: User, user_agent: str | None) -> TokenPair:
        raw, token_hash = new_refresh_token()
        await self.repo.add(
            RefreshToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC) + self.refresh_ttl,
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        return TokenPair(access_token=self.access_tokens.issue(user.id, user.role), refresh_token=raw)

    async def find(self, raw_token: str, *, lock: bool = False) -> RefreshToken | None:
        """With `lock=True` the row is locked and re-read, so concurrent use of one token is serialized."""
        return await self.repo.get_by_hash(hash_token(raw_token), for_update=lock)

    async def is_blacklisted(self, token: RefreshToken) -> bool:
        return await self.blacklist.contains(token.token_hash)

    def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(UTC)

    async def revoke_all(self, user_id: int) -> list[RefreshToken]:
        return await self.repo.revoke_all_for_user(user_id, datetime.now(UTC))

    async def blacklist_revoked(self, tokens: list[RefreshToken]) -> None:
        """Call AFTER the transaction commit."""
        await self.blacklist.add(tokens)
