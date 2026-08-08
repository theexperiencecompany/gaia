"""Activity-badge promotion ARQ task."""

from typing import Any

from app.constants.log_tags import LogTag
from app.services.usage_activity import sync_activity_tiers
from shared.py.wide_events import log, wide_task


async def promote_usage_badges(_ctx: dict[str, Any]) -> str:
    """Daily sweep: recompute every user's activity tier and email first-time
    promotions. All semantics (thresholds, monotonic promotion, idempotency,
    silent seeding) live in ``sync_activity_tiers`` — this is just the cron
    entry point.
    """
    async with wide_task("promote_usage_badges"):
        stats = await sync_activity_tiers(send_emails=True)
        log.set(**stats)
        message = (
            f"Scanned {stats['scanned']} users, {stats['promoted']} promoted, "
            f"{stats['emailed']} badge emails sent"
        )
        log.info(f"{LogTag.WORKER} usage badge sweep complete", summary=message)
        return message
