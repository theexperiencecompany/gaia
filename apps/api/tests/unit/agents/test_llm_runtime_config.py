"""Unit tests for runtime-configurable LLM providers (self-host wave 1).

Covers:
- init_ollama_llm: ChatOpenAI construction (base_url/model/api_key), explicit
  OLLAMA_BASE_URL env and credential-store sources, trailing-slash
  normalization
- actionable LLMNotConfiguredError from the provider init functions when no
  configuration exists
- resolver precedence: credential-store snapshot beats env fallback; the env
  fallback IS provider_credentials_service._env_fallback (one shared policy —
  OpenRouter forwards an explicitly-set OPENROUTER_BASE_URL, Ollama counts only
  an explicitly-set OLLAMA_BASE_URL)
- _get_available_providers consulting resolver results instead of import-time
  registry availability
- refresh_provider_configs populating the snapshot; scheduling is a no-op
  outside a running loop
- reset_aux_llm_caches actually clearing every @cache'd builder
"""

from types import SimpleNamespace
from typing import Any, ClassVar, cast

from pydantic import SecretStr
import pytest

from app.agents.llm import client as client_module
from app.agents.llm.client import (
    NO_PROVIDER_CONFIGURED_MESSAGE,
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _build_default_llm,
    _build_memory_llm,
    _build_vision_llm,
    _get_available_providers,
    _sim_llm,
    get_default_llm,
    get_memory_llm,
    get_vision_llm,
    init_custom_llm,
    init_gemini_llm,
    init_ollama_llm,
    init_openrouter_llm,
    memory_lane_available,
    refresh_provider_configs,
    reset_aux_llm_caches,
)
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.llm.types import LLMProviderName
from app.constants.llm import DEFAULT_LLM_TEMPERATURE, DEFAULT_MAX_TOKENS


def _store_config(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, str | None]:
    """A ProviderConfig-shaped dict as the credential service returns it."""
    return {"api_key": api_key, "base_url": base_url, "model": model, "preset": None}


class _FakeChatOpenRouter:
    """ChatOpenRouter double recording construction kwargs.

    Carries ``client.sdk_configuration`` because ``without_sdk_retry`` writes
    there — a double missing it would pass where the production path raises.
    """

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).calls.append(kwargs)
        self.client = SimpleNamespace(sdk_configuration=SimpleNamespace(retry_config=None))
        self.profile: dict[str, int] | None = None

    def configurable_fields(self, **_: object) -> "_FakeChatOpenRouter":
        return self


