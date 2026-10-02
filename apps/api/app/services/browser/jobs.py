"""Redis-backed store for a background browser job.

All cross-process because the run lives in an ARQ worker while the turn that
asked for it lives in the API: the one-task-per-conversation slot lease, the
conversation's latest job, the job's durable state, the joiner lease and the
delivery claim that decide who speaks the result, the stop flag, the handoff
the run is waiting on, and the inbox of what the user said while it runs.
"""

from redis.exceptions import WatchError

from app.constants.browser import (
    BROWSER_JOB_CANCEL_PREFIX,
    BROWSER_JOB_DELIVERED_PREFIX,
    BROWSER_JOB_INBOX_PREFIX,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_PREFIX,
    BROWSER_JOB_LATEST_PREFIX,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    BROWSER_JOB_STATE_PREFIX,
    BROWSER_JOB_WAIT_PREFIX,
    ResultSpeaker,
)
from app.db.redis import redis_cache
from app.schemas.browser_job import BrowserJobState
from app.services.browser.job_lifetime import browser_job_ttl_seconds


def _lock_key(conversation_id: str) -> str:
    return f"{BROWSER_JOB_LOCK_PREFIX}{conversation_id}"


def _latest_key(key: str) -> str:
    return f"{BROWSER_JOB_LATEST_PREFIX}{key}"


def _state_key(job_id: str) -> str:
    return f"{BROWSER_JOB_STATE_PREFIX}{job_id}"


def _joiner_key(job_id: str) -> str:
    return f"{BROWSER_JOB_JOINER_PREFIX}{job_id}"


def _hold_key(job_id: str) -> str:
    return f"{BROWSER_JOB_JOINER_PREFIX}{job_id}:hold"


def _released_key(job_id: str) -> str:
    return f"{BROWSER_JOB_JOINER_PREFIX}{job_id}:released"


def _delivered_key(job_id: str) -> str:
    return f"{BROWSER_JOB_DELIVERED_PREFIX}{job_id}"


def _cancel_key(job_id: str) -> str:
    return f"{BROWSER_JOB_CANCEL_PREFIX}{job_id}"


def _wait_key(job_id: str) -> str:
    return f"{BROWSER_JOB_WAIT_PREFIX}{job_id}"


def _inbox_key(job_id: str) -> str:
    return f"{BROWSER_JOB_INBOX_PREFIX}{job_id}"


async def claim_conversation_slot(conversation_id: str, job_id: str) -> str | None:
    """Claim the one browser slot for this conversation; returns the holding job id when taken."""
    holder: str | None = await redis_cache.client.set(
        _lock_key(conversation_id), job_id, ex=BROWSER_JOB_LOCK_TTL_SECONDS, nx=True, get=True
    )
    return holder


async def heartbeat_conversation_slot(conversation_id: str, job_id: str) -> bool:
    """Refresh the slot lease while this job holds it; False once another job does."""
    return await _if_held(_lock_key(conversation_id), job_id, refresh=BROWSER_JOB_LOCK_TTL_SECONDS)


async def release_conversation_slot(conversation_id: str, job_id: str) -> None:
    """Free the slot only while this job still holds it, so a late release never frees a newer run's lease."""
    await _if_held(_lock_key(conversation_id), job_id, refresh=None)


async def get_conversation_slot(conversation_id: str) -> str | None:
    """Return the job id holding this conversation's browser slot, or None when it is free."""
    return await redis_cache.client.get(_lock_key(conversation_id)) or None


async def _if_held(key: str, holder: str, *, refresh: int | None) -> bool:
    """Re-arm key for refresh seconds, or delete it when refresh is None, only while holder holds it."""
    async with redis_cache.client.pipeline() as pipe:
        await pipe.watch(key)
        if await pipe.get(key) != holder:
            await pipe.unwatch()
            return False
        pipe.multi()
        if refresh is None:
            pipe.delete(key)
        else:
            pipe.expire(key, refresh)
        try:
            await pipe.execute()
        except WatchError:
            # Another writer replaced the key between the read and the write: no longer ours.
            return False
    return True


async def set_latest_job(key: str, job_id: str) -> None:
    """Record the latest browser job started at key: its conversation, and for a bot run the requester's bot chat too."""
    await redis_cache.client.set(_latest_key(key), job_id, ex=browser_job_ttl_seconds())


