"""The gaia up first-boot save: what the CLI's --llm-* flags store, through the wizard's own path."""

import pytest

from app.scripts import save_provider
from app.services.providers.provider_credentials_service import resolve
from tests.helpers import InMemoryCredentialStore


async def test_ollama_defaults_to_the_endpoint_its_card_prefills(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(save_provider.API_KEY_ENV, raising=False)

    assert await save_provider.run(["--provider", "ollama", "--model", "qwen3"]) == 0

    config = await resolve("ollama")
    assert config is not None
    assert (config["base_url"], config["model"], config["api_key"]) == (
        "http://host.docker.internal:11434",
        "qwen3",
        None,
    )


async def test_custom_stores_the_key_from_the_environment(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(save_provider.API_KEY_ENV, "sk-custom")
    argv = ["--provider", "custom", "--base-url", "https://gateway.example/v1", "--model", "m-1"]

    assert await save_provider.run(argv) == 0

    config = await resolve("custom")
    assert config is not None
    assert (config["api_key"], config["base_url"], config["model"]) == (
        "sk-custom",
        "https://gateway.example/v1",
        "m-1",
    )


async def test_a_refused_endpoint_exits_non_zero_naming_why(
    selfhost_credential_store: InMemoryCredentialStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(save_provider.API_KEY_ENV, "sk")

    code = await save_provider.run(["--provider", "custom", "--base-url", "ftp://gw"])

    assert code == 1
    assert capsys.readouterr().err == "Could not save custom: base_url must be an http(s) URL\n"
    assert await resolve("custom") is None
