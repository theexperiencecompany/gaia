"""The one place the cached plan tier is dropped.

The gate reads ``get_cached_plan_type`` (five-minute TTL); every path that
changes a user's subscription must drop the key, or a user who just paid is
told to pay again until the cache expires.
"""

from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX
from app.db.redis import redis_cache
from shared.py.wide_events import log


async def invalidate_plan_cache(user_id: str) -> None:
    """Drop ``user_id``'s cached plan tier so the next gate read is fresh."""
    await redis_cache.delete(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}")
    # On the event rather than a line of its own — this runs on every billing
    # change, and the question it answers ("did the bust actually run, and for
    # whom") only ever gets asked about a user who is still being paywalled.
    # The id matters most on the webhook paths, which have no authenticated
    # request for the middleware to attribute to.
    log.set(user={"id": user_id}, payment={"plan_cache_dropped": True})
