"""Brave Search API (https://brave.com/search/api) — booster on its own index.

~$5 of free credit per month (~1k queries); budget-capped so it never bills.
"""

import httpx

from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT = 15.0
_MAX_COUNT = 20


class BraveProvider(SearchProvider):
    name = "brave"
    monthly_free_limit = 1_000

    def is_configured(self) -> bool:
        return bool(settings.BRAVE_API_KEY)

    async def search(self, query: str, count: int) -> SearchResponse:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                _ENDPOINT,
                headers={
                    "X-Subscription-Token": settings.BRAVE_API_KEY or "",
                    "Accept": "application/json",
                },
                params={"q": query, "count": min(count, _MAX_COUNT)},
            )
            response.raise_for_status()
            payload = response.json()
        web_results = (payload.get("web") or {}).get("results", [])
        results = [
            SearchResultItem(
                url=item["url"],
                title=item.get("title") or "",
                content=item.get("description") or "",
                published_date=item.get("age") or "",
                favicon=(item.get("meta_url") or {}).get("favicon") or "",
            )
            for item in web_results
            if item.get("url")
        ]
        return SearchResponse(results=results, provider=self.name)
