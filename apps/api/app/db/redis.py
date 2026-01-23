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

import json
from datetime import datetime
from typing import Any, Optional

import redis.asyncio as redis
from app.config.loggers import redis_logger as logger
from app.config.settings import settings
from app.constants.cache import (
    DEFAULT_CACHE_TTL,
    ONE_YEAR_TTL,
)
from pydantic import TypeAdapter
from pydantic.type_adapter import TypeAdapter as TypeAdapterType

# Re-export for backwards compatibility
CACHE_TTL = DEFAULT_CACHE_TTL


def serialize_any(data: Any, model: Optional[type] = None) -> str:
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


def deserialize_any(json_str: str, model: Optional[type] = None) -> Any:
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


class RedisCache:
    def __init__(self, redis_url="redis://localhost:6379", default_ttl=3600):
        self.redis_url = settings.REDIS_URL or redis_url
        self.default_ttl = default_ttl
        self.redis = None

        if self.redis_url:
            try:
                self.redis = redis.from_url(self.redis_url, decode_responses=True)
                logger.info("Redis connection initialized.")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
        else:
            logger.warning("REDIS_URL is not set. Caching will be disabled.")

    async def get(self, key: str, model: Optional[type] = None):
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
            logger.warning("Redis is not initialized. Skipping get operation.")
            return None

        try:
            value = await self.redis.get(name=key)
            if value:
                # Use TypeAdapter to deserialize any data structure
                return deserialize_any(value, model)
            return None
        except Exception as e:
            logger.error(f"Error accessing Redis for key {key}: {e}")
            return None

    async def set(
        self, key: str, value: Any, ttl: int = 3600, model: Optional[type] = None
    ):
        """
        Store value in cache with TTL and optional type validation.

        Args:
            key: Cache key to store under
            value: Data to cache (any serializable Python object)
            ttl: Time-to-live in seconds (default: 3600/1 hour)
            model: Optional Pydantic model for type-safe serialization

        Examples:
            # Generic caching
            await cache.set("user:123", {"name": "John"}, ttl=1800)

            # Type-safe caching
            await cache.set("user:123", user_obj, model=User, ttl=3600)
        """
        if not self.redis:
            logger.warning("Redis is not initialized. Skipping set operation.")
            return

        try:
            ttl = ttl or self.default_ttl
            # Use TypeAdapter to handle any data structure with Pydantic models
            json_str = serialize_any(value, model)
            await self.redis.setex(key, ttl, json_str)
        except Exception as e:
            logger.error(f"Error setting Redis key {key}: {e}")

    async def delete(self, key: str):
        """
        Delete a cached key.
        """
        if not self.redis:
            logger.warning("Redis is not initialized. Skipping delete operation.")
            return

        try:
            await self.redis.delete(key)
            logger.info(f"Cache deleted for key: {key}")
        except Exception as e:
            logger.error(f"Error deleting Redis key {key}: {e}")

    @property
    def client(self):
        """
        Get the Redis client instance.
        """
        if not self.redis:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            logger.info("Re-initialized Redis connection.")

        return self.redis


# Initialize the Redis cache
redis_cache = RedisCache()


# Wrappers for RedisCache instance methods
async def get_cache(key: str, model: Optional[type] = None):
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
    key: str, value: Any, ttl: int = ONE_YEAR_TTL, model: Optional[type] = None
):
    """
    Convenience wrapper for storing cached values.

    Args:
        key: Cache key to store under
        value: Data to cache
        ttl: Time-to-live in seconds (default: 1 year)
        model: Optional Pydantic model for type validation

    Example:
        await set_cache("user:123", user, ttl=3600, model=User)
    """
    await redis_cache.set(key, value, ttl, model)


async def delete_cache(key: str):
    """
    Delete a cached key.
    """
    # TODO: Optimize this
    if key.endswith("*"):
        await delete_cache_by_pattern(key)
        return

    await redis_cache.delete(key)


async def get_and_delete_cache(key: str) -> Any | None:
    """
    Atomically get and delete a cached value using Redis GETDEL.

    Used for one-time use tokens like OAuth state to prevent replay attacks.
    This is atomic - if two requests come in, only one will get the value.

    Args:
        key: Cache key to get and delete

    Returns:
        Cached value (deserialized from JSON) or None if not found
    """
    if not redis_cache.redis:
        logger.warning("Redis is not initialized. Skipping get_and_delete operation.")
        return None

    try:
        value = await redis_cache.redis.getdel(key)
        if value:
            return deserialize_any(value)
        return None
    except Exception as e:
        logger.error(f"Error in get_and_delete for key {key}: {e}")
        return None


async def delete_cache_by_pattern(pattern: str):
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
        logger.warning("Redis is not initialized. Skipping delete operation.")
        return

    try:
        keys = await redis_cache.redis.keys(pattern)
        if not keys:
            logger.info(f"No keys found for pattern: {pattern}")
            return
        for key in keys:
            await redis_cache.delete(key)
            logger.info(f"Cache deleted for key: {key}")
    except Exception as e:
        logger.error(f"Error deleting Redis keys by pattern {pattern}: {e}")


# Caching decorators have been moved to app.decorators.caching
# Import them from there: from app.decorators.caching import Cacheable, CacheInvalidator
