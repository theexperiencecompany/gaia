"""Redis-backed store for a background browser job.

All cross-process because the run lives in an ARQ worker while the turn that
asked for it lives in the API: the one-task-per-conversation slot lease, the
conversation's latest job, the state of a job that has not ended, the one
record of how it ended, the handoff the run is waiting on, and the inbox of
what the user said while it runs.
"""

from dataclasses import dataclass

from redis.exceptions import WatchError

from app.agents.core.background.executor_channel import RedisInbox
from app.constants.browser import (
    BROWSER_JOB_ENDING_PREFIX,
    BROWSER_JOB_INBOX_PREFIX,
    BROWSER_JOB_LATEST_PREFIX,
    BROWSER_JOB_LIVE_KEY,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    BROWSER_JOB_STATE_PREFIX,
    BROWSER_JOB_WAIT_PREFIX,
    JobEnding,
)
from app.db.redis import redis_cache
from app.models.agent_models import InboxEntry
from app.schemas.browser_job import BROWSER_JOB_ENDING, BrowserJobEnding, BrowserJobState
from app.services.browser.job_lifetime import browser_job_ttl_seconds


def _lock_key(conversation_id: str) -> str:
    return f"{BROWSER_JOB_LOCK_PREFIX}{conversation_id}"


def _latest_key(key: str) -> str:
    return f"{BROWSER_JOB_LATEST_PREFIX}{key}"


def _state_key(job_id: str) -> str:
    return f"{BROWSER_JOB_STATE_PREFIX}{job_id}"


def _ending_key(job_id: str) -> str:
    return f"{BROWSER_JOB_ENDING_PREFIX}{job_id}"


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
    return await if_held(_lock_key(conversation_id), job_id, refresh=BROWSER_JOB_LOCK_TTL_SECONDS)


async def release_conversation_slot(conversation_id: str, job_id: str) -> None:
    """Free the slot only while this job still holds it, so a late release never frees a newer run's lease."""
    await if_held(_lock_key(conversation_id), job_id, refresh=None)


async def get_conversation_slot(conversation_id: str) -> str | None:
    """Return the job id holding this conversation's browser slot, or None when it is free."""
    return await redis_cache.client.get(_lock_key(conversation_id)) or None


async def if_held(key: str, holder: str, *, refresh: int | None) -> bool:
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


async def set_latest_job(key: str, job_id: str) -> str | None:
    """Record the latest browser job started at key (its conversation, or a bot run's requester chat); return the one it replaced."""
    previous: str | None = await redis_cache.client.set(
        _latest_key(key), job_id, ex=browser_job_ttl_seconds(), get=True
    )
    return previous


async def restore_latest_job(key: str, job_id: str, previous: str | None) -> None:
    """Point key back at the job before job_id, which never ran, unless a newer job took key since."""
    latest = _latest_key(key)
    async with redis_cache.client.pipeline() as pipe:
        await pipe.watch(latest)
        if await pipe.get(latest) != job_id:
            await pipe.unwatch()
            return
        pipe.multi()
        if previous is None:
            pipe.delete(latest)
        else:
            pipe.set(latest, previous, ex=browser_job_ttl_seconds())
        try:
            await pipe.execute()
        except WatchError:
            # A newer job took the key between the read and the write: it is the latest now.
            return


async def get_latest_job(key: str) -> str | None:
    """Return the latest browser job recorded at key, finished or not, while its state is kept."""
    return await redis_cache.client.get(_latest_key(key)) or None


async def put_job_state(state: BrowserJobState) -> None:
    """Write the state of a job that has not ended, and keep it where the reaper looks."""
    await redis_cache.set(_state_key(state.job_id), state, ttl=browser_job_ttl_seconds())
    await redis_cache.client.sadd(BROWSER_JOB_LIVE_KEY, state.job_id)


async def get_job_state(job_id: str) -> BrowserJobState | None:
    """Load the state a job was queued or run with, or None when it is unknown or has expired."""
    return await redis_cache.get(_state_key(job_id), model=BrowserJobState)


async def live_job_ids() -> list[str]:
    """Return every job recorded as not ended, as the reaper walks them."""
    return [str(job_id) for job_id in await redis_cache.client.smembers(BROWSER_JOB_LIVE_KEY)]


async def forget_live_job(job_id: str) -> None:
    """Stop looking at a job the reaper found ended or expired."""
    await redis_cache.client.srem(BROWSER_JOB_LIVE_KEY, job_id)


@dataclass(frozen=True)
class InboxLanding:
    """An executor inbox entry written with the ending it tells, or not at all."""

    inbox: RedisInbox
    entry: InboxEntry


async def record_ending(
    job_id: str, ending: BrowserJobEnding, landing: InboxLanding | None = None
) -> BrowserJobEnding:
    """Record how the job ends unless an ending is recorded already; return the ending of record.

    The one decision point between a stop, the run's own end and the reaper:
    whoever records first wins, and gets its own ending object back. The landing
    is written in the same transaction, so an ending is never told unrecorded.
    """
    key = _ending_key(job_id)
    async with redis_cache.client.pipeline() as pipe:
        while True:
            await pipe.watch(key)
            held = await pipe.get(key)
            if held is not None:
                await pipe.unwatch()
                return BROWSER_JOB_ENDING.validate_json(held)
            pipe.multi()
            pipe.set(key, BROWSER_JOB_ENDING.dump_json(ending), ex=browser_job_ttl_seconds())
            pipe.srem(BROWSER_JOB_LIVE_KEY, job_id)
            if landing is not None:
                landing.inbox.stage_append(pipe, landing.entry)
            try:
                await pipe.execute()
            except WatchError:
                # Another ending landed between the read and the write: read it instead.
                continue
            return ending


async def done_state(job_id: str) -> BrowserJobEnding | None:
    """Return how the job ended, its result with it, or None while it has not ended."""
    recorded = await redis_cache.client.get(_ending_key(job_id))
    return BROWSER_JOB_ENDING.validate_json(recorded) if recorded else None


async def job_cancel_requested(job_id: str) -> bool:
    """Whether a stop won the job's ending: the run is to stop, and nothing tells its result."""
    ended = await done_state(job_id)
    return ended is not None and ended.ending is JobEnding.STOPPED


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
