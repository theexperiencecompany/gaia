"""Brave Search API (https://brave.com/search/api) — booster on its own index.

~$5 of free credit per month (~1k queries); budget-capped so it never bills.
"""

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import CredentialSearchProvider

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT = 15.0
_MAX_COUNT = 20
_AUTH_HEADER = "X-Subscription-Token"


class _BraveMetaUrl(BaseModel):
    """The ``meta_url`` block of a Brave web result (only the favicon is read)."""

    model_config = ConfigDict(extra="ignore")

    favicon: str | None = None


class _BraveResult(BaseModel):
    """One Brave web result.

    A result without a url is skipped rather than failing the whole page.
    """

    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    title: str | None = None
    description: str | None = None
    age: str | None = None
    meta_url: _BraveMetaUrl | None = None


class _BraveWeb(BaseModel):
    """The ``web`` section of a Brave search response."""

    model_config = ConfigDict(extra="ignore")

    results: list[_BraveResult] = Field(default_factory=list)


class _BravePayload(BaseModel):
    """Brave ``/res/v1/web/search`` response — only the web results are read."""

    model_config = ConfigDict(extra="ignore")

    web: _BraveWeb | None = None


class BraveProvider(CredentialSearchProvider):
    """Brave Search API — booster on Brave's own index ($5 credit/mo)."""

    name = "brave"
    monthly_free_limit = 1_000

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query Brave and map results to the shared search shape."""
        api_key = await self._credential()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                _ENDPOINT,
                headers={
                    _AUTH_HEADER: api_key,
                    "Accept": "application/json",
                },
                params={"q": query, "count": min(count, _MAX_COUNT)},
            )
            response.raise_for_status()
            payload = _BravePayload.model_validate(response.json())
        web_results = payload.web.results if payload.web else []
        results = [
            SearchResultItem(
                url=item.url,
                title=item.title or "",
                content=item.description or "",
                published_date=item.age or "",
                favicon=(item.meta_url.favicon if item.meta_url else None) or "",
            )
            for item in web_results
            if item.url
        ]
        return SearchResponse(results=results, provider=self.name)
