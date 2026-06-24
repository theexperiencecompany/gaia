"""Tavily AI search (https://tavily.com) — booster (1k req/mo free).

Uniquely returns an LLM-ready ``answer`` and inline images alongside results.
"""

import asyncio

from tavily import TavilyClient

from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider


class TavilyProvider(SearchProvider):
    name = "tavily"
    monthly_free_limit = 1_000

    def __init__(self) -> None:
        self._client: TavilyClient | None = None

    def is_configured(self) -> bool:
        return bool(settings.TAVILY_API_KEY)

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        return self._client

    async def search(self, query: str, count: int) -> SearchResponse:
        # tavily-python is synchronous; off-load it so the event loop keeps moving.
        payload = await asyncio.to_thread(
            self._get_client().search,
            query=query,
            max_results=count,
            topic="general",
            include_images=True,
            include_favicon=True,
        )
        results = [
            SearchResultItem(
                url=item["url"],
                title=item.get("title") or "",
                content=item.get("content") or "",
                score=item["score"] if item.get("score") is not None else 0.5,
                favicon=item.get("favicon") or "",
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]
        return SearchResponse(
            results=results,
            answer=payload.get("answer") or "",
            images=[str(image) for image in payload.get("images", [])],
            provider=self.name,
        )
