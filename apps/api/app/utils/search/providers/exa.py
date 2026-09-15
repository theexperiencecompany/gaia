"""Exa neural search (https://exa.ai) — primary free workhorse (20k req/mo)."""

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider

_ENDPOINT = "https://api.exa.ai/search"
_TIMEOUT = 20.0
_MAX_TEXT_CHARS = 2000


class _ExaResult(BaseModel):
    """One Exa result.

    A result without a url is skipped rather than failing the whole page.
    """

    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    title: str | None = None
    text: str | None = None
    score: float | None = None
    publishedDate: str | None = None
    favicon: str | None = None


class _ExaPayload(BaseModel):
    """Exa ``/search`` response — only ``results`` is read."""

    model_config = ConfigDict(extra="ignore")

    results: list[_ExaResult] = Field(default_factory=list)


class ExaProvider(SearchProvider):
    """Exa neural search — primary free workhorse (20k req/mo)."""

    name = "exa"
    monthly_free_limit = 20_000

    def is_configured(self) -> bool:
        """Return True when an Exa API key is configured."""
        return bool(settings.EXA_API_KEY)

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query Exa and map results to the shared search shape."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _ENDPOINT,
                headers={"x-api-key": settings.EXA_API_KEY or ""},
                json={
                    "query": query,
                    "numResults": count,
                    "contents": {"text": {"maxCharacters": _MAX_TEXT_CHARS}},
                },
            )
            response.raise_for_status()
            payload = _ExaPayload.model_validate(response.json())
        results = [
            SearchResultItem(
                url=item.url,
                title=item.title or "",
                content=item.text or "",
                score=item.score if item.score is not None else 0.5,
                published_date=item.publishedDate or "",
                favicon=item.favicon or "",
            )
            for item in payload.results
            if item.url
        ]
        return SearchResponse(results=results, provider=self.name)
