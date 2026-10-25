"""Search provider implementations and the default waterfall ordering."""

from app.config.settings import settings
from app.utils.search.providers.base import SearchProvider
from app.utils.search.providers.brave import BraveProvider
from app.utils.search.providers.duckduckgo import DuckDuckGoProvider
from app.utils.search.providers.exa import ExaProvider
from app.utils.search.providers.searxng import SearxngProvider
from app.utils.search.providers.tavily import TavilyProvider


def default_providers() -> list[SearchProvider]:
    """Waterfall order: budget-capped APIs first, then the keyless and self-hosted floors.

    The capped APIs auto-stop at their free limits, so they can't bill. A self-host
    tries its own SearXNG before keyless DuckDuckGo, which then is the last resort;
    elsewhere DuckDuckGo comes first and the unlimited SearXNG is the final floor.
    """
    floors: list[SearchProvider] = [DuckDuckGoProvider(), SearxngProvider()]
    if settings.deployment.searxng_before_duckduckgo:
        floors.reverse()
    return [ExaProvider(), TavilyProvider(), BraveProvider(), *floors]


__all__ = [
    "BraveProvider",
    "DuckDuckGoProvider",
    "ExaProvider",
    "SearchProvider",
    "SearxngProvider",
    "TavilyProvider",
    "default_providers",
]
