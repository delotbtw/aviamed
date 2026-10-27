"""Login attempt counters in Redis. Fail-open: if Redis is unavailable there is no limit."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

from app.core.redis import REDIS_ERRORS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Blocked:
    retry_after: int
    first: bool  # this very attempt crossed the threshold (later blocked attempts have first=False)


class AttemptLimiter(Protocol):
    async def acquire(self, email: str, ip: str | None, *, count_ip: bool = True) -> Blocked | None:
        """Reserve one attempt BEFORE the password is checked. Returns details if the limit is exceeded."""

    async def release_success(self, email: str, ip: str | None, *, count_ip: bool = True) -> None:
        """Successful attempt: reset the account counter and give the IP reservation back."""


class RedisAttemptLimiter:
    """Per-account (hashed email, also for unknown accounts) and per-IP counters with a fixed window.

    The reservation is one atomic INCR per key, so parallel guesses cannot slip through a check-then-increment gap.
    """

    def __init__(self, redis: Redis, *, max_attempts: int, max_attempts_ip: int, window_s: int) -> None:
        self.redis = redis
        self.max_attempts = max_attempts
        self.max_attempts_ip = max_attempts_ip
        self.window_s = window_s

    @staticmethod
    def _account_key(email: str) -> str:
        return f"login:acct:{hashlib.sha256(email.encode()).hexdigest()}"

    @staticmethod
    def _ip_key(ip: str | None) -> str:
        return f"login:ip:{ip or 'unknown'}"

    def _limits(self, email: str, ip: str | None, with_ip: bool) -> dict[str, int]:
        limits = {self._account_key(email): self.max_attempts}
        if with_ip:
            limits[self._ip_key(ip)] = self.max_attempts_ip
        return limits

    async def acquire(self, email: str, ip: str | None, *, count_ip: bool = True) -> Blocked | None:
        blocked_for, first = 0, False
        try:
            for key, limit in self._limits(email, ip, count_ip).items():
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.incr(key)
                    pipe.expire(key, self.window_s, nx=True)  # the window starts at the first attempt
                    pipe.ttl(key)
                    count, _, ttl = await pipe.execute()
                if count > limit:
                    blocked_for = max(blocked_for, ttl if ttl > 0 else self.window_s)
                    first = first or count == limit + 1
        except REDIS_ERRORS:
            log.warning("Redis unavailable: login rate limit skipped")
            return None
        return Blocked(blocked_for, first) if blocked_for else None

    async def release_success(self, email: str, ip: str | None, *, count_ip: bool = True) -> None:
        try:
            await self.redis.delete(self._account_key(email))
            if count_ip:
                await self._decrement_if_positive(self._ip_key(ip))
        except REDIS_ERRORS:
            log.warning("Redis unavailable: login counters not released")

    async def _decrement_if_positive(self, key: str) -> None:
        """WATCH-guarded DECR: never creates a negative, TTL-less key if the window already expired."""

        async def txn(pipe) -> None:
            value = await pipe.get(key)
            pipe.multi()
            if value is not None and int(value) > 0:
                pipe.decr(key)

        await self.redis.transaction(txn, key)
