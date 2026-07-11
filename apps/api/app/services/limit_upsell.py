"""Fire-and-forget upsell side effects when a FREE user hits a usage wall.

Called from the two exceed seams — the tiered rate limiter (covers every
decorated endpoint and agent tool) and the daily cost-budget gate — so every
wall a free user can hit produces one analytics event and, at most once a
week (deduped in ``send_limit_reached_email``), one upsell email whose
benefits are derived live from FEATURE_LIMITS. Never blocks or raises into
the caller: losing a marketing email must not affect the 429 itself.
"""

import asyncio

from app.models.payment_models import PlanType
from app.services.analytics_service import capture_event
from app.services.email.senders import send_limit_reached_email
from shared.py.wide_events import log

# asyncio.create_task only keeps a weakref; hold refs so sends aren't GC'd mid-flight.
_upsell_tasks: set[asyncio.Task] = set()


def schedule_limit_upsell(user_id: str, feature_key: str, user_plan: PlanType) -> None:
    """Queue the limit-hit side effects for a free user (no-op for paid plans)."""
    if user_plan != PlanType.FREE:
        return
    task = asyncio.create_task(_run(user_id, feature_key))
    _upsell_tasks.add(task)
    task.add_done_callback(_upsell_tasks.discard)


async def _run(user_id: str, feature_key: str) -> None:
    try:
        capture_event(user_id, "rate_limit_hit", {"feature": feature_key})
        await send_limit_reached_email(user_id, feature_key)
    except Exception as e:
        log.warning(f"Limit upsell side effects failed for user {user_id}: {e}")
