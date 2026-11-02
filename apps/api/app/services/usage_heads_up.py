"""The one-time in-app heads-up before a pro user's monthly allowance runs out."""

from app.config.rate_limits import RateLimitPeriod, get_reset_time, get_time_window_key
from app.constants.cache import COST_BUDGET_NEAR_NOTIFIED_KEY
from app.constants.llm import MONTHLY_BUDGET_TTL_SECONDS
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.cost_budget import format_reset_date
from app.services.notification_service import notification_service
from shared.py.wide_events import log


async def notify_monthly_heads_up_once(user_id: str) -> None:
    """In-app heads-up the first time a month enters the heads-up band (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NEAR_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
            return
        reset = format_reset_date(get_reset_time(RateLimitPeriod.MONTH))
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.USAGE_LIMIT,
                content=NotificationContent(
                    title="Most of this month's usage allowance is used",
                    body=(
                        "When it runs out, chat, workflows and tracked todos pause "
                        f"until {reset}, when it resets."
                    ),
                ),
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly heads-up notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )
