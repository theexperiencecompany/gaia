"""Unit tests for runtime-configurable LLM providers (self-host wave 1).

Covers the Ollama and OpenRouter init lanes, resolver precedence (stored
snapshot beats env fallback), provider availability from resolver results,
snapshot refresh, and aux-cache resets.
"""

import asyncio
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from unittest.mock import AsyncMock

from pydantic import SecretStr
import pytest

from app.agents.llm import client as client_module
from app.agents.llm.client import (
    NO_PROVIDER_CONFIGURED_MESSAGE,
    _build_default_llm,
    _build_gemini_one_shot,
    _get_available_providers,
    _sim_llm,
    init_custom_llm,
    init_gemini_llm,
    init_ollama_llm,
    init_openrouter_llm,
    memory_lane_available,
    refresh_provider_configs,
    reset_aux_llm_caches,
    resolve_model,
)
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.llm.types import LLMProviderName
from app.constants.llm import DEFAULT_LLM_TEMPERATURE, DEFAULT_MAX_TOKENS, ModelUse
from app.services.providers import provider_credentials_service as service
from tests.helpers import captured_wide_event


def _store_config(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, str | None]:
    """Return a ProviderConfig-shaped dict as the credential service does."""
    return {"api_key": api_key, "base_url": base_url, "model": model, "preset": None}


class _FakeChatOpenRouter:
    """ChatOpenRouter double recording construction kwargs, with the sdk_configuration surface."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).calls.append(kwargs)
        self.client = SimpleNamespace(sdk_configuration=SimpleNamespace(retry_config=None))
        self.profile: dict[str, int] | None = None
        self.model_kwargs: dict[str, object] | None = None

    def configurable_fields(self, **_: object) -> "_FakeChatOpenRouter":
        return self

    def model_copy(self, update: dict[str, object] | None = None) -> "_FakeChatOpenRouter":
        # Bypass __init__: a copy is not a construction and must not record one,
        # or the cache assertions below count copies as rebuilds.
        fresh = object.__new__(_FakeChatOpenRouter)
        fresh.client = self.client
        fresh.profile = self.profile
        fresh.model_kwargs = {**(self.model_kwargs or {}), **(update or {})}
        return fresh


class _FakeChatOpenAI:
    """Provide the ChatOpenAI double for the Ollama lane.

    It carries no sdk_configuration — the real langchain-openai class has none,
    which is why without_sdk_retry must not touch it.
    """

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).calls.append(kwargs)
        self.profile: dict[str, int] | None = None

    def configurable_fields(self, **_: object) -> "_FakeChatOpenAI":
        return self


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch):
    """Blank credentials and isolate module-level state between tests."""
    # Runtime-stored credentials only exist on a self-hosted instance.
    monkeypatch.setattr(client_module.settings, "ENV", "selfhost")
    monkeypatch.setattr(client_module.settings, "AUTH_MODE", "local")
    monkeypatch.setattr(client_module.settings, "GAIA_SIM_MODE", False, raising=False)
    monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", None, raising=False)
    monkeypatch.setattr(client_module.settings, "OPENROUTER_BASE_URL", None, raising=False)
    monkeypatch.setattr(client_module.settings, "GOOGLE_API_KEY", None, raising=False)
    monkeypatch.setattr(client_module.settings, "OPENAI_API_KEY", None, raising=False)
    monkeypatch.setattr(client_module.settings, "OLLAMA_BASE_URL", None)
    monkeypatch.setattr(client_module.settings, "DEV_LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(client_module.settings, "DEV_LLM_BASE_URL", None, raising=False)
    monkeypatch.setattr(client_module.settings, "DEV_LLM_MODEL", None, raising=False)
    client_module._runtime_configs.clear()
    _sim_llm.cache_clear()
    _build_default_llm.cache_clear()
    _build_gemini_one_shot.cache_clear()
    yield
    client_module._runtime_configs.clear()
    _sim_llm.cache_clear()
    _build_default_llm.cache_clear()
    _build_gemini_one_shot.cache_clear()


# ---------------------------------------------------------------------------
# priority tables
# ---------------------------------------------------------------------------


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
        """Take the keyless lane env source from OLLAMA_BASE_URL."""
        monkeypatch.setattr(client_module, "ChatOpenAI", _FakeChatOpenAI)
        monkeypatch.setattr(client_module.settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11500")
        _FakeChatOpenAI.calls.clear()

        init_ollama_llm().loader_func()

        [kwargs] = _FakeChatOpenAI.calls
        assert kwargs["base_url"] == "http://127.0.0.1:11500/v1"
        assert kwargs["model"] == "llama3.2"

    def test_an_unset_endpoint_is_not_a_configuration_source(self) -> None:
        """No Ollama lane until an endpoint is set; a guessed default dies on connect."""
        with pytest.raises(LLMNotConfiguredError):
            init_ollama_llm().loader_func()
        assert client_module.resolved_config(LLMProviderName.OLLAMA) is None

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
        monkeypatch.setattr(client_module.settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
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
        """Forward no base_url kwarg when unconfigured; None would clobber the client default."""
        monkeypatch.setattr(client_module, "ChatOpenRouter", _FakeChatOpenRouter)
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-env-key")
        _FakeChatOpenRouter.calls.clear()

        init_openrouter_llm().loader_func()

        [kwargs] = _FakeChatOpenRouter.calls
        assert kwargs["api_key"] == SecretStr("sk-env-key")
        assert "base_url" not in kwargs

    def test_explicit_env_base_url_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ride the resolved config into client construction; explicit env base_url is forwarded."""
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

        resolve_model()

        [kwargs] = _FakeChatOpenRouter.calls
        assert kwargs["api_key"] == SecretStr("sk-store-aux")