class _FakeChatOpenAI:
    """ChatOpenAI double for the Ollama lane (no sdk_configuration — the real
    langchain-openai class has none, which is why without_sdk_retry must not
    touch it)."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).calls.append(kwargs)
        self.profile: dict[str, int] | None = None

    def configurable_fields(self, **_: object) -> "_FakeChatOpenAI":
        return self


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch):
    """Blank credentials and isolate module-level state between tests.

    OLLAMA_BASE_URL is removed from os.environ (not just settings): the env
    fallback reads the explicit var only, so an ambient value on a developer
    machine would leak a lane into every test here.
    """
    monkeypatch.setattr(client_module.settings, "GAIA_SIM_MODE", False, raising=False)
    monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", None, raising=False)
    monkeypatch.setattr(client_module.settings, "OPENROUTER_BASE_URL", None, raising=False)
    monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", None, raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(client_module.settings, "DEV_LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(client_module.settings, "DEV_LLM_BASE_URL", None, raising=False)
    monkeypatch.setattr(client_module.settings, "DEV_LLM_MODEL", None, raising=False)
    client_module._runtime_configs.clear()
    _sim_llm.cache_clear()
    _build_default_llm.cache_clear()
    _build_vision_llm.cache_clear()
    _build_memory_llm.cache_clear()
    yield
    client_module._runtime_configs.clear()
    _sim_llm.cache_clear()
    _build_default_llm.cache_clear()
    _build_vision_llm.cache_clear()
    _build_memory_llm.cache_clear()


# ---------------------------------------------------------------------------
# priority tables
# ---------------------------------------------------------------------------


class TestPriorityTables:
    def test_priority_slots(self) -> None:
        assert PROVIDER_PRIORITY == {
            1: LLMProviderName.OPENROUTER,
            2: LLMProviderName.GEMINI,
            3: LLMProviderName.OLLAMA,
            4: LLMProviderName.CUSTOM,
        }

    def test_ollama_default_model(self) -> None:
        assert PROVIDER_MODELS[LLMProviderName.OLLAMA] == "llama3.2"


# ---------------------------------------------------------------------------
# init_ollama_llm
# ---------------------------------------------------------------------------


class TestOllamaInit:
    def test_store_config_builds_expected_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module, "ChatOpenAI", _FakeChatOpenAI)
        client_module._runtime_configs["ollama"] = _store_config(
            base_url="http://ollama.internal:11434/", model="qwen3:8b"
        )
        _FakeChatOpenAI.calls.clear()

        instance = init_ollama_llm().loader_func()

        [kwargs] = _FakeChatOpenAI.calls
        assert kwargs["model"] == "qwen3:8b"
        # Trailing slash stripped before the /v1 suffix is appended.
        assert kwargs["base_url"] == "http://ollama.internal:11434/v1"
        assert kwargs["api_key"] == SecretStr("ollama")
        assert kwargs["streaming"] is True
        assert kwargs["temperature"] == DEFAULT_LLM_TEMPERATURE
        assert kwargs["max_retries"] == 0
        assert cast(Any, instance).profile == {"max_input_tokens": DEFAULT_MAX_TOKENS}

    def test_explicit_env_var_builds_expected_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The EXPLICIT OLLAMA_BASE_URL env var (not the settings default) is the
        env-side source for the keyless lane."""
        monkeypatch.setattr(client_module, "ChatOpenAI", _FakeChatOpenAI)
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11500")
        _FakeChatOpenAI.calls.clear()

        init_ollama_llm().loader_func()

        [kwargs] = _FakeChatOpenAI.calls
        assert kwargs["base_url"] == "http://127.0.0.1:11500/v1"
        assert kwargs["model"] == "llama3.2"

    def test_code_default_url_is_not_a_configuration_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F10: the settings default (docker-internal DNS name) must not satisfy
        the lane — only an explicitly-set env var counts, exactly like the
        credential service's fallback."""
        monkeypatch.setattr(
            client_module.settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
        )
        # _hermetic already removed the env var.

        with pytest.raises(LLMNotConfiguredError):
            init_ollama_llm().loader_func()
        assert client_module._provider_config(LLMProviderName.OLLAMA) is None

    def test_sim_mode_returns_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        monkeypatch.setattr(client_module.settings, "GAIA_SIM_MODE", True)
        monkeypatch.setattr(client_module, "_sim_llm", lambda temperature=0.0: sentinel)

        assert init_ollama_llm().loader_func() is sentinel


# ---------------------------------------------------------------------------
# actionable error when nothing is configured
# ---------------------------------------------------------------------------


