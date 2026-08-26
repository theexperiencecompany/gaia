"""Tavily AI search (https://tavily.com) — booster (1k req/mo free).

Uniquely returns an LLM-ready ``answer`` and inline images alongside results.
"""

import asyncio
import importlib
from typing import TYPE_CHECKING, cast

from tavily import TavilyClient

from app.agents.llm.client import runtime_provider_config
from app.config.settings import settings
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.services.providers.provider_credentials_service import ProviderConfig


class TavilyProvider(SearchProvider):
    """Tavily AI search — booster with an LLM-ready answer + images (1k req/mo).

    The active API key follows the runtime credential service (store entry →
    ``TAVILY_API_KEY`` env fallback), so a key saved in Settings takes effect
    without a restart. Availability additionally reads the runtime snapshot the
    LLM refresh keeps warm — ``is_configured`` must stay synchronous, and env
    alone answers before the first refresh.
    """

    name = "tavily"
    monthly_free_limit = 1_000

    def __init__(self) -> None:
        self._client: TavilyClient | None = None
        self._client_api_key: str | None = None

    def is_configured(self) -> bool:
        """True when a Tavily API key is configured (env or credential store)."""
        if settings.TAVILY_API_KEY:
            return True
        config = runtime_provider_config(self.name)
        return bool(config and config.get("api_key"))

    async def _active_api_key(self) -> str | None:
        """The key this search should run with, resolved fresh (the service's
        60s TTL keeps this off Mongo in steady state). Lazily imported through
        the module to match the LLM client's cycle-avoidance pattern."""
        service = importlib.import_module("app.services.providers.provider_credentials_service")
        resolve = cast("Callable[[str], Awaitable[ProviderConfig | None]]", service.resolve)
        config = await resolve(self.name)
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
        payload = await asyncio.to_thread(
            self._get_client(api_key).search,
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
