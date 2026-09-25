"""The registry of a conversation's currently-running subagents.

While a subagent runs, the executor needs a stable, addressable handle for it —
to steer it (message_subagent) or stop it (cancel_subagent). This is that
handle: a Redis hash keyed by conversation_id whose fields are subagent ids, so
the executor can enumerate exactly what is live and address one by id.

Claiming a run also claims its checkpoint thread, so one thread never carries two
live runs. Claimed when a run starts, released when it finishes or parks — running
only. A parked subagent is not here; its resume claims it again.
"""

from dataclasses import asdict
import json

from app.constants.cache import (
    RUNNING_SUBAGENT_THREAD_PREFIX,
    RUNNING_SUBAGENTS_PREFIX,
    RUNNING_SUBAGENTS_TTL,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.models.agent_models import RunningSubagent
from shared.py.wide_events import log


class RunningSubagents:
    """Currently-running subagents for one conversation, addressable by id."""

    def __init__(self, conversation_id: str) -> None:
        self._key = f"{RUNNING_SUBAGENTS_PREFIX}{conversation_id}"

    async def claim(self, subagent: RunningSubagent) -> bool:
        """Mark a subagent live; False when another run already holds its thread.

        Without Redis there is nothing to coordinate on, so the run is allowed —
        the same degradation the executor busy lock applies.
        """
        client = redis_cache.client
        if not client:
            return True
        thread_key = f"{RUNNING_SUBAGENT_THREAD_PREFIX}{subagent.subagent_thread_id}"
        if not await client.set(
            thread_key, subagent.subagent_id, nx=True, ex=RUNNING_SUBAGENTS_TTL
        ):
            return False
        # Equivalent under mutation: every reader json.loads the record, so key order is invisible.
        record = json.dumps(asdict(subagent), sort_keys=True)  # pragma: no mutate
        await client.hset(self._key, mapping={subagent.subagent_id: record})
        await client.expire(self._key, RUNNING_SUBAGENTS_TTL)
        return True

    async def deregister(self, subagent: RunningSubagent) -> None:
        """Drop a subagent that finished or parked, freeing its thread."""
        client = redis_cache.client
        if client:
            await client.hdel(self._key, subagent.subagent_id)
            await client.delete(f"{RUNNING_SUBAGENT_THREAD_PREFIX}{subagent.subagent_thread_id}")

    async def holds_thread(self, subagent_thread_id: str) -> bool:
        """Whether a live run is on this checkpoint thread right now."""
        client = redis_cache.client
        return bool(
            client and await client.exists(f"{RUNNING_SUBAGENT_THREAD_PREFIX}{subagent_thread_id}")
        )

    async def live(self) -> list[RunningSubagent]:
        """Every currently-running subagent for this conversation."""
        if not redis_cache.client:
            return []
        raw = await redis_cache.client.hgetall(self._key)
        return [subagent for value in raw.values() if (subagent := _decode(value)) is not None]

    async def get(self, subagent_id: str) -> RunningSubagent | None:
        """Return the named subagent if it is still running, else None."""
        return next(
            (s for s in await self.live() if s.subagent_id == subagent_id),
            None,
        )

    async def stop_dispatched_by(self, stream_id: str) -> list[RunningSubagent]:
        """Stop every run the stream dispatched, and every run those dispatched in turn.

        A background run outlives the stream that dispatched it, so stopping that
        stream alone never reaches it.
        """
        live = await self.live()
        stopped: list[RunningSubagent] = []
        stopped_streams = {stream_id}
        parents = [stream_id]
        while parents:
            parent = parents.pop()
            for subagent in live:
                if subagent.dispatched_by != parent or subagent.stream_id in stopped_streams:
                    continue
                await _stop(subagent)
                stopped.append(subagent)
                if subagent.stream_id:
                    stopped_streams.add(subagent.stream_id)
                    parents.append(subagent.stream_id)
        return stopped

    async def stop_all(self) -> list[RunningSubagent]:
        """Stop every live run in the conversation."""
        live = await self.live()
        for subagent in live:
            await _stop(subagent)
        return live


async def stop_stream(conversation_id: str, stream_id: str) -> list[RunningSubagent]:
    """Stop a stream and every subagent it dispatched, however deep; the one way to stop a run."""
    await stream_manager.cancel_stream(stream_id)
    return await RunningSubagents(conversation_id).stop_dispatched_by(stream_id)


async def _stop(subagent: RunningSubagent) -> None:
    """Stop the run's own stream; a run sharing its dispatcher's stream stops with it."""
    if subagent.stream_id and not await stream_manager.is_cancelled(subagent.stream_id):
        await stream_manager.cancel_stream(subagent.stream_id)
        log.info(
            f"{LogTag.AGENT} Stopped a running subagent",
            subagent_id=subagent.subagent_id,
            stream_id=subagent.stream_id,
        )


def _decode(value: str) -> RunningSubagent | None:
    """Decode one stored record, skipping anything unreadable."""
    try:
        return RunningSubagent(**json.loads(value))
    except (json.JSONDecodeError, TypeError):
        log.warning(f"{LogTag.AGENT} Discarding unreadable running-subagent record")
        return None
