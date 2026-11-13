"""Putting a user's flush on the queue: one deferred job per user and instant."""

from datetime import datetime

from app.constants.outbox_attention import OUTBOX_FLUSH_JOB_ID_PREFIX, OUTBOX_FLUSH_TASK
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
