"""Unit tests for the LLM client layer.

Covers:
- init_llm: provider selection, fallback logic, free-model path, error handling
- _get_available_providers: registry lookups
- _get_ordered_providers: priority ordering with/without preferred provider
- _create_configurable_llm: primary-only vs. primary+alternatives
- get_default_llm: the default model for auxiliary tasks
- ainvoke_llm: the single invoke primitive — retry, fallback to default, fail-loud
- _record_auxiliary_usage: what auxiliary (non-graph) spend gets booked as
- chatbot: default-model one-shot path, error handling
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock, patch

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_openrouter import ChatOpenRouter
from pydantic import BaseModel, SecretStr
import pytest

from app.agents.llm import client as client_module
from app.agents.llm.chatbot import chatbot
from app.agents.llm.client import (
    _MODEL_FIELD,
    LLM_RETRYABLE_EXCEPTIONS,
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _build_default_llm,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    _openrouter_wire_configurables,
    _record_auxiliary_usage,
    ainvoke_llm,
    ainvoke_structured,
    get_default_llm,
    init_llm,
    register_llm_providers,
)
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, LLMNotConfiguredError
from app.agents.llm.types import LLMProviderName
from app.constants.llm import (
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_MODEL_NAME,
    OPENROUTER_MAX_OUTPUT_TOKENS,
)
from app.core.lazy_loader import ProviderRegistry
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_provider(name: str = "fake") -> MagicMock:
    """Return a MagicMock that quacks enough like a BaseChatModel."""
    mock = MagicMock()
    mock.configurable_alternatives.return_value = mock
    mock.ainvoke = AsyncMock(return_value=AIMessage(content=f"response-from-{name}"))
    return mock


def _make_llm_provider(name: str) -> dict[str, Any]:
    return {"name": name, "instance": _make_fake_provider(name)}


# ---------------------------------------------------------------------------
# _get_available_providers
# ---------------------------------------------------------------------------


class TestGetAvailableProviders:
    @patch("app.agents.llm.client.providers")
    def test_all_providers_available(self, mock_providers: MagicMock) -> None:
        gemini_inst = _make_fake_provider("gemini")
        openrouter_inst = _make_fake_provider("openrouter")

        def _get(key: str) -> MagicMock | None:
            return {
                "gemini_llm": gemini_inst,
                "openrouter_llm": openrouter_inst,
            }.get(key)

        mock_providers.get.side_effect = _get

        result = _get_available_providers()

        assert "gemini" in result
        assert "openrouter" in result
        assert result["gemini"] is gemini_inst

    @patch("app.agents.llm.client.providers")
    def test_no_providers_available(self, mock_providers: MagicMock) -> None:
        mock_providers.get.return_value = None

        result = _get_available_providers()

        assert result == {}

    @patch("app.agents.llm.client.providers")
    def test_partial_providers_available(self, mock_providers: MagicMock) -> None:
        gemini_inst = _make_fake_provider("gemini")

        def _get(key: str) -> MagicMock | None:
            if key == "gemini_llm":
                return gemini_inst
            return None

        mock_providers.get.side_effect = _get

        result = _get_available_providers()

        assert list(result.keys()) == ["gemini"]

    def test_unregistered_provider_is_skipped_not_fatal(self) -> None:
        """custom_llm is registered only when ENV=development, so in production
        the registry has no such key. Against the REAL registry (which raises
        KeyError on an unregistered name, unlike the mock the sibling tests use)
        that killed init_llm, and with it every agent graph.
        """
        registry = ProviderRegistry()
        gemini_inst = _make_fake_provider("gemini")
        openrouter_inst = _make_fake_provider("openrouter")
        registry.register("gemini_llm", lambda: gemini_inst)
        registry.register("openrouter_llm", lambda: openrouter_inst)

        with patch("app.agents.llm.client.providers", registry):
            result = _get_available_providers()

        assert result == {"gemini": gemini_inst, "openrouter": openrouter_inst}


# ---------------------------------------------------------------------------
# next_fallback_provider
# ---------------------------------------------------------------------------


class TestNextFallbackProvider:
    """What a caller that caught a provider failure retries onto. The graph
    selects its lane by ``configurable["provider"]`` and never fails over itself,
    so a wrong answer here is a turn that dies on the provider that just 402'd."""

    def _available(self, *names: LLMProviderName) -> Any:
        return patch(
            "app.agents.llm.client._get_available_providers",
            return_value={name: _make_fake_provider(name) for name in names},
        )

    def test_the_failed_provider_is_never_returned_to(self) -> None:
        with self._available(LLMProviderName.OPENROUTER, LLMProviderName.GEMINI):
            assert client_module.next_fallback_provider(LLMProviderName.OPENROUTER) == (
                LLMProviderName.GEMINI,
                DEFAULT_GEMINI_MODEL_NAME,
            )

    def test_the_highest_priority_other_provider_wins(self) -> None:
        with self._available(
            LLMProviderName.OPENROUTER, LLMProviderName.GEMINI, LLMProviderName.CUSTOM
        ):
            assert client_module.next_fallback_provider(LLMProviderName.GEMINI) == (
                LLMProviderName.OPENROUTER,
                DEFAULT_MODEL_NAME,
            )

    def test_a_run_with_no_lane_yet_gets_the_highest_priority_provider(self) -> None:
        with self._available(LLMProviderName.OPENROUTER, LLMProviderName.GEMINI):
            assert client_module.next_fallback_provider(None) == (
                LLMProviderName.OPENROUTER,
                DEFAULT_MODEL_NAME,
            )

    def test_nothing_else_configured_yields_no_fallback(self) -> None:
        with self._available(LLMProviderName.OPENROUTER):
            assert client_module.next_fallback_provider(LLMProviderName.OPENROUTER) is None

    def test_an_unconfigured_provider_is_skipped_not_returned_modelless(self) -> None:
        """The custom dev endpoint's PROVIDER_MODELS entry is ``DEV_LLM_MODEL or
        ""``; pinning ``""`` trades one dead provider for a guaranteed bad
        request."""
        with (
            self._available(LLMProviderName.OPENROUTER, LLMProviderName.CUSTOM),
            patch.dict(PROVIDER_MODELS, {LLMProviderName.CUSTOM: ""}),
        ):
            assert client_module.next_fallback_provider(LLMProviderName.OPENROUTER) is None

    def test_a_configured_custom_endpoint_is_a_real_fallback_target(self) -> None:
        with (
            self._available(LLMProviderName.OPENROUTER, LLMProviderName.CUSTOM),
            patch.dict(PROVIDER_MODELS, {LLMProviderName.CUSTOM: "local/dev-model"}),
        ):
            assert client_module.next_fallback_provider(LLMProviderName.OPENROUTER) == (
                LLMProviderName.CUSTOM,
                "local/dev-model",
            )


