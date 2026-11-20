"""Unit tests for app.utils.redis_utils (RedisPoolManager)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.redis_utils import RedisPoolManager

# ---------------------------------------------------------------------------
# Fixtures — reset the singleton between every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset RedisPoolManager singleton state before each test."""
    RedisPoolManager._instance = None
    RedisPoolManager._pool = None
    RedisPoolManager._lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Singleton behaviour (__new__)
# ---------------------------------------------------------------------------


class TestRedisPoolManagerSingleton:
    def test_returns_same_instance(self) -> None:
        a = RedisPoolManager()
        b = RedisPoolManager()
        assert a is b

    def test_instance_is_of_correct_type(self) -> None:
        inst = RedisPoolManager()
        assert isinstance(inst, RedisPoolManager)


# ---------------------------------------------------------------------------
# get_pool
# ---------------------------------------------------------------------------


class TestGetPool:
    async def test_creates_pool_on_first_call(self) -> None:
        mock_pool = AsyncMock()

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=AsyncMock(return_value=mock_pool)),
                },
            ),
            patch("app.config.arq_redis.arq_redis_settings", MagicMock()),
        ):
            pool = await RedisPoolManager.get_pool()

        assert pool is mock_pool

    async def test_returns_cached_pool_on_second_call(self) -> None:
        """If _pool is already set, get_pool returns it immediately."""
        sentinel = AsyncMock()
        RedisPoolManager._pool = sentinel

        pool = await RedisPoolManager.get_pool()
        assert pool is sentinel

    async def test_raises_when_create_pool_fails(self) -> None:
        """If arq.create_pool raises, the exception propagates."""
        mock_create = AsyncMock(side_effect=ConnectionError("Redis down"))

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=mock_create),
                },
            ),
            patch("app.config.arq_redis.arq_redis_settings", MagicMock()),
        ):
            with pytest.raises(ConnectionError, match="Redis down"):
                await RedisPoolManager.get_pool()

        # Pool should remain None after failure
        assert RedisPoolManager._pool is None

    async def test_double_check_locking_only_creates_once(self) -> None:
        """Concurrent calls should only create the pool once (double-checked locking)."""
        call_count = 0
        sentinel_pool = AsyncMock()

        async def fake_create_pool(settings: MagicMock) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            # Simulate slow initialization
            await asyncio.sleep(0.01)
            return sentinel_pool

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=fake_create_pool),
                },
            ),
            patch("app.config.arq_redis.arq_redis_settings", MagicMock()),
        ):
            results = await asyncio.gather(
                RedisPoolManager.get_pool(),
                RedisPoolManager.get_pool(),
                RedisPoolManager.get_pool(),
            )

        # All should return the same pool
        for r in results:
            assert r is sentinel_pool
        # create_pool should only be called once thanks to double-checked locking
        assert call_count == 1