async def get_latest_job(key: str) -> str | None:
    """Return the latest browser job recorded at key, finished or not, while its state is kept."""
    return await redis_cache.client.get(_latest_key(key)) or None


async def put_job_state(state: BrowserJobState) -> None:
    """Write the job's durable state, replacing whatever the last transition left."""
    await redis_cache.set(_state_key(state.job_id), state, ttl=browser_job_ttl_seconds())


async def get_job_state(job_id: str) -> BrowserJobState | None:
    """Load a job's state, or None when it is unknown or has expired."""
    return await redis_cache.get(_state_key(job_id), model=BrowserJobState)


async def take_joiner_lease(job_id: str, stream_id: str) -> None:
    """Announce that this turn is waiting on the job: it reads a guidance ask at once and speaks the result."""
    await redis_cache.client.set(
        _joiner_key(job_id), stream_id, ex=BROWSER_JOB_JOINER_LEASE_SECONDS
    )


async def refresh_joiner_lease(job_id: str, stream_id: str) -> None:
    """Re-arm this turn's lease; a no-op for a stream that does not hold it."""
    await _if_held(_joiner_key(job_id), stream_id, refresh=BROWSER_JOB_JOINER_LEASE_SECONDS)


async def drop_joiner_lease(job_id: str, stream_id: str) -> None:
    """End this turn's wait on the job, only while its lease is the one held."""
    await _drop(job_id, _joiner_key(job_id), stream_id)


async def joiner_lease_held(job_id: str) -> bool:
    """Whether a live turn is waiting on this job right now."""
    return bool(await redis_cache.client.exists(_joiner_key(job_id)))


async def hold_result_for_run(job_id: str, stream_id: str) -> None:
    """Keep the result for the executor run that started the job, which may still join and speak it."""
    await redis_cache.client.set(_hold_key(job_id), stream_id, ex=BROWSER_JOB_JOINER_LEASE_SECONDS)


async def release_result_hold(job_id: str, stream_id: str) -> None:
    """Give the result up once that run has ended, only while its hold is the one held."""
    await _drop(job_id, _hold_key(job_id), stream_id)


async def _drop(job_id: str, key: str, holder: str) -> None:
    """Delete a claim on the result while holder holds it, and wake a worker waiting for it to go."""
    if await _if_held(key, holder, refresh=None):
        released = _released_key(job_id)
        await redis_cache.client.rpush(released, holder)
        await redis_cache.client.expire(released, BROWSER_JOB_JOINER_LEASE_SECONDS)


async def await_result_unclaimed(job_id: str) -> None:
    """Return once no turn may still speak the result: neither a join nor the starting run holds it.

    Wakes when one is dropped; one whose API died has lapsed within a lease window.
    """
    while await redis_cache.client.exists(_joiner_key(job_id), _hold_key(job_id)):
        await redis_cache.client.blpop(
            [_released_key(job_id)], timeout=BROWSER_JOB_JOINER_LEASE_SECONDS
        )


async def claim_result_delivery(job_id: str, speaker: ResultSpeaker) -> ResultSpeaker:
    """Claim the one telling of the job's result for speaker; return who holds it, speaker when this call won."""
    holder: str | None = await redis_cache.client.set(
        _delivered_key(job_id), speaker.value, ex=browser_job_ttl_seconds(), nx=True, get=True
    )
    return speaker if holder is None else ResultSpeaker(holder)


async def request_job_cancel(job_id: str) -> None:
    """Flag a job as stopped; the run reads it at its start, between steps and before every wait."""
    await redis_cache.client.set(
        _cancel_key(job_id),
        "1",  # pragma: no mutate — read by EXISTS alone, the value carries nothing
        ex=browser_job_ttl_seconds(),
    )


async def job_cancel_requested(job_id: str) -> bool:
    """Whether a stop was requested against this job."""
    return bool(await redis_cache.client.exists(_cancel_key(job_id)))


async def set_job_wait(job_id: str, handoff_id: str) -> None:
    """Record the handoff the run is paused on, so a stop can settle it."""
    await redis_cache.client.set(_wait_key(job_id), handoff_id, ex=browser_job_ttl_seconds())


async def get_job_wait(job_id: str) -> str | None:
    """Return the handoff the run is paused on, or None when it is not waiting."""
    return await redis_cache.client.get(_wait_key(job_id)) or None


async def clear_job_wait(job_id: str) -> None:
    await redis_cache.delete(_wait_key(job_id))


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
    async with redis_cache.client.pipeline() as pipe:
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
