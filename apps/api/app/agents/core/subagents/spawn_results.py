"""A finished spawned subagent's answer, remembered just long enough to survive a replay.

A spawn is disposable: it deletes its checkpoint thread as soon as it produces an
answer. The one thing that still needs to outlive it is the answer itself —
several spawns in one AI message run sequentially, so when a later sibling pauses
on a HIL approval the tool node re-runs from the top, and a finished spawn with
no thread would redo its whole task (every side effect included).

Redis, keyed by conversation (never ``stream_id`` — it changes on resume), same
tier and lifetime as the background subagent results that cross the same pause.
"""

from app.constants.hil import HIL_SPAWN_RESULT_KEY_PREFIX, HIL_SPAWN_RESULT_TTL_SECONDS
from app.db.redis import redis_cache


def _key(conversation_id: str, tool_call_id: str) -> str:
    return f"{HIL_SPAWN_RESULT_KEY_PREFIX}{conversation_id}:{tool_call_id}"


async def remember_spawn_result(conversation_id: str, tool_call_id: str, result: str) -> None:
    """Record what this spawn returned, so a replay of its tool call reuses it."""
    await redis_cache.client.set(
        _key(conversation_id, tool_call_id), result, ex=HIL_SPAWN_RESULT_TTL_SECONDS
    )


async def recall_spawn_result(conversation_id: str, tool_call_id: str) -> str | None:
    """What this spawn already returned, or ``None`` if it never finished."""
    return await redis_cache.client.get(_key(conversation_id, tool_call_id))
