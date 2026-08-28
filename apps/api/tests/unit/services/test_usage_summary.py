"""Unit tests for the usage summary assembly service.

The service reads live Redis rate-limit windows and the payment provider, so
every seam (limiter redis, subscription status, budget status) is mocked at its
owner — the service logic under test is the window math and the summary shape.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config.rate_limits import RateLimitPeriod
from app.models.payment_models import PlanType
from app.schemas.usage import UsageBudget
from app.services import usage_summary

MODULE = "app.services.usage_summary"
USER_ID = "user-1"

_MOCK_BUDGET = UsageBudget.model_validate(
    {
        "daily": {"percentage": 12.5, "reset_time": "2026-01-02T00:00:00+00:00"},
        "monthly": None,
        "per_request_token_ceiling": 300_000,
    }
)


def _limits(day: int, month: int) -> SimpleNamespace:
    return SimpleNamespace(day=day, month=month)


@pytest.mark.unit
class TestGetRealtimeUsage:
    @staticmethod
    def _metered_feature() -> str:
        return next(key for key, cfg in usage_summary.FEATURE_LIMITS.items() if cfg.free.day > 0)

    async def test_window_reads_redis_and_reports_used_remaining_and_reset(self) -> None:
        feature = self._metered_feature()
        limits = usage_summary.get_limits_for_plan(feature, PlanType.FREE)

        with (
            patch(f"{MODULE}.tiered_limiter") as limiter,
            patch(f"{MODULE}.get_reset_time", return_value=datetime(2026, 1, 2, tzinfo=UTC)),
        ):
            limiter._get_redis_key.return_value = "rl:key"
            limiter.redis.get = AsyncMock(return_value="7")

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        period = features[feature].periods["day"]
        assert period.used == 7
        assert period.limit == limits.day
        assert period.remaining == max(0, limits.day - 7)
        assert period.percentage == pytest.approx(7 / limits.day * 100)
        assert period.reset_time == "2026-01-02T00:00:00+00:00"
        assert (USER_ID, feature, RateLimitPeriod.DAY) in [
            c.args for c in limiter._get_redis_key.call_args_list
        ]

    async def test_feature_without_a_daily_limit_has_no_day_period(self) -> None:
        feature = next(
            key
            for key, cfg in usage_summary.FEATURE_LIMITS.items()
            if getattr(cfg.free, "day", None) == 0
        )

        with patch(f"{MODULE}.tiered_limiter") as limiter:
            limiter.redis.get = AsyncMock()

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        assert "day" not in features[feature].periods
        # Nothing with a zero limit ever touches Redis for that window.
        assert not [
            c
            for c in limiter._get_redis_key.call_args_list
            if c.args[1] == feature and c.args[2] is RateLimitPeriod.DAY
        ]

    async def test_usage_over_the_limit_clamps_remaining_to_zero(self) -> None:
        feature = self._metered_feature()
        limits = usage_summary.get_limits_for_plan(feature, PlanType.FREE)
        over = limits.day + 100

        with patch(f"{MODULE}.tiered_limiter") as limiter:
            limiter._get_redis_key.return_value = "rl:key"
            limiter.redis.get = AsyncMock(return_value=str(over))

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        period = features[feature].periods["day"]
        assert period.used == over
        assert period.remaining == 0

    async def test_every_configured_feature_appears_in_the_result(self) -> None:
        with patch(f"{MODULE}.tiered_limiter") as limiter:
            limiter.redis.get = AsyncMock(return_value=None)

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        assert set(features) == set(usage_summary.FEATURE_LIMITS)
        # Every summary carries the pro delta so a free user sees the upgrade.
        for key, summary in features.items():
            pro = usage_summary.get_limits_for_plan(key, PlanType.PRO)
            assert summary.upgrade.day == pro.day
            assert summary.upgrade.month == pro.month

    async def test_monthly_window_is_read_and_reported_alongside_the_daily_one(self) -> None:
        """Both windows are projected, not just the day.

        Every other case here asserts ``periods["day"]``, so a service that
        stopped reading the month — or asked Redis for a window name that does
        not exist — would look completely healthy.
        """
        feature = next(
            key
            for key, cfg in usage_summary.FEATURE_LIMITS.items()
            if cfg.free.month > 0 and cfg.free.day > 0
        )
        limits = usage_summary.get_limits_for_plan(feature, PlanType.FREE)

        with (
            patch(f"{MODULE}.tiered_limiter") as limiter,
            patch(f"{MODULE}.get_reset_time", return_value=datetime(2026, 2, 1, tzinfo=UTC)),
        ):
            limiter._get_redis_key.return_value = "rl:key"
            limiter.redis.get = AsyncMock(return_value="4")

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        month = features[feature].periods["month"]
        assert month.used == 4
        assert month.limit == limits.month
        assert (USER_ID, feature, RateLimitPeriod.MONTH) in [
            c.args for c in limiter._get_redis_key.call_args_list
        ]

    async def test_each_window_resets_on_its_own_period(self) -> None:
        """The reset clock is derived from the window, not a fixed one."""
        with (
            patch(f"{MODULE}.tiered_limiter") as limiter,
            patch(
                f"{MODULE}.get_reset_time", return_value=datetime(2026, 1, 2, tzinfo=UTC)
            ) as reset,
        ):
            limiter.redis.get = AsyncMock(return_value=None)

            await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        asked = {c.args[0] for c in reset.call_args_list}
        assert asked == {RateLimitPeriod.DAY, RateLimitPeriod.MONTH}

    async def test_an_empty_redis_window_reads_as_zero_used(self) -> None:
        """A never-used feature has consumed nothing — not one call."""
        feature = self._metered_feature()
        limits = usage_summary.get_limits_for_plan(feature, PlanType.FREE)

        with patch(f"{MODULE}.tiered_limiter") as limiter:
            limiter._get_redis_key.return_value = "rl:key"
            limiter.redis.get = AsyncMock(return_value=None)

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        period = features[feature].periods["day"]
        assert period.used == 0
        assert period.percentage == 0.0
        assert period.remaining == limits.day

    async def test_a_single_call_allowance_is_still_a_reported_window(self) -> None:
        """A limit of exactly 1 is a real limit.

        The window filter is ``limit > 0``; nudged to ``> 1`` it would silently
        drop every allowance-of-one feature from the summary, and the real
        config has such features (free image generation).
        """
        feature = next(
            key for key, cfg in usage_summary.FEATURE_LIMITS.items() if cfg.free.day == 1
        )

        with patch(f"{MODULE}.tiered_limiter") as limiter:
            limiter._get_redis_key.return_value = "rl:key"
            limiter.redis.get = AsyncMock(return_value=None)

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        assert features[feature].periods["day"].limit == 1

    async def test_a_free_user_never_reads_a_pro_only_window(self) -> None:
        """Windows are selected from the USER's plan, not the paid one.

        Reading pro windows for a free user would report allowances they do not
        have and burn a Redis round trip per phantom window.
        """
        pro_only = next(
            key
            for key, cfg in usage_summary.FEATURE_LIMITS.items()
            if cfg.free.day == 0 and cfg.pro.day > 0
        )

        with patch(f"{MODULE}.tiered_limiter") as limiter:
            limiter.redis.get = AsyncMock(return_value=None)

            features = await usage_summary.get_realtime_usage(USER_ID, PlanType.FREE)

        assert "day" not in features[pro_only].periods
        assert not [
            c
            for c in limiter._get_redis_key.call_args_list
            if c.args[1] == pro_only and c.args[2] is RateLimitPeriod.DAY
        ]


@pytest.mark.unit
class TestBuildUsageSummary:
    async def test_free_plan_with_no_recorded_usage_builds_the_default_summary(self) -> None:
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=None)),
            ),
            patch(f"{MODULE}.tiered_limiter") as limiter,
            patch(
                f"{MODULE}.get_budget_status", new=AsyncMock(return_value=_MOCK_BUDGET)
            ) as get_budget,
        ):
            limiter.redis.get = AsyncMock(return_value=None)

            summary = await usage_summary.build_usage_summary(USER_ID)

        assert summary.user_id == USER_ID
        assert summary.plan_type == PlanType.FREE.value
        assert summary.primary_feature == usage_summary.PRIMARY_METERED_FEATURE
        assert summary.budget is _MOCK_BUDGET
        get_budget.assert_awaited_once_with(USER_ID, PlanType.FREE)
        assert set(summary.features) == set(usage_summary.FEATURE_LIMITS)

    async def test_pro_plan_reads_the_pro_windows(self) -> None:
        pro_only = next(
            key for key, cfg in usage_summary.FEATURE_LIMITS.items() if cfg.pro.day > cfg.free.day
        )

        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                new=AsyncMock(
                    return_value=SimpleNamespace(plan_type=PlanType.PRO),
                ),
            ),
            patch(f"{MODULE}.tiered_limiter") as limiter,
            patch(f"{MODULE}.get_budget_status", new=AsyncMock(return_value=_MOCK_BUDGET)),
        ):
            limiter.redis.get = AsyncMock(return_value="1")

            summary = await usage_summary.build_usage_summary(USER_ID)

        assert summary.plan_type == PlanType.PRO.value
        pro_limits = usage_summary.get_limits_for_plan(pro_only, PlanType.PRO)
        assert summary.features[pro_only].periods["day"].limit == pro_limits.day

    async def test_the_summary_is_assembled_for_the_requested_user_and_their_plan(self) -> None:
        """Both downstream reads are keyed to this user AND this plan.

        The mocked seams answer the same whatever they are handed, so nothing
        else here can catch a summary built from another user's windows or from
        the wrong tier's allowances.
        """
        subscription = AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.PRO))
        realtime = AsyncMock(return_value={})
        with (
            patch(f"{MODULE}.payment_service.get_user_subscription_status", new=subscription),
            patch(f"{MODULE}.get_realtime_usage", new=realtime),
            patch(f"{MODULE}.get_budget_status", new=AsyncMock(return_value=_MOCK_BUDGET)),
        ):
            await usage_summary.build_usage_summary(USER_ID)

        subscription.assert_awaited_once_with(USER_ID)
        realtime.assert_awaited_once_with(USER_ID, PlanType.PRO)

    async def test_last_updated_is_an_absolute_utc_instant(self) -> None:
        """Naive local time here is unreadable to every other timezone."""
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(f"{MODULE}.get_realtime_usage", new=AsyncMock(return_value={})),
            patch(f"{MODULE}.get_budget_status", new=AsyncMock(return_value=_MOCK_BUDGET)),
        ):
            summary = await usage_summary.build_usage_summary(USER_ID)

        stamped = datetime.fromisoformat(summary.last_updated)
        assert stamped.tzinfo is not None
        assert stamped.utcoffset() == timedelta(0)

    async def test_budget_failure_propagates_instead_of_faking_success(self) -> None:
        with (
            patch(
                f"{MODULE}.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(f"{MODULE}.tiered_limiter") as limiter,
            patch(
                f"{MODULE}.get_budget_status",
                new=AsyncMock(side_effect=RuntimeError("budget source down")),
            ),
        ):
            limiter.redis.get = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="budget source down"):
                await usage_summary.build_usage_summary(USER_ID)
