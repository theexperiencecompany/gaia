"""Tests for Redis caching infrastructure.

Covers:
- serialize_any / deserialize_any: Pydantic TypeAdapter serialization
- RedisCache: init, get, set, delete, client property
- Module-level wrappers: get_cache, set_cache, delete_cache
- get_and_delete_cache: atomic GETDEL
- delete_cache_by_pattern: pattern-based bulk deletion
- Edge cases: Redis unavailable, exceptions, TTL handling
"""

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from app.db.redis import (
    RedisCache,
    delete_cache,
    delete_cache_by_pattern,
    deserialize_any,
    get_and_delete_cache,
    get_cache,
    redis_cache,
    serialize_any,
    set_cache,
)


# ---------------------------------------------------------------------------
# Test Pydantic models for type-safe serialization
# ---------------------------------------------------------------------------


class SampleUser(BaseModel):
    name: str
    email: str
    age: int


class SampleNested(BaseModel):
    items: List[str]
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# serialize_any
# ---------------------------------------------------------------------------


class TestSerializeAny:
    """Tests for serialize_any() function."""

    def test_serialize_dict(self) -> None:
        """Should serialize a plain dict to JSON string."""
        data = {"name": "John", "age": 30}
        result = serialize_any(data)

        assert isinstance(result, str)
        assert "John" in result
        assert "30" in result

    def test_serialize_list(self) -> None:
        """Should serialize a list to JSON string."""
        data = [1, 2, 3, "hello"]
        result = serialize_any(data)

        assert isinstance(result, str)
        assert "hello" in result

    def test_serialize_with_model(self) -> None:
        """Should serialize a Pydantic model with type checking."""
        user = SampleUser(name="Jane", email="jane@test.com", age=25)
        result = serialize_any(user, model=SampleUser)

        assert isinstance(result, str)
        assert "Jane" in result
        assert "jane@test.com" in result

    def test_serialize_string(self) -> None:
        """Should serialize a plain string."""
        result = serialize_any("hello world")
        assert isinstance(result, str)

    def test_serialize_none(self) -> None:
        """Should serialize None to 'null'."""
        result = serialize_any(None)
        assert result == "null"

    def test_serialize_nested_model(self) -> None:
        """Should handle nested Pydantic models."""
        nested = SampleNested(items=["a", "b"], metadata={"key": "val"})
        result = serialize_any(nested, model=SampleNested)

        assert "a" in result
        assert "key" in result

    def test_serialize_integer(self) -> None:
        """Should serialize an integer value."""
        result = serialize_any(42)
        assert result == "42"

    def test_serialize_boolean(self) -> None:
        """Should serialize boolean values."""
        assert serialize_any(True) == "true"
        assert serialize_any(False) == "false"


# ---------------------------------------------------------------------------
# deserialize_any
# ---------------------------------------------------------------------------


class TestDeserializeAny:
    """Tests for deserialize_any() function."""

    def test_deserialize_dict(self) -> None:
        """Should deserialize JSON string to dict."""
        json_str = '{"name": "John", "age": 30}'
        result = deserialize_any(json_str)

        assert isinstance(result, dict)
        assert result["name"] == "John"
        assert result["age"] == 30

    def test_deserialize_list(self) -> None:
        """Should deserialize JSON array to list."""
        json_str = "[1, 2, 3]"
        result = deserialize_any(json_str)

        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_deserialize_with_model(self) -> None:
        """Should deserialize and validate against a Pydantic model."""
        json_str = '{"name": "Jane", "email": "jane@test.com", "age": 25}'
        result = deserialize_any(json_str, model=SampleUser)

        assert isinstance(result, SampleUser)
        assert result.name == "Jane"
        assert result.email == "jane@test.com"
        assert result.age == 25

    def test_deserialize_with_model_validation_error(self) -> None:
        """Should raise ValidationError if data doesn't match model schema."""
        json_str = '{"name": "Jane"}'  # Missing required fields

        with pytest.raises(ValidationError):
            deserialize_any(json_str, model=SampleUser)

    def test_deserialize_invalid_json(self) -> None:
        """Should raise an error for invalid JSON."""
        with pytest.raises(Exception):
            deserialize_any("not valid json{")

    def test_deserialize_null(self) -> None:
        """Should deserialize 'null' to None."""
        result = deserialize_any("null")
        assert result is None

    def test_roundtrip_dict(self) -> None:
        """Serialize then deserialize should return equivalent data."""
        original = {"key": "value", "num": 42, "nested": {"a": 1}}
        json_str = serialize_any(original)
        result = deserialize_any(json_str)

        assert result == original

    def test_roundtrip_model(self) -> None:
        """Roundtrip with a Pydantic model should preserve all fields."""
        original = SampleUser(name="Test", email="test@test.com", age=30)
        json_str = serialize_any(original, model=SampleUser)
        result = deserialize_any(json_str, model=SampleUser)

        assert result == original


