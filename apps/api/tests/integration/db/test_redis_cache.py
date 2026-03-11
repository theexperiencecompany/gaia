"""Integration tests for Redis cache operations.

Tests the RedisCache class and module-level wrappers with a mocked
Redis connection to verify serialization, TTL handling, and CRUD ops.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.db.redis import (
    RedisCache,
    delete_cache,
    deserialize_any,
    get_and_delete_cache,
    get_cache,
    serialize_any,
    set_cache,
)


class SampleModel(BaseModel):
    """Pydantic model for serialization tests."""

    name: str
    age: int
    active: bool = True


@pytest.mark.integration
class TestSerializationHelpers:
    """Test serialize_any / deserialize_any roundtrips."""

    def test_serialize_dict(self):
        """Serializing a dict should produce a valid JSON string."""
        data = {"key": "value", "number": 42}
        json_str = serialize_any(data)
        assert isinstance(json_str, str)
        assert '"key"' in json_str

    def test_roundtrip_dict(self):
        """Serializing then deserializing a dict should return the original."""
        data = {"name": "Alice", "scores": [1, 2, 3]}
        json_str = serialize_any(data)
        result = deserialize_any(json_str)
        assert result == data

    def test_roundtrip_pydantic_model(self):
        """Serializing then deserializing with a model should return a model instance."""
        model = SampleModel(name="Bob", age=30, active=False)
        json_str = serialize_any(model, model=SampleModel)
        result = deserialize_any(json_str, model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "Bob"
        assert result.age == 30
        assert result.active is False

    def test_roundtrip_list(self):
        """Lists should serialize and deserialize correctly."""
        data = [1, "two", 3.0, None]
        json_str = serialize_any(data)
        result = deserialize_any(json_str)
        assert result == data

    def test_roundtrip_string(self):
        """Plain strings should serialize and deserialize correctly."""
        data = "hello world"
        json_str = serialize_any(data)
        result = deserialize_any(json_str)
        assert result == data

    def test_roundtrip_nested_structure(self):
        """Nested dicts and lists should roundtrip correctly."""
        data = {
            "users": [
                {"name": "A", "tags": ["x", "y"]},
                {"name": "B", "tags": []},
            ],
            "meta": {"count": 2},
        }
        json_str = serialize_any(data)
        result = deserialize_any(json_str)
        assert result == data


@pytest.mark.integration
class TestRedisCacheOperations:
    """Test RedisCache get/set/delete with mocked Redis."""

    async def test_set_and_get_cache(self):
        """set() then get() should return the cached value.

        Uses a capture-and-replay mock so that what set_cache serializes
        and writes is exactly what get_cache reads and deserializes.
        A bug in serialize_any or deserialize_any will cause the final
        assertion to fail, making this a real serialization roundtrip.
        """
        stored: dict[str, str] = {}

        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 3600
        cache.redis = AsyncMock()
        cache.redis.setex = AsyncMock(
            side_effect=lambda k, ttl, v: stored.update({k: v})
        )
        cache.redis.get = AsyncMock(side_effect=lambda name: stored.get(name))

        data = {"key": "value", "count": 5}

        await cache.set("test:key", data, ttl=300)

        cache.redis.setex.assert_awaited_once()
        call_args = cache.redis.setex.call_args
        assert call_args[0][0] == "test:key"
        assert call_args[0][1] == 300

        result = await cache.get("test:key")
        assert result == data

    async def test_get_returns_none_for_missing_key(self):
        """get() should return None when key does not exist."""
        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 3600
        cache.redis = AsyncMock()
        cache.redis.get = AsyncMock(return_value=None)

        result = await cache.get("nonexistent:key")
        assert result is None

    async def test_delete_cache(self):
        """delete() should call redis.delete with the key."""
        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 3600
        cache.redis = AsyncMock()
        cache.redis.delete = AsyncMock()

        await cache.delete("test:delete")
        cache.redis.delete.assert_awaited_once_with("test:delete")

    async def test_set_with_pydantic_model(self):
        """set() with a model should serialize using the model's TypeAdapter."""
        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 3600
        cache.redis = AsyncMock()
        cache.redis.setex = AsyncMock()

        model = SampleModel(name="Charlie", age=25)
        await cache.set("model:key", model, ttl=600, model=SampleModel)

        cache.redis.setex.assert_awaited_once()
        stored_json = cache.redis.setex.call_args[0][2]
        # Deserialize and verify
        restored = deserialize_any(stored_json, model=SampleModel)
        assert restored.name == "Charlie"
        assert restored.age == 25

    async def test_get_with_pydantic_model(self):
        """get() with a model should return a typed instance."""
        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 3600
        cache.redis = AsyncMock()

        model = SampleModel(name="Dana", age=40)
        json_str = serialize_any(model, model=SampleModel)
        cache.redis.get = AsyncMock(return_value=json_str)

        result = await cache.get("model:key", model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "Dana"

    async def test_ttl_defaults_when_zero(self):
        """When ttl=0, set() should use the default_ttl."""
        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 7200
        cache.redis = AsyncMock()
        cache.redis.setex = AsyncMock()

        await cache.set("ttl:test", "data", ttl=0)
        call_args = cache.redis.setex.call_args
        # ttl=0 is falsy, so `ttl or self.default_ttl` -> 7200
        assert call_args[0][1] == 7200

    async def test_operations_noop_when_redis_unavailable(self):
        """Operations should not raise when redis is None."""
        cache = RedisCache.__new__(RedisCache)
        cache.default_ttl = 3600
        cache.redis = None

        # These should all return None/silently without exceptions
        result = await cache.get("key")
        assert result is None
        await cache.set("key", "value")
        await cache.delete("key")


@pytest.mark.integration
class TestModuleLevelWrappers:
    """Test the module-level set_cache/get_cache/delete_cache wrappers."""

    @patch("app.db.redis.redis_cache")
    async def test_get_cache_wrapper(self, mock_cache):
        """get_cache() should delegate to redis_cache.get()."""
        mock_cache.get = AsyncMock(return_value={"cached": True})
        result = await get_cache("wrapper:key")
        mock_cache.get.assert_awaited_once_with("wrapper:key", None)
        assert result == {"cached": True}

    @patch("app.db.redis.redis_cache")
    async def test_set_cache_wrapper(self, mock_cache):
        """set_cache() should delegate to redis_cache.set()."""
        mock_cache.set = AsyncMock()
        await set_cache("wrapper:key", "data", ttl=100)
        mock_cache.set.assert_awaited_once()

    @patch("app.db.redis.redis_cache")
    async def test_delete_cache_wrapper(self, mock_cache):
        """delete_cache() should delegate to redis_cache.delete()."""
        mock_cache.delete = AsyncMock()
        await delete_cache("wrapper:key")
        mock_cache.delete.assert_awaited_once_with("wrapper:key")

    @patch("app.db.redis.redis_cache")
    async def test_get_and_delete_cache(self, mock_cache):
        """get_and_delete_cache should use Redis GETDEL."""
        mock_cache.redis = AsyncMock()
        serialized = serialize_any({"token": "abc"})
        mock_cache.redis.getdel = AsyncMock(return_value=serialized)

        result = await get_and_delete_cache("one-time:key")
        assert result == {"token": "abc"}
        mock_cache.redis.getdel.assert_awaited_once_with("one-time:key")
