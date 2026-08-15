"""Cluster-wide cap on concurrent browser sessions.

Each session is a real Chromium instance, so unbounded concurrency thrashes the
Steel container. The cap is enforced against a Redis sorted set (the single
source of truth across workers/replicas) so it holds no matter how the API is
scaled. Admission is a single atomic Lua step (prune expired → count → add) so
concurrent acquires can't race past the limit. This fails fast when the cap is
reached rather than queueing — a browser task is long, so the user is told to
retry rather than wait silently. A crashed worker's slot self-heals: its member
carries an expiry deadline as its score and is pruned on the next acquire.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import uuid

from app.config.settings import settings
from app.constants.browser import BROWSER_ACTIVE_SESSIONS_KEY
from app.db.redis import redis_cache
from app.services.browser.exceptions import BrowserConcurrencyLimit

# Atomically prune expired members, then admit only if below the cap.
# Returns 1 when a slot was reserved, 0 when the cap is already reached.
_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, now + ttl, member)
return 1
"""

# Backstop lifetime for a leaked slot (worker crash). Longer than any single
# task can run, so a live task is never evicted; a crashed one frees by itself.
_SLOT_TTL_SECONDS = settings.BROWSER_USE_SESSION_TTL_SECONDS


@asynccontextmanager
async def session_slot() -> AsyncIterator[None]:
    """Reserve one of the ``BROWSER_USE_MAX_CONCURRENT_SESSIONS`` slots.

    Raises :class:`BrowserConcurrencyLimit` when the cluster is already at the
    cap. The slot is always released on exit.
    """
    redis = redis_cache.client
    slot_id = uuid.uuid4().hex
    now_seconds = (await redis.time())[0]

    admitted = await redis.eval(
        _ACQUIRE_SCRIPT,
        1,
        BROWSER_ACTIVE_SESSIONS_KEY,
        str(now_seconds),
        str(_SLOT_TTL_SECONDS),
        str(settings.BROWSER_USE_MAX_CONCURRENT_SESSIONS),
        slot_id,
    )
    if not admitted:
        raise BrowserConcurrencyLimit(
            "Too many browser tasks are running right now. Please try again in a bit."
        )

    try:
        yield
    finally:
        await redis.zrem(BROWSER_ACTIVE_SESSIONS_KEY, slot_id)
