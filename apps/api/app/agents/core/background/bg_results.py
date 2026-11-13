"""Durable background-dispatch idempotency, keyed by conversation (Redis).

Results themselves go straight to the executor inbox on completion — no
collect call, no bucket. What stays here is the dispatch claim that keeps a
node replay from spawning the same background subagent twice.
"""

from app.constants.hil import HIL_BG_RESULTS_KEY_PREFIX, HIL_BG_RESULTS_TTL_SECONDS
from app.db.redis import redis_cache


def _dispatch_key(conversation_id: str, tool_call_id: str) -> str:
    return f"{HIL_BG_RESULTS_KEY_PREFIX}dispatch:{conversation_id}:{tool_call_id}"


async def try_claim_bg_dispatch(conversation_id: str, tool_call_id: str) -> bool:
    """Claim the one dispatch slot for a delegating tool call; False when a replay already did.

    A delegation sharing its node run with a pause re-runs when the pause resumes,
    and tool_call_id lives in the checkpointed AI message, so this SETNX makes
    spawning the subagent idempotent. True means first dispatch, proceed.
    """
    key = _dispatch_key(conversation_id, tool_call_id)
    return bool(await redis_cache.client.set(key, "1", nx=True, ex=HIL_BG_RESULTS_TTL_SECONDS))


async def release_bg_dispatch(conversation_id: str, tool_call_id: str) -> None:
    """Give a claim back when the dispatch it guarded was refused, so a replay decides afresh."""
    await redis_cache.client.delete(_dispatch_key(conversation_id, tool_call_id))
