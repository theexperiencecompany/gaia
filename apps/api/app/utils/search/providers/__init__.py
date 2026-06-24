"""Search provider implementations and the default waterfall ordering."""

from app.utils.search.providers.base import SearchProvider
from app.utils.search.providers.brave import BraveProvider
from app.utils.search.providers.duckduckgo import DuckDuckGoProvider
from app.utils.search.providers.exa import ExaProvider
from app.utils.search.providers.searxng import SearxngProvider
from app.utils.search.providers.tavily import TavilyProvider


def default_providers() -> list[SearchProvider]:
    """Waterfall order: premium/free-credit APIs first, self-hosted SearXNG last.

    Exa → Tavily → Brave → DuckDuckGo → SearXNG. The budget-capped APIs are tried
    first (they auto-stop at their free limits, so they can't bill), and the
    unlimited self-hosted SearXNG is the final guaranteed fallback.
    """
    return [
        ExaProvider(),
        TavilyProvider(),
        BraveProvider(),
        DuckDuckGoProvider(),
        SearxngProvider(),
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