# ---------------------------------------------------------------------------
# _get_ordered_providers
# ---------------------------------------------------------------------------


class TestGetOrderedProviders:
    def test_default_priority_order(self) -> None:
        available: dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }
        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=True)

        # Should follow PROVIDER_PRIORITY: 1=gemini, 2=openrouter
        names = [p["name"] for p in ordered]
        assert names == ["openrouter", "gemini"]

    def test_preferred_provider_is_first(self) -> None:
        available: dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        names = [p["name"] for p in ordered]
        assert names[0] == "openai"
        # Remaining follow priority order (gemini before openrouter)
        assert names[1:] == ["openrouter", "gemini"]

    def test_preferred_provider_not_available_fallback_enabled(self) -> None:
        available: dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        # openai not available, fallback picks gemini
        names = [p["name"] for p in ordered]
        assert names == ["gemini"]

    def test_preferred_provider_not_available_fallback_disabled(self) -> None:
        available: dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=False
        )

        # openai not in available, fallback disabled but ordered is empty so
        # the branch `if fallback_enabled or not ordered` fires.
        # The code adds remaining by priority when ordered is empty even if fallback disabled.
        names = [p["name"] for p in ordered]
        assert names == ["gemini"]

    def test_no_fallback_only_preferred(self) -> None:
        available: dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=False
        )

        # Preferred is available and fallback disabled -> only preferred provider
        names = [p["name"] for p in ordered]
        assert names == ["openai"]

    def test_no_preferred_no_fallback(self) -> None:
        available: dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }
        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=False)

        # No preferred, ordered is empty, so all providers by priority added
        names = [p["name"] for p in ordered]
        assert names == ["openrouter", "gemini"]

    def test_empty_available(self) -> None:
        ordered = _get_ordered_providers({}, preferred_provider=None, fallback_enabled=True)

        assert ordered == []

    def test_no_duplicate_when_preferred_is_also_in_priority(self) -> None:
        available: dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="gemini", fallback_enabled=True
        )

        names = [p["name"] for p in ordered]
        # gemini first (preferred), openrouter from priority; gemini not duplicated
        assert names == ["gemini", "openrouter"]