# ---------------------------------------------------------------------------
# RedisCache.__init__
# ---------------------------------------------------------------------------


class TestRedisCacheInit:
    """Tests for RedisCache constructor."""

    @patch("app.db.redis.settings")
    @patch("app.db.redis.redis.from_url")
    @patch("app.db.redis.log")
    def test_init_with_valid_url(
        self, mock_log: MagicMock, mock_from_url: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Should initialize Redis client when URL is provided."""
        mock_settings.REDIS_URL = "redis://localhost:6379"
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client

        cache = RedisCache()

        assert cache.redis is mock_client
        mock_from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )

    @patch("app.db.redis.settings")
    @patch("app.db.redis.log")
    def test_init_with_no_url(
        self, mock_log: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Should warn and disable caching when REDIS_URL is not set."""
        mock_settings.REDIS_URL = None

        cache = RedisCache(redis_url="")

        assert cache.redis is None
        mock_log.warning.assert_called()

    @patch("app.db.redis.settings")
    @patch("app.db.redis.redis.from_url", side_effect=Exception("conn refused"))
    @patch("app.db.redis.log")
    def test_init_connection_error(
        self, mock_log: MagicMock, mock_from_url: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Connection errors should be caught, redis set to None is not done but error logged."""
        mock_settings.REDIS_URL = "redis://bad-host:6379"

        RedisCache()

        mock_log.error.assert_called()

    @patch("app.db.redis.settings")
    @patch("app.db.redis.redis.from_url")
    @patch("app.db.redis.log")
    def test_default_ttl(
        self, mock_log: MagicMock, mock_from_url: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Default TTL should be 3600 seconds."""
        mock_settings.REDIS_URL = "redis://localhost:6379"

        cache = RedisCache()

        assert cache.default_ttl == 3600

    @patch("app.db.redis.settings")
    @patch("app.db.redis.redis.from_url")
    @patch("app.db.redis.log")
    def test_custom_ttl(
        self, mock_log: MagicMock, mock_from_url: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Should accept a custom default TTL."""
        mock_settings.REDIS_URL = "redis://localhost:6379"

        cache = RedisCache(default_ttl=7200)

        assert cache.default_ttl == 7200

    @patch("app.db.redis.settings")
    @patch("app.db.redis.redis.from_url")
    @patch("app.db.redis.log")
    def test_settings_url_overrides_param(
        self, mock_log: MagicMock, mock_from_url: MagicMock, mock_settings: MagicMock
    ) -> None:
        """settings.REDIS_URL should take precedence over the constructor param."""
        mock_settings.REDIS_URL = "redis://from-settings:6379"

        cache = RedisCache(redis_url="redis://from-param:6379")

        assert cache.redis_url == "redis://from-settings:6379"


# ---------------------------------------------------------------------------
# RedisCache.get
# ---------------------------------------------------------------------------


class TestRedisCacheGet:
    """Tests for RedisCache.get() method."""

    async def test_get_returns_deserialized_value(self) -> None:
        """Should return deserialized value when key exists."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.redis.get.return_value = '{"name": "John"}'

        result = await cache.get("user:123")

        cache.redis.get.assert_awaited_once_with(name="user:123")
        assert result == {"name": "John"}

    async def test_get_returns_none_for_missing_key(self) -> None:
        """Should return None when key doesn't exist."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.redis.get.return_value = None

        result = await cache.get("nonexistent")

        assert result is None

    async def test_get_with_model(self) -> None:
        """Should deserialize with model validation when model is provided."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.redis.get.return_value = '{"name":"Jane","email":"j@t.com","age":25}'

        result = await cache.get("user:123", model=SampleUser)

        assert isinstance(result, SampleUser)
        assert result.name == "Jane"

    async def test_get_returns_none_when_redis_not_initialized(self) -> None:
        """Should return None and warn when redis is None."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = None

        with patch("app.db.redis.log") as mock_log:
            result = await cache.get("key")

        assert result is None
        mock_log.warning.assert_called()

    async def test_get_returns_none_on_exception(self) -> None:
        """Should catch exceptions and return None."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.redis.get.side_effect = Exception("connection lost")

        with patch("app.db.redis.log") as mock_log:
            result = await cache.get("key")

        assert result is None
        mock_log.error.assert_called()

    async def test_get_empty_string_value(self) -> None:
        """Empty string from Redis is falsy, should return None."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.redis.get.return_value = ""

        result = await cache.get("key")

        assert result is None


# ---------------------------------------------------------------------------
# RedisCache.set
# ---------------------------------------------------------------------------


class TestRedisCacheSet:
    """Tests for RedisCache.set() method."""

    async def test_set_stores_serialized_value(self) -> None:
        """Should serialize value and store with TTL."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.default_ttl = 3600

        await cache.set("user:123", {"name": "John"}, ttl=1800)

        cache.redis.setex.assert_awaited_once()
        call_args = cache.redis.setex.call_args
        assert call_args[0][0] == "user:123"
        assert call_args[0][1] == 1800
        # Third arg should be JSON string
        assert "John" in call_args[0][2]

    async def test_set_with_model(self) -> None:
        """Should serialize using model TypeAdapter when model is provided."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.default_ttl = 3600

        user = SampleUser(name="Jane", email="j@test.com", age=25)
        await cache.set("user:456", user, model=SampleUser)

        cache.redis.setex.assert_awaited_once()
        stored_json = cache.redis.setex.call_args[0][2]
        assert "Jane" in stored_json

    async def test_set_uses_default_ttl_when_zero(self) -> None:
        """When ttl is 0 (falsy), should use default_ttl."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.default_ttl = 3600

        await cache.set("key", "value", ttl=0)

        call_args = cache.redis.setex.call_args
        assert call_args[0][1] == 3600

    async def test_set_skips_when_redis_not_initialized(self) -> None:
        """Should warn and return when redis is None."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = None

        with patch("app.db.redis.log") as mock_log:
            await cache.set("key", "value")

        mock_log.warning.assert_called()

    async def test_set_catches_exception(self) -> None:
        """Should catch and log exceptions during set."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.default_ttl = 3600
        cache.redis.setex.side_effect = Exception("write failed")

        with patch("app.db.redis.log") as mock_log:
            await cache.set("key", "value")

        mock_log.error.assert_called()


# ---------------------------------------------------------------------------
# RedisCache.delete
# ---------------------------------------------------------------------------


class TestRedisCacheDelete:
    """Tests for RedisCache.delete() method."""

    async def test_delete_removes_key(self) -> None:
        """Should call redis.delete with the key."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()

        with patch("app.db.redis.log"):
            await cache.delete("user:123")

        cache.redis.delete.assert_awaited_once_with("user:123")

    async def test_delete_skips_when_redis_not_initialized(self) -> None:
        """Should warn and return when redis is None."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = None

        with patch("app.db.redis.log") as mock_log:
            await cache.delete("key")

        mock_log.warning.assert_called()

    async def test_delete_catches_exception(self) -> None:
        """Should catch and log exceptions during delete."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = AsyncMock()
        cache.redis.delete.side_effect = Exception("delete failed")

        with patch("app.db.redis.log") as mock_log:
            await cache.delete("key")

        mock_log.error.assert_called()


# ---------------------------------------------------------------------------
# RedisCache.client property
# ---------------------------------------------------------------------------


class TestRedisCacheClientProperty:
    """Tests for RedisCache.client property."""

    @patch("app.db.redis.redis.from_url")
    @patch("app.db.redis.log")
    def test_client_returns_existing_redis(
        self, mock_log: MagicMock, mock_from_url: MagicMock
    ) -> None:
        """Should return existing redis client when already initialized."""
        cache = RedisCache.__new__(RedisCache)
        mock_client = MagicMock()
        cache.redis = mock_client

        result = cache.client

        assert result is mock_client
        mock_from_url.assert_not_called()

    @patch("app.db.redis.redis.from_url")
    @patch("app.db.redis.log")
    def test_client_reinitializes_when_none(
        self, mock_log: MagicMock, mock_from_url: MagicMock
    ) -> None:
        """Should re-initialize redis connection when self.redis is None."""
        cache = RedisCache.__new__(RedisCache)
        cache.redis = None
        cache.redis_url = "redis://localhost:6379"

        new_client = MagicMock()
        mock_from_url.return_value = new_client

        result = cache.client

        mock_from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )
        assert result is new_client


# ---------------------------------------------------------------------------
# Module-level wrappers: get_cache, set_cache, delete_cache
# ---------------------------------------------------------------------------


class TestModuleLevelWrappers:
    """Tests for convenience wrapper functions."""

    async def test_get_cache_delegates_to_redis_cache(self) -> None:
        """get_cache should call redis_cache.get with key and model."""
        with patch.object(redis_cache, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"data": 1}

            result = await get_cache("my:key", model=SampleUser)

            mock_get.assert_awaited_once_with("my:key", SampleUser)
            assert result == {"data": 1}

    async def test_set_cache_delegates_to_redis_cache(self) -> None:
        """set_cache should call redis_cache.set with key, value, ttl, model."""
        with patch.object(redis_cache, "set", new_callable=AsyncMock) as mock_set:
            await set_cache("my:key", {"data": 1}, ttl=600, model=SampleUser)

            mock_set.assert_awaited_once_with("my:key", {"data": 1}, 600, SampleUser)

    async def test_set_cache_default_ttl_is_one_year(self) -> None:
        """Default TTL for set_cache should be ONE_YEAR_TTL (31536000)."""
        with patch.object(redis_cache, "set", new_callable=AsyncMock) as mock_set:
            await set_cache("key", "value")

            call_args = mock_set.call_args
            assert call_args[0][2] == 31_536_000

    async def test_delete_cache_calls_redis_delete(self) -> None:
        """delete_cache for a non-pattern key should call redis_cache.delete."""
        with patch.object(redis_cache, "delete", new_callable=AsyncMock) as mock_del:
            await delete_cache("user:123")

            mock_del.assert_awaited_once_with("user:123")

    async def test_delete_cache_with_wildcard_calls_pattern_delete(self) -> None:
        """delete_cache with '*' suffix should delegate to delete_cache_by_pattern."""
        with patch(
            "app.db.redis.delete_cache_by_pattern", new_callable=AsyncMock
        ) as mock_pattern:
            await delete_cache("user:*")

            mock_pattern.assert_awaited_once_with("user:*")


# ---------------------------------------------------------------------------
# get_and_delete_cache
# ---------------------------------------------------------------------------


class TestGetAndDeleteCache:
    """Tests for get_and_delete_cache() atomic operation."""

    async def test_returns_deserialized_value(self) -> None:
        """Should return deserialized value when key exists."""
        with patch.object(redis_cache, "redis") as mock_redis:
            mock_redis.getdel = AsyncMock(return_value='{"token": "abc"}')

            result = await get_and_delete_cache("oauth:state:xyz")

            mock_redis.getdel.assert_awaited_once_with("oauth:state:xyz")
            assert result == {"token": "abc"}

    async def test_returns_none_for_missing_key(self) -> None:
        """Should return None when key doesn't exist."""
        with patch.object(redis_cache, "redis") as mock_redis:
            mock_redis.getdel = AsyncMock(return_value=None)

            result = await get_and_delete_cache("nonexistent")

            assert result is None

    async def test_returns_none_when_redis_not_initialized(self) -> None:
        """Should return None when redis_cache.redis is None."""
        original_redis = redis_cache.redis
        redis_cache.redis = None

        try:
            with patch("app.db.redis.log"):
                result = await get_and_delete_cache("key")

            assert result is None
        finally:
            redis_cache.redis = original_redis

    async def test_catches_exception_returns_none(self) -> None:
        """Should catch exceptions and return None."""
        with patch.object(redis_cache, "redis") as mock_redis:
            mock_redis.getdel = AsyncMock(side_effect=Exception("getdel error"))

            with patch("app.db.redis.log") as mock_log:
                result = await get_and_delete_cache("key")

            assert result is None
            mock_log.error.assert_called()


# ---------------------------------------------------------------------------
# delete_cache_by_pattern
# ---------------------------------------------------------------------------


class TestDeleteCacheByPattern:
    """Tests for delete_cache_by_pattern() function."""

    async def test_deletes_matching_keys(self) -> None:
        """Should find keys matching pattern and delete each one."""
        with (
            patch.object(redis_cache, "redis") as mock_redis,
            patch.object(redis_cache, "delete", new_callable=AsyncMock) as mock_delete,
        ):
            mock_redis.keys = AsyncMock(return_value=["user:1", "user:2", "user:3"])

            with patch("app.db.redis.log"):
                await delete_cache_by_pattern("user:*")

            assert mock_delete.await_count == 3

    async def test_no_keys_found(self) -> None:
        """Should log info and return when no keys match."""
        with patch.object(redis_cache, "redis") as mock_redis:
            mock_redis.keys = AsyncMock(return_value=[])

            with patch("app.db.redis.log") as mock_log:
                await delete_cache_by_pattern("nonexistent:*")

            mock_log.info.assert_called()

    async def test_skips_when_redis_not_initialized(self) -> None:
        """Should warn and return when redis is None."""
        original_redis = redis_cache.redis
        redis_cache.redis = None

        try:
            with patch("app.db.redis.log") as mock_log:
                await delete_cache_by_pattern("key:*")

            mock_log.warning.assert_called()
        finally:
            redis_cache.redis = original_redis

    async def test_catches_exception(self) -> None:
        """Should catch and log exceptions during pattern deletion."""
        with patch.object(redis_cache, "redis") as mock_redis:
            mock_redis.keys = AsyncMock(side_effect=Exception("scan failed"))

            with patch("app.db.redis.log") as mock_log:
                await delete_cache_by_pattern("key:*")

            mock_log.error.assert_called()

    async def test_empty_keys_list(self) -> None:
        """Empty list (different from None) should be handled."""
        with patch.object(redis_cache, "redis") as mock_redis:
            mock_redis.keys = AsyncMock(return_value=[])

            with patch("app.db.redis.log") as mock_log:
                await delete_cache_by_pattern("prefix:*")

            # Should not attempt any deletes
            info_msgs = [c[0][0] for c in mock_log.info.call_args_list]
            assert any("No keys" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# CACHE_TTL re-export
# ---------------------------------------------------------------------------


class TestCacheTTLReExport:
    """Test that the CACHE_TTL backwards-compat alias is correct."""

    def test_cache_ttl_equals_default(self) -> None:
        """CACHE_TTL should equal DEFAULT_CACHE_TTL (3600)."""
        from app.db.redis import CACHE_TTL

        assert CACHE_TTL == 3600