# ---------------------------------------------------------------------------
# availability consults resolver results
# ---------------------------------------------------------------------------


class TestAvailableProviders:
    @pytest.fixture
    def registry(self, monkeypatch: pytest.MonkeyPatch):
        """Provide a fake provider registry keyed by registry name."""
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
        """Leave every lane unavailable with no snapshot entries and no explicit env."""
        available = _get_available_providers()

        assert available == {}

    def test_explicit_ollama_env_makes_it_available(
        self, registry: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")

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
        monkeypatch.setattr(
            service.provider_credentials_repository,
            "find_by_provider",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-openrouter")
        monkeypatch.setattr(client_module.settings, "TAVILY_API_KEY", "sk-tavily")
        service._cache.clear()

        await refresh_provider_configs()

        assert client_module._runtime_configs["openrouter"]["api_key"] == "sk-openrouter"
        assert client_module._runtime_configs["tavily"]["api_key"] == "sk-tavily"
        assert client_module._runtime_configs["gemini"] is None

    async def test_scheduling_inside_a_loop_refreshes_and_forgets_the_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.provider_credentials_repository,
            "find_by_provider",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(client_module.settings, "OPENROUTER_API_KEY", "sk-openrouter")
        service._cache.clear()

        client_module._schedule_runtime_config_refresh()
        [task] = client_module._refresh_tasks
        await task
        await asyncio.sleep(0)  # let the done callback run

        assert client_module._runtime_configs["openrouter"]["api_key"] == "sk-openrouter"
        assert client_module._refresh_tasks == set()

    async def test_a_failed_refresh_is_logged_with_its_cause(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.provider_credentials_repository,
            "find_by_provider",
            AsyncMock(side_effect=ConnectionError("mongo down")),
        )
        service._cache.clear()

        async with captured_wide_event() as event:
            client_module._schedule_runtime_config_refresh()
            [task] = client_module._refresh_tasks
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)  # let the done callback run

        assert event["errors"] == [
            {
                "msg": "Runtime provider-config refresh failed",
                "error": "mongo down",
                "error_type": "ConnectionError",
            }
        ]
        assert client_module._refresh_tasks == set()

    async def test_a_successful_refresh_logs_no_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service.provider_credentials_repository,
            "find_by_provider",
            AsyncMock(return_value=None),
        )
        service._cache.clear()

        async with captured_wide_event() as event:
            client_module._schedule_runtime_config_refresh()
            [task] = client_module._refresh_tasks
            await task
            await asyncio.sleep(0)  # let the done callback run

        assert "errors" not in event

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

        resolve_model()
        resolve_model()
        assert len(_FakeChatOpenRouter.calls) == 1  # cached

        reset_aux_llm_caches()
        resolve_model()
        assert len(_FakeChatOpenRouter.calls) == 2  # rebuilt

    def test_vision_and_memory_caches_are_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        constructions: list[tuple[str, float]] = []

        class _FakeGemini:
            def __init__(self, model: str, temperature: float, **_: object) -> None:
                constructions.append((model, temperature))

        monkeypatch.setattr(client_module, "ChatGoogleGenerativeAI", _FakeGemini)
        client_module._runtime_configs["gemini"] = _store_config(api_key="g-key")

        resolve_model(ModelUse.VISION)
        resolve_model(ModelUse.MEMORY)
        # Both run the same Gemini model, so they share one cached client.
        assert len(constructions) == 1

        reset_aux_llm_caches()
        client_module._runtime_configs["gemini"] = _store_config(api_key="g-key")
        resolve_model(ModelUse.VISION)
        resolve_model(ModelUse.MEMORY)
        assert len(constructions) == 2  # rebuilt

    def test_snapshot_is_dropped_so_stale_store_keys_never_serve(self) -> None:
        client_module._runtime_configs["openrouter"] = _store_config(api_key="sk-stale")

        reset_aux_llm_caches()

        assert client_module._runtime_configs == {}


# ---------------------------------------------------------------------------
# one-shot factories name the role nothing can serve
# ---------------------------------------------------------------------------


class TestOneShotNotConfiguredErrors:
    def test_helper_names_its_role(self) -> None:
        with pytest.raises(LLMNotConfiguredError, match="helper"):
            resolve_model()

    def test_vision_names_its_role(self) -> None:
        with pytest.raises(LLMNotConfiguredError, match="vision"):
            resolve_model(ModelUse.VISION)

    def test_memory_lane_reports_availability(self) -> None:
        assert memory_lane_available() is False
        with pytest.raises(LLMNotConfiguredError, match="memory"):
            resolve_model(ModelUse.MEMORY)
