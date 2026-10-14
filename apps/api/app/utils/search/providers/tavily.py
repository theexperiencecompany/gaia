"""Tavily AI search (https://tavily.com) — booster (1k req/mo free).

Uniquely returns an LLM-ready answer and inline images alongside results.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field
from tavily import TavilyClient

from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolve,
    resolved_config,
)
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
    """Tavily AI search booster with an LLM-ready answer and images.

    The key resolves store-first with env fallback so a saved key applies
    without a restart; availability reads the cached snapshot synchronously.
    """

    name = "tavily"
    monthly_free_limit = 1_000

    def __init__(self) -> None:
        self._client: TavilyClient | None = None
        self._client_api_key: str | None = None

    def is_configured(self) -> bool:
        """Report whether a Tavily API key is configured (env or credential store).

        The store leg matters: on a self-host instance the key is saved through
        Settings, so an env-only check reports the engine unconfigured and the
        whole search chain silently skips it.
        """
        # resolved_config, not the LLM client's alias of it: app.utils must
        # never import app.agents (model-stack layer contract) — and both read
        # the same snapshot dict.
        config: ProviderConfig | None = resolved_config(self.name)
        return bool(config and config.get("api_key"))

    async def _active_api_key(self) -> str | None:
        """Return the key this search should run with; the service's 60s TTL keeps it off Mongo."""
        config: ProviderConfig | None = await resolve(self.name)
        return config.get("api_key") if config else None

    def _get_client(self, api_key: str) -> TavilyClient:
        if self._client is None or self._client_api_key != api_key:
            self._client_api_key = api_key
            self._client = TavilyClient(api_key=api_key)
        return self._client

    async def search(self, query: str, count: int) -> SearchResponse:
        """Query Tavily (off the event loop) and map results to the shared shape."""
        api_key = await self._active_api_key()
        if api_key is None:
            # The engine gates on is_configured(); reaching here means the key
            # vanished mid-flight. Fail loud rather than send an unauthenticated
            # request.
            raise RuntimeError("Tavily API key not configured. Set it in Settings → AI Providers.")
        # tavily-python is synchronous; off-load it so the event loop keeps moving.
        payload = _TavilyPayload.model_validate(
            await asyncio.to_thread(
                self._get_client(api_key).search,
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
