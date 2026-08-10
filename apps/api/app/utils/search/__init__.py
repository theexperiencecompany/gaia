"""Multi-provider web search with automatic failover and free-tier budgets.

Provider order (each falls through on error or empty results):
    Exa (20k/mo free) -> Tavily (1k) -> Brave ($5 credit) -> DuckDuckGo
    -> SearXNG (self-hosted, unlimited last resort)

Budget-capped providers stop before exceeding their free allowance, so the
self-hosted floor means search can never incur a bill. ``perform_search`` and
``search_for_research`` are the cached entry points the agent tools and the
search API use — ``perform_search`` returns a typed ``WebSearchResult``,
``search_for_research`` returns a dict[str, Any] wire shape.
"""

from typing import Any

from app.constants.cache import WEB_SEARCH_CACHE_TTL
from app.decorators.caching import Cacheable
from app.utils.search.engine import SearchEngine
from app.utils.search.models import SearchResponse, WebSearchResult

__all__ = ["SearchResponse", "WebSearchResult", "perform_search", "search_for_research"]


@Cacheable(
    key_pattern="search:{query}:{count}",
    ttl=WEB_SEARCH_CACHE_TTL,
    namespace="search",
    model=WebSearchResult,
)
async def perform_search(query: str, count: int) -> WebSearchResult:
    """Run the waterfall and return the web/images/answer result (cached)."""
    response = await SearchEngine().search(query, count)
    return WebSearchResult(
        web=response.results,
        images=response.images,
        answer=response.answer,
        query=query,
        provider=response.provider,
    )


@Cacheable(
    key_pattern="research_search:{query}:{count}",
    ttl=WEB_SEARCH_CACHE_TTL,
    namespace="search",
)
async def search_for_research(query: str, count: int = 5) -> dict[str, Any]:
    """Run the waterfall for deep research; returns ``{"results": [...]}`` (cached)."""
    response = await SearchEngine().search(query, count)
    return {"results": [item.model_dump() for item in response.results]}
