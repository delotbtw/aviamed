from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

# Redis outage: callers degrade gracefully (rate limit fail-open, DB as source of truth).
REDIS_ERRORS = (RedisError, OSError)

REDIS_TIMEOUT_S = 1.0

_redis: Redis | None = None


def get_redis() -> Redis:
    """Lazy client: Redis is used for rate limits, refresh blacklist, slot cache."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=REDIS_TIMEOUT_S,  # a hung Redis must not hold request handlers (and their DB locks)
            socket_connect_timeout=REDIS_TIMEOUT_S,
        )
    return _redis


async def close_redis() -> None:
    """Shutdown hook."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
