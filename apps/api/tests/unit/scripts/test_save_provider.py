"""The gaia up first-boot save: what the CLI's --llm-* flags store, through the wizard's own path."""

import socket

import httpx
import pytest
import respx

from app.scripts import save_provider
from app.services.providers.provider_credentials_service import resolve
from tests.helpers import InMemoryCredentialStore

_PUBLIC_IP = "8.8.8.8"
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_CHAT_COMPLETION = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer every hostname with a public address so no test touches real DNS."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (_PUBLIC_IP, port))
        ],
    )


async def test_ollama_defaults_to_the_endpoint_its_card_prefills(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(save_provider.API_KEY_ENV, raising=False)

    with respx.mock:
        respx.get("http://host.docker.internal:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3"}]})
        )
        assert await save_provider.run(["--provider", "ollama", "--model", "qwen3"]) == 0

    config = await resolve("ollama")
    assert config is not None
    assert (config["base_url"], config["model"], config["api_key"]) == (
        "http://host.docker.internal:11434",
        "qwen3",
        None,
    )


async def test_custom_stores_the_key_from_the_environment(
    selfhost_credential_store: InMemoryCredentialStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(save_provider.API_KEY_ENV, "sk-custom")
    argv = ["--provider", "custom", "--base-url", "https://gateway.example/v1", "--model", "m-1"]

    with respx.mock:
        respx.post("https://gateway.example/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_CHAT_COMPLETION)
        )
        assert await save_provider.run(argv) == 0

    assert capsys.readouterr().out == (
        "Saved custom. Change it any time in Settings → Providers & Tools.\n"
    )

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
    assert capsys.readouterr().err == (
        "Could not save custom: This URL looks private or unreachable — use a public endpoint "
        "or set OLLAMA_BASE_URL in your .env for local Ollama (unsupported URL scheme: 'ftp')\n"
    )
    assert await resolve("custom") is None


async def test_a_key_the_provider_rejects_saves_nothing_and_says_why(
    selfhost_credential_store: InMemoryCredentialStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(save_provider.API_KEY_ENV, "sk-bad")

    with respx.mock:
        route = respx.post(_OPENAI_CHAT_URL).mock(
            return_value=httpx.Response(
                401, json={"error": {"message": "Incorrect API key provided: sk-bad."}}
            )
        )
        code = await save_provider.run(["--provider", "openai"])

    assert (b"Authorization", b"Bearer sk-bad") in route.calls.last.request.headers.raw
    assert code == 1
    assert capsys.readouterr().err == (
        "Could not save openai: OpenAI rejected the key: Incorrect API key provided: [redacted].\n"
    )
    assert await resolve("openai") is None


async def test_a_key_the_provider_accepts_is_saved(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(save_provider.API_KEY_ENV, "sk-good")

    with respx.mock:
        route = respx.post(_OPENAI_CHAT_URL).mock(
            return_value=httpx.Response(200, json=_CHAT_COMPLETION)
        )
        assert await save_provider.run(["--provider", "openai"]) == 0

    assert route.called
    config = await resolve("openai")
    assert config is not None
    assert config["api_key"] == "sk-good"


async def test_help_describes_what_the_script_does(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        await save_provider.run(["--help"])

    assert exit_info.value.code == 0
    assert (
        "Save one provider credential exactly as the setup wizard does" in capsys.readouterr().out
    )


@pytest.mark.parametrize(
    ("argv", "complaint"),
    [
        ([], "the following arguments are required: --provider"),
        (["--provider", "anthropic"], "argument --provider: invalid choice: 'anthropic'"),
    ],
)
async def test_a_missing_or_unknown_provider_exits_with_usage(
    selfhost_credential_store: InMemoryCredentialStore,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    complaint: str,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        await save_provider.run(argv)

    assert exit_info.value.code == 2
    assert complaint in capsys.readouterr().err
