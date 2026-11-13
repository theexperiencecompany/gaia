"""Self-hosted SearXNG metasearch — the unlimited, free floor of the waterfall.

Requires a server address (Settings or SEARXNG_BASE_URL) and an instance with the JSON format enabled.
Because it runs on our own infrastructure it has no per-query cost and is never
budget-capped, so search can never incur a bill while it is reachable.
"""

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.services.providers.provider_credentials_service import ProviderConfig
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import CredentialSearchProvider

_TIMEOUT = 15.0


class _SearxngResult(BaseModel):
    """One SearXNG result.

    A result without a url is skipped rather than failing the whole page.
    """

    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    title: str | None = None
    content: str | None = None
    score: float | None = None
    publishedDate: str | None = None


class _SearxngPayload(BaseModel):
    """SearXNG ``/search?format=json`` response — only ``results`` is read."""

    model_config = ConfigDict(extra="ignore")

    results: list[_SearxngResult] | None = Field(default_factory=list)


class SearxngProvider(CredentialSearchProvider):
    """Self-hosted SearXNG — unlimited, free, last-resort metasearch."""

    name = "searxng"
    monthly_free_limit = None

    @staticmethod
    def credential_of(config: ProviderConfig) -> str | None:
        """Return the self-hosted instance's base URL; SearXNG has no key."""
        return config.base_url

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query the SearXNG JSON API and map results to the shared shape."""
        base_url = (await self._credential()).rstrip("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = _SearxngPayload.model_validate(response.json())
        results = [
            SearchResultItem(
                url=item.url,
                title=item.title or "",
                content=item.content or "",
                score=item.score if item.score is not None else 0.5,
                published_date=item.publishedDate or "",
            )
            for item in (payload.results or [])[:count]
            if item.url
        ]
        return SearchResponse(results=results, provider=self.name)
