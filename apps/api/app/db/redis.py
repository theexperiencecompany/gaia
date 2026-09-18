"""Redis caching infrastructure with type-safe Pydantic model support.

Supports generic JSON caching, TTL, pattern-based invalidation, and graceful fallback when
Redis is unavailable.
"""

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, cast, overload

from pydantic import TypeAdapter
from pydantic.type_adapter import TypeAdapter as TypeAdapterType
import redis.asyncio as redis
from redis.asyncio.client import Pipeline, PubSub
from redis.asyncio.lock import Lock

from app.config.settings import settings
from app.constants.cache import (
    DEFAULT_CACHE_TTL,
    ONE_YEAR_TTL,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# Re-export for backwards compatibility
CACHE_TTL = DEFAULT_CACHE_TTL

# Carries the ``model=`` argument through to the return type: ``get_cache(key, model=User)``
# is ``User | None``, not ``Any`` — without it a mismatched model goes unnoticed.
T = TypeVar("T")

# The four remaining ``Any`` returns are the no-model overload stubs (deserialize_any,
# RedisCache.get, get_cache, get_and_delete_cache). Measured: narrowing them to ``object``
# produced 31 new mypy errors across 14 files — do not re-litigate without re-measuring.


def serialize_any(data: object, model: type[Any] | None = None) -> str:
    """Serialize a Python object to a JSON string, validating against model if provided."""
    adapter: TypeAdapterType[Any] = TypeAdapter(model or Any)
    return adapter.dump_json(data).decode()


@overload
def deserialize_any(json_str: str, model: type[T]) -> T: ...


@overload
def deserialize_any(json_str: str, model: type[Any] | None = None) -> Any: ...


def deserialize_any(json_str: str, model: type[T] | None = None) -> Any:
    """Deserialize a JSON string, validating against model if provided."""
    adapter: TypeAdapterType[Any] = TypeAdapter(model or Any)
    return adapter.validate_json(json_str)


class AsyncRedisCommands(Protocol):
    """The Redis commands this codebase issues, typed as the async client actually returns them.

    redis-py's shared mixin annotates each command Awaitable[T] | T, which doesn't
    type-check awaiting on the async client. Values are str, not bytes, since
    decode_responses=True.
    """

    async def ping(self) -> bool:
        """Liveness probe."""
        ...

    async def get(self, name: str) -> str | None:
        """GET — None when the key is absent."""
        ...

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        """SET — with nx returns None when the key already existed."""
        ...

    async def setex(self, name: str, time: int, value: str) -> bool:
        """SET with a TTL in seconds."""
        ...

    async def getdel(self, name: str) -> str | None:
        """Atomic GET + DEL — None when the key was absent."""
        ...

    async def delete(self, *names: str) -> int:
        """DEL — returns how many of the keys existed."""
        ...

    async def exists(self, *names: str) -> int:
        """EXISTS — count of the named keys present."""
        ...

    async def expire(self, name: str, time: int) -> bool:
        """Set a TTL in seconds on an existing key."""
        ...

    async def ttl(self, name: str) -> int:
        """Seconds left on a key — -1 when it has no TTL, -2 when it is gone."""
        ...

    async def keys(self, pattern: str = "*") -> list[str]:
        """KEYS — full scan; only for small, bounded keyspaces."""
        ...

    async def incr(self, name: str, amount: int = 1) -> int:
        """INCRBY — returns the value after the increment."""
        ...

    async def llen(self, name: str) -> int:
        """LLEN — 0 for a missing key."""
        ...

    async def lpop(self, name: str) -> str | None:
        """LPOP — None when the list is empty or absent."""
        ...

    async def lrange(self, name: str, start: int, end: int) -> list[str]:
        """LRANGE — inclusive on both ends; -1 is the last element."""
        ...

    async def ltrim(self, name: str, start: int, end: int) -> bool:
        """LTRIM — keep only [start, end]; negative indexes count from the tail."""
        ...

    async def rpush(self, name: str, *values: str) -> int:
        """RPUSH — returns the list length after the push."""
        ...

    async def hset(self, name: str, *, mapping: Mapping[str, str]) -> int:
        """HSET from a mapping — returns how many fields were newly added."""
        ...

    async def hgetall(self, name: str) -> dict[str, str]:
        """HGETALL — empty dict for a missing key."""
        ...

    async def publish(self, channel: str, message: str) -> int:
        """PUBLISH — returns the number of subscribers that received it."""
        ...

    async def xadd(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        """XADD — returns the new entry's stream id."""
        ...

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        """XREAD — [(stream, [(entry_id, fields)])] for streams with new entries."""
        ...

    # Lua's return type is whatever the script yields — genuinely dynamic, so the
    # caller narrows it (the one call site coerces to bool).
    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any:
        """EVAL — runs a Lua script; the caller narrows the dynamic result."""
        ...

    def pubsub(self) -> PubSub:
        """Return a pub/sub interface bound to this client."""
        ...

    def lock(
        self,
        name: str,
        *,
        timeout: float | None = None,
        sleep: float = 0.1,
        blocking: bool = True,
        blocking_timeout: float | None = None,
        thread_local: bool = True,
    ) -> Lock:
        """Return a distributed mutex — SET NX lease with a token-checked Lua release."""
        ...

    def pipeline(self, transaction: bool = True) -> Pipeline:
        """Return a command pipeline; transaction=True wraps it in MULTI/EXEC."""
        ...


def _new_client(redis_url: str) -> AsyncRedisCommands:
    """Build the async client, described by what it really returns.

    The cast is the one place the library's sync/async-shared annotations are
    traded for the async-accurate ones in AsyncRedisCommands; see that
    protocol for why they differ. from_url is lazy — this does not connect.
    """
    return cast(AsyncRedisCommands, redis.from_url(redis_url, decode_responses=True))


class RedisCache:
    """Async Redis wrapper with type-safe (de)serialization and graceful degradation.

    The client is created lazily (redis.from_url does not connect on
    construction); call verify_connection at startup to assert reachability.
    When Redis is unavailable, read/write helpers no-op instead of raising.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379", default_ttl: int = 3600) -> None:
        self.redis_url = settings.REDIS_URL or redis_url
        self.default_ttl = default_ttl
        self.redis: AsyncRedisCommands | None = None

        if self.redis_url:
            try:
                # NB: from_url is lazy — it does NOT connect here. Real
                # connectivity is asserted by verify_connection() at startup.
                self.redis = _new_client(self.redis_url)
                log.set(db={"connection_status": "configured", "backend": "redis"})
                log.info(
                    f"{LogTag.STORAGE} Redis client configured (connection verified at startup)."
                )
            except Exception as e:
                log.set(db={"connection_status": "error", "backend": "redis"})
                log.error(
                    f"{LogTag.STORAGE} Failed to create Redis client",
                    error=str(e),
                    error_type=type(e).__name__,
                )
        else:
            log.warning(f"{LogTag.STORAGE} REDIS_URL is not set. Caching will be disabled.")

    async def verify_connection(self) -> None:
        """Assert Redis is reachable, failing fast in production and logging loudly elsewhere.

        from_url connects lazily, so without this check an unavailable Redis silently
        looked "connected".
        """
        if self.redis is None:
            message = "Redis is UNAVAILABLE: REDIS_URL is not configured."
            log.set(db={"connection_status": "unavailable", "backend": "redis"})
            log.error(f"{LogTag.STORAGE} Redis is UNAVAILABLE: REDIS_URL is not configured")
            if settings.ENV == "production":
                raise ConnectionError(message)
            return

        try:
            await self.redis.ping()
            log.set(db={"connection_status": "verified", "backend": "redis"})
            log.info(f"{LogTag.STORAGE} Redis connection verified.")
        except Exception as e:
            message = f"Redis is UNAVAILABLE: ping failed ({type(e).__name__}: {e})"
            log.set(db={"connection_status": "error", "backend": "redis"})
            log.error(
                f"{LogTag.STORAGE} Redis is UNAVAILABLE: ping failed", error_type=type(e).__name__
            )
            if settings.ENV == "production":
                raise ConnectionError(message) from e

    @overload
    async def get(self, key: str, model: type[T]) -> T | None: ...

    @overload
    async def get(self, key: str, model: type[Any] | None = None) -> Any: ...

    async def get(self, key: str, model: type[T] | None = None) -> Any:
        """Retrieve a cached value by key, deserialized against model if provided."""
        if not self.redis:
            log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping get operation.")
            return None

        try:
            value = await self.redis.get(name=key)
            if value:
                # Use TypeAdapter to deserialize any data structure
                return deserialize_any(value, model)
            return None
        except Exception as e:
            log.error(
                "redis_op_failed",
                op="get",
                key=key,
                error_type=type(e).__name__,
                error=str(e),
            )
            return None

    async def set(
        self, key: str, value: object, ttl: int = 3600, model: type[Any] | None = None
    ) -> bool:
        """Store a value with a TTL, serialized against model if provided.

        Returns False (not raised) if Redis was unavailable or the write failed — callers
        that must not act on an unstored value (e.g. single-use tokens) should check this.
        """
        if not self.redis:
            log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping set operation.")
            return False

        try:
            ttl = ttl or self.default_ttl
            # Use TypeAdapter to handle any data structure with Pydantic models
            json_str = serialize_any(value, model)
            await self.redis.setex(key, ttl, json_str)
            return True
        except Exception as e:
            log.error(
                "redis_op_failed",
                op="set",
                key=key,
                ttl=ttl,
                error_type=type(e).__name__,
                error=str(e),
            )
            return False

    async def get_and_delete(self, key: str, model: type[Any] | None = None) -> Any:
        """Atomically read and remove key (GETDEL), so a one-time credential is redeemed exactly once."""
        if not self.redis:
            log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping get_and_delete.")
            return None

        try:
            value = await self.redis.getdel(key)
            if value:
                return deserialize_any(value, model)
            return None
        except Exception as e:
            log.error(
                "redis_op_failed",
                op="get_and_delete",
                key=key,
                error_type=type(e).__name__,
                error=str(e),
            )
            return None

    async def set_if_absent(
        self, key: str, value: object, *, ttl: int, model: type[Any] | None = None
    ) -> bool:
        """SET NX with a TTL: True when this call created the key, False when it already existed.

        The one atomic "first writer wins" the cache offers, for state that may be
        settled from several processes at once. False also when Redis is down or
        the write failed, so a caller never proceeds as the winner on an unstored key.
        """
        if not self.redis:
            log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping set_if_absent.")
            return False

        try:
            created = await self.redis.set(key, serialize_any(value, model), ex=ttl, nx=True)
            return created is not None
        except Exception as e:
            log.error(
                "redis_op_failed",
                op="set_if_absent",
                key=key,
                ttl=ttl,
                error_type=type(e).__name__,
                error=str(e),
            )
            return False

    async def ttl_seconds(self, key: str) -> int | None:
        """Seconds until key expires, or None when it is absent, has no expiry, or Redis is down."""
        if not self.redis:
            log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping ttl operation.")
            return None

        try:
            remaining = await self.redis.ttl(key)
        except Exception as e:
            log.error(
                "redis_op_failed",
                op="ttl",
                key=key,
                error_type=type(e).__name__,
                error=str(e),
            )
            return None
        return remaining if remaining >= 0 else None

    async def delete(self, key: str) -> None:
        """Delete a cached key."""
        if not self.redis:
            log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping delete operation.")
            return

        try:
            await self.redis.delete(key)
            log.info(f"{LogTag.STORAGE} Cache deleted for key", key=key)
        except Exception as e:
            log.error(
                "redis_op_failed",
                op="delete",
                key=key,
                error_type=type(e).__name__,
                error=str(e),
            )

    @property
    def client(self) -> AsyncRedisCommands:
        """Get the Redis client instance."""
        if not self.redis:
            self.redis = _new_client(self.redis_url)
            log.info(f"{LogTag.STORAGE} Re-initialized Redis connection.")

        return self.redis


# Initialize the Redis cache
redis_cache = RedisCache()


# Wrappers for RedisCache instance methods
@overload
async def get_cache(key: str, model: type[T]) -> T | None: ...


@overload
async def get_cache(key: str, model: type[Any] | None = None) -> Any: ...


async def get_cache(key: str, model: type[T] | None = None) -> Any:
    """Retrieve a cached value, or None if not found."""
    return await redis_cache.get(key, model)


async def set_cache(
    key: str, value: object, ttl: int = ONE_YEAR_TTL, model: type[Any] | None = None
) -> bool:
    """Store a value with a TTL, returning False if Redis was unavailable/failed."""
    return await redis_cache.set(key, value, ttl, model)


async def delete_cache(key: str) -> None:
    """Delete a cached key."""
    # TODO: Optimize this
    if key.endswith("*"):
        await delete_cache_by_pattern(key)
        return

    await redis_cache.delete(key)


@overload
async def get_and_delete_cache(key: str, model: type[T]) -> T | None: ...


@overload
async def get_and_delete_cache(key: str, model: type[Any] | None = None) -> Any: ...


async def get_and_delete_cache(key: str, model: type[T] | None = None) -> Any:
    """Atomically get and delete a value (GETDEL) so a replayed one-time token can't also read it."""
    return await redis_cache.get_and_delete(key, model)


async def delete_cache_by_pattern(pattern: str) -> None:
    """Delete cache keys matching a glob pattern, using KEYS then deleting each one.

    KEYS can be slow on large Redis instances — use sparingly in production.
    """
    if not redis_cache.redis:
        log.warning(f"{LogTag.STORAGE} Redis is not initialized. Skipping delete operation.")
        return

    try:
        keys = await redis_cache.redis.keys(pattern)
        if not keys:
            log.info(f"{LogTag.STORAGE} No keys found for pattern", pattern=pattern)
            return
        for key in keys:
            await redis_cache.delete(key)
            log.info(f"{LogTag.STORAGE} Cache deleted for key", key=key)
    except Exception as e:
        log.error(
            f"{LogTag.STORAGE} Error deleting Redis keys by pattern",
            pattern=pattern,
            error=str(e),
            error_type=type(e).__name__,
        )


# Caching decorators have been moved to app.decorators.caching
# Import them from there: from app.decorators.caching import Cacheable, CacheInvalidator
