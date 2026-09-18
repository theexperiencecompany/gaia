"""Redis-backed store for a background browser job.

Four pieces of shared state, all cross-process because the run lives in an ARQ
worker while the turn that asked for it lives in the API: the one-task-per-
conversation slot lease, the job's durable state, the joiner lease that decides
who speaks the result, and the cancel flag for a job whose turn has ended.
"""

from app.constants.browser import (
    BROWSER_JOB_CANCEL_PREFIX,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_PREFIX,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    BROWSER_JOB_STATE_PREFIX,
    BROWSER_JOB_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.schemas.browser_job import BrowserJobState


def _lock_key(conversation_id: str) -> str:
    return f"{BROWSER_JOB_LOCK_PREFIX}{conversation_id}"


def _state_key(job_id: str) -> str:
    return f"{BROWSER_JOB_STATE_PREFIX}{job_id}"


def _joiner_key(job_id: str) -> str:
    return f"{BROWSER_JOB_JOINER_PREFIX}{job_id}"


def _cancel_key(job_id: str) -> str:
    return f"{BROWSER_JOB_CANCEL_PREFIX}{job_id}"


async def claim_conversation_slot(conversation_id: str, job_id: str) -> str | None:
    """Claim the one browser slot for this conversation; returns the holding job id when taken."""
    key = _lock_key(conversation_id)
    if await redis_cache.client.set(key, job_id, ex=BROWSER_JOB_LOCK_TTL_SECONDS, nx=True):
        return None
    return await get_conversation_slot(conversation_id)


async def heartbeat_conversation_slot(conversation_id: str, job_id: str) -> None:
    """Refresh the slot lease; a no-op once another job owns it."""
    if await get_conversation_slot(conversation_id) != job_id:
        return
    await redis_cache.client.expire(_lock_key(conversation_id), BROWSER_JOB_LOCK_TTL_SECONDS)


async def release_conversation_slot(conversation_id: str, job_id: str) -> None:
    """Free the slot only while this job still holds it, so a late release never frees a newer run's lease."""
    if await get_conversation_slot(conversation_id) != job_id:
        return
    await redis_cache.delete(_lock_key(conversation_id))


async def get_conversation_slot(conversation_id: str) -> str | None:
    """Return the job id running a browser task in this conversation, or None when the slot is free."""
    return await redis_cache.client.get(_lock_key(conversation_id)) or None


async def put_job_state(state: BrowserJobState) -> None:
    """Write the job's durable state, replacing whatever the last transition left."""
    await redis_cache.set(
        _state_key(state.job_id), state, ttl=BROWSER_JOB_TTL_SECONDS, model=BrowserJobState
    )


async def get_job_state(job_id: str) -> BrowserJobState | None:
    """Load a job's state, or None when it is unknown or has expired."""
    return await redis_cache.get(_state_key(job_id), model=BrowserJobState)


async def take_joiner_lease(job_id: str, stream_id: str) -> None:
    """Announce that this turn is waiting on the job, so the worker leaves the result for it to speak."""
    await redis_cache.client.set(
        _joiner_key(job_id), stream_id, ex=BROWSER_JOB_JOINER_LEASE_SECONDS
    )


async def refresh_joiner_lease(job_id: str, stream_id: str) -> None:
    """Re-arm this turn's lease; a no-op for a stream that does not hold it."""
    if await redis_cache.client.get(_joiner_key(job_id)) != stream_id:
        return
    await redis_cache.client.expire(_joiner_key(job_id), BROWSER_JOB_JOINER_LEASE_SECONDS)


async def drop_joiner_lease(job_id: str) -> None:
    """Hand delivery back to the worker — on collecting the result, on timing out, and on any failure in between."""
    await redis_cache.delete(_joiner_key(job_id))


async def joiner_lease_held(job_id: str) -> bool:
    """Whether a live turn is still waiting on this job."""
    return bool(await redis_cache.client.exists(_joiner_key(job_id)))


async def request_job_cancel(job_id: str) -> None:
    """Flag a job as cancelled for a stop whose turn has already ended, where the stream's own signal is gone."""
    await redis_cache.client.set(_cancel_key(job_id), "1", ex=BROWSER_JOB_TTL_SECONDS)


async def job_cancel_requested(job_id: str) -> bool:
    """Whether a stop was requested against this job itself."""
    return bool(await redis_cache.client.exists(_cancel_key(job_id)))