# ---------------------------------------------------------------------------
# _create_configurable_llm
# ---------------------------------------------------------------------------


class TestCreateConfigurableLlm:
    def test_no_alternatives_returns_primary_instance(self) -> None:
        primary = _make_llm_provider("gemini")
        result = _create_configurable_llm(primary, [])  # type: ignore[arg-type]

        assert result is primary["instance"]

    def test_with_alternatives_calls_configurable_alternatives(self) -> None:
        primary = _make_llm_provider("gemini")
        alt1 = _make_llm_provider("openai")
        alt2 = _make_llm_provider("openrouter")

        _create_configurable_llm(primary, [alt1, alt2])  # type: ignore[arg-type, list-item]

        primary["instance"].configurable_alternatives.assert_called_once()
        call_args = primary["instance"].configurable_alternatives.call_args
        # Check that both alternatives are passed as keyword arguments
        kwargs = call_args.kwargs
        assert "openai" in kwargs
        assert "openrouter" in kwargs
        assert kwargs["default_key"] == "gemini"
        assert kwargs["prefix_keys"] is False


# ---------------------------------------------------------------------------
# init_llm
# ---------------------------------------------------------------------------


class TestInitLlm:
    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_default_provider_selection(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("gemini")
        alt = _make_llm_provider("openai")
        mock_available.return_value = {
            "gemini": primary["instance"],
            "openai": alt["instance"],
        }
        mock_ordered.return_value = [primary, alt]
        mock_create.return_value = MagicMock()

        init_llm()

        mock_ordered.assert_called_once_with(mock_available.return_value, None, True)
        mock_create.assert_called_once_with(primary, [alt])

    def test_invalid_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid preferred_provider 'cerebras'"):
            init_llm(preferred_provider="cerebras")

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_available_providers")
    def test_no_providers_raises_runtime_error(
        self, mock_available: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_available.return_value = {}

        with pytest.raises(RuntimeError, match="No LLM providers are properly configured"):
            init_llm()

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_provider_unavailable_no_fallback(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_available.return_value = {"gemini": _make_fake_provider("gemini")}
        mock_ordered.return_value = []

        with pytest.raises(RuntimeError, match="Preferred provider"):
            init_llm(preferred_provider="openrouter", fallback_enabled=False)

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_fallback_disabled_no_alternatives(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("openrouter")
        mock_available.return_value = {"openrouter": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="openrouter", fallback_enabled=False)

        # With fallback disabled, alternatives list should be empty
        mock_create.assert_called_once_with(primary, [])

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_provider_gemini(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("gemini")
        mock_available.return_value = {"gemini": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="gemini")

        mock_ordered.assert_called_once_with(mock_available.return_value, "gemini", True)

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_provider_openrouter(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("openrouter")
        mock_available.return_value = {"openrouter": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="openrouter")

        mock_ordered.assert_called_once_with(mock_available.return_value, "openrouter", True)


# ---------------------------------------------------------------------------
# get_default_llm
# ---------------------------------------------------------------------------


class TestGetDefaultLlm:
    @pytest.fixture(autouse=True)
    def _fresh_cache(self):
        # get_default_llm caches instances per temperature; isolate each test.
        _build_default_llm.cache_clear()
        yield
        _build_default_llm.cache_clear()

    @patch("app.agents.llm.client.ChatOpenRouter")
    @patch("app.agents.llm.client.settings")
    def test_returns_the_openrouter_default_model(
        self, mock_settings: MagicMock, mock_chat_openrouter: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = False
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_chat_openrouter.return_value = MagicMock()

        assert get_default_llm() is mock_chat_openrouter.return_value
        kwargs = mock_chat_openrouter.call_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL_NAME
        # stream_usage only attaches usage metadata to a STREAM; without
        # streaming it is inert, and the model fallback built from this factory
        # would arrive as one lump instead of streaming like the primary.
        assert kwargs["streaming"] is True
        assert kwargs["stream_usage"] is True
        # get_default_llm feeds the agent-graph fallback (create_agent) and the
        # summarization/compaction middleware — both legitimately need the full
        # reservation, not the helper cap.
        assert kwargs["max_tokens"] == OPENROUTER_MAX_OUTPUT_TOKENS

    @patch("app.agents.llm.client.ChatOpenRouter")
    @patch("app.agents.llm.client.settings")
    def test_caches_per_temperature(
        self, mock_settings: MagicMock, mock_chat_openrouter: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = False
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_chat_openrouter.side_effect = lambda **_: MagicMock()

        assert get_default_llm() is get_default_llm()
        assert get_default_llm() is not get_default_llm(temperature=0.7)
        assert mock_chat_openrouter.call_count == 2

    @patch("app.agents.llm.client.settings")
    def test_no_openrouter_key_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.GAIA_SIM_MODE = False
        mock_settings.OPENROUTER_API_KEY = None

        with pytest.raises(LLMNotConfiguredError, match="Default LLM not configured"):
            get_default_llm()

    @patch("app.agents.llm.client._sim_llm")
    @patch("app.agents.llm.client.settings")
    def test_sim_mode_returns_stub_client(
        self, mock_settings: MagicMock, mock_sim_llm: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = True
        mock_settings.GOOGLE_API_KEY = None

        assert get_default_llm() is mock_sim_llm.return_value


# ---------------------------------------------------------------------------
# ainvoke_llm — the single LLM invocation primitive (retry + fallback)
# ---------------------------------------------------------------------------


class TestAinvokeLlm:
    @staticmethod
    def _runnable(side_effect: Any = None, result: Any = None) -> NonCallableMagicMock:
        # with_llm_retry calls runnable.with_retry(...) -> return self so the mock
        # .ainvoke is what actually runs (the real retry is LangChain's concern).
        # NonCallable because real Runnables aren't callable — ainvoke_llm treats
        # a callable fallback as a lazy factory.
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(side_effect=side_effect, return_value=result)
        return runnable

    async def test_primary_success(self) -> None:
        primary = self._runnable(result=AIMessage(content="ok"))
        result = await ainvoke_llm(primary, [HumanMessage(content="hi")])
        assert result.content == "ok"

    @patch("app.agents.llm.client.log")
    async def test_falls_back_to_default_on_provider_error(self, mock_log: MagicMock) -> None:
        primary = self._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._runnable(result=AIMessage(content="fallback-ok"))

        result = await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback)

        assert result.content == "fallback-ok"
        # The fallback path is retry-wrapped too.
        fallback.with_retry.assert_called_once()

    @patch("app.agents.llm.client.log")
    async def test_fallback_factory_called_lazily(self, mock_log: MagicMock) -> None:
        fallback = self._runnable(result=AIMessage(content="fallback-ok"))
        factory = MagicMock(return_value=fallback)

        ok_primary = self._runnable(result=AIMessage(content="ok"))
        assert (
            await ainvoke_llm(ok_primary, [HumanMessage(content="hi")], fallback=factory)
        ).content == "ok"
        factory.assert_not_called()

        failing_primary = self._runnable(side_effect=ConnectionError("provider down"))
        result = await ainvoke_llm(failing_primary, [HumanMessage(content="hi")], fallback=factory)
        assert result.content == "fallback-ok"
        factory.assert_called_once()

    async def test_fallback_factory_returning_none_reraises(self) -> None:
        primary = self._runnable(side_effect=ConnectionError("provider down"))
        with pytest.raises(ConnectionError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=lambda: None)

    async def test_reraises_provider_error_when_no_fallback(self) -> None:
        primary = self._runnable(side_effect=ConnectionError("provider down"))
        with pytest.raises(ConnectionError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")])

    async def test_programming_error_propagates_not_downgraded(self) -> None:
        primary = self._runnable(side_effect=ValueError("a real bug"))
        fallback = self._runnable(result=AIMessage(content="must-not-be-used"))

        with pytest.raises(ValueError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback)
        fallback.ainvoke.assert_not_called()

    async def test_attaches_usage_handler_by_default(self) -> None:
        primary = self._runnable(result=AIMessage(content="ok"))
        await ainvoke_llm(primary, [HumanMessage(content="hi")], config=RunnableConfig())
        assert primary.ainvoke.call_args.kwargs["config"]["callbacks"]

    async def test_graph_calls_skip_auxiliary_metering(self) -> None:
        # The agent graph is metered by LLMAccountingMiddleware; attaching the
        # usage handler here too booked every graph call a second time.
        primary = self._runnable(result=AIMessage(content="ok"))
        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=RunnableConfig(),
            meter_auxiliary=False,
        )
        assert "callbacks" not in primary.ainvoke.call_args.kwargs["config"]


# ---------------------------------------------------------------------------
# register_llm_providers
# ---------------------------------------------------------------------------


class TestRegisterLlmProviders:
    @patch("app.agents.llm.client.init_custom_llm")
    @patch("app.agents.llm.client.init_openrouter_llm")
    @patch("app.agents.llm.client.init_gemini_llm")
    def test_calls_all_init_functions(
        self,
        mock_gemini: MagicMock,
        mock_openrouter: MagicMock,
        mock_custom: MagicMock,
    ) -> None:
        register_llm_providers()

        mock_gemini.assert_called_once()
        mock_openrouter.assert_called_once()
        # conftest sets ENV=development, where the dev-only custom provider registers.
        mock_custom.assert_called_once()

    @patch("app.agents.llm.client.init_custom_llm")
    @patch("app.agents.llm.client.init_openrouter_llm")
    @patch("app.agents.llm.client.init_gemini_llm")
    def test_custom_not_registered_outside_development(
        self,
        mock_gemini: MagicMock,
        mock_openrouter: MagicMock,
        mock_custom: MagicMock,
    ) -> None:
        with patch("app.agents.llm.client.settings") as mock_settings:
            mock_settings.ENV = "production"
            register_llm_providers()

        mock_gemini.assert_called_once()
        mock_openrouter.assert_called_once()
        mock_custom.assert_not_called()


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestConstants:
    def test_provider_models_keys(self) -> None:
        assert set(PROVIDER_MODELS.keys()) == {"gemini", "openrouter", "custom"}

    def test_provider_priority_values(self) -> None:
        assert set(PROVIDER_PRIORITY.values()) == {"gemini", "openrouter", "custom"}

    def test_provider_priority_is_ordered(self) -> None:
        sorted_keys = sorted(PROVIDER_PRIORITY.keys())
        providers_in_order = [PROVIDER_PRIORITY[k] for k in sorted_keys]
        assert providers_in_order == ["openrouter", "gemini", "custom"]

    def test_retryable_exceptions_contains_expected_types(self) -> None:
        from google.genai.errors import ServerError

        # Gemini 5xx (google-genai SDK) + stdlib transient types must all be
        # retryable. The tuple is provider-agnostic, so it is a superset (also
        # covers the OpenRouter SDK transient errors) — assert containment.
        expected = {ServerError, ConnectionError, TimeoutError}
        assert expected.issubset(set(LLM_RETRYABLE_EXCEPTIONS))

    def test_retryable_exceptions_isinstance_check(self) -> None:
        from google.genai.errors import ServerError

        exc = ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        assert isinstance(exc, LLM_RETRYABLE_EXCEPTIONS)

    def test_gemini_runtime_errors_covered_by_fallback_set(self) -> None:
        # Regression guard: langchain-google-genai wraps 4xx into
        # ChatGoogleGenerativeAIError and lets google-genai ServerError (5xx)
        # propagate raw — the sets must be built from THOSE classes, not the
        # legacy google-api-core hierarchy the SDK no longer raises.
        from google.genai.errors import APIError, ClientError, ServerError
        from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

        for cls in (ChatGoogleGenerativeAIError, ServerError, ClientError, APIError):
            assert issubclass(cls, LLM_FALLBACK_EXCEPTIONS), cls.__name__

    def test_non_retryable_exception_not_in_tuple(self) -> None:
        assert not isinstance(ValueError("bad"), LLM_RETRYABLE_EXCEPTIONS)
        assert not isinstance(KeyError("missing"), LLM_RETRYABLE_EXCEPTIONS)


# ---------------------------------------------------------------------------
# chatbot (from chatbot.py)
# ---------------------------------------------------------------------------


class TestChatbot:
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_chatbot_default_path(
        self, mock_get_default: MagicMock, mock_ainvoke: AsyncMock
    ) -> None:
        mock_model = MagicMock()
        mock_get_default.return_value = mock_model
        mock_ainvoke.return_value = AIMessage(content="default response")

        messages = [HumanMessage(content="hello")]
        result = await chatbot(messages)

        mock_get_default.assert_called_once()
        mock_ainvoke.assert_called_once_with(mock_model, messages, label="chatbot")
        assert result["messages"][0].content == "default response"

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_chatbot_no_provider_logs_and_raises(
        self, mock_get_default: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_get_default.side_effect = LLMNotConfiguredError("no providers")

        with pytest.raises(LLMNotConfiguredError):
            await chatbot([HumanMessage(content="hello")])

        mock_log.error.assert_called_once()

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_chatbot_provider_error_logs_and_raises(
        self, mock_get_default: MagicMock, mock_ainvoke: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.side_effect = ConnectionError("provider down")

        with pytest.raises(ConnectionError, match="provider down"):
            await chatbot([HumanMessage(content="hello")])

        mock_log.error.assert_called_once()

    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_chatbot_programming_bug_propagates(
        self, mock_get_default: MagicMock, mock_ainvoke: AsyncMock
    ) -> None:
        # Bare RuntimeError is a programming bug, not an operational failure —
        # it must fail loud instead of degrading to the friendly message.
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.side_effect = RuntimeError("event loop is closed")

        with pytest.raises(RuntimeError, match="event loop is closed"):
            await chatbot([HumanMessage(content="hello")])


# ---------------------------------------------------------------------------
# _record_auxiliary_usage
# ---------------------------------------------------------------------------


class TestRecordAuxiliaryUsage:
    """What one-shot helper spend gets booked as.

    ``ainvoke_structured`` runs outside the agent graph, so
    ``LLMAccountingMiddleware`` never sees it — this is the only place auxiliary
    COGS is recorded. ``record_llm_call`` is the persistence seam and is the only
    thing mocked; the real ``UsageMetadataCallbackHandler`` carries the usage.
    """

    @staticmethod
    def _handler(**usage_by_model: dict[str, Any]) -> UsageMetadataCallbackHandler:
        handler = UsageMetadataCallbackHandler()
        handler.usage_metadata = dict(usage_by_model)
        return handler

    async def test_books_reasoning_tokens_from_the_output_details(self) -> None:
        """Reasoning tokens are billed and priced separately, so losing them
        under-reports the cost of every reasoning-model helper call."""
        handler = self._handler(
            gemini={
                "input_tokens": 100,
                "output_tokens": 20,
                "output_token_details": {"reasoning": 77},
            }
        )

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.5)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        assert rec.call_args.kwargs["reasoning_tokens"] == 77

    async def test_reasoning_defaults_to_zero_without_output_details(self) -> None:
        """A non-reasoning model sends no ``output_token_details`` at all; that
        must book zero rather than a placeholder."""
        handler = self._handler(gemini={"input_tokens": 100, "output_tokens": 20})

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.5)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        assert rec.call_args.kwargs["reasoning_tokens"] == 0

    async def test_an_explicit_zero_reasoning_count_stays_zero(self) -> None:
        handler = self._handler(
            gemini={
                "input_tokens": 100,
                "output_tokens": 20,
                "output_token_details": {"reasoning": 0},
            }
        )

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.5)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        assert rec.call_args.kwargs["reasoning_tokens"] == 0

    async def test_books_the_whole_token_breakdown_and_never_the_budget(self) -> None:
        """``charge_to_budget=False`` is the load-bearing part: background work
        GAIA does on the user's behalf must not eat their chat allowance."""
        handler = self._handler(
            gemini={
                "input_tokens": 100,
                "output_tokens": 20,
                "input_token_details": {"cache_read": 40},
                "output_token_details": {"reasoning": 7},
            }
        )

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.5)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        assert rec.call_args.kwargs == {
            "user_id": "user-1",
            "model_name": "gemini",
            "input_tokens": 100,
            "output_tokens": 20,
            "cached_tokens": 40,
            "reasoning_tokens": 7,
            "charge_to_budget": False,
        }

    async def test_a_call_that_burned_no_tokens_is_not_booked(self) -> None:
        handler = self._handler(gemini={"input_tokens": 0, "output_tokens": 0})

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock()) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        rec.assert_not_called()

    async def test_every_model_in_one_run_is_booked(self) -> None:
        """A retry that fell back to another provider leaves two models on the
        handler; booking only the first under-reports the run."""
        handler = self._handler(
            gemini={"input_tokens": 10, "output_tokens": 1},
            openrouter={
                "input_tokens": 20,
                "output_tokens": 2,
                "output_token_details": {"reasoning": 5},
            },
        )

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.1)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        booked = {c.kwargs["model_name"]: c.kwargs["reasoning_tokens"] for c in rec.call_args_list}
        assert booked == {"gemini": 0, "openrouter": 5}

    async def test_spend_without_a_user_id_is_still_booked(self) -> None:
        """A threading gap must not silently drop the COGS — it is warned about
        and recorded against no user, never skipped."""
        handler = self._handler(gemini={"input_tokens": 100, "output_tokens": 20})

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.5)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", None)

        assert rec.call_args.kwargs["user_id"] is None


class TestAuxiliaryMeteringWiring:
    """The plumbing between ``ainvoke_llm`` and the metering call: which config
    the provider is handed, and what reaches ``_record_auxiliary_usage``."""

    @staticmethod
    def _reporting_runnable(usage: dict[str, Any]) -> NonCallableMagicMock:
        """A runnable that reports token usage the way a real provider does —
        through the ``UsageMetadataCallbackHandler`` attached to its config."""

        async def _ainvoke(_messages: Any, config: RunnableConfig | None = None) -> AIMessage:
            for handler in (config or {}).get("callbacks") or []:
                if isinstance(handler, UsageMetadataCallbackHandler):
                    handler.usage_metadata = {"gemini": usage}
            return AIMessage(content="ok")

        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(side_effect=_ainvoke)
        return runnable

    async def test_the_config_user_id_is_who_the_spend_is_booked_against(self) -> None:
        """``configurable.user_id`` is the only thread between the caller and the
        COGS row; dropping it books every helper call against nobody."""
        primary = self._reporting_runnable({"input_tokens": 10, "output_tokens": 2})

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.1)) as rec:
            await ainvoke_llm(
                primary,
                [HumanMessage(content="hi")],
                config=RunnableConfig(configurable={"user_id": "user-9"}),
                label="memory_extraction",
            )

        assert rec.call_args.kwargs["user_id"] == "user-9"

    async def test_unattributed_spend_is_warned_about_with_its_label(self) -> None:
        """The warning is the only trail back to which helper leaked its user_id,
        so the label has to be on the recorded event, not just in the message."""
        log.reset()
        primary = self._reporting_runnable({"input_tokens": 10, "output_tokens": 2})

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.1)):
            await ainvoke_llm(
                primary,
                [HumanMessage(content="hi")],
                config=RunnableConfig(),
                label="memory_extraction",
            )

        warned = [w for w in log.get().get("warnings", []) if w.get("llm")]
        assert [w["llm"]["label"] for w in warned] == ["memory_extraction"]

    async def test_skipping_metering_still_forwards_the_caller_config(self) -> None:
        """``meter_auxiliary=False`` only means "attach no handler". Replacing the
        caller's config with a fresh one strips ``configurable`` — the graph's
        thread id, user id and run metadata all travel in there."""
        primary = self._reporting_runnable({"input_tokens": 10, "output_tokens": 2})

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=RunnableConfig(configurable={"user_id": "user-9"}),
            meter_auxiliary=False,
        )

        forwarded = primary.ainvoke.call_args.kwargs["config"]
        assert forwarded["configurable"] == {"user_id": "user-9"}


