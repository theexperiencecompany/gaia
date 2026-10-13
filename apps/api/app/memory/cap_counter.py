"""Redis-backed live-fact counter for the free-plan memory cap.

The authoritative count is a Postgres COUNT over a user's active memories
(see pg_store.count_live_memories); this per-user Redis counter mirrors it so
a read far below the 50-fact cap needs only a Redis hit, not a COUNT.

The counter is an OPTIMISTIC cache, never the source of truth: forget_after
expiry can drift it ABOVE the real count (the safe direction — it only
shrinks the apparent remaining budget), adjust_live_count only mutates a key
that already exists (a missing key re-initializes from Postgres on next read,
never from a bare delta), and every key carries a 24h TTL to self-heal.

Enforcement (ingestion._free_cap_remaining) falls back to the authoritative
COUNT whenever the cached budget is close enough to the cap to matter.
Redis-unavailable reads return None (a miss) and writes no-op.
"""

from app.constants.memory import MEMORY_LIVE_COUNT_CACHE_KEY, MEMORY_LIVE_COUNT_CACHE_TTL
from app.db.redis import redis_cache
from shared.py.wide_events import log

# Atomically add a delta to the counter, only if it already exists, then
# refresh its TTL. A missing key returns -1 and is left absent; the result is
# clamped at 0 so an over-eager decrement can never go negative.
_ADJUST_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return -1
end
local value = redis.call('INCRBY', KEYS[1], ARGV[1])
if value < 0 then
    value = 0
    redis.call('SET', KEYS[1], 0)
end
redis.call('EXPIRE', KEYS[1], ARGV[2])
return value
"""


def _key(user_id: str) -> str:
    return MEMORY_LIVE_COUNT_CACHE_KEY.format(user_id=user_id)


async def get_cached_live_count(user_id: str) -> int | None:
    """Return the cached live-fact count, or None on a miss or Redis outage.

    None tells the caller to fall back to the authoritative COUNT — it
    never means "zero".
    """
    client = redis_cache.redis
    if client is None:
        return None
    try:
        raw = await client.get(_key(user_id))
    except Exception as e:
        log.warning(
            "Memory live-count read failed (treating as miss)",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Corrupt value — treat as a miss so the next read re-COUNTs.
        return None


async def set_cached_live_count(user_id: str, count: int) -> None:
    """Seed the counter with an authoritative value (best-effort)."""
    client = redis_cache.redis
    if client is None:
        return
    try:
        await client.set(_key(user_id), str(count), ex=MEMORY_LIVE_COUNT_CACHE_TTL)
    except Exception as e:
        log.warning(
            "Memory live-count seed failed",
            error=str(e),
            error_type=type(e).__name__,
        )


async def adjust_live_count(user_id: str, delta: int) -> None:
    """Apply a signed delta to the cached counter if it is present.

    Called after every memory mutation. A no-op when the key is absent (paid
    users never seed it; a free user's key re-seeds authoritatively on the next
    read) or when Redis is unavailable.
    """
    if delta == 0:
        return
    client = redis_cache.redis
    if client is None:
        return
    try:
        await client.eval(
            _ADJUST_SCRIPT, 1, _key(user_id), str(delta), str(MEMORY_LIVE_COUNT_CACHE_TTL)
        )
    except Exception as e:
        log.warning(
            "Memory live-count adjust failed",
            delta=delta,
            error=str(e),
            error_type=type(e).__name__,
        )
