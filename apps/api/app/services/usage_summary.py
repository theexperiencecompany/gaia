"""Usage summary assembly — the shared source for ``GET /usage/summary`` and
the ``account/usage.json`` workspace projection.

Lives in the service layer so the endpoint stays a delegate and every consumer
(the UI API, the agent's account view) reads the same numbers from the same
code path.
"""

import asyncio
from datetime import UTC, datetime

from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.rate_limits import (
    FEATURE_LIMITS,
    PRIMARY_METERED_FEATURE,
    RateLimitPeriod,
    get_feature_info,
    get_limits_for_plan,
    get_reset_time,
)
from app.models.payment_models import PlanType
from app.schemas.usage import (
    FeaturePeriodUsage,
    FeatureUpgrade,
    FeatureUsageSummary,
    UsageSummary,
)
from app.services.cost_budget import get_budget_status
from app.services.payments.payment_service import payment_service


async def get_realtime_usage(user_id: str, user_plan: PlanType) -> dict[str, FeatureUsageSummary]:
    """Real-time per-feature usage read straight from the Redis rate-limit windows."""
    features_formatted: dict[str, FeatureUsageSummary] = {}

    for feature_key in FEATURE_LIMITS:
        feature_info = get_feature_info(feature_key)
        pro_limits = get_limits_for_plan(feature_key, PlanType.PRO)
        periods: dict[str, FeaturePeriodUsage] = {}

        current_limits = get_limits_for_plan(feature_key, user_plan)

        for period in ["day", "month"]:
            limit = getattr(current_limits, period, 0)
            if limit > 0:
                redis_key = tiered_limiter._get_redis_key(
                    user_id, feature_key, getattr(RateLimitPeriod, period.upper())
                )
                current_usage = await tiered_limiter.redis.get(redis_key)
                current_usage = int(current_usage) if current_usage else 0

                reset_time = get_reset_time(getattr(RateLimitPeriod, period.upper()))
                periods[period] = FeaturePeriodUsage(
                    used=current_usage,
                    limit=limit,
                    percentage=(current_usage / limit * 100),
                    reset_time=reset_time.isoformat(),
                    remaining=max(0, limit - current_usage),
                )

        features_formatted[feature_key] = FeatureUsageSummary(
            title=feature_info.title,
            description=feature_info.description,
            # Pro tier's limits, so a free user's UI can show the upgrade delta.
            upgrade=FeatureUpgrade(day=pro_limits.day, month=pro_limits.month),
            periods=periods,
        )

    return features_formatted


async def build_usage_summary(user_id: str) -> UsageSummary:
    """The full usage summary: plan tier, per-feature windows, budget percentages."""
    subscription = await payment_service.get_user_subscription_status(user_id)
    user_plan = subscription.plan_type or PlanType.FREE

    # Both read independent sources — issue them concurrently.
    features_formatted, budget = await asyncio.gather(
        get_realtime_usage(user_id, user_plan),
        get_budget_status(user_id, user_plan),
    )

    return UsageSummary(
        user_id=user_id,
        plan_type=user_plan.value,
        # The feature the usage UI leads with (its free wall is the cost
        # budget) — sourced from config so client and server never drift.
        primary_feature=PRIMARY_METERED_FEATURE,
        features=features_formatted,
        budget=budget,
        last_updated=datetime.now(UTC).isoformat(),
    )


__all__ = ["build_usage_summary", "get_realtime_usage"]