class TestAinvokeStructured:
    """The one canonical one-shot structured call.

    It runs on ``get_helper_llm``, not ``get_default_llm``: structured output is
    always a small JSON blob, so reserving the full output budget for it wastes
    the reservation on every helper call in the app.
    """

    class _Schema(BaseModel):
        answer: str

    async def test_runs_on_the_capped_helper_model_with_the_requested_schema(self) -> None:
        structured = MagicMock(name="structured_runnable")
        helper = MagicMock()
        helper.with_structured_output = MagicMock(return_value=structured)

        with (
            patch("app.agents.llm.client.get_helper_llm", return_value=helper) as mock_helper,
            patch(
                "app.agents.llm.client.ainvoke_llm",
                new=AsyncMock(return_value=self._Schema(answer="42")),
            ) as mock_invoke,
        ):
            result = await ainvoke_structured(
                self._Schema, "what is the answer?", label="the_judge", temperature=0.3
            )

        assert mock_helper.call_args.kwargs["temperature"] == 0.3
        assert helper.with_structured_output.call_args.args[0] is self._Schema
        assert mock_invoke.call_args.args[0] is structured
        assert result.answer == "42"

    async def test_the_label_and_config_reach_the_invoke(self) -> None:
        """``label`` names the call in the COGS event and ``config`` carries the
        user the spend is attributed to; losing either drops the attribution."""
        helper = MagicMock()
        helper.with_structured_output = MagicMock(return_value=MagicMock())
        config = RunnableConfig(configurable={"user_id": "user-3"})

        with (
            patch("app.agents.llm.client.get_helper_llm", return_value=helper),
            patch(
                "app.agents.llm.client.ainvoke_llm",
                new=AsyncMock(return_value=self._Schema(answer="ok")),
            ) as mock_invoke,
        ):
            await ainvoke_structured(
                self._Schema, "prompt", label="memory_extraction", config=config
            )

        assert mock_invoke.call_args.kwargs["label"] == "memory_extraction"
        assert mock_invoke.call_args.kwargs["config"] is config


