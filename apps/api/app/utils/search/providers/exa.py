"""Exa neural search (https://exa.ai) — primary free workhorse (20k req/mo)."""

import httpx

from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider

_ENDPOINT = "https://api.exa.ai/search"
_TIMEOUT = 20.0
_MAX_TEXT_CHARS = 2000


class ExaProvider(SearchProvider):
    """Exa neural search — primary free workhorse (20k req/mo)."""

    name = "exa"
    monthly_free_limit = 20_000

    def is_configured(self) -> bool:
        """True when an Exa API key is configured."""
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
            payload = response.json()
        results = [
            SearchResultItem(
                url=item["url"],
                title=item.get("title") or "",
                content=item.get("text") or "",
                score=item["score"] if item.get("score") is not None else 0.5,
                published_date=item.get("publishedDate") or "",
                favicon=item.get("favicon") or "",
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]
        return SearchResponse(results=results, provider=self.name)
