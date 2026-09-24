"""Redis-backed store for a background browser job.

Five pieces of shared state, all cross-process because the run lives in an ARQ
worker while the turn that asked for it lives in the API: the one-task-per-
conversation slot lease, the job's durable state, the joiner lease that decides
who speaks the result, the cancel flag for a job whose turn has ended, and the
inbox of what the user said while the job runs.
"""

from app.constants.browser import (
    BROWSER_JOB_CANCEL_PREFIX,
    BROWSER_JOB_INBOX_PREFIX,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_PREFIX,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    BROWSER_JOB_STATE_PREFIX,
)
from app.db.redis import redis_cache
from app.schemas.browser_job import BrowserJobState
from app.services.browser.job_lifetime import browser_job_ttl_seconds


def _lock_key(conversation_id: str) -> str:
    return f"{BROWSER_JOB_LOCK_PREFIX}{conversation_id}"


def _state_key(job_id: str) -> str:
    return f"{BROWSER_JOB_STATE_PREFIX}{job_id}"


def _joiner_key(job_id: str) -> str:
    return f"{BROWSER_JOB_JOINER_PREFIX}{job_id}"


def _cancel_key(job_id: str) -> str:
    return f"{BROWSER_JOB_CANCEL_PREFIX}{job_id}"


def _inbox_key(job_id: str) -> str:
    return f"{BROWSER_JOB_INBOX_PREFIX}{job_id}"


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
        _state_key(state.job_id), state, ttl=browser_job_ttl_seconds(), model=BrowserJobState
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
    await redis_cache.client.set(
        _cancel_key(job_id),
        "1",  # pragma: no mutate — read by EXISTS alone, the value carries nothing
        ex=browser_job_ttl_seconds(),
    )


async def job_cancel_requested(job_id: str) -> bool:
    """Whether a stop was requested against this job itself."""
    return bool(await redis_cache.client.exists(_cancel_key(job_id)))


async def cancel_conversation_browser_job(conversation_id: str) -> str | None:
    """Flag this conversation's in-flight browser job as cancelled; returns the job id.

    A stop names a conversation, never a job, so the slot is the way back to the
    run — and the only one left once the turn that started it has ended.
    """
    job_id = await get_conversation_slot(conversation_id)
    if job_id is None:
        return None
    await request_job_cancel(job_id)
    return job_id


async def post_job_message(job_id: str, text: str) -> None:
    """Queue what the user said for the running job to read at its next step."""
    key = _inbox_key(job_id)
    await redis_cache.client.rpush(key, text)
    await redis_cache.client.expire(key, browser_job_ttl_seconds())


async def job_messages_waiting(job_id: str) -> bool:
    return bool(await redis_cache.client.llen(_inbox_key(job_id)))


async def take_job_messages(job_id: str) -> list[str]:
    """Return and clear the messages waiting for this job, oldest first."""
    key = _inbox_key(job_id)
    async with redis_cache.client.pipeline(transaction=True) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        messages, _deleted = await pipe.execute()
    return [str(message) for message in messages]


async def post_conversation_message(conversation_id: str, text: str) -> str | None:
    """Queue a user message for this conversation's running browser job; returns its id, or None when none runs."""
    job_id = await get_conversation_slot(conversation_id)
    if job_id is None:
        return None
    await post_job_message(job_id, text)
    return job_id
