"""Integration tests for Redis cache operations.

Uses fakeredis to exercise real serialization/deserialization code paths
against an in-process Redis emulator.  No mocks of Redis internals.
If the production serialization logic breaks, these tests will catch it.
"""

import asyncio

import fakeredis.aioredis as fakeredis_aioredis
import pytest
from pydantic import BaseModel

from app.db.redis import (
    RedisCache,
    delete_cache_by_pattern,
    deserialize_any,
    get_and_delete_cache,
    get_cache,
    redis_cache,
    serialize_any,
    set_cache,
)


class SampleModel(BaseModel):
    """Pydantic model for serialization tests."""

    name: str
    age: int
    active: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_cache(fake_client, default_ttl: int = 3600) -> RedisCache:
    """Return a RedisCache instance wired to *fake_client* (no real Redis)."""
    cache = RedisCache.__new__(RedisCache)
    cache.redis_url = "redis://fake"
    cache.default_ttl = default_ttl
    cache.redis = fake_client
    return cache


# ---------------------------------------------------------------------------
# Serialization helpers (pure, no Redis)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSerializationHelpers:
    """Test serialize_any / deserialize_any roundtrips."""

    def test_serialize_dict_produces_json_string(self):
        data = {"key": "value", "number": 42}
        json_str = serialize_any(data)
        assert isinstance(json_str, str)
        assert '"key"' in json_str

    def test_roundtrip_dict(self):
        data = {"name": "Alice", "scores": [1, 2, 3]}
        assert deserialize_any(serialize_any(data)) == data

    def test_roundtrip_pydantic_model(self):
        model = SampleModel(name="Bob", age=30, active=False)
        result = deserialize_any(serialize_any(model, model=SampleModel), model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "Bob"
        assert result.age == 30
        assert result.active is False

    def test_roundtrip_list(self):
        data = [1, "two", 3.0, None]
        assert deserialize_any(serialize_any(data)) == data

    def test_roundtrip_string(self):
        data = "hello world"
        assert deserialize_any(serialize_any(data)) == data

    def test_roundtrip_nested_structure(self):
        data = {
            "users": [
                {"name": "A", "tags": ["x", "y"]},
                {"name": "B", "tags": []},
            ],
            "meta": {"count": 2},
        }
        assert deserialize_any(serialize_any(data)) == data


# ---------------------------------------------------------------------------
# RedisCache — real fakeredis backend
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRedisCacheOperations:
    """Test RedisCache.get / set / delete against a live fakeredis instance."""

    @pytest.fixture
    async def fake_client(self):
        """Provide an async fakeredis client that behaves like redis.asyncio."""
        client = fakeredis_aioredis.FakeRedis(decode_responses=True)
        yield client
        await client.aclose()

    @pytest.fixture
    def cache(self, fake_client) -> RedisCache:
        return _make_fake_cache(fake_client)

    # --- basic set/get roundtrip -------------------------------------------

    async def test_set_and_get_dict_roundtrip(self, cache: RedisCache):
        """Data written via set() must be returned identically by get()."""
        data = {"key": "value", "count": 5}
        await cache.set("test:roundtrip", data, ttl=300)
        result = await cache.get("test:roundtrip")
        assert result == data

    async def test_set_and_get_pydantic_model_roundtrip(self, cache: RedisCache):
        """Pydantic model must survive a set/get cycle with correct types."""
        model = SampleModel(name="Charlie", age=25, active=False)
        await cache.set("model:roundtrip", model, ttl=300, model=SampleModel)
        result = await cache.get("model:roundtrip", model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "Charlie"
        assert result.age == 25
        assert result.active is False

    async def test_set_and_get_list_roundtrip(self, cache: RedisCache):
        data = [1, "two", {"three": 3}]
        await cache.set("test:list", data, ttl=300)
        assert await cache.get("test:list") == data

    # --- cache miss -----------------------------------------------------------

    async def test_get_returns_none_for_missing_key(self, cache: RedisCache):
        """get() must return None when the key has never been set."""
        result = await cache.get("nonexistent:key")
        assert result is None

    # --- overwrite ------------------------------------------------------------

    async def test_overwrite_updates_value(self, cache: RedisCache):
        """Writing the same key twice must replace the first value."""
        await cache.set("overwrite:key", {"v": 1}, ttl=300)
        await cache.set("overwrite:key", {"v": 2}, ttl=300)
        result = await cache.get("overwrite:key")
        assert result == {"v": 2}

    # --- delete ---------------------------------------------------------------

    async def test_delete_removes_key(self, cache: RedisCache):
        """After delete(), get() must return None."""
        await cache.set("delete:key", "some_value", ttl=300)
        assert await cache.get("delete:key") == "some_value"
        await cache.delete("delete:key")
        assert await cache.get("delete:key") is None

    # --- TTL defaults ---------------------------------------------------------

    async def test_ttl_zero_falls_back_to_default_ttl(self, cache: RedisCache, fake_client):
        """When ttl=0 is passed, set() should store with default_ttl instead."""
        cache.default_ttl = 7200
        await cache.set("ttl:zero", "data", ttl=0)
        # Key must exist (if default_ttl were also 0 the key wouldn't be set)
        ttl_remaining = await fake_client.ttl("ttl:zero")
        # fakeredis returns -1 for "no expiry" and -2 for "does not exist".
        # A positive value means setex was called with a real TTL (7200).
        assert ttl_remaining > 0

    async def test_ttl_expiry_removes_key(self, cache: RedisCache, fake_client):
        """A key set with ttl=1 should not be readable after it expires."""
        await cache.set("ttl:expiry", "expires_soon", ttl=1)
        assert await cache.get("ttl:expiry") == "expires_soon"

        # Manually expire the key via the fake client (avoids sleeping)
        await fake_client.expire("ttl:expiry", 0)

        result = await cache.get("ttl:expiry")
        assert result is None

    # --- Redis unavailable ----------------------------------------------------

    async def test_operations_noop_when_redis_none(self):
        """All operations must be silent no-ops when redis attribute is None."""
        cache = _make_fake_cache(None)
        assert await cache.get("any:key") is None
        await cache.set("any:key", "value")   # must not raise
        await cache.delete("any:key")          # must not raise


# ---------------------------------------------------------------------------
# delete_cache_by_pattern — real fakeredis backend
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteCacheByPattern:
    """Test delete_cache_by_pattern() via a patched redis_cache singleton."""

    @pytest.fixture
    async def fake_client(self):
        client = fakeredis_aioredis.FakeRedis(decode_responses=True)
        yield client
        await client.aclose()

    @pytest.fixture(autouse=True)
    def patch_redis_cache(self, fake_client):
        """Replace the module-level redis_cache.redis with our fake client."""
        original = redis_cache.redis
        redis_cache.redis = fake_client
        yield
        redis_cache.redis = original

    async def test_pattern_deletes_matching_keys(self, fake_client):
        """Keys matching the glob must be gone after delete_cache_by_pattern()."""
        await fake_client.setex("user:1", 3600, serialize_any({"id": 1}))
        await fake_client.setex("user:2", 3600, serialize_any({"id": 2}))
        await fake_client.setex("session:abc", 3600, serialize_any({"s": "abc"}))

        await delete_cache_by_pattern("user:*")

        assert await fake_client.get("user:1") is None
        assert await fake_client.get("user:2") is None
        # unrelated key must still exist
        assert await fake_client.get("session:abc") is not None

    async def test_pattern_with_no_matching_keys_is_noop(self, fake_client):
        """Calling delete_cache_by_pattern() when nothing matches must not raise."""
        await delete_cache_by_pattern("ghost:*")  # should not raise

    async def test_pattern_deletes_all_matching_prefixes(self, fake_client):
        """All keys under a prefix must be cleared in a single call."""
        for i in range(5):
            await fake_client.setex(f"temp:{i}", 3600, serialize_any(i))

        await delete_cache_by_pattern("temp:*")

        for i in range(5):
            assert await fake_client.get(f"temp:{i}") is None

    async def test_delete_cache_wrapper_dispatches_to_pattern_delete(self, fake_client):
        """delete_cache() with a wildcard key must delegate to pattern deletion."""
        await fake_client.setex("tag:alpha", 3600, serialize_any("a"))
        await fake_client.setex("tag:beta", 3600, serialize_any("b"))

        # The module-level delete_cache() checks for trailing '*'
        from app.db.redis import delete_cache

        await delete_cache("tag:*")

        assert await fake_client.get("tag:alpha") is None
        assert await fake_client.get("tag:beta") is None


# ---------------------------------------------------------------------------
# get_and_delete_cache — real fakeredis backend
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetAndDeleteCache:
    """Test the atomic get-and-delete operation."""

    @pytest.fixture
    async def fake_client(self):
        client = fakeredis_aioredis.FakeRedis(decode_responses=True)
        yield client
        await client.aclose()

    @pytest.fixture(autouse=True)
    def patch_redis_cache(self, fake_client):
        original = redis_cache.redis
        redis_cache.redis = fake_client
        yield
        redis_cache.redis = original

    async def test_get_and_delete_returns_value_and_removes_key(self, fake_client):
        """get_and_delete_cache() must return the value and leave no key behind."""
        payload = {"token": "abc123"}
        await fake_client.setex("one-time:key", 600, serialize_any(payload))

        result = await get_and_delete_cache("one-time:key")
        assert result == payload

        # Key must be gone after the call
        assert await fake_client.get("one-time:key") is None

    async def test_get_and_delete_returns_none_for_missing_key(self):
        """get_and_delete_cache() must return None for a key that never existed."""
        result = await get_and_delete_cache("never:set:key")
        assert result is None

    async def test_get_and_delete_is_atomic_second_call_returns_none(self, fake_client):
        """The second call for the same key must return None (one-time token)."""
        await fake_client.setex("one-time:atom", 600, serialize_any("secret"))

        first = await get_and_delete_cache("one-time:atom")
        second = await get_and_delete_cache("one-time:atom")

        assert first == "secret"
        assert second is None


# ---------------------------------------------------------------------------
# Module-level set_cache / get_cache wrappers — real fakeredis backend
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestModuleLevelWrappers:
    """Test set_cache / get_cache using the patched singleton."""

    @pytest.fixture
    async def fake_client(self):
        client = fakeredis_aioredis.FakeRedis(decode_responses=True)
        yield client
        await client.aclose()

    @pytest.fixture(autouse=True)
    def patch_redis_cache(self, fake_client):
        original = redis_cache.redis
        redis_cache.redis = fake_client
        yield
        redis_cache.redis = original

    async def test_set_cache_then_get_cache_roundtrip(self):
        """set_cache() followed by get_cache() must return the original value."""
        await set_cache("wrapper:dict", {"hello": "world"}, ttl=300)
        result = await get_cache("wrapper:dict")
        assert result == {"hello": "world"}

    async def test_get_cache_returns_none_for_missing_key(self):
        assert await get_cache("wrapper:missing") is None

    async def test_set_cache_with_model_roundtrip(self):
        """set_cache() / get_cache() with a Pydantic model must roundtrip correctly."""
        model = SampleModel(name="Dana", age=40, active=True)
        await set_cache("wrapper:model", model, ttl=300, model=SampleModel)
        result = await get_cache("wrapper:model", model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "Dana"
        assert result.age == 40

    async def test_set_cache_overwrites_previous_value(self):
        await set_cache("wrapper:overwrite", {"v": 1}, ttl=300)
        await set_cache("wrapper:overwrite", {"v": 99}, ttl=300)
        assert await get_cache("wrapper:overwrite") == {"v": 99}
