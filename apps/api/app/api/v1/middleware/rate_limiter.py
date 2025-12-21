from slowapi import Limiter
from slowapi.util import get_remote_address

from app.db.redis import redis_cache

# Initialize limiter with default rate
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri=redis_cache.redis_url,
)
