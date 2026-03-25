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


@pytest.mark.unit
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


@pytest.mark.unit
class TestGetPool:
    async def test_creates_pool_on_first_call(self) -> None:
        mock_pool = AsyncMock()
        mock_redis_settings = MagicMock()

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=AsyncMock(return_value=mock_pool)),
                    "arq.connections": MagicMock(
                        RedisSettings=MagicMock(
                            from_dsn=MagicMock(return_value=mock_redis_settings)
                        )
                    ),
                },
            ),
            patch(
                "app.config.settings.settings",
                MagicMock(REDIS_URL="redis://localhost:6379/0"),
            ),
        ):
            pool = await RedisPoolManager.get_pool()

        assert pool is mock_pool

    async def test_returns_cached_pool_on_second_call(self) -> None:
        """If _pool is already set, get_pool returns it immediately."""
        sentinel = AsyncMock()
        RedisPoolManager._pool = sentinel  # type: ignore[assignment]

        pool = await RedisPoolManager.get_pool()
        assert pool is sentinel

    async def test_raises_when_create_pool_fails(self) -> None:
        """If arq.create_pool raises, the exception propagates."""
        mock_create = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis_settings_cls = MagicMock()
        mock_redis_settings_cls.from_dsn = MagicMock(return_value=MagicMock())

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=mock_create),
                    "arq.connections": MagicMock(
                        RedisSettings=mock_redis_settings_cls,
                    ),
                },
            ),
            patch(
                "app.config.settings.settings",
                MagicMock(REDIS_URL="redis://localhost:6379/0"),
            ),
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

        mock_redis_settings_cls = MagicMock()
        mock_redis_settings_cls.from_dsn = MagicMock(return_value=MagicMock())

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=fake_create_pool),
                    "arq.connections": MagicMock(
                        RedisSettings=mock_redis_settings_cls,
                    ),
                },
            ),
            patch(
                "app.config.settings.settings",
                MagicMock(REDIS_URL="redis://localhost:6379/0"),
            ),
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


# ---------------------------------------------------------------------------
# close_pool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClosePool:
    async def test_close_when_pool_exists(self) -> None:
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()
        RedisPoolManager._pool = mock_pool  # type: ignore[assignment]

        await RedisPoolManager.close_pool()

        mock_pool.close.assert_awaited_once()
        assert RedisPoolManager._pool is None

    async def test_close_when_no_pool_is_noop(self) -> None:
        """Closing without a pool should not raise."""
        RedisPoolManager._pool = None
        await RedisPoolManager.close_pool()  # should not raise
        assert RedisPoolManager._pool is None

    async def test_close_sets_pool_to_none_even_on_error(self) -> None:
        """If pool.close() raises, the pool reference is still cleared."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock(side_effect=RuntimeError("close failed"))
        RedisPoolManager._pool = mock_pool  # type: ignore[assignment]

        # close_pool catches the exception internally and sets _pool to None
        await RedisPoolManager.close_pool()
        assert RedisPoolManager._pool is None

    async def test_close_is_idempotent(self) -> None:
        """Calling close_pool twice does not raise."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()
        RedisPoolManager._pool = mock_pool  # type: ignore[assignment]

        await RedisPoolManager.close_pool()
        await RedisPoolManager.close_pool()

        # Only closed once because second call sees _pool is None
        mock_pool.close.assert_awaited_once()

    async def test_close_then_get_creates_new_pool(self) -> None:
        """After closing, get_pool should create a fresh pool."""
        old_pool = AsyncMock()
        old_pool.close = AsyncMock()
        RedisPoolManager._pool = old_pool  # type: ignore[assignment]

        await RedisPoolManager.close_pool()
        assert RedisPoolManager._pool is None

        new_pool = AsyncMock()
        mock_redis_settings_cls = MagicMock()
        mock_redis_settings_cls.from_dsn = MagicMock(return_value=MagicMock())

        with (
            patch.dict(
                "sys.modules",
                {
                    "arq": MagicMock(create_pool=AsyncMock(return_value=new_pool)),
                    "arq.connections": MagicMock(
                        RedisSettings=mock_redis_settings_cls,
                    ),
                },
            ),
            patch(
                "app.config.settings.settings",
                MagicMock(REDIS_URL="redis://localhost:6379/0"),
            ),
        ):
            pool = await RedisPoolManager.get_pool()

        assert pool is new_pool
        assert pool is not old_pool

    async def test_double_check_locking_on_close(self) -> None:
        """Concurrent close calls should only close once."""
        mock_pool = AsyncMock()
        close_count = 0

        async def tracked_close() -> None:
            nonlocal close_count
            close_count += 1
            await asyncio.sleep(0.01)

        mock_pool.close = tracked_close
        RedisPoolManager._pool = mock_pool  # type: ignore[assignment]

        await asyncio.gather(
            RedisPoolManager.close_pool(),
            RedisPoolManager.close_pool(),
            RedisPoolManager.close_pool(),
        )

        assert RedisPoolManager._pool is None
        # Due to double-checked locking, only one close should succeed
        assert close_count == 1
