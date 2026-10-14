"""The provider abstraction behind the search waterfall."""

from abc import ABC, abstractmethod
from typing import ClassVar, Literal

from app.services.providers.provider_credentials_service import resolve, resolved_config
from app.utils.search.models import SearchResponse


class SearchProvider(ABC):
    """A single search backend.

    name doubles as the budget/registry key. monthly_free_limit is the
    free upstream-call allowance per calendar month, or None when the backend
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


class CredentialSearchProvider(SearchProvider):
    """A backend whose credential resolves through the credential store under its name.

    Store-first with env fallback where runtime credentials exist, env alone
    elsewhere; availability reads the synchronous snapshot, a search re-resolves.
    """

    credential_field: ClassVar[Literal["api_key", "base_url"]] = "api_key"

    def is_configured(self) -> bool:
        """Report whether the store or env holds this provider's credential."""
        config = resolved_config(self.name)
        return bool(config and config[self.credential_field])

    async def _credential(self) -> str:
        """Return the credential this search runs with; raise when it vanished after the gate."""
        config = await resolve(self.name)
        credential = config[self.credential_field] if config else None
        if not credential:
            raise RuntimeError(f"{self.name} is not configured. Add it in Settings → Providers.")
        return credential
