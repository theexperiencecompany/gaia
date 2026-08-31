from slowapi import Limiter
from slowapi.util import get_remote_address

from app.db.redis import redis_cache

# Redis-backed, not slowapi's in-memory default: every replica has to count
# against the same window, or an N-replica deployment silently allows N x the
# limit and the ceiling stops meaning anything.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri=redis_cache.redis_url,
)
