"""Activity-badge promotion ARQ task."""

from app.constants.log_tags import LogTag
from shared.py.wide_events import log, wide_task


async def promote_usage_badges(ctx: dict) -> str:
    """Daily sweep: recompute every user's activity tier and email first-time
    promotions. All semantics (thresholds, monotonic promotion, idempotency,
    silent seeding) live in ``sync_activity_tiers`` — this is just the cron
    entry point.
    """
    async with wide_task("promote_usage_badges"):
        from app.services.usage_activity import sync_activity_tiers

        stats = await sync_activity_tiers(send_emails=True)
        log.set(**stats)
        message = (
            f"Scanned {stats['scanned']} users, {stats['promoted']} promoted, "
            f"{stats['emailed']} badge emails sent"
        )
        log.info(f"{LogTag.WORKER} {message}")
        return message
