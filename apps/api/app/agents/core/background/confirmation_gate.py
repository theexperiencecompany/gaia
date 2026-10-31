"""Who may say an irreversible action is approved: only a user answering GAIA's own question.

Comms sets call_executor's irreversible_approved, and a model reads "delete all
my todos" as its own approval often enough (measured on gpt-5.6-luna: it set the
flag on the first turn and the todos were gone). So the flag is honoured only
when the previous executor run in this conversation ended asking the user to
confirm. That ask is recorded here at finalize and spent by the next dispatch.
"""

from app.constants.cache import AWAITING_CONFIRMATION_PREFIX, AWAITING_CONFIRMATION_TTL
from app.db.redis import redis_cache


def _key(conversation_id: str) -> str:
    return f"{AWAITING_CONFIRMATION_PREFIX}{conversation_id}"


async def record_confirmation_asked(conversation_id: str) -> None:
    """Note that this conversation's executor just asked the user to confirm."""
    if redis_cache.client:
        await redis_cache.client.set(_key(conversation_id), "1", ex=AWAITING_CONFIRMATION_TTL)


async def spend_confirmation(conversation_id: str) -> bool:
    """Return whether a confirmation was pending, consuming it.

    Fails closed: without Redis no approval can be proven, so none is granted.
    """
    if not redis_cache.client:
        return False
    return bool(await redis_cache.client.getdel(_key(conversation_id)))
