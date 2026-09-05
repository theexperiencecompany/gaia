"""The registry of a conversation's currently-running subagents.

While a subagent runs, the executor needs a stable, addressable handle for it —
to steer it (``message_subagent``) or stop it (``cancel_subagent``). Nothing
tracked that before: a running subagent was only a pending count plus an
integration set, neither of which names one worker. This is that handle: a Redis
hash keyed by ``conversation_id`` whose fields are subagent ids, so the executor
can enumerate exactly what is live and address one by id.

Registered when a subagent starts, deregistered when it finishes — running only.
A finished or HIL-parked subagent is not here (a parked one has stopped and is
resumed through its own approval path, not steered).
"""

from dataclasses import asdict
import json

from app.constants.cache import RUNNING_SUBAGENTS_PREFIX, RUNNING_SUBAGENTS_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import RunningSubagent
from shared.py.wide_events import log


class RunningSubagents:
    """Currently-running subagents for one conversation, addressable by id."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._key = f"{RUNNING_SUBAGENTS_PREFIX}{conversation_id}"

    async def register(self, subagent: RunningSubagent) -> None:
        """Mark a subagent live. Idempotent on ``subagent_id``."""
        if not redis_cache.client:
            return
        await redis_cache.client.hset(
            self._key, mapping={subagent.subagent_id: json.dumps(asdict(subagent), sort_keys=True)}
        )
        await redis_cache.client.expire(self._key, RUNNING_SUBAGENTS_TTL)

    async def deregister(self, subagent_id: str) -> None:
        """Drop a subagent that has finished."""
        if redis_cache.client:
            await redis_cache.client.hdel(self._key, subagent_id)

    async def list(self) -> list[RunningSubagent]:
        """Every currently-running subagent for this conversation."""
        if not redis_cache.client:
            return []
        raw = await redis_cache.client.hgetall(self._key)
        return [subagent for value in raw.values() if (subagent := _decode(value)) is not None]

    async def get(self, subagent_id: str) -> RunningSubagent | None:
        """The named subagent if it is still running, else ``None``."""
        return next(
            (s for s in await self.list() if s.subagent_id == subagent_id),
            None,
        )


def _decode(value: str) -> RunningSubagent | None:
    """Decode one stored record, skipping anything unreadable."""
    try:
        return RunningSubagent(**json.loads(value))
    except (json.JSONDecodeError, TypeError):
        log.warning(f"{LogTag.AGENT} Discarding unreadable running-subagent record")
        return None
