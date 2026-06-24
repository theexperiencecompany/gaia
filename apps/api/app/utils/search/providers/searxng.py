"""Self-hosted SearXNG metasearch — the unlimited, free floor of the waterfall.

Requires ``SEARXNG_BASE_URL`` and an instance with the JSON format enabled.
Because it runs on our own infrastructure it has no per-query cost and is never
budget-capped, so search can never incur a bill while it is reachable.
"""

import httpx

from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider

_TIMEOUT = 15.0


class SearxngProvider(SearchProvider):
    """Self-hosted SearXNG — unlimited, free, last-resort metasearch."""

    name = "searxng"
    monthly_free_limit = None

    def is_configured(self) -> bool:
        """True when a SearXNG base URL is configured."""
        return bool(settings.SEARXNG_BASE_URL)

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query the SearXNG JSON API and map results to the shared shape."""
        base_url = (settings.SEARXNG_BASE_URL or "").rstrip("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        results = [
            SearchResultItem(
                url=item["url"],
                title=item.get("title") or "",
                content=item.get("content") or "",
                score=item["score"] if item.get("score") is not None else 0.5,
                published_date=item.get("publishedDate") or "",
            )
            for item in (payload.get("results") or [])[:count]
            if item.get("url")
        ]
        return SearchResponse(results=results, provider=self.name)
