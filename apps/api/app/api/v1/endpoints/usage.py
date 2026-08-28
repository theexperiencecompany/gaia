"""
Usage tracking API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.config.rate_limits import FEATURE_LIMITS, get_feature_info
from app.models.usage_models import (
    HistoryFeatureUsage,
    HistoryUsagePeriod,
    UsageHistoryEntry,
)
from app.schemas.usage import UsageActivityResponse, UsageSummary
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.usage_activity import get_activity
from app.services.usage_service import UsageService
from app.services.usage_summary import build_usage_summary
from shared.py.wide_events import log

router = APIRouter(prefix="/usage", tags=["usage"])
usage_service = UsageService()


@router.get("/summary")
# evlog-map-disable-next-line audit -- read-only usage lookup, no state change to audit
async def get_usage_summary(user_id: str = Depends(get_user_id)) -> UsageSummary:
    """Get real-time usage summary for the current user."""
    log.set(operation="get_usage_summary")

    try:
        summary = await build_usage_summary(user_id)

        log.set(period="realtime", result_count=len(summary.features))
        log.set(outcome="success")
        capture_context_event(
            AnalyticsEvents.USAGE_QUERIED,
            {"plan_type": summary.plan_type},
        )
        return summary
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
        raise HTTPException(status_code=500, detail="Failed to get usage activity") from e
