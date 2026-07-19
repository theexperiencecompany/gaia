"""Durable background-subagent results, keyed by conversation (Redis).

These outlive the process and the executor's HIL approval pause — unlike the
in-process ``StreamSession`` — so a result produced before the pause is still
collectible after the resume, which runs as a fresh dispatch under a new
``stream_id`` (hence conversation-keyed). Redis is the same durability tier the
executor busy lock already relies on across the pause.
"""

import json

from app.constants.hil import HIL_BG_RESULTS_KEY_PREFIX, HIL_BG_RESULTS_TTL_SECONDS
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log


def _key(conversation_id: str) -> str:
    return f"{HIL_BG_RESULTS_KEY_PREFIX}{conversation_id}"


async def append_bg_subagent_result(conversation_id: str, agent: str, result: str) -> None:
    """Append one background subagent's final result for this conversation."""
    key = _key(conversation_id)
    client = redis_cache.client
    await client.rpush(key, json.dumps({"agent": agent, "message": result}))
    await client.expire(key, HIL_BG_RESULTS_TTL_SECONDS)


async def try_claim_bg_dispatch(conversation_id: str, tool_call_id: str) -> bool:
    """One background dispatch per handoff tool call, durable across node replays.

    A ``handoff`` sharing its node run with ``wait_for_subagents`` re-runs when the
    join's interrupt is resumed; ``tool_call_id`` lives in the checkpointed AI message,
    so this SETNX makes the side effect (spawning the subagent) idempotent as the
    pre-interrupt code must be. ``True`` = first dispatch, proceed.
    """
    key = f"{HIL_BG_RESULTS_KEY_PREFIX}dispatch:{conversation_id}:{tool_call_id}"
    return bool(await redis_cache.client.set(key, "1", nx=True, ex=HIL_BG_RESULTS_TTL_SECONDS))


async def has_bg_subagent_results(conversation_id: str) -> bool:
    """Whether uncollected background subagent results exist (no drain)."""
    return bool(await redis_cache.client.llen(_key(conversation_id)))


async def drain_bg_subagent_results(conversation_id: str) -> list[dict[str, str]]:
    """Return and clear all collected background subagent results, oldest first."""
    key = _key(conversation_id)
    client = redis_cache.client
    async with client.pipeline(transaction=True) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        raw_items, _ = await pipe.execute()
    results: list[dict[str, str]] = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
        except (TypeError, ValueError):
            log.error(f"{LogTag.AGENT} Dropping malformed bg subagent result", raw=str(raw)[:200])
            continue
        if isinstance(item, dict) and "agent" in item and "message" in item:
            results.append({"agent": str(item["agent"]), "message": str(item["message"])})
    return results
