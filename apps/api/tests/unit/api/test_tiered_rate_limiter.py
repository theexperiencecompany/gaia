"""Tests for tiered rate limiter middleware."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as aioredis

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
    tiered_rate_limit,
)
from app.config.rate_limits import RateLimitPeriod
from app.models.payment_models import PlanType


# ---------------------------------------------------------------------------
# RateLimitExceededException
# ---------------------------------------------------------------------------


class TestRateLimitExceededException:
    def test_basic_exception(self) -> None:
        exc = RateLimitExceededException("file_upload")
        assert exc.status_code == 429
        assert exc.detail["error"] == "rate_limit_exceeded"  # type: ignore[index]
        assert exc.detail["feature"] == "file_upload"  # type: ignore[index]
        assert "plan_required" not in exc.detail  # type: ignore[operator]
        assert "reset_time" not in exc.detail  # type: ignore[operator]

    def test_with_plan_required(self) -> None:
        exc = RateLimitExceededException("file_upload", plan_required="pro")
        assert exc.detail["plan_required"] == "pro"  # type: ignore[index]
        assert "PRO" in exc.detail["message"]  # type: ignore[index]

    def test_with_reset_time(self) -> None:
        reset = datetime(2026, 4, 1, tzinfo=timezone.utc)
        exc = RateLimitExceededException("file_upload", reset_time=reset)
        assert exc.detail["reset_time"] == reset.isoformat()  # type: ignore[index]

    def test_with_all_fields(self) -> None:
        reset = datetime(2026, 4, 1, tzinfo=timezone.utc)
        exc = RateLimitExceededException(
            "file_upload", plan_required="pro", reset_time=reset
        )
        assert exc.detail["plan_required"] == "pro"  # type: ignore[index]
        assert exc.detail["reset_time"] == reset.isoformat()  # type: ignore[index]


# ---------------------------------------------------------------------------
# TieredRateLimiter helpers
# ---------------------------------------------------------------------------


class TestTieredRateLimiterHelpers:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    def test_get_redis_key(self, mock_twk: MagicMock) -> None:
        key = self.limiter._get_redis_key("user1", "chat_messages", RateLimitPeriod.DAY)
        # The key embeds the enum repr, not .value
        assert "rate_limit:user1:chat_messages:" in key
        assert "20260320" in key
        mock_twk.assert_called_once_with(RateLimitPeriod.DAY)

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    def test_get_ttl_positive(self, mock_reset: MagicMock) -> None:
        future = datetime(2027, 3, 21, tzinfo=timezone.utc)
        mock_reset.return_value = future
        ttl = self.limiter._get_ttl(RateLimitPeriod.DAY)
        assert isinstance(ttl, int)
        assert ttl > 0


# ---------------------------------------------------------------------------
# check_and_increment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckAndIncrement:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_under_limit_increments(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        """When usage is under the limit, it should increment and return usage info."""
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=1000)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter.redis.get = AsyncMock(return_value="5")

        # Mock pipeline
        pipe_mock = AsyncMock()
        pipe_mock.watch = AsyncMock()
        pipe_mock.multi = MagicMock()
        pipe_mock.incr = AsyncMock()
        pipe_mock.expire = AsyncMock()
        pipe_mock.execute = AsyncMock()
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=False)

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        self.limiter.redis.redis = redis_mock

        with patch("app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task"):
            result = await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.PRO
            )

        assert "day" in result or "month" in result

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_over_limit_raises(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=10, month=100)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        # Current usage already at limit
        self.limiter.redis.get = AsyncMock(return_value="10")

        with pytest.raises(RateLimitExceededException):
            await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.FREE
            )

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_zero_limit_skipped(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        """When limit is 0 for a period, that period is skipped entirely."""
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=0, month=0)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)

        with patch("app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task"):
            result = await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.FREE
            )

        assert result == {}

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_no_redis_connection_raises(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=1000)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter.redis.get = AsyncMock(return_value="5")
        self.limiter.redis.redis = None

        with pytest.raises(Exception, match="Redis connection not available"):
            await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.FREE
            )

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_watch_error_retries(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        """WatchError should cause a retry in the pipeline loop."""
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter.redis.get = AsyncMock(return_value="5")

        pipe_mock = AsyncMock()
        call_count = 0

        async def watch_side_effect(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aioredis.WatchError()

        pipe_mock.watch = AsyncMock(side_effect=watch_side_effect)
        pipe_mock.multi = MagicMock()
        pipe_mock.incr = AsyncMock()
        pipe_mock.expire = AsyncMock()
        pipe_mock.execute = AsyncMock()
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=False)

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        self.limiter.redis.redis = redis_mock

        with patch("app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task"):
            await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.FREE
            )

        assert call_count == 2  # First attempt fails, second succeeds

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_concurrent_limit_exceeded_in_pipeline(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        """If current val hits limit inside pipeline, it should raise."""
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=10, month=0)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        # First check returns 9 (under limit), but pipeline read returns 10
        self.limiter.redis.get = AsyncMock(side_effect=["9", "10"])

        pipe_mock = AsyncMock()
        pipe_mock.watch = AsyncMock()
        pipe_mock.unwatch = AsyncMock()
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=False)

        redis_mock = MagicMock()
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)
        self.limiter.redis.redis = redis_mock

        with pytest.raises(RateLimitExceededException):
            await self.limiter.check_and_increment(
                "user1", "chat_messages", PlanType.FREE
            )


# ---------------------------------------------------------------------------
# get_usage_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetUsageInfo:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_returns_usage(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=1000)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter.redis.get = AsyncMock(return_value="42")

        result = await self.limiter.get_usage_info(
            "user1", "chat_messages", PlanType.PRO
        )

        assert "day" in result
        assert result["day"].used == 42
        assert result["day"].limit == 100

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_returns_zero_for_no_usage(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=50, month=500)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter.redis.get = AsyncMock(return_value=None)

        result = await self.limiter.get_usage_info(
            "user1", "chat_messages", PlanType.FREE
        )

        assert result["day"].used == 0

    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_zero_limit_skipped(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=0, month=0)
        result = await self.limiter.get_usage_info(
            "user1", "chat_messages", PlanType.FREE
        )
        assert result == {}


# ---------------------------------------------------------------------------
# _sync_usage_real_time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSyncUsageRealTime:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.UsageService.save_usage_snapshot",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    async def test_syncs_with_credits(
        self,
        mock_reset: MagicMock,
        mock_save: AsyncMock,
    ) -> None:
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter._collect_feature_usage = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await self.limiter._sync_usage_real_time(
            "user1", "chat_messages", PlanType.PRO, credits_used=1.5
        )

        mock_save.assert_called_once()
        snapshot = mock_save.call_args[0][0]
        assert len(snapshot.credits) == 1
        assert snapshot.credits[0].credits_used == pytest.approx(1.5)

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.UsageService.save_usage_snapshot",
        new_callable=AsyncMock,
    )
    async def test_syncs_without_credits(self, mock_save: AsyncMock) -> None:
        self.limiter._collect_feature_usage = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await self.limiter._sync_usage_real_time(
            "user1", "chat_messages", PlanType.PRO, credits_used=0.0
        )

        # No features, no credits -> no save
        mock_save.assert_not_called()

    @patch("app.api.v1.middleware.tiered_rate_limiter.log")
    async def test_error_logged_not_raised(self, mock_log: MagicMock) -> None:
        self.limiter._collect_feature_usage = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )

        # Should not raise
        await self.limiter._sync_usage_real_time("user1", "chat_messages", PlanType.PRO)

        mock_log.error.assert_called_once()


# ---------------------------------------------------------------------------
# _collect_feature_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCollectFeatureUsage:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_feature_info",
        return_value={"title": "Chat"},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_reset_time")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_collects_active_usage(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
        mock_reset: MagicMock,
        mock_info: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        mock_reset.return_value = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.limiter.redis.get = AsyncMock(return_value="5")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert len(result) == 1
        assert result[0].feature_key == "test_feat"
        assert result[0].used == 5

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_handles_redis_exception(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(side_effect=RuntimeError("redis down"))

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        # Exceptions are skipped, so result is empty
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_skips_zero_usage(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="0")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.FEATURE_LIMITS",
        {"test_feat": MagicMock()},
    )
    @patch("app.api.v1.middleware.tiered_rate_limiter.get_limits_for_plan")
    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.get_time_window_key",
        return_value="20260320",
    )
    async def test_handles_invalid_redis_value(
        self,
        mock_twk: MagicMock,
        mock_limits: MagicMock,
    ) -> None:
        from app.config.rate_limits import RateLimitConfig

        mock_limits.return_value = RateLimitConfig(day=100, month=0)
        self.limiter.redis.get = AsyncMock(return_value="not_a_number")

        result = await self.limiter._collect_feature_usage("user1", PlanType.PRO)
        assert result == []


# ---------------------------------------------------------------------------
# tiered_rate_limit decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTieredRateLimitDecorator:
    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_decorator_with_user_in_kwargs(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        sub_mock = MagicMock()
        sub_mock.plan_type = PlanType.PRO
        mock_pay.get_user_subscription_status = AsyncMock(return_value=sub_mock)
        mock_limiter.check_and_increment = AsyncMock(return_value={})

        @tiered_rate_limit("file_upload")
        async def my_endpoint(user: dict = None) -> str:  # type: ignore[assignment]
            return "ok"

        result = await my_endpoint(user={"user_id": "u1"})
        assert result == "ok"
        mock_limiter.check_and_increment.assert_called_once()

    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_decorator_with_user_in_args(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        sub_mock = MagicMock()
        sub_mock.plan_type = PlanType.FREE
        mock_pay.get_user_subscription_status = AsyncMock(return_value=sub_mock)
        mock_limiter.check_and_increment = AsyncMock(return_value={})

        @tiered_rate_limit("file_upload")
        async def my_endpoint(user: dict) -> str:
            return "ok"

        result = await my_endpoint({"user_id": "u1"})
        assert result == "ok"

    async def test_decorator_skips_when_no_user(self) -> None:
        @tiered_rate_limit("file_upload")
        async def my_endpoint() -> str:
            return "ok"

        result = await my_endpoint()
        assert result == "ok"

    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_decorator_raises_401_when_no_user_id(
        self, mock_pay: MagicMock
    ) -> None:
        from fastapi import HTTPException

        @tiered_rate_limit("file_upload")
        async def my_endpoint(user: dict = None) -> str:  # type: ignore[assignment]
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await my_endpoint(user={"email": "no_id"})
        assert exc_info.value.status_code == 401

    async def test_decorator_stores_metadata(self) -> None:
        @tiered_rate_limit("file_upload")
        async def my_endpoint() -> str:
            return "ok"

        assert hasattr(my_endpoint, "_rate_limit_metadata")
        assert my_endpoint._rate_limit_metadata["feature_key"] == "file_upload"

    @patch("app.api.v1.middleware.tiered_rate_limiter.tiered_limiter")
    @patch("app.api.v1.middleware.tiered_rate_limiter.payment_service")
    async def test_decorator_defaults_to_free_plan(
        self, mock_pay: MagicMock, mock_limiter: MagicMock
    ) -> None:
        sub_mock = MagicMock()
        sub_mock.plan_type = None
        mock_pay.get_user_subscription_status = AsyncMock(return_value=sub_mock)
        mock_limiter.check_and_increment = AsyncMock(return_value={})

        @tiered_rate_limit("file_upload")
        async def my_endpoint(user: dict = None) -> str:  # type: ignore[assignment]
            return "ok"

        await my_endpoint(user={"user_id": "u1"})
        call_args = mock_limiter.check_and_increment.call_args
        assert call_args.kwargs["user_plan"] == PlanType.FREE
