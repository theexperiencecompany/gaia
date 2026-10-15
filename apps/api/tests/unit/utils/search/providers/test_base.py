"""CredentialSearchProvider gates and searches on the one credential field its provider names."""

import pytest

from app.config.settings import settings
from app.services.providers.provider_credentials_service import resolve
from app.utils.search.providers.base import CredentialSearchProvider
from app.utils.search.providers.exa import ExaProvider
from app.utils.search.providers.searxng import SearxngProvider
from tests.helpers import InMemoryCredentialStore


@pytest.fixture(autouse=True)
def _no_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EXA_API_KEY", None)
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", None)


async def _configured(provider: CredentialSearchProvider) -> bool:
    await resolve(provider.name)
    return provider.is_configured()


async def test_a_stored_credential_in_the_named_field_configures_the_provider(
    selfhost_credential_store: InMemoryCredentialStore,
) -> None:
    selfhost_credential_store.save("exa", api_key="stored-exa-key")  # pragma: allowlist secret
    selfhost_credential_store.save("searxng", base_url="http://searxng:8080")

    assert await _configured(ExaProvider()) is True
    assert await _configured(SearxngProvider()) is True


async def test_a_credential_in_another_field_does_not_configure_the_provider(
    selfhost_credential_store: InMemoryCredentialStore,
) -> None:
    selfhost_credential_store.save("searxng", api_key="not-a-base-url")  # pragma: allowlist secret

    assert await _configured(SearxngProvider()) is False
    with pytest.raises(RuntimeError) as refused:
        await SearxngProvider().search("q", 1)
    assert str(refused.value) == "searxng is not configured. Add it in Settings → Providers."


async def test_a_search_runs_with_the_credential_stored_in_its_named_field(
    selfhost_credential_store: InMemoryCredentialStore,
) -> None:
    selfhost_credential_store.save("searxng", base_url="http://searxng:8080")

    assert await SearxngProvider()._credential() == "http://searxng:8080"


@pytest.mark.usefixtures("selfhost_credential_store")
async def test_a_provider_with_no_credential_anywhere_refuses_to_search() -> None:
    assert await _configured(ExaProvider()) is False
    with pytest.raises(RuntimeError) as refused:
        await ExaProvider().search("q", 1)
    assert str(refused.value) == "exa is not configured. Add it in Settings → Providers."
