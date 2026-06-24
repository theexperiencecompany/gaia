"""Multi-provider web search with automatic failover and free-tier budgets.

Provider order (each falls through on error or empty results):
    Exa (20k/mo free) -> SearXNG (self-hosted, unlimited) -> Tavily (1k/mo)
    -> Brave ($5 credit) -> DuckDuckGo (no key, last resort)

Budget-capped providers stop before exceeding their free allowance, so the
self-hosted floor means search can never incur a bill. ``perform_search`` and
``search_for_research`` are the cached, dict-returning entry points the agent
tools and API use; ``web_search`` exposes the typed response for new callers.
"""

from app.constants.cache import WEB_SEARCH_CACHE_TTL
from app.decorators.caching import Cacheable
from app.utils.search.engine import SearchEngine
from app.utils.search.models import SearchResponse

_engine = SearchEngine()


async def web_search(query: str, count: int) -> SearchResponse:
    """Run the provider waterfall and return the typed response."""
    return await _engine.search(query, count)


@Cacheable(key_pattern="search:{query}:{count}", ttl=WEB_SEARCH_CACHE_TTL, namespace="search")
async def perform_search(query: str, count: int) -> dict:
    """Web search returning the legacy web/news/images/answer wire dict (cached)."""
    response = await web_search(query, count)
    return {
        "web": [item.model_dump() for item in response.results],
        "news": [],
        "images": response.images,
        "answer": response.answer,
        "query": query,
        "response_time": 0,
        "request_id": "",
        "provider": response.provider,
    }


@Cacheable(
    key_pattern="research_search:{query}:{count}",
    ttl=WEB_SEARCH_CACHE_TTL,
    namespace="search",
)
async def search_for_research(query: str, count: int = 5) -> dict:
    """Web search for the deep-research pipeline; returns ``{"results": [...]}`` (cached)."""
    response = await web_search(query, count)
    return {"results": [item.model_dump() for item in response.results]}


__all__ = ["SearchResponse", "perform_search", "search_for_research", "web_search"]
