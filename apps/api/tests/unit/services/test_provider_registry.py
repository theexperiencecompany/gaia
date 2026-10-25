"""The provider registry: one spec per credential-store provider, and the rules every reader derives from it."""

import pytest

from app.config.settings import settings
from app.constants.providers import LLM_PROVIDER_PRIORITY, CredentialProviderName
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    env_config,
    is_usable,
)
from app.services.providers.provider_registry import (
    PROVIDER_SPECS,
    _api_key_spec,
    is_chat_provider,
)

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


@pytest.mark.parametrize("provider", list(CredentialProviderName))
def test_a_provider_is_a_chat_provider_exactly_when_an_llm_lane_routes_to_it(
    provider: CredentialProviderName,
) -> None:
    routed = provider.value in {p.value for p in LLM_PROVIDER_PRIORITY}

    assert is_chat_provider(provider) is routed
    assert PROVIDER_SPECS[provider].preset.takes_model is routed


def test_every_chat_provider_rebuilds_an_llm() -> None:
    chat = [p for p in CredentialProviderName if is_chat_provider(p)]

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


_API_KEY_TOOL_SETTINGS = {
    CredentialProviderName.TAVILY: "TAVILY_API_KEY",
    CredentialProviderName.EXA: "EXA_API_KEY",
    CredentialProviderName.BRAVE: "BRAVE_API_KEY",
    CredentialProviderName.E2B: "E2B_API_KEY",
    CredentialProviderName.RESEND: "RESEND_API_KEY",
    CredentialProviderName.FIRECRAWL: "FIRECRAWL_API_KEY",
    CredentialProviderName.OPENWEATHER: "OPENWEATHER_API_KEY",
    CredentialProviderName.LLAMAPARSE: "LLAMA_INDEX_KEY",
    CredentialProviderName.GITHUB: "GITHUB_TOKEN",
}


def _assert_configured_by_its_key_alone(
    monkeypatch: pytest.MonkeyPatch, provider: CredentialProviderName, setting: str
) -> None:
    monkeypatch.setattr(settings, setting, "key-from-env")
    assert env_config(provider) == ProviderConfig(api_key="key-from-env")
    monkeypatch.setattr(settings, setting, None)
    assert env_config(provider) is None

    assert is_usable(provider, ProviderConfig(api_key="saved-key"))
    assert not is_usable(provider, ProviderConfig(base_url="https://tool.example"))


@pytest.mark.parametrize(("provider", "setting"), list(_API_KEY_TOOL_SETTINGS.items()))
def test_an_api_key_tool_is_configured_by_its_own_key_alone(
    monkeypatch: pytest.MonkeyPatch, provider: CredentialProviderName, setting: str
) -> None:
    _assert_configured_by_its_key_alone(monkeypatch, provider, setting)


def test_the_api_key_factory_builds_a_spec_its_readers_honour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebuilt at test time: the declared specs are built once at import, before any mutant is live."""
    provider = CredentialProviderName.TAVILY
    preset = PROVIDER_SPECS[provider].preset
    monkeypatch.setitem(
        PROVIDER_SPECS, provider, _api_key_spec(preset, lambda: settings.TAVILY_API_KEY)
    )

    assert PROVIDER_SPECS[provider].preset is preset
    _assert_configured_by_its_key_alone(monkeypatch, provider, "TAVILY_API_KEY")
