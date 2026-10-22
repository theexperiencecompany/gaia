"""The provider registry: one spec per credential-store provider, and the rules every reader derives from it."""

import pytest

from app.config.settings import settings
from app.constants.providers import LLM_PROVIDER_PRIORITY, CredentialProviderName
from app.services.providers.provider_credentials_service import env_config
from app.services.providers.provider_registry import PROVIDER_SPECS

pytestmark = pytest.mark.unit


def test_every_credential_provider_has_exactly_one_spec_in_display_order() -> None:
    assert list(PROVIDER_SPECS) == list(CredentialProviderName)


@pytest.mark.parametrize("provider", list(CredentialProviderName))
def test_the_environment_can_configure_every_field_a_spec_requires(
    provider: CredentialProviderName,
) -> None:
    """A required field no env reader sets would make the provider unconfigurable from .env."""
    spec = PROVIDER_SPECS[provider]

    assert spec.requires <= set(spec.env)


def test_exactly_the_chat_providers_take_a_model_and_rebuild_an_llm() -> None:
    chat = {p for p, spec in PROVIDER_SPECS.items() if spec.preset.takes_model}

    assert chat == set(LLM_PROVIDER_PRIORITY)
    assert all(str(PROVIDER_SPECS[p].registry_key).endswith("_llm") for p in chat)


def test_the_custom_endpoint_reads_the_dev_settings_only_where_dev_tools_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DEV_LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setattr(settings, "DEV_LLM_API_KEY", "sk-dev")
    monkeypatch.setattr(settings, "DEV_LLM_MODEL", "m")

    monkeypatch.setattr(settings, "ENV", "development")
    assert env_config(CredentialProviderName.CUSTOM) is not None
    monkeypatch.setattr(settings, "ENV", "selfhost")
    assert env_config(CredentialProviderName.CUSTOM) is None
