"""
TEST 12: Rate Limiting Under Load

Integration tests for the tiered rate limiting system.
Tests rate limit configuration, enforcement, tier differentiation,
recovery after window expiry, per-feature independence, and atomic
counter increments under concurrent load.

Uses fakeredis so no external Redis instance is required.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
)
from app.config.rate_limits import (
    FEATURE_LIMITS,
    RateLimitConfig,
    RateLimitPeriod,
    TieredRateLimits,
    get_feature_limits,
    get_limits_for_plan,
    get_reset_time,
    get_time_window_key,
)
from app.models.payment_models import PlanType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def frozen_time(iso: str) -> Generator[datetime, None, None]:
    """Patch ``datetime.now`` in the rate_limits and tiered_rate_limiter modules
    to return a fixed UTC datetime.  Unlike freezegun this does not touch every
    module in the process, avoiding the transformers/torch NameError."""
    frozen = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)

    _original_rate_limits_datetime = __import__(
        "app.config.rate_limits", fromlist=["datetime"]
    ).datetime
    _original_tiered_datetime = __import__(
        "app.api.v1.middleware.tiered_rate_limiter", fromlist=["datetime"]
    ).datetime

    class _FrozenDatetime(datetime):  # type: ignore[type-arg]
        @classmethod  # type: ignore[override]
        def now(cls, tz: timezone | None = None) -> datetime:  # type: ignore[override]
            return frozen

    with (
        patch("app.config.rate_limits.datetime", _FrozenDatetime),
        patch("app.api.v1.middleware.tiered_rate_limiter.datetime", _FrozenDatetime),
    ):
        yield frozen


def _make_limiter_with_fake_redis() -> tuple[
    TieredRateLimiter, fakeredis.aioredis.FakeRedis
]:
    """Create a TieredRateLimiter backed by fakeredis."""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = TieredRateLimiter()
    # Replace the redis_cache proxy with a duck-typed object that exposes
    # the same .get / .redis interface the limiter relies on.
    limiter.redis = _FakeRedisCache(fake_redis)
    return limiter, fake_redis


class _FakeRedisCache:
    """Minimal stand-in for ``app.db.redis.RedisCache`` backed by fakeredis."""

    def __init__(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        self.redis = fake_redis

    async def get(self, key: str, model: type | None = None) -> str | None:
        return await self.redis.get(key)

    async def set(
        self, key: str, value: str, ttl: int = 3600, model: type | None = None
    ) -> None:
        await self.redis.setex(key, ttl, value)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)


# ---------------------------------------------------------------------------
# 1. Rate limit configuration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRateLimitConfiguration:
    """Verify that rate limit tiers are defined correctly."""

    def test_feature_limits_has_expected_features(self) -> None:
        expected_features = [
            "chat_messages",
            "file_upload",
            "generate_image",
            "web_search",
            "todo_operations",
            "deep_research",
        ]
        for feature in expected_features:
            assert feature in FEATURE_LIMITS, f"Missing feature: {feature}"

    def test_each_feature_has_free_and_pro_tiers(self) -> None:
        for key, limits in FEATURE_LIMITS.items():
            assert isinstance(limits, TieredRateLimits), (
                f"{key} is not TieredRateLimits"
            )
            assert isinstance(limits.free, RateLimitConfig), f"{key}.free wrong type"
            assert isinstance(limits.pro, RateLimitConfig), f"{key}.pro wrong type"

    def test_pro_limits_are_greater_than_or_equal_to_free(self) -> None:
        for key, limits in FEATURE_LIMITS.items():
            assert limits.pro.day >= limits.free.day, (
                f"{key}: pro daily ({limits.pro.day}) < free daily ({limits.free.day})"
            )
            assert limits.pro.month >= limits.free.month, (
                f"{key}: pro monthly ({limits.pro.month}) < free monthly ({limits.free.month})"
            )

    def test_get_feature_limits_returns_correct_config(self) -> None:
        result = get_feature_limits("chat_messages")
        assert result.free.day == 200
        assert result.pro.day == 3000

    def test_get_feature_limits_raises_for_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature key"):
            get_feature_limits("nonexistent_feature")

    def test_get_limits_for_plan_free(self) -> None:
        config = get_limits_for_plan("generate_image", PlanType.FREE)
        assert config.day == 1
        assert config.month == 2

    def test_get_limits_for_plan_pro(self) -> None:
        config = get_limits_for_plan("generate_image", PlanType.PRO)
        assert config.day == 45
        assert config.month == 1350


# ---------------------------------------------------------------------------
# 2. Time window helpers
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTimeWindowHelpers:
    """Verify reset-time and window-key calculations."""

    def test_get_reset_time_day(self) -> None:
        with frozen_time("2026-04-01T14:30:00"):
            reset = get_reset_time(RateLimitPeriod.DAY)
            expected = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)
            assert reset == expected

    def test_get_reset_time_month(self) -> None:
        with frozen_time("2026-04-01T14:30:00"):
            reset = get_reset_time(RateLimitPeriod.MONTH)
            expected = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
            assert reset == expected

    def test_get_reset_time_month_december_rolls_year(self) -> None:
        with frozen_time("2026-12-15T10:00:00"):
            reset = get_reset_time(RateLimitPeriod.MONTH)
            expected = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            assert reset == expected

    def test_get_time_window_key_day(self) -> None:
        with frozen_time("2026-04-01T14:30:00"):
            assert get_time_window_key(RateLimitPeriod.DAY) == "20260401"

    def test_get_time_window_key_month(self) -> None:
        with frozen_time("2026-04-01T14:30:00"):
            assert get_time_window_key(RateLimitPeriod.MONTH) == "202604"


# ---------------------------------------------------------------------------
# 3. Tiered limiter -- check_and_increment
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTieredRateLimiterCheckAndIncrement:
    """Test the core check_and_increment method with fakeredis."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.limiter, self.fake_redis = _make_limiter_with_fake_redis()

    async def test_first_call_increments_counter(self) -> None:
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            usage = await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )

        # Free generate_image: day=1, month=2
        assert "day" in usage
        assert "month" in usage
        # Before increment the reported usage is 0 (snapshot taken before incr)
        assert usage["day"].used == 0
        assert usage["day"].limit == 1

    async def test_counter_increments_on_each_call(self) -> None:
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="web_search",
                user_plan=PlanType.FREE,
            )
            usage = await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="web_search",
                user_plan=PlanType.FREE,
            )

        # Second call should see used=1 (the first call already incremented)
        assert usage["day"].used == 1

    async def test_limit_exceeded_raises_429(self) -> None:
        """Exhaust the daily limit for generate_image (free=1/day) then verify 429."""
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            # First call succeeds (uses the one allowed request)
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )

            # Second call should raise
            with pytest.raises(RateLimitExceededException) as exc_info:
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["feature"] == "generate_image"
        assert exc_info.value.detail["error"] == "rate_limit_exceeded"

    async def test_premium_user_gets_higher_limits(self) -> None:
        """Pro user should be able to make more requests than free."""
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            # Free limit for generate_image is 1/day. Pro is 45/day.
            await self.limiter.check_and_increment(
                user_id="pro_user",
                feature_key="generate_image",
                user_plan=PlanType.PRO,
            )
            # A second call should succeed for pro (limit is 45)
            await self.limiter.check_and_increment(
                user_id="pro_user",
                feature_key="generate_image",
                user_plan=PlanType.PRO,
            )

            # Verify the counter is at 2 for the day key (must read inside frozen_time
            # so the time window key matches what was written)
            day_key = self.limiter._get_redis_key(
                "pro_user", "generate_image", RateLimitPeriod.DAY
            )
            counter = await self.fake_redis.get(day_key)
            assert int(counter) == 2

    async def test_monthly_limit_exceeded(self) -> None:
        """Exhaust the monthly limit for generate_image (free=2/month)."""
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            # generate_image free: day=1, month=2
            # Manually set the monthly counter close to the limit.
            month_key = self.limiter._get_redis_key(
                "user1", "generate_image", RateLimitPeriod.MONTH
            )
            # Set monthly usage to 1 (one away from limit of 2)
            await self.fake_redis.set(month_key, "1")

            # Day counter is 0 so daily check passes, but after increment
            # monthly will be at 2. Next call hits the limit.
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )

            # Reset the day counter so the daily check passes again
            day_key = self.limiter._get_redis_key(
                "user1", "generate_image", RateLimitPeriod.DAY
            )
            await self.fake_redis.set(day_key, "0")

            # Monthly is now at 2 (the limit), so next call should fail
            with pytest.raises(RateLimitExceededException) as exc_info:
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )

        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# 4. Rate limit recovery after window expiry
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRateLimitRecovery:
    """Verify that limits reset when the time window rolls over."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.limiter, self.fake_redis = _make_limiter_with_fake_redis()

    async def test_daily_limit_resets_next_day(self) -> None:
        """Exhaust limit on day 1, then advance clock to day 2 and verify reset."""
        with patch.object(
            self.limiter, "_sync_usage_real_time", new_callable=AsyncMock
        ):
            # Day 1: exhaust the limit (generate_image free = 1/day)
            with frozen_time("2026-04-01T12:00:00"):
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )
                with pytest.raises(RateLimitExceededException):
                    await self.limiter.check_and_increment(
                        user_id="user1",
                        feature_key="generate_image",
                        user_plan=PlanType.FREE,
                    )

            # Day 2: the time window key changes, so the counter is fresh
            with frozen_time("2026-04-02T00:01:00"):
                # Should succeed because the day key is now "20260402"
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )

    async def test_monthly_limit_resets_next_month(self) -> None:
        """Set counter to monthly limit, advance to next month, verify reset."""
        with patch.object(
            self.limiter, "_sync_usage_real_time", new_callable=AsyncMock
        ):
            with frozen_time("2026-04-30T23:00:00"):
                month_key = self.limiter._get_redis_key(
                    "user1", "generate_image", RateLimitPeriod.MONTH
                )
                await self.fake_redis.set(month_key, "2")  # at the limit (free=2/month)

                # Reset the day key so day check passes
                day_key = self.limiter._get_redis_key(
                    "user1", "generate_image", RateLimitPeriod.DAY
                )
                await self.fake_redis.set(day_key, "0")

                with pytest.raises(RateLimitExceededException):
                    await self.limiter.check_and_increment(
                        user_id="user1",
                        feature_key="generate_image",
                        user_plan=PlanType.FREE,
                    )

            # May 1: month window key changes to "202605"
            with frozen_time("2026-05-01T00:01:00"):
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )


# ---------------------------------------------------------------------------
# 5. Different endpoints have independent counters
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPerFeatureIndependence:
    """Verify that rate limit counters are per-feature, not global."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.limiter, self.fake_redis = _make_limiter_with_fake_redis()

    async def test_exhausting_one_feature_does_not_affect_another(self) -> None:
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            # Exhaust generate_image (free = 1/day)
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )
            with pytest.raises(RateLimitExceededException):
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )

            # web_search (free = 10/day) should still work
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="web_search",
                user_plan=PlanType.FREE,
            )

    async def test_different_users_have_independent_counters(self) -> None:
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            # Exhaust generate_image for user1
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )
            with pytest.raises(RateLimitExceededException):
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )

            # user2 should still be able to use generate_image
            await self.limiter.check_and_increment(
                user_id="user2",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )


# ---------------------------------------------------------------------------
# 7. RateLimitExceededException detail structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRateLimitExceptionDetail:
    """Verify the exception carries the right metadata."""

    def test_basic_exception_detail(self) -> None:
        exc = RateLimitExceededException(feature="generate_image")
        assert exc.status_code == 429
        assert exc.detail["feature"] == "generate_image"
        assert exc.detail["error"] == "rate_limit_exceeded"

    def test_exception_with_plan_required(self) -> None:
        exc = RateLimitExceededException(feature="generate_image", plan_required="pro")
        assert exc.detail["plan_required"] == "pro"
        assert "Upgrade to PRO" in exc.detail["message"]

    def test_exception_with_reset_time(self) -> None:
        reset = datetime(2026, 4, 2, 0, 0, 0, tzinfo=timezone.utc)
        exc = RateLimitExceededException(feature="generate_image", reset_time=reset)
        assert exc.detail["reset_time"] == reset.isoformat()


# ---------------------------------------------------------------------------
# 8. Concurrent requests -- atomic counter increments
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentRequests:
    """Verify that concurrent calls increment the counter atomically."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.limiter, self.fake_redis = _make_limiter_with_fake_redis()

    async def test_concurrent_increments_are_atomic(self) -> None:
        """Fire many concurrent requests and verify the final counter is correct."""
        num_requests = 20

        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            tasks = [
                self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="chat_messages",  # free = 200/day
                    user_plan=PlanType.FREE,
                )
                for _ in range(num_requests)
            ]
            await asyncio.gather(*tasks)

            day_key = self.limiter._get_redis_key(
                "user1", "chat_messages", RateLimitPeriod.DAY
            )
            counter = await self.fake_redis.get(day_key)
            assert int(counter) == num_requests

    async def test_concurrent_requests_respect_limit(self) -> None:
        """Fire more concurrent requests than the limit allows.

        Some should succeed and some should raise RateLimitExceededException.
        The total successful increments must not exceed the limit.
        """
        # deep_research free = 2/day
        limit = 2
        num_requests = 10

        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):

            async def _attempt() -> bool:
                try:
                    await self.limiter.check_and_increment(
                        user_id="user1",
                        feature_key="deep_research",
                        user_plan=PlanType.FREE,
                    )
                    return True
                except RateLimitExceededException:
                    return False

            results = await asyncio.gather(*[_attempt() for _ in range(num_requests)])
            succeeded = sum(1 for r in results if r)
            rate_limited = sum(1 for r in results if not r)

        # Exactly `limit` requests should have succeeded
        assert succeeded == limit, f"Expected {limit} successes, got {succeeded}"
        assert rate_limited == num_requests - limit


# ---------------------------------------------------------------------------
# 9. Redis key structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRedisKeyStructure:
    """Verify Redis key format used by the limiter."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.limiter, _ = _make_limiter_with_fake_redis()

    def test_daily_key_format(self) -> None:
        with frozen_time("2026-04-01T14:00:00"):
            key = self.limiter._get_redis_key(
                "user123", "web_search", RateLimitPeriod.DAY
            )
            # Key embeds the enum repr and the YYYYMMDD window
            assert "user123" in key
            assert "web_search" in key
            assert "20260401" in key
            assert key.startswith("rate_limit:")

    def test_monthly_key_format(self) -> None:
        with frozen_time("2026-04-01T14:00:00"):
            key = self.limiter._get_redis_key(
                "user123", "web_search", RateLimitPeriod.MONTH
            )
            assert "user123" in key
            assert "web_search" in key
            assert "202604" in key
            assert key.startswith("rate_limit:")


# ---------------------------------------------------------------------------
# 10. Plan-gated features
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPlanGatedFeatures:
    """Verify that the exception indicates when a plan upgrade is needed."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        self.limiter, self.fake_redis = _make_limiter_with_fake_redis()

    async def test_rate_limit_exceeded_on_free_suggests_upgrade(self) -> None:
        """When a free user is rate-limited on a feature where free limit is 0
        for that period, the exception should include plan_required='pro'."""
        with (
            frozen_time("2026-04-01T12:00:00"),
            patch.object(self.limiter, "_sync_usage_real_time", new_callable=AsyncMock),
        ):
            # Exhaust generate_image (free day=1)
            await self.limiter.check_and_increment(
                user_id="user1",
                feature_key="generate_image",
                user_plan=PlanType.FREE,
            )
            with pytest.raises(RateLimitExceededException) as exc_info:
                await self.limiter.check_and_increment(
                    user_id="user1",
                    feature_key="generate_image",
                    user_plan=PlanType.FREE,
                )

        # Free daily limit for generate_image is 1 (not 0), so plan_required
        # should be None (it is only set when the free limit for that period is 0).
        assert exc_info.value.detail.get("plan_required") is None
