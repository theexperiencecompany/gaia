"""
Service tests: rate limiter enforcement with real Redis.

Verifies that limits are actually enforced, keys follow the expected
naming pattern, and concurrent increments are atomic.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
    tiered_limiter,
)
from app.config.rate_limits import RateLimitPeriod
from app.models.payment_models import PlanType


@pytest.fixture
def real_rate_limiter(monkeypatch):
    """Restore the real check_and_increment method for enforcement tests.

    The root conftest patches tiered_limiter.check_and_increment with an AsyncMock
    to prevent rate limit hits in regular tests. This fixture temporarily unbinds
    that mock so service tests can test real enforcement behavior.
    """
    real_method = types.MethodType(
        TieredRateLimiter.check_and_increment, tiered_limiter
    )
    monkeypatch.setattr(tiered_limiter, "check_and_increment", real_method)
    return tiered_limiter


@pytest.mark.service
class TestRateLimiterRedisKeys:
    """Key naming and TTL correctness tests."""

    async def test_redis_key_contains_user_id(self, real_redis):
        """Generated key must embed the user_id."""
        user_id = "key-test-user-1"
        key = tiered_limiter._get_redis_key(
            user_id, "chat_messages", RateLimitPeriod.DAY
        )
        assert user_id in key

    async def test_redis_key_contains_feature(self, real_redis):
        """Generated key must embed the feature name."""
        key = tiered_limiter._get_redis_key("u1", "file_upload", RateLimitPeriod.DAY)
        assert "file_upload" in key

    async def test_redis_key_contains_period(self, real_redis):
        """Generated key must embed the period identifier."""
        day_key = tiered_limiter._get_redis_key(
            "u1", "chat_messages", RateLimitPeriod.DAY
        )
        month_key = tiered_limiter._get_redis_key(
            "u1", "chat_messages", RateLimitPeriod.MONTH
        )
        # In Python 3.12, f"{StrEnum.MEMBER}" returns "ClassName.MEMBER",
        # so the key contains "RateLimitPeriod.DAY" / "RateLimitPeriod.MONTH".
        assert "DAY" in day_key
        assert "MONTH" in month_key

    async def test_day_and_month_keys_are_distinct(self, real_redis):
        """Daily and monthly keys must be different strings."""
        user_id = "key-test-user-2"
        day_key = tiered_limiter._get_redis_key(
            user_id, "chat_messages", RateLimitPeriod.DAY
        )
        month_key = tiered_limiter._get_redis_key(
            user_id, "chat_messages", RateLimitPeriod.MONTH
        )
        assert day_key != month_key

    async def test_key_written_to_real_redis_on_increment(
        self, real_redis, real_rate_limiter
    ):
        """After check_and_increment, the Redis key must exist with value >= 1."""
        user_id = "incr-test-user-1"
        feature = "chat_messages"

        day_key = tiered_limiter._get_redis_key(user_id, feature, RateLimitPeriod.DAY)
        month_key = tiered_limiter._get_redis_key(
            user_id, feature, RateLimitPeriod.MONTH
        )
        await real_redis.delete(day_key, month_key)

        with patch.object(
            tiered_limiter,
            "_sync_usage_real_time",
            new=AsyncMock(),
        ):
            await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key=feature,
                user_plan=PlanType.FREE,
            )

        day_val = await real_redis.get(day_key)
        month_val = await real_redis.get(month_key)
        assert day_val is not None, "Daily key must be set after increment"
        assert month_val is not None, "Monthly key must be set after increment"
        assert int(day_val) >= 1
        assert int(month_val) >= 1


@pytest.mark.service
class TestRateLimiterEnforcement:
    """Limit enforcement tests with real Redis state."""

    async def test_request_rejected_when_daily_limit_reached(
        self, real_redis, real_rate_limiter
    ):
        """check_and_increment must raise RateLimitExceededException when limit is met."""
        user_id = "limit-enforce-user-1"
        feature = "chat_messages"

        day_key = tiered_limiter._get_redis_key(user_id, feature, RateLimitPeriod.DAY)
        month_key = tiered_limiter._get_redis_key(
            user_id, feature, RateLimitPeriod.MONTH
        )
        await real_redis.delete(day_key, month_key)

        # Seed the daily counter at exactly the FREE daily limit (200)
        await real_redis.set(day_key, "200", ex=3600)

        with patch.object(
            tiered_limiter,
            "_sync_usage_real_time",
            new=AsyncMock(),
        ):
            with pytest.raises(RateLimitExceededException) as exc_info:
                await tiered_limiter.check_and_increment(
                    user_id=user_id,
                    feature_key=feature,
                    user_plan=PlanType.FREE,
                )

        assert exc_info.value.status_code == 429

    async def test_request_allowed_below_daily_limit(
        self, real_redis, real_rate_limiter
    ):
        """check_and_increment must succeed when usage is below the limit."""
        user_id = "limit-enforce-user-2"
        feature = "chat_messages"

        day_key = tiered_limiter._get_redis_key(user_id, feature, RateLimitPeriod.DAY)
        month_key = tiered_limiter._get_redis_key(
            user_id, feature, RateLimitPeriod.MONTH
        )
        await real_redis.delete(day_key, month_key)

        # Seed well below the FREE daily limit
        await real_redis.set(day_key, "1", ex=3600)

        with patch.object(
            tiered_limiter,
            "_sync_usage_real_time",
            new=AsyncMock(),
        ):
            result = await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key=feature,
                user_plan=PlanType.FREE,
            )

        assert isinstance(result, dict)

    async def test_counter_increments_on_each_allowed_request(
        self, real_redis, real_rate_limiter
    ):
        """Each successful check_and_increment must advance the counter by 1."""
        user_id = "limit-enforce-user-3"
        feature = "chat_messages"

        day_key = tiered_limiter._get_redis_key(user_id, feature, RateLimitPeriod.DAY)
        month_key = tiered_limiter._get_redis_key(
            user_id, feature, RateLimitPeriod.MONTH
        )
        await real_redis.delete(day_key, month_key)

        with patch.object(
            tiered_limiter,
            "_sync_usage_real_time",
            new=AsyncMock(),
        ):
            for _ in range(3):
                await tiered_limiter.check_and_increment(
                    user_id=user_id,
                    feature_key=feature,
                    user_plan=PlanType.FREE,
                )

        day_val = int(await real_redis.get(day_key))
        month_val = int(await real_redis.get(month_key))
        assert day_val == 3
        assert month_val == 3


@pytest.mark.service
class TestRateLimiterAtomicity:
    """Atomicity and concurrency tests using raw Redis operations."""

    async def test_concurrent_increments_are_atomic(self, real_redis):
        """Concurrent INCR calls must not lose counts."""
        counter_key = "rate_limit_test:atomic_counter"
        await real_redis.delete(counter_key)
        await real_redis.set(counter_key, "0", ex=3600)

        async def increment() -> None:
            await real_redis.incr(counter_key)

        await asyncio.gather(*[increment() for _ in range(50)])

        final = int(await real_redis.get(counter_key))
        assert final == 50, f"Expected 50, got {final}"

    async def test_pipeline_watch_retries_on_concurrent_modification(self, real_redis):
        """Two concurrent pipeline transactions on the same key must both commit."""
        key = "rate_limit_test:pipeline_key"
        await real_redis.delete(key)
        await real_redis.set(key, "0", ex=3600)

        async def pipeline_incr() -> None:
            async with real_redis.pipeline() as pipe:
                while True:
                    try:
                        await pipe.watch(key)
                        current = int(await real_redis.get(key) or 0)
                        pipe.multi()
                        await pipe.set(key, str(current + 1), ex=3600)
                        await pipe.execute()
                        break
                    except Exception:
                        continue

        await asyncio.gather(pipeline_incr(), pipeline_incr())

        final = int(await real_redis.get(key))
        assert final == 2, f"Both pipeline transactions must commit, got {final}"

    async def test_independent_users_do_not_share_counters(self, real_redis):
        """Rate limit counters for different users must be fully independent."""
        feature = "chat_messages"
        user_a = "isolation-user-a"
        user_b = "isolation-user-b"

        key_a = tiered_limiter._get_redis_key(user_a, feature, RateLimitPeriod.DAY)
        key_b = tiered_limiter._get_redis_key(user_b, feature, RateLimitPeriod.DAY)
        await real_redis.delete(key_a, key_b)

        await real_redis.set(key_a, "5", ex=3600)
        await real_redis.set(key_b, "99", ex=3600)

        val_a = int(await real_redis.get(key_a))
        val_b = int(await real_redis.get(key_b))

        assert val_a == 5
        assert val_b == 99
        assert val_a != val_b
