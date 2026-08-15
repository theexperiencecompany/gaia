"""
Usage tracking API endpoints.
"""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.dependencies.oauth_dependencies import get_user_id
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
from app.models.usage_models import (
    HistoryFeatureUsage,
    HistoryUsagePeriod,
    UsageHistoryEntry,
)
from app.schemas.usage import (
    FeaturePeriodUsage,
    FeatureUpgrade,
    FeatureUsageSummary,
    UsageActivityResponse,
    UsageSummary,
)
from app.services.cost_budget import get_budget_status
from app.services.payments.payment_service import payment_service
from app.services.usage_activity import get_activity
from app.services.usage_service import UsageService
from shared.py.wide_events import log

router = APIRouter(prefix="/usage", tags=["usage"])
usage_service = UsageService()


@router.get("/summary")
# evlog-map-disable-next-line audit -- read-only usage lookup, no state change to audit
async def get_usage_summary(user_id: str = Depends(get_user_id)) -> UsageSummary:
    """Get real-time usage summary for the current user."""
    log.set(operation="get_usage_summary")

    try:
        # Get user subscription
        subscription = await payment_service.get_user_subscription_status(user_id)
        user_plan = subscription.plan_type or PlanType.FREE

        # Both read independent Redis keys — issue them concurrently.
        features_formatted, budget = await asyncio.gather(
            _get_realtime_usage(user_id, user_plan),
            get_budget_status(user_id, user_plan),
        )

        log.set(period="realtime", result_count=len(features_formatted))
        log.set(outcome="success")
        return UsageSummary(
            user_id=user_id,
            plan_type=user_plan.value if hasattr(user_plan, "value") else str(user_plan),
            # The feature the usage UI leads with (its free wall is the cost
            # budget) — sourced from config so client and server never drift.
            primary_feature=PRIMARY_METERED_FEATURE,
            features=features_formatted,
            budget=budget,
            last_updated=datetime.now(UTC).isoformat(),
        )
    except Exception as e:
        log.error(
            "Error getting usage summary",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to get usage summary") from e


@router.get("/history")
# evlog-map-disable-next-line audit -- read-only usage/plan history lookup, no state change to audit
async def get_usage_history(
    days: int = Query(default=7, ge=1, le=90, description="Number of days to retrieve"),
    feature_key: str | None = Query(default=None, description="Specific feature to filter by"),
    user_id: str = Depends(get_user_id),
) -> list[UsageHistoryEntry]:
    """Get usage history for the current user."""
    log.set(operation="get_usage_history", period=f"{days}d")

    # Validate feature_key if provided
    if feature_key and feature_key not in FEATURE_LIMITS:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature_key}")

    try:
        history = await usage_service.get_usage_history(user_id, feature_key, days)

        formatted_history: list[UsageHistoryEntry] = []
        for snapshot in history:
            features_formatted: dict[str, HistoryFeatureUsage] = {}
            for feature in snapshot.features:
                key = feature.feature_key
                if key not in features_formatted:
                    feature_info = get_feature_info(key)
                    features_formatted[key] = HistoryFeatureUsage(title=feature_info.title)

                features_formatted[key].periods[feature.period] = HistoryUsagePeriod(
                    used=feature.used,
                    limit=feature.limit,
                    percentage=(feature.used / feature.limit * 100) if feature.limit > 0 else 0,
                )

            formatted_history.append(
                UsageHistoryEntry(
                    date=snapshot.created_at.isoformat(),
                    plan_type=snapshot.plan_type,
                    features=features_formatted,
                )
            )

        log.set(result_count=len(formatted_history))
        log.set(outcome="success")
        return formatted_history
    except Exception as e:
        log.error(
            "Error getting usage history",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to get usage history") from e


@router.get("/activity")
# evlog-map-disable-next-line audit -- read-only activity lookup, no state change to audit
async def get_usage_activity(
    days: int = Query(default=365, ge=1, le=366, description="Trailing window in days"),
    user_id: str = Depends(get_user_id),
) -> UsageActivityResponse:
    """Daily activity for the heatmap: per-day actions and tokens, streak, and standing."""
    log.set(operation="get_usage_activity", period=f"{days}d")
    try:
        result = await get_activity(user_id, days)
        log.set(outcome="success")
        return result
    except Exception as e:
        log.error(
            "Error getting usage activity",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=500, detail="Failed to get usage activity")


async def _get_realtime_usage(user_id: str, user_plan: PlanType) -> dict[str, FeatureUsageSummary]:
    """Get real-time usage data directly from Redis for all features."""
    features_formatted: dict[str, FeatureUsageSummary] = {}

    for feature_key in FEATURE_LIMITS:
        feature_info = get_feature_info(feature_key)
        pro_limits = get_limits_for_plan(feature_key, PlanType.PRO)
        periods: dict[str, FeaturePeriodUsage] = {}

        current_limits = get_limits_for_plan(feature_key, user_plan)

        for period in ["day", "month"]:
            limit = getattr(current_limits, period, 0)
            if limit > 0:
                # Get real-time usage from Redis
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
