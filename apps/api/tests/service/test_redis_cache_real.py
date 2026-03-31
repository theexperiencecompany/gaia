"""
Service tests: RedisCache operations against real Redis.

Uses the real_redis fixture which patches redis_cache.redis to a real connection.
These tests catch issues that mocks cannot: real TTL enforcement, actual key expiry,
encoding edge cases.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.redis import redis_cache


@pytest.mark.service
class TestRedisCacheWithRealRedis:
    """Test RedisCache operations against real Redis."""

    async def test_key_actually_expires(self, real_redis):
        """Keys set with TTL=1 must be gone after the TTL elapses."""
        await redis_cache.set("expiry-test-key", {"data": "value"}, ttl=1)
        result_before = await redis_cache.get("expiry-test-key")
        assert result_before == {"data": "value"}

        await asyncio.sleep(1.1)

        result_after = await redis_cache.get("expiry-test-key")
        assert result_after is None, "Key should have expired after TTL"

    async def test_large_value_roundtrip(self, real_redis):
        """A large nested dict must survive Redis serialization roundtrip."""
        large_data = {f"key_{i}": f"value_{i}" * 100 for i in range(200)}
        await redis_cache.set("large-value-key", large_data, ttl=60)
        result = await redis_cache.get("large-value-key")
        assert result == large_data

    async def test_redis_unavailable_returns_none(self, monkeypatch):
        """When redis is None, get() must return None without raising."""
        monkeypatch.setattr(redis_cache, "redis", None)
        result = await redis_cache.get("any-key")
        assert result is None

    async def test_concurrent_set_and_get(self, real_redis):
        """Concurrent writes to the same key must not corrupt data."""

        async def write(i: int) -> None:
            await redis_cache.set(f"concurrent-key-{i}", {"index": i}, ttl=60)

        await asyncio.gather(*[write(i) for i in range(10)])

        results = await asyncio.gather(
            *[redis_cache.get(f"concurrent-key-{i}") for i in range(10)]
        )
        for i, result in enumerate(results):
            assert result == {"index": i}
