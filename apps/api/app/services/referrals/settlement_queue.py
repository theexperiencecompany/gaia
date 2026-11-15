"""Hand a referrer's rewards to the worker, which settles them one referrer at a time."""

from app.constants.referrals import SETTLE_REWARDS_TASK
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job


def settle_job_id(referrer_user_id: str, friend_user_id: str | None = None) -> str:
    """Return the settle job's id: per friend for a payment or refund, per referrer otherwise.

    A friend's own id keeps their job from collapsing onto one already running
    for another friend, which may have read the owed list before this friend paid.
    """
    parts = [SETTLE_REWARDS_TASK, referrer_user_id]
    if friend_user_id is not None:
        parts.append(friend_user_id)
    return ":".join(parts)


async def queue_settlement(referrer_user_id: str, *, friend_user_id: str | None = None) -> None:
    """Queue the referrer's settle job; raises when Redis refuses, so the caller's retry owns it."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        SETTLE_REWARDS_TASK,
        referrer_user_id,
        _job_id=settle_job_id(referrer_user_id, friend_user_id),
    )
