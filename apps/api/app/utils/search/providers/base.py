"""The provider abstraction behind the search waterfall."""

from abc import ABC, abstractmethod

from app.constants.providers import CredentialProviderName
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolve,
    resolved_config,
)
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

    @staticmethod
    def credential_of(config: ProviderConfig) -> str | None:
        """Return the field of a resolved config this backend dials with: its API key."""
        return config.api_key

    def is_configured(self) -> bool:
        """Report whether the store or env holds this provider's credential."""
        config = resolved_config(CredentialProviderName(self.name))
        return bool(config and self.credential_of(config))

    async def _credential(self) -> str:
        """Return the credential this search runs with; raise when it vanished after the gate."""
        config = await resolve(CredentialProviderName(self.name))
        credential = self.credential_of(config) if config else None
        if not credential:
            raise RuntimeError(f"{self.name} is not configured. Add it in Settings → Providers.")
        return credential