class TestProviderModelFieldId:
    """Both provider lanes must read the model from the SAME configurable key.

    They historically did not. Gemini's ``model`` attribute was bound to the
    field id ``"model_name"`` while OpenRouter's ``model_name`` attribute was
    bound to the field id ``"model"`` — two swapped ids sharing one flat
    namespace (``prefix_keys=False``). That collision is the entire reason every
    writer had to set both keys, and why a configurable carrying only one of them
    silently resolved a *different* model than the one it named.

    Scope: the OpenRouter case is exercised end-to-end through the real registry.
    The Gemini case is asserted on the field id directly, because the hermetic
    env blanks ``GOOGLE_API_KEY`` and the provider therefore resolves to ``None``
    — there is no Gemini client to drive here. The id is the whole contract.
    """

    @staticmethod
    def _resolved_model(llm: Any, configurable: dict[str, str]) -> str | None:
        runnable, _ = llm._prepare({"configurable": configurable})
        return getattr(runnable, "model", None)

    def test_openrouter_exposes_its_model_under_the_same_id(self) -> None:
        """Driven through the real wire helper rather than the provider registry:
        the hermetic fence blanks OPENROUTER_API_KEY, so the registered provider
        is ``None`` in CI and there is no client to resolve. The client is
        constructed here with a dummy key — no network, construction only."""
        llm = _openrouter_wire_configurables(
            ChatOpenRouter(model="vendor/default", api_key=SecretStr("test-key"))
        )

        assert self._resolved_model(llm, {"model": "vendor/probe-model"}) == "vendor/probe-model"
        assert self._resolved_model(llm, {"model_name": "legacy"}) != "legacy"

    def test_gemini_declares_its_model_under_the_same_id_as_openrouter(self) -> None:
        assert _MODEL_FIELD.id == "model"


