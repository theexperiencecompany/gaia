"""
Redis caching infrastructure with type-safe Pydantic model support.

Features:
- Type-safe model serialization/deserialization
- Generic JSON caching for any Python objects
- TTL support and pattern-based cache invalidation
- Graceful fallback when Redis is unavailable

Basic Usage:
    await set_cache("key", data)
    data = await get_cache("key")

Type-safe Usage:
    await set_cache("user:123", user_obj, model=User)
    user = await get_cache("user:123", model=User)  # Returns User instance

Pattern deletion:
    await delete_cache("user:*")  # Delete all user keys
"""

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, cast, overload

from pydantic import TypeAdapter
from pydantic.type_adapter import TypeAdapter as TypeAdapterType
import redis.asyncio as redis
from redis.asyncio.client import Pipeline, PubSub

from app.config.settings import settings
from app.constants.cache import (
    DEFAULT_CACHE_TTL,
    ONE_YEAR_TTL,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# Re-export for backwards compatibility
CACHE_TTL = DEFAULT_CACHE_TTL

# The cached value's type, carried from the ``model=`` argument through to the
# return type: ``get_cache(key, model=User)`` is ``User | None``, not ``Any``.
# Without it a caller's annotation on the result is unchecked — mypy accepts any
# annotation on an ``Any`` — so a mismatched model went unnoticed.
T = TypeVar("T")

# The four remaining ``Any`` returns are the *no-model* overload stubs
# (deserialize_any / RedisCache.get / get_cache / get_and_delete_cache). Measured,
# don't re-litigate: narrowing them to ``object`` produced **31 new mypy errors
# across 14 files** — stream_manager, bot_auth_middleware, tiered_rate_limiter,
# payment_service, mcp_token_store and memory/consolidation all subscript,
# ``.get()`` or ``int()`` the untyped cache read directly. Callers that want a
# real type already pass ``model=`` and get it; the model-less overload is the
# genuinely dynamic one. The three input params (serialize_any's ``data``,
# ``set``/``set_cache``'s ``value``) and the overload *implementation* returns do
# narrow to ``object`` at zero cost — a follow-up, not an ANN401 unblock.


def serialize_any(data: object, model: type[Any] | None = None) -> str:
    """
    Serialize Python objects to JSON string using Pydantic TypeAdapter.

    Supports type-safe serialization when model is provided, ensuring data
    conforms to the expected structure before serialization.

    Args:
        data: Any Python object to serialize (Pydantic models, dicts, lists, etc.)
        model: Optional Pydantic model class for type-specific serialization

    Returns:
        JSON string representation of the data

    Examples:
        # Generic serialization
        json_str = serialize_any({"name": "John", "age": 30})

        # Type-safe serialization
        user = User(name="John", email="john@example.com")
        json_str = serialize_any(user, model=User)
    """
    adapter: TypeAdapterType[Any] = TypeAdapter(model or Any)
    return adapter.dump_json(data).decode()


@overload
def deserialize_any(json_str: str, model: type[T]) -> T: ...


@overload
def deserialize_any(json_str: str, model: type[Any] | None = None) -> Any: ...


def deserialize_any(json_str: str, model: type[T] | None = None) -> Any:
    """
    Deserialize JSON string back to Python objects with optional type validation.

    When model is provided, validates the deserialized data against the model
    schema and returns a properly typed instance. Without model, returns
    generic Python objects (dict, list, etc.).

    Args:
        json_str: JSON string to deserialize
        model: Optional Pydantic model class for type validation

    Returns:
        Deserialized and optionally validated Python object

    Raises:
        ValidationError: If data doesn't match the provided model schema
        ValueError: If JSON string is invalid

    Examples:
        # Generic deserialization
        data = deserialize_any('{"name": "John", "age": 30}')

        # Type-safe deserialization
        user = deserialize_any(json_str, model=User)  # Returns User instance
    """
    adapter: TypeAdapterType[Any] = TypeAdapter(model or Any)
    return adapter.validate_json(json_str)


class AsyncRedisCommands(Protocol):
    """The Redis commands this codebase issues, typed as the async client returns them.

    redis-py declares each command once, on a mixin shared by the sync and async
    clients, annotated ``Awaitable[T] | T``. That union is honest for the pair but
    wrong for ``redis.asyncio.Redis``, where every command returns an awaitable —
    so ``await client.llen(key)`` does not type-check against the library's own
    annotations, and the ones declared ``ResponseT`` (an alias containing bare
    ``Any``) type-check but return ``Any`` and check nothing downstream.

    Restating the commands we actually use fixes both: awaits resolve, and results
    arrive as real types (``hgetall`` is a ``dict[str, str]``, not ``dict[Any, Any]``).
    Values are ``str`` rather than ``bytes`` because the client is constructed with
    ``decode_responses=True``.

    Adding a command here is the cost of using a new one — mypy will name it.
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
        """SET — with ``nx`` returns None when the key already existed."""
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
        """A pub/sub interface bound to this client."""
        ...

    def pipeline(self, transaction: bool = True) -> Pipeline:
        """A command pipeline; ``transaction=True`` wraps it in MULTI/EXEC."""
        ...


def _new_client(redis_url: str) -> AsyncRedisCommands:
    """Build the async client, described by what it really returns.

    The cast is the one place the library's sync/async-shared annotations are
    traded for the async-accurate ones in ``AsyncRedisCommands``; see that
    protocol for why they differ. ``from_url`` is lazy — this does not connect.
    """
    return cast(AsyncRedisCommands, redis.from_url(redis_url, decode_responses=True))


class RedisCache:
    """Async Redis wrapper with type-safe (de)serialization and graceful degradation.

    The client is created lazily (``redis.from_url`` does not connect on
    construction); call ``verify_connection`` at startup to assert reachability.
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
        """Assert Redis is actually reachable, and scream if it is not.

        Redis backs caching, SSE streaming, rate limiting and stream
        cancellation, so an unavailable Redis is a real outage — surface it
        loudly instead of silently degrading (the prior behavior optimistically
        reported "connected" because ``from_url`` connects lazily). Fails fast
        in production; logs loudly elsewhere so local dev still runs.
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
        """
        Retrieve cached value by key with optional type validation.

        Args:
            key: Cache key to retrieve
            model: Optional Pydantic model for type-safe deserialization

        Returns:
            Cached value (typed if model provided, generic dict/list otherwise)
            None if key doesn't exist or Redis unavailable

        Examples:
            # Generic retrieval
            data = await cache.get("user:123")

            # Type-safe retrieval
            user = await cache.get("user:123", model=User)
        """
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
        """
        Store value in cache with TTL and optional type validation.

        Args:
            key: Cache key to store under
            value: Data to cache (any serializable Python object)
            ttl: Time-to-live in seconds (default: 3600/1 hour)
            model: Optional Pydantic model for type-safe serialization

        Returns:
            True if the value was written, False if Redis was unavailable or the
            write failed. Callers that must not act on an unstored value (e.g.
            single-use tokens) should check this.

        Examples:
            # Generic caching
            await cache.set("user:123", {"name": "John"}, ttl=1800)

            # Type-safe caching
            await cache.set("user:123", user_obj, model=User, ttl=3600)
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

    async def delete(self, key: str) -> None:
        """
        Delete a cached key.
        """
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
        """
        Get the Redis client instance.
        """
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
    """
    Convenience wrapper for retrieving cached values.

    Args:
        key: Cache key to retrieve
        model: Optional Pydantic model for type validation

    Returns:
        Cached value or None if not found

    Example:
        user = await get_cache("user:123", model=User)
    """
    return await redis_cache.get(key, model)


async def set_cache(
    key: str, value: object, ttl: int = ONE_YEAR_TTL, model: type[Any] | None = None
) -> bool:
    """
    Convenience wrapper for storing cached values.

    Args:
        key: Cache key to store under
        value: Data to cache
        ttl: Time-to-live in seconds (default: 1 year)
        model: Optional Pydantic model for type validation

    Returns:
        True if the value was written, False if Redis was unavailable/failed.

    Example:
        await set_cache("user:123", user, ttl=3600, model=User)
    """
    return await redis_cache.set(key, value, ttl, model)


async def delete_cache(key: str) -> None:
    """
    Delete a cached key.
    """
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
    """
    Atomically get and delete a cached value using Redis GETDEL.

    Used for one-time use tokens like OAuth state to prevent replay attacks.
    This is atomic - if two requests come in, only one will get the value.

    Args:
        key: Cache key to get and delete
        model: Optional type to validate the stored value into. Passing it makes
            the return type that model rather than ``Any``; omitting it keeps the
            untyped behaviour, since the one-time payloads here have no single
            shape.

    Returns:
        Cached value (deserialized from JSON) or None if not found
    """
    if not redis_cache.redis:
        log.warning(
            f"{LogTag.STORAGE} Redis is not initialized. Skipping get_and_delete operation."
        )
        return None

    try:
        value = await redis_cache.redis.getdel(key)
        if value:
            return deserialize_any(value, model)
        return None
    except Exception as e:
        log.error(
            f"{LogTag.STORAGE} Error in get_and_delete for key",
            key=key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def delete_cache_by_pattern(pattern: str) -> None:
    """
    Delete multiple cache keys matching a pattern.

    Uses Redis KEYS command to find matching keys, then deletes each one.
    Useful for bulk cache invalidation (e.g., clearing all user data).

    Args:
        pattern: Redis glob pattern (e.g., "user:*", "session:abc*")

    Warning:
        KEYS command can be slow on large Redis instances. Use sparingly
        in production or during low-traffic periods.

    Examples:
        await delete_cache_by_pattern("user:*")  # Delete all user cache
        await delete_cache_by_pattern("temp:*")  # Delete temporary data
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
