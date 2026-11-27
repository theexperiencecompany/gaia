"""The Redis client scouts keep their day's spend and their refreshed results in."""

from app.db.redis import AsyncRedisCommands, redis_cache
from app.utils.errors import AppError


def scouts_redis(*, message: str, why: str, fix: str) -> AsyncRedisCommands:
    """Return the client; with Redis unavailable, raise an AppError saying what that costs."""
    client = redis_cache.redis
    if client is None:
        raise AppError(message=message, why=why, fix=fix)
    return client