class TestFallbackRunsOnTheOtherProvider:
    """The fallback must actually leave the failed lane.

    Regression: the fallback runnable carried its lane via ``with_config``, but the
    invoke re-passed the run's own config — and LangChain merges a passed config
    OVER a bound one, so the just-failed provider, model and pin were all restored
    and the "failover" retried the same dead lane. Nothing caught it because no
    test drove the fallback path with a real config attached.
    """

    @pytest.mark.regression
    async def test_the_fallback_attempt_does_not_inherit_the_failed_lane(self) -> None:
        seen: dict[str, Any] = {}

        def _record(_input: Any, config: RunnableConfig | None = None) -> AIMessage:
            seen.update((config or {}).get("configurable", {}))
            return AIMessage(content="from-fallback")

        def _boom(_input: Any, config: RunnableConfig | None = None) -> AIMessage:
            raise ConnectionError("primary down")

        primary = RunnableLambda(_boom)
        failed_lane_config: RunnableConfig = cast(
            RunnableConfig,
            {
                "configurable": {
                    "provider": "openrouter",
                    "model": "dead-model",
                    "model_kwargs": {"provider": {"only": ["dead-vendor"]}},
                }
            },
        )
        fallback_config: RunnableConfig = cast(
            RunnableConfig, {"configurable": {"provider": "gemini", "model": "gemini-x"}}
        )

        result = await ainvoke_llm(
            primary,
            "hi",
            fallback=RunnableLambda(_record),
            config=failed_lane_config,
            fallback_config=fallback_config,
        )

        assert result.content == "from-fallback"
        assert seen["provider"] == "gemini"
        assert seen["model"] == "gemini-x"
        # the dead lane's routing pin must not ride along to the new provider
        assert "model_kwargs" not in seen