class TestActionableMissingConfig:
    @pytest.mark.parametrize("factory", [init_openrouter_llm, init_gemini_llm, init_custom_llm])
    def test_missing_config_raises_actionable_error(
        self, factory: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.settings, "ENV", "development")

        with pytest.raises(LLMNotConfiguredError) as excinfo:
            factory().loader_func()

        message = str(excinfo.value)
        assert message == NO_PROVIDER_CONFIGURED_MESSAGE
        assert "AI Providers" in message
        assert "setup wizard" in message

    def test_ollama_with_explicit_env_is_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ollama is keyless: an explicitly-set endpoint env var satisfies it."""
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        init_ollama_llm().loader_func()


# ---------------------------------------------------------------------------
# resolver precedence: store > env > unconfigured
# ---------------------------------------------------------------------------


class TestResolverPrecedence:
    def test_store_credential_beats_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module, "ChatOpenRouter", _FakeChatOpenRouter)
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-env-key")
        client_module._runtime_configs["openrouter"] = _store_config(
            api_key="sk-store-key", base_url="http://gateway.internal:8080/v1"
        )
        _FakeChatOpenRouter.calls.clear()

        init_openrouter_llm().loader_func()

        [kwargs] = _FakeChatOpenRouter.calls
        assert kwargs["api_key"] == SecretStr("sk-store-key")
        assert kwargs["base_url"] == "http://gateway.internal:8080/v1"

    def test_env_serves_when_never_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pre-refresh (empty snapshot) the env path serves from settings. With
        no OPENROUTER_BASE_URL configured, NO base_url kwarg is forwarded — a
        None kwarg would clobber ChatOpenRouter's OPENROUTER_API_BASE default."""
        monkeypatch.setattr(client_module, "ChatOpenRouter", _FakeChatOpenRouter)
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-env-key")
        _FakeChatOpenRouter.calls.clear()

        init_openrouter_llm().loader_func()

        [kwargs] = _FakeChatOpenRouter.calls
        assert kwargs["api_key"] == SecretStr("sk-env-key")
        assert "base_url" not in kwargs

    def test_explicit_env_base_url_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shared env-fallback policy: an explicitly-set OPENROUTER_BASE_URL
        rides the resolved config into client construction, same as it does for
        the credential service's resolution."""
        monkeypatch.setattr(client_module, "ChatOpenRouter", _FakeChatOpenRouter)
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-env-key")
        monkeypatch.setattr(client_module.settings, "OPENROUTER_BASE_URL", "http://localhost:9797")
        _FakeChatOpenRouter.calls.clear()

        init_openrouter_llm().loader_func()

        [kwargs] = _FakeChatOpenRouter.calls
        assert kwargs["base_url"] == "http://localhost:9797"

    def test_aux_default_llm_builds_from_store_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module, "ChatOpenRouter", _FakeChatOpenRouter)
        client_module._runtime_configs["openrouter"] = _store_config(api_key="sk-store-aux")
        _FakeChatOpenRouter.calls.clear()

        get_default_llm()

        [kwargs] = _FakeChatOpenRouter.calls
        assert kwargs["api_key"] == SecretStr("sk-store-aux")


# ---------------------------------------------------------------------------
# availability consults resolver results
# ---------------------------------------------------------------------------


