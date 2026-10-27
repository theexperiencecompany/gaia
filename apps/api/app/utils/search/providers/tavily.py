"""Tavily AI search (https://tavily.com) — booster (1k req/mo free).

Uniquely returns an LLM-ready answer and inline images alongside results.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field
from tavily import TavilyClient

from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import CredentialSearchProvider


class _TavilyResult(BaseModel):
    """One Tavily result.

    A result without a url is skipped rather than failing the whole page.
    """

    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    title: str | None = None
    content: str | None = None
    score: float | None = None
    favicon: str | None = None


class _TavilyPayload(BaseModel):
    """TavilyClient.search response.

    Images are plain URLs because the request never asks for image descriptions.
    """

    model_config = ConfigDict(extra="ignore")

    results: list[_TavilyResult] = Field(default_factory=list)
    answer: str | None = None
    images: list[str] = Field(default_factory=list)


class TavilyProvider(CredentialSearchProvider):
    """Tavily AI search booster with an LLM-ready answer and images.

    The key resolves store-first with env fallback so a saved key applies
    without a restart; availability reads the cached snapshot synchronously.
    """

    name = "tavily"
    monthly_free_limit = 1_000

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query Tavily (off the event loop) and map results to the shared shape."""
        api_key = await self._credential()
        # tavily-python is synchronous; off-load it so the event loop keeps moving.
        payload = _TavilyPayload.model_validate(
            await asyncio.to_thread(
                TavilyClient(api_key=api_key).search,
                query=query,
                max_results=count,
                topic="general",
                include_images=True,
                include_favicon=True,
            )
        )
        results = [
            SearchResultItem(
                url=item.url,
                title=item.title or "",
                content=item.content or "",
                score=item.score if item.score is not None else 0.5,
                favicon=item.favicon or "",
            )
            for item in payload.results
            if item.url
        ]
        return SearchResponse(
            results=results,
            answer=payload.answer or "",
            images=payload.images,
            provider=self.name,
        )
