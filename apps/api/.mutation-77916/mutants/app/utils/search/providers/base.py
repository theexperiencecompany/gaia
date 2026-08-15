"""The provider abstraction behind the search waterfall."""

from abc import ABC, abstractmethod

from app.utils.search.models import SearchResponse


class SearchProvider(ABC):
    """A single search backend.

    ``name`` doubles as the budget/registry key. ``monthly_free_limit`` is the
    free upstream-call allowance per calendar month, or ``None`` when the backend
    is self-hosted and effectively unlimited.
    """

    name: str
    monthly_free_limit: int | None = None

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the credentials / base URL this provider needs are present."""

    @abstractmethod
    async def search(self, query: str, count: int) -> SearchResponse:
        """Run one search, raising on transport/API errors so the engine fails over."""
