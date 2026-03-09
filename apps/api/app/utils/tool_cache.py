"""Redis-backed cache decorator for CUSTOM_GATHER_CONTEXT tool results."""

import functools
import hashlib
import json
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from shared.py.wide_events import log

F = TypeVar("F", bound=Callable[..., Awaitable[Dict[str, Any]]])

_DEFAULT_TTL = 300  # 5 minutes


def cache_gather_context(ttl: int = _DEFAULT_TTL) -> Callable[[F], F]:
    """Decorator that caches CUSTOM_GATHER_CONTEXT results in Redis.

    Keyed by toolkit name + user identifier extracted from auth_credentials.
    Falls through to the original function on any cache error.

    Args:
        ttl: Cache TTL in seconds (default: 300 / 5 minutes)
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            log.set(
                operation="cache_gather_context",
                tool_func=func.__qualname__,
                cache_ttl=ttl,
            )
            cache_key = _build_cache_key(func.__qualname__, auth_credentials)
            redis_client = _get_redis_client()

            if redis_client is not None and cache_key:
                try:
                    cached = await redis_client.get(cache_key)
                    if cached:
                        return json.loads(cached)  # type: ignore[no-any-return]
                except Exception as exc:
                    log.debug("Cache read miss for %s: %s", cache_key, exc)

            result: Dict[str, Any] = await func(
                request, execute_request, auth_credentials
            )

            if redis_client is not None and cache_key:
                try:
                    await redis_client.setex(cache_key, ttl, json.dumps(result))
                except Exception as exc:
                    log.debug("Cache write failed for %s: %s", cache_key, exc)

            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _build_cache_key(func_name: str, auth_credentials: Dict[str, Any]) -> Optional[str]:
    """Build a stable cache key from the function name and user token hash."""
    token = auth_credentials.get("access_token", "")
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    return f"tool_cache:{func_name}:{token_hash}"


def _get_redis_client() -> Optional[Any]:
    """Get the async Redis client from the app's DB layer, returning None on failure."""
    try:
        from app.db.redis import redis_cache

        return redis_cache.redis
    except Exception:
        return None
