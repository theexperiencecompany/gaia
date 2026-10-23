"""Record that a human used GAIA: the only writer of users.last_active_at.

Called once, from the request middleware, for every request whose analytics
context says a user acted. Agent and system work binds actor=agent, so a
workflow run, a brief or a sweep can never count as its owner being active.
"""

from datetime import UTC, datetime

from redis.exceptions import RedisError

from app.constants.cache import LAST_ACTIVE_DEBOUNCE_SECONDS, LAST_ACTIVE_GATE_PREFIX
from app.constants.user_activity import REACTIVATE_USER_TASK, ActivityStatus
from app.db.redis import redis_cache
from app.db.repositories.users import user_repository
from app.services.user_activity.status import activity_status_of
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics.catalog.attribution import EntrySurface
from shared.py.wide_events import log


async def record_activity(user_id: str, surface: EntrySurface) -> None:
    """Mark user_id as seen now, queueing their reactivation when they were dormant.

    One write per user per debounce window. A Redis failure is logged, never
    raised: it must not fail the request. A failed reactivation enqueue skips
    the write, so the user stays dormant and the next request retries it.
    """
    gate = f"{LAST_ACTIVE_GATE_PREFIX}:{user_id}"
    client = redis_cache.redis
    if client is not None:
        try:
            if await client.exists(gate):
                return
        except RedisError as e:
            _log_redis_failure("gate_read", e)
    previous = await activity_status_of(user_id)
    if previous is ActivityStatus.DORMANT:
        try:
            await enqueue_worker_job(
                await RedisPoolManager.get_pool(),
                REACTIVATE_USER_TASK,
                user_id,
                _job_id=f"{REACTIVATE_USER_TASK}:{user_id}",
            )
        except RedisError as e:
            _log_redis_failure("reactivation_enqueue", e)
            return
    await user_repository.set_last_active(user_id, datetime.now(UTC))
    if client is not None:
        try:
            await client.set(gate, "1", ex=LAST_ACTIVE_DEBOUNCE_SECONDS)
        except RedisError as e:
            _log_redis_failure("gate_write", e)
    log.set_ns("activity", surface=surface.value, previous_status=previous.value)


def _log_redis_failure(step: str, error: RedisError) -> None:
    log.error(
        "user_activity.redis_failed",
        activity_step=step,
        error_type=type(error).__name__,
        error=str(error),
    )