class TestAvailableProviders:
    @pytest.fixture
    def registry(self, monkeypatch: pytest.MonkeyPatch):
        """A fake provider registry whose instances are keyed by registry name."""
        instances = {
            f"{name}_llm": object() for name in ("gemini", "openrouter", "ollama", "custom")
        }

        class _Registry:
            def get(self, key: str) -> object:
                if key not in instances:
                    raise KeyError(key)
                return instances[key]

        monkeypatch.setattr(client_module, "providers", _Registry())
        return instances

    def test_store_only_credentials_make_provider_available(
        self, registry: dict[str, object]
    ) -> None:
        client_module._runtime_configs["openrouter"] = _store_config(api_key="sk-store")

        available = _get_available_providers()

        assert available[LLMProviderName.OPENROUTER] is registry["openrouter_llm"]

    def test_unconfigured_providers_excluded(self, registry: dict[str, object]) -> None:
        """No snapshot entries, no explicit env: every lane is unavailable —
        including Ollama, whose code-default URL is not a configuration source."""
        available = _get_available_providers()

        assert available == {}

    def test_explicit_ollama_env_makes_it_available(
        self, registry: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

        available = _get_available_providers()

        assert set(available) == {LLMProviderName.OLLAMA}

    def test_env_keys_still_configure_their_providers(
        self, registry: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-env")
        monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", "g-key")

        available = _get_available_providers()

        assert LLMProviderName.OPENROUTER in available
        assert LLMProviderName.GEMINI in available

    def test_resolved_none_marks_provider_unavailable(
        self, registry: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-env")
        # A resolved None means the resolver ran and found nothing usable —
        # it wins over the stale ambient env read.
        client_module._runtime_configs["openrouter"] = None

        available = _get_available_providers()

        assert LLMProviderName.OPENROUTER not in available


# ---------------------------------------------------------------------------
# refresh + scheduling
# ---------------------------------------------------------------------------


class TestRefreshProviderConfigs:
    async def test_refresh_populates_snapshot_for_every_consumer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolved: dict[str, dict[str, str | None]] = {}

        async def fake_resolve(provider: str) -> dict[str, str | None] | None:
            return resolved.get(provider)

        async def seed_and_refresh() -> None:
            for name in ("openrouter", "tavily"):
                resolved[name] = _store_config(api_key=f"sk-{name}")
            await refresh_provider_configs()

        from unittest.mock import patch

        # client.py imports `resolve` directly (the phantom cycle was disproven),
        # so the patch lands on the client module's binding of it.
        with patch(
            "app.agents.llm.client.resolve",
            side_effect=fake_resolve,
        ):
            await seed_and_refresh()

        assert client_module._runtime_configs["openrouter"]["api_key"] == "sk-openrouter"
        assert client_module._runtime_configs["tavily"]["api_key"] == "sk-tavily"
        assert client_module._runtime_configs["gemini"] is None

    def test_scheduling_without_a_loop_is_a_noop(self) -> None:
        client_module._schedule_runtime_config_refresh()

        assert client_module._runtime_configs == {}


# ---------------------------------------------------------------------------
# reset_aux_llm_caches
# ---------------------------------------------------------------------------


class TestResetAuxLlmCaches:
    def test_default_llm_cache_is_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module, "ChatOpenRouter", _FakeChatOpenRouter)
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-test")
        _FakeChatOpenRouter.calls.clear()

        get_default_llm()
        get_default_llm()
        assert len(_FakeChatOpenRouter.calls) == 1  # cached

        reset_aux_llm_caches()
        get_default_llm()
        assert len(_FakeChatOpenRouter.calls) == 2  # rebuilt

    def test_vision_and_memory_caches_are_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constructions: list[tuple[str, float]] = []

        class _FakeGemini:
            def __init__(self, model: str, temperature: float, **_: object) -> None:
                constructions.append((model, temperature))

        monkeypatch.setattr(client_module, "ChatGoogleGenerativeAI", _FakeGemini)
        monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", "g-key")

        get_vision_llm()
        get_memory_llm()
        assert len(constructions) == 2  # cached after first call each

        reset_aux_llm_caches()
        get_vision_llm()
        get_memory_llm()
        assert len(constructions) == 4  # both rebuilt

    def test_snapshot_is_dropped_so_stale_store_keys_never_serve(self) -> None:
        client_module._runtime_configs["openrouter"] = _store_config(api_key="sk-stale")

        reset_aux_llm_caches()

        assert client_module._runtime_configs == {}


# ---------------------------------------------------------------------------
# aux-lane factories keep their env-var-naming errors
# ---------------------------------------------------------------------------


class TestAuxLaneErrorsPreserved:
    def test_default_llm_names_env_var(self) -> None:
        with pytest.raises(LLMNotConfiguredError, match="OPENROUTER_API_KEY"):
            get_default_llm()

    def test_vision_llm_names_env_var(self) -> None:
        with pytest.raises(LLMNotConfiguredError, match="GOOGLE_API_KEY"):
            get_vision_llm()

    def test_memory_lane_reports_availability(self) -> None:
        assert memory_lane_available() is False
        with pytest.raises(LLMNotConfiguredError, match="GOOGLE_API_KEY"):
            get_memory_llm()
