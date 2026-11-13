"""Putting a user's flush on the queue: one deferred job per user and instant."""

from collections.abc import Collection
from datetime import datetime, timedelta

from app.constants.outbox_attention import (
    OUTBOX_FLUSH_JOB_ID_PREFIX,
    OUTBOX_FLUSH_TASK,
    HoldReason,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.utils import clock
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job


async def schedule_flush(user_id: str, at: datetime) -> None:
    """Have the user's held items flushed once the instant comes; raises when the enqueue fails.

    The job id names the instant, so two holds ending together schedule one job. A job that
    runs with nothing due (a hold released earlier, a return that flushed first) does nothing.
    """
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        OUTBOX_FLUSH_TASK,
        user_id,
        _job_id=f"{OUTBOX_FLUSH_JOB_ID_PREFIX}{user_id}:{int(at.timestamp())}",
        _defer_until=at,
    )


async def release_and_flush(
    user_id: str, reasons: Collection[HoldReason], *, delay: timedelta
) -> None:
    """End the user's holds for these reasons and flush them after the delay; nothing is scheduled when none was held."""
    now = clock.now()
    if await outbox_items_repository.release_held(user_id, reasons, now):
        await schedule_flush(user_id, now + delay)


async def release_silence_holds(user_id: str) -> None:
    """End the holds waiting on the user's DND or quiet hours, which they just changed, and re-place them now."""
    await release_and_flush(user_id, (HoldReason.DND, HoldReason.QUIET_HOURS), delay=timedelta())
