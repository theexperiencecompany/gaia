"""Per-conversation executor resume slot (Redis).

A batch pause has several approvals sharing one executor thread; two decisions
landing close together must not start two concurrent LangGraph runs on it
(checkpoint corruption). ``resolution`` claims the slot before dispatching a
resume; the dispatched run releases it when it finalizes (completes, errors, or
pauses again). A decision that loses the claim skips dispatch — it is already
durable on its record, and the in-flight join round or the sweep collects it.
"""

from app.constants.hil import HIL_RESUME_ACTIVE_KEY_PREFIX, HIL_RESUME_ACTIVE_TTL_SECONDS
from app.db.redis import redis_cache


def _key(conversation_id: str) -> str:
    return f"{HIL_RESUME_ACTIVE_KEY_PREFIX}{conversation_id}"


async def claim_resume_dispatch(conversation_id: str) -> bool:
    """SETNX claim. TTL is crash insurance only (aligned with the busy-lock TTL)."""
    return bool(
        await redis_cache.client.set(
            _key(conversation_id), "1", nx=True, ex=HIL_RESUME_ACTIVE_TTL_SECONDS
        )
    )


async def release_resume_dispatch(conversation_id: str) -> None:
    """Free the slot. Safe when unset; at most one executor run exists per
    conversation (busy lock), so an unconditional delete cannot hit another run's
    claim."""
    await redis_cache.client.delete(_key(conversation_id))
