"""Redis-backed monthly free-tier budgets for paid search providers.

Each budget-capped provider gets a per-calendar-month counter. The engine checks
``has_headroom`` before calling a provider and records the call after a successful
upstream request, so a provider is never used beyond its free allowance — the
self-hosted floor (SearXNG/DuckDuckGo) carries everything past that point.
"""

from datetime import UTC, datetime

from app.db.redis import redis_cache
from shared.py.wide_events import log

_TTL_SECONDS = 35 * 24 * 60 * 60  # ~35 days: outlives any single calendar month


class FreeTierBudget:
    """Tracks monthly upstream-call usage against each provider's free allowance."""

    def __init__(self, limits: dict[str, int]) -> None:
        self._limits = limits

    def _key(self, provider: str) -> str:
        return f"search_budget:{provider}:{datetime.now(UTC):%Y%m}"

    async def has_headroom(self, provider: str) -> bool:
        """True if the provider still has free-tier calls left this month (or is uncapped)."""
        limit = self._limits.get(provider)
        if not limit:
            return True
        try:
            used_raw = await redis_cache.get(self._key(provider))
            used = int(used_raw) if used_raw else 0
        except Exception:
            # Fail open: a Redis hiccup or a malformed counter must not disable search.
            return True
        return used < limit

    async def record_call(self, provider: str) -> None:
        """Count one real upstream call against the provider's monthly allowance."""
        if provider not in self._limits:
            return
        client = redis_cache.redis
        if client is None:
            return
        try:
            key = self._key(provider)
            await client.incr(key)
            await client.expire(key, _TTL_SECONDS)
        except Exception as e:
            log.warning(f"Search budget update failed for {provider}: {e}")
