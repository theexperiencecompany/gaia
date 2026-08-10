"""The tiered limiter's plan decision logic, with the real constants.

The root conftest pins ``tiered_limiter.check_and_increment`` to a mock that
always returns ``{}``, so no test exercises the real plan-to-limit decision or
the limit-exceeded signal. These tests run the real ``TieredRateLimiter`` with
the real ``FEATURE_LIMITS`` / ``get_limits_for_plan`` — only the Redis storage
seam is mocked, following tests/unit/api/test_tiered_rate_limiter.py.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
)
from app.config.rate_limits import get_limits_for_plan
from app.models.payment_models import PlanType


def _noop_create_task(coro: object, **kwargs: object) -> MagicMock:
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


def _pipeline_mock() -> MagicMock:
    """Redis pipeline with WATCH that always succeeds on the first attempt."""
    pipe = AsyncMock()
    pipe.watch = AsyncMock()
    pipe.multi = MagicMock()
    pipe.incr = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.execute = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


# ---------------------------------------------------------------------------
# Real plan-tier limits from FEATURE_LIMITS
# ---------------------------------------------------------------------------


class TestPlanTierLimits:
    """PRO must out-bill FREE on the real constants for the same window."""

    def test_generate_image_pro_limit_exceeds_free(self) -> None:
        free = get_limits_for_plan("generate_image", PlanType.FREE)
        pro = get_limits_for_plan("generate_image", PlanType.PRO)
        assert (free.day, free.month) == (1, 2)
        assert (pro.day, pro.month) == (45, 1350)
        assert pro.day > free.day
        assert pro.month > free.month

    def test_chat_messages_pro_limit_exceeds_free(self) -> None:
        free = get_limits_for_plan("chat_messages", PlanType.FREE)
        pro = get_limits_for_plan("chat_messages", PlanType.PRO)
        # Day=0 on both: the daily wall is the rolling COST budget (see
        # rate_limits.py), not a message tally; the monthly count is the
        # abuse backstop, and pro's must exceed free's.
        assert (free.day, free.month) == (0, 2000)
        assert (pro.day, pro.month) == (0, 60000)
        assert pro.month > free.month

    def test_voice_mode_is_pro_only(self) -> None:
        """FREE has zero access to voice_mode — the plan gate decision."""
        free = get_limits_for_plan("voice_mode", PlanType.FREE)
        pro = get_limits_for_plan("voice_mode", PlanType.PRO)
        assert (free.day, free.month) == (0, 0)
        assert (pro.day, pro.month) == (200, 6000)


# ---------------------------------------------------------------------------
# check_and_increment with the real decision logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTieredLimiterRealDecision:
    def setup_method(self) -> None:
        self.limiter = TieredRateLimiter()
        self.limiter.redis = AsyncMock()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
        side_effect=_noop_create_task,
    )
    async def test_pro_under_limit_reports_real_pro_limits(
        self, mock_create_task: MagicMock
    ) -> None:
        """A PRO user at zero usage gets the real PRO numbers in usage_info."""
        self.limiter.redis.get = AsyncMock(return_value=None)
        self.limiter.redis.redis = _pipeline_mock()

        result = await self.limiter.check_and_increment("user1", "generate_image", PlanType.PRO)

        assert result["day"].used == 0
        assert result["day"].limit == 45
        assert result["month"].limit == 1350
        assert result["day"].reset_time > datetime.now(UTC)

    async def test_free_at_daily_limit_raises_429_signal(self) -> None:
        """generate_image free = 1/day: at 1 use, the limiter must raise the
        signal the endpoint layer turns into a 429."""
        reset_time = datetime.now(UTC) + timedelta(days=1)
        self.limiter.redis.get = AsyncMock(return_value="1")
        with patch(
            "app.api.v1.middleware.tiered_rate_limiter.get_reset_time",
            return_value=reset_time,
        ):
            with pytest.raises(RateLimitExceededException) as exc_info:
                await self.limiter.check_and_increment("user1", "generate_image", PlanType.FREE)

        exc = exc_info.value
        assert exc.status_code == 429
        assert exc.detail["error"] == "rate_limit_exceeded"
        assert exc.detail["feature"] == "generate_image"
        assert exc.detail["reset_time"] == reset_time.isoformat()
        # FREE has nonzero daily limits for generate_image, so it is an
        # exhausted window, not a plan gate.
        assert "plan_required" not in exc.detail

    async def test_pro_only_feature_gated_for_free_user(self) -> None:
        """voice_mode: FREE (0/0) is plan-gated — raises before any Redis read."""
        with pytest.raises(RateLimitExceededException) as exc_info:
            await self.limiter.check_and_increment("user1", "voice_mode", PlanType.FREE)

        exc = exc_info.value
        assert exc.status_code == 429
        assert exc.detail["plan_required"] == "pro"
        self.limiter.redis.get.assert_not_called()

    @patch(
        "app.api.v1.middleware.tiered_rate_limiter.asyncio.create_task",
        side_effect=_noop_create_task,
    )
    async def test_pro_user_passes_pro_only_feature(self, mock_create_task: MagicMock) -> None:
        """The same voice_mode feature is enforceable for a PRO subscriber."""
        self.limiter.redis.get = AsyncMock(return_value=None)
        self.limiter.redis.redis = _pipeline_mock()

        result = await self.limiter.check_and_increment("user1", "voice_mode", PlanType.PRO)

        assert result["day"].limit == 200
        assert result["month"].limit == 6000
