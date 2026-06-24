"""Search provider implementations and the default waterfall ordering."""

from app.utils.search.providers.base import SearchProvider
from app.utils.search.providers.brave import BraveProvider
from app.utils.search.providers.duckduckgo import DuckDuckGoProvider
from app.utils.search.providers.exa import ExaProvider
from app.utils.search.providers.searxng import SearxngProvider
from app.utils.search.providers.tavily import TavilyProvider


def default_providers() -> list[SearchProvider]:
    """Waterfall order: free workhorse → unlimited self-hosted floor → boosters → last resort."""
    return [
        ExaProvider(),
        SearxngProvider(),
        TavilyProvider(),
        BraveProvider(),
        DuckDuckGoProvider(),
    ]


__all__ = [
    "BraveProvider",
    "DuckDuckGoProvider",
    "ExaProvider",
    "SearchProvider",
    "SearxngProvider",
    "TavilyProvider",
    "default_providers",
]
