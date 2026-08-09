"""Redis-backed live-fact counter for the free-plan memory cap.

The authoritative live count is a Postgres ``COUNT`` over a user's active
memories (latest, not forgotten, not expired — see
``pg_store.count_live_memories``). Running it on every passive-ingestion turn
is wasteful when a free user sits far below the 50-fact cap, so this module
keeps a per-user Redis counter that mirrors that count: every memory mutation
adjusts it by a delta, and a read far below the cap needs only the Redis hit.

The counter is an OPTIMISTIC cache, never the source of truth:

- ``forget_after`` expiry drops facts from the live set with no mutation, so
  the cached value can drift ABOVE the real count. That is the safe direction
  for a cap — it only ever makes the remaining budget look smaller, never
  larger, so it can never admit a batch that overshoots the cap.
- ``adjust_live_count`` only mutates a key that already exists. A missing key
  is left missing so the next read re-initializes it from the authoritative
  ``COUNT`` (which already reflects the mutation, applied in Postgres first),
  rather than being created at a bare delta that would under-count.
- Every key carries a 24h TTL, so any residual drift self-heals.

The enforcement path (``ingestion._free_cap_remaining``) still falls back to
the authoritative ``COUNT`` whenever the cached budget is close enough to the
cap that a batch might cross it, keeping the cap exact per batch. Concurrent
same-user batches are not serialized (enforcement is fail-open by design), so
a small transient overshoot is possible before growth stops converging back
at the cap.

Redis-unavailable is not fatal: reads return ``None`` (a miss, so the caller
COUNTs) and writes no-op. The cap stays exact by falling back to Postgres.
"""

from app.constants.memory import MEMORY_LIVE_COUNT_CACHE_KEY, MEMORY_LIVE_COUNT_CACHE_TTL
from app.db.redis import redis_cache
from shared.py.wide_events import log

# Atomically add a delta to the counter, but ONLY if it already exists, then
# refresh its TTL. A missing key returns -1 and is left absent so the next read
# re-initializes it authoritatively. The value is clamped at 0 so an over-eager
# decrement (drift) can never make the counter negative.
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
    """The cached live-fact count, or ``None`` on a miss or Redis outage.

    ``None`` tells the caller to fall back to the authoritative ``COUNT`` — it
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
