"""What happens when a usage wall refuses a request: one analytics event, and an upsell for FREE.

capture_limit_hit is called once per refusal by every wall (the tiered rate
limiter, the cost-budget gate, the mid-run budget stop, the bot burst limit).
schedule_limit_upsell sends a FREE user at most one email a week (deduped in
the senders). origin picks the email: an
interactive hit (the user did something and was blocked) gets the upsell
pitch; a background hit (a workflow run the user never initiated) gets an
informative "your workflows are taking a break" email instead — telling a
user who hasn't touched the app that *they* hit *their* limit reads as a bug.
Never blocks or raises into the caller: losing a marketing email must not
affect the 429 itself.
"""

from enum import StrEnum

from app.models.payment_models import PlanType
from app.services.analytics_service import capture
from app.services.email.senders import (
    send_limit_reached_email,
    send_workflows_paused_email,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.analytics import AnalyticsId
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.catalog.billing import LimitWindow, RateLimitHit
from shared.py.analytics.context import current_analytics_context
from shared.py.wide_events import log


class LimitHitOrigin(StrEnum):
    """Who ran into the wall: the user directly, or a background run."""

    INTERACTIVE = "interactive"
    BACKGROUND = "background"


def current_limit_origin() -> LimitHitOrigin:
    """Whether the work running right now was started by the user or by GAIA."""
    if current_analytics_context().attribution.trigger is Trigger.INTERACTIVE:
        return LimitHitOrigin.INTERACTIVE
    return LimitHitOrigin.BACKGROUND


def capture_limit_hit(
    analytics_id: AnalyticsId,
    feature_key: str,
    plan: PlanType | None,
    *,
    origin: LimitHitOrigin | None = None,
    window: LimitWindow | None = None,
) -> None:
    """Record one refusal by a usage wall, after the wall has decided to refuse."""
    capture(
        analytics_id,
        RateLimitHit(
            feature=feature_key,
            plan=plan.value if plan else None,
            origin=origin.value if origin else None,
            window=window,
        ),
    )


def schedule_limit_upsell(
    user_id: str, feature_key: str, user_plan: PlanType, origin: LimitHitOrigin
) -> None:
    """Queue the upsell email for a free user (no-op for paid plans)."""
    if user_plan != PlanType.FREE:
        return
    spawn_background_task(_run(user_id, feature_key, origin))


async def _run(user_id: str, feature_key: str, origin: LimitHitOrigin) -> None:
    try:
        if origin == LimitHitOrigin.BACKGROUND:
            await send_workflows_paused_email(user_id)
        else:
            await send_limit_reached_email(user_id, feature_key)
    except Exception as e:
        log.warning(
            "Limit upsell side effects failed",
            user={"id": user_id},
            origin=origin.value,
            error=str(e),
            error_type=type(e).__name__,
        )
