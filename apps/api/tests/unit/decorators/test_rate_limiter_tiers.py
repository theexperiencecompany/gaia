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
from app.services.limit_upsell import LimitHitOrigin


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


# ---------------------------------------------------------------------------
# RATE_LIMIT_HIT analytics at the decorator seams
# ---------------------------------------------------------------------------


class TestRateLimitHitAnalytics:
    """Paid-plan hits are captured at the decorator seam; FREE hits are
    already captured by the limit-upsell side effect (schedule_limit_upsell)."""

    def _exceeded(self) -> RateLimitExceededException:
        return RateLimitExceededException("fake_feature")

    @pytest.mark.asyncio
    async def test_with_rate_limiting_captures_pro_hit(self) -> None:
        from app.decorators.rate_limiting import (
            LangChainRateLimitError,
            clear_user_context,
            set_user_context,
            with_rate_limiting,
        )
        from app.services.analytics_service import AnalyticsEvents

        async def fake_tool(config: dict) -> dict:
            return {"ok": True}

        wrapped = with_rate_limiting("fake_feature")(fake_tool)
        set_user_context("user-1")
        try:
            with (
                patch(
                    "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
                    new_callable=AsyncMock,
                    return_value=PlanType.PRO,
                ),
                patch(
                    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                    new_callable=AsyncMock,
                    side_effect=self._exceeded(),
                ),
                patch("app.decorators.rate_limiting.capture_event") as mock_capture,
            ):
                with pytest.raises(LangChainRateLimitError):
                    await wrapped(config={})
        finally:
            clear_user_context()

        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[0] == "user-1"
        assert mock_capture.call_args.args[1] == AnalyticsEvents.RATE_LIMIT_HIT
        assert mock_capture.call_args.args[2] == {"feature": "fake_feature", "plan": "pro"}

    @pytest.mark.asyncio
    async def test_with_rate_limiting_skips_free_hit(self) -> None:
        """FREE hits are captured by the upsell seam — no decorator duplicate."""
        from app.decorators.rate_limiting import (
            LangChainRateLimitError,
            clear_user_context,
            set_user_context,
            with_rate_limiting,
        )

        async def fake_tool(config: dict) -> dict:
            return {"ok": True}

        wrapped = with_rate_limiting("fake_feature")(fake_tool)
        set_user_context("user-1")
        try:
            with (
                patch(
                    "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
                    new_callable=AsyncMock,
                    return_value=PlanType.FREE,
                ),
                patch(
                    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                    new_callable=AsyncMock,
                    side_effect=self._exceeded(),
                ),
                patch("app.decorators.rate_limiting.capture_event") as mock_capture,
            ):
                with pytest.raises(LangChainRateLimitError):
                    await wrapped(config={})
        finally:
            clear_user_context()

        mock_capture.assert_not_called()

    @pytest.mark.asyncio
    async def test_tiered_rate_limit_captures_pro_hit(self) -> None:
        from app.decorators.rate_limiting import tiered_rate_limit
        from app.services.analytics_service import AnalyticsEvents

        async def fake_endpoint() -> dict:
            return {"ok": True}

        wrapped = tiered_rate_limit("fake_feature")(fake_endpoint)
        subscription = MagicMock(plan_type=PlanType.PRO)
        with (
            patch(
                "app.decorators.rate_limiting.get_authenticated_user",
                return_value={"user_id": "user-1"},
            ),
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=subscription,
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
                side_effect=self._exceeded(),
            ),
            patch("app.decorators.rate_limiting.capture_event") as mock_capture,
        ):
            with pytest.raises(RateLimitExceededException):
                await wrapped()

        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[0] == "user-1"
        assert mock_capture.call_args.args[1] == AnalyticsEvents.RATE_LIMIT_HIT
        assert mock_capture.call_args.args[2] == {"feature": "fake_feature", "plan": "pro"}

    @pytest.mark.asyncio
    async def test_tiered_rate_limit_skips_free_hit(self) -> None:
        from app.decorators.rate_limiting import tiered_rate_limit

        async def fake_endpoint() -> dict:
            return {"ok": True}

        wrapped = tiered_rate_limit("fake_feature")(fake_endpoint)
        subscription = MagicMock(plan_type=PlanType.FREE)
        with (
            patch(
                "app.decorators.rate_limiting.get_authenticated_user",
                return_value={"user_id": "user-1"},
            ),
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=subscription,
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
                side_effect=self._exceeded(),
            ),
            patch("app.decorators.rate_limiting.capture_event") as mock_capture,
        ):
            with pytest.raises(RateLimitExceededException):
                await wrapped()

        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# enforce_tiered_limit — the manual metering seam
# ---------------------------------------------------------------------------


class TestEnforceTieredLimit:
    """``enforce_tiered_limit`` is what non-decorated callers (bot endpoints,
    background paths) use to meter a feature, so the arguments it forwards to
    the limiter are the whole contract — a dropped ``feature_key`` silently
    meters the wrong bucket."""

    @pytest.mark.asyncio
    async def test_forwards_user_feature_and_resolved_plan_to_the_limiter(self) -> None:
        from app.decorators.rate_limiting import enforce_tiered_limit

        subscription = MagicMock(plan_type=PlanType.PRO)
        with (
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=subscription,
            ) as mock_status,
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            await enforce_tiered_limit("user-1", "fake_feature")

        mock_status.assert_awaited_once_with("user-1")
        mock_check.assert_awaited_once_with(
            user_id="user-1",
            feature_key="fake_feature",
            user_plan=PlanType.PRO,
            origin=LimitHitOrigin.INTERACTIVE,
        )

    @pytest.mark.asyncio
    async def test_a_planless_subscription_meters_as_free(self) -> None:
        """No plan on the subscription record means FREE limits, not None —
        passing None through would blow up limit lookup at the storage seam."""
        from app.decorators.rate_limiting import enforce_tiered_limit

        subscription = MagicMock(plan_type=None)
        with (
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=subscription,
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            await enforce_tiered_limit("user-1", "fake_feature")

        assert mock_check.await_args.kwargs["user_plan"] == PlanType.FREE

    @pytest.mark.asyncio
    async def test_captures_the_paid_plan_hit_and_re_raises(self) -> None:
        from app.decorators.rate_limiting import enforce_tiered_limit
        from app.services.analytics_service import AnalyticsEvents

        subscription = MagicMock(plan_type=PlanType.PRO)
        with (
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=subscription,
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
                side_effect=RateLimitExceededException("fake_feature"),
            ),
            patch("app.decorators.rate_limiting.capture_event") as mock_capture,
        ):
            with pytest.raises(RateLimitExceededException):
                await enforce_tiered_limit("user-1", "fake_feature")

        mock_capture.assert_called_once_with(
            "user-1",
            AnalyticsEvents.RATE_LIMIT_HIT,
            {"feature": "fake_feature", "plan": "pro"},
        )

    @pytest.mark.asyncio
    async def test_skips_the_free_hit_and_still_re_raises(self) -> None:
        """FREE hits are captured by the limit-upsell seam — a second event
        here would double-count every free user's wall."""
        from app.decorators.rate_limiting import enforce_tiered_limit

        subscription = MagicMock(plan_type=PlanType.FREE)
        with (
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=subscription,
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
                side_effect=RateLimitExceededException("fake_feature"),
            ),
            patch("app.decorators.rate_limiting.capture_event") as mock_capture,
        ):
            with pytest.raises(RateLimitExceededException):
                await enforce_tiered_limit("user-1", "fake_feature")

        mock_capture.assert_not_called()
