"""Per-conversation record of in-context activated integrations.

activate_integration stamps the integrations it loads; retrieve_tools discovery
reads the set and searches those namespaces too, so tools beyond the preloaded
subset are discoverable from the activating run. Without this, activation's "use
retrieve_tools for the rest" points at a dead end: discovery otherwise searches
only the caller's own tool space.

Storage only — namespace mapping lives with the reader. Stamped solely on the
successful-activation path (which gates on the connection check), so a member
implies the user is entitled to it; custom MCPs never stamp (they route to
handoff instead). Every Redis absence degrades to "nothing active" with a
warning rather than failing the caller.
"""

from app.constants.cache import ACTIVATION_ACTIVE_PREFIX, ACTIVATION_ACTIVE_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log


def _key(conversation_id: str) -> str:
    return f"{ACTIVATION_ACTIVE_PREFIX}{conversation_id}"


async def mark_active(conversation_id: str, integration_id: str) -> None:
    """Record an activated integration for its conversation, refreshing the TTL."""
    client = redis_cache.client
    if client is None:
        log.warning(
            f"{LogTag.AGENT} Activation stamp dropped: no Redis client",
            integration_id=integration_id,
        )
        return
    key = _key(conversation_id)
    await client.sadd(key, integration_id)
    await client.expire(key, ACTIVATION_ACTIVE_TTL)


async def get_active(conversation_id: str | None) -> set[str]:
    """Integration ids activated in this conversation, or empty when unknown."""
    if not conversation_id:
        return set()
    client = redis_cache.client
    if client is None:
        return set()
    try:
        members = await client.smembers(_key(conversation_id))
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Active integrations unreadable; degrading to none",
            error_type=type(e).__name__,
        )
        return set()
    # The client is built with decode_responses=True (see AsyncRedisCommands),
    # so members arrive as str.
    return set(members)
