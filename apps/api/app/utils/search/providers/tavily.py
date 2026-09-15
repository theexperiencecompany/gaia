"""Tavily AI search (https://tavily.com) — booster (1k req/mo free).

Uniquely returns an LLM-ready answer and inline images alongside results.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field
from tavily import TavilyClient

from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider


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


class TavilyProvider(SearchProvider):
    """Tavily AI search — booster with an LLM-ready answer + images (1k req/mo)."""

    name = "tavily"
    monthly_free_limit = 1_000

    def __init__(self) -> None:
        self._client: TavilyClient | None = None

    def is_configured(self) -> bool:
        """Return True when a Tavily API key is configured."""
        return bool(settings.TAVILY_API_KEY)

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        return self._client

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query Tavily (off the event loop) and map results to the shared shape."""
        # tavily-python is synchronous; off-load it so the event loop keeps moving.
        payload = _TavilyPayload.model_validate(
            await asyncio.to_thread(
                self._get_client().search,
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
