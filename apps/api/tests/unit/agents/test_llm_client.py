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

import asyncio
from collections.abc import Iterator
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
    _meter_discarded_replay,
    _openrouter_wire_configurables,
    _record_auxiliary_usage,
    _silenced,
    _stamp_fallback,
    ainvoke_llm,
    ainvoke_structured,
    ainvoke_structured_gemini,
    get_default_llm,
    init_llm,
    register_llm_providers,
)
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, LLMNotConfiguredError
from app.agents.llm.types import LLMProviderName
from app.constants.llm import (
    AUX_MODEL_NAME,
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_MODEL_NAME,
    OPENROUTER_MAX_OUTPUT_TOKENS,
    STICKY_FLIP_RETRY_MIN_INPUT,
)
from app.constants.log_tags import LogTag
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


class TestFallbackHandover:
    """What the fallback is handed when the primary fails: the conversation's
    sticky session, the caller's messages, a metered config — and a run stamped
    so the rest of the run skips the broken primary."""

    @staticmethod
    def _bindable_runnable(result: Any) -> NonCallableMagicMock:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.bind = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(return_value=result)
        return runnable

    @patch("app.agents.llm.client.log")
    async def test_the_fallback_inherits_the_conversation_sticky_session(
        self, mock_log: MagicMock
    ) -> None:
        """The key is BOUND on the runnable, not left in config.

        A config-carried session_id is dropped before the wire, so a fallback
        that only inherited the config would land on a provider with no warm
        cache for this conversation.
        """
        primary = TestAinvokeLlm._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._bindable_runnable(AIMessage(content="fallback-ok"))
        config = RunnableConfig(configurable={"user_id": "u1", "session_id": "conv-1"})
        messages = [HumanMessage(content="hi")]

        result = await ainvoke_llm(primary, messages, fallback=fallback, config=config)

        assert result.content == "fallback-ok"
        # Suffixed: this call is auxiliary (meter_auxiliary defaults True), and an
        # aux request must keep its own sticky session on the fallback too — the
        # conversation's key would re-pin its provider from a background call.
        assert fallback.bind.call_args.kwargs == {"session_id": "conv-1-aux"}
        assert fallback.ainvoke.call_args.args[0] is messages
        forwarded = fallback.ainvoke.call_args.kwargs["config"]
        assert forwarded["configurable"]["session_id"] == "conv-1"
        # The auxiliary meter rides along on the fallback attempt too — its
        # tokens are as real as the primary's.
        assert any(
            isinstance(handler, UsageMetadataCallbackHandler) for handler in forwarded["callbacks"]
        )

    @patch("app.agents.llm.client.log")
    async def test_the_downgrade_warning_names_the_call_that_fell_back(
        self, mock_log: MagicMock
    ) -> None:
        """The warning is the only record of a downgrade; unlabelled it cannot
        be attributed to a caller."""
        primary = TestAinvokeLlm._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._bindable_runnable(AIMessage(content="fallback-ok"))

        await ainvoke_llm(
            primary, [HumanMessage(content="hi")], fallback=fallback, label="the_judge"
        )

        assert mock_log.warning.call_args.kwargs["llm"] == {
            "label": "the_judge",
            "error_type": "ConnectionError",
            "fell_back": True,
        }


def _replay_result(content: str, *, prompt: int, cached: int) -> AIMessage:
    """A provider answer carrying the usage the sticky-flip gate reads."""
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": 5,
            "total_tokens": prompt + 5,
            "input_token_details": {"cache_read": cached},
        },
    )


def _replaying_primary(first: Any, second: Any) -> NonCallableMagicMock:
    """A primary that answers ``first``, then ``second`` on the replay."""
    runnable = NonCallableMagicMock()
    runnable.with_retry = MagicMock(return_value=runnable)
    runnable.ainvoke = AsyncMock(side_effect=[first, second])
    return runnable


# Only the graph lane of a sticky-routing provider replays at all, so the
# thresholds and the replay's own wiring are unreachable without one.
_STICKY_LANE = RunnableConfig(configurable={"provider": "openrouter"})


@pytest.fixture
def booked_replay() -> Iterator[AsyncMock]:
    """The metering seam a fired replay reaches, stubbed.

    A replay meters its discarded first answer through ``record_llm_call``,
    which prices the model and writes the spend — real I/O the unit tier must
    not do, and the seam these tests read to see what was booked.
    """
    with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.25)) as rec:
        yield rec


class TestStickyFlipReplayThresholds:
    """The cold-cache replay fires on a big prompt whose cache came back cold,
    and on nothing else: a re-send costs a whole extra request."""

    async def test_a_prompt_exactly_at_the_input_floor_is_replayed(
        self, booked_replay: AsyncMock
    ) -> None:
        """The floor is inclusive — a prompt that just reaches it still counts."""
        primary = _replaying_primary(
            _replay_result("cold", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=0),
            _replay_result("warm", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=7_900),
        )

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            meter_auxiliary=False,
        )

        # "cold" — the answer the user already watched stream. The replay is a
        # cache-warming write, so its answer is discarded rather than returned;
        # returning it would persist text that differs from what was on screen.
        assert result.content == "cold"
        assert primary.ainvoke.await_count == 2

    async def test_a_prompt_just_under_the_input_floor_is_not_replayed(self) -> None:
        """Under the floor the prompt is too small for a re-send to pay off."""
        prompt = STICKY_FLIP_RETRY_MIN_INPUT - 1
        primary = _replaying_primary(
            _replay_result("cold", prompt=prompt, cached=0),
            _replay_result("unused", prompt=prompt, cached=prompt),
        )

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            meter_auxiliary=False,
        )

        assert result.content == "cold"
        assert primary.ainvoke.await_count == 1

    async def test_a_hit_rate_exactly_at_the_floor_is_not_replayed(self) -> None:
        """At the floor the cache is warm enough; re-sending would just pay twice."""
        prompt = 10_000
        primary = _replaying_primary(
            _replay_result("warm", prompt=prompt, cached=int(prompt * 0.92)),
            _replay_result("unused", prompt=prompt, cached=prompt),
        )

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            meter_auxiliary=False,
        )

        assert result.content == "warm"
        assert primary.ainvoke.await_count == 1

    async def test_auxiliary_metering_is_on_unless_a_caller_opts_out(self) -> None:
        """The default is what one-shot callers get without thinking about it.

        Auxiliary calls (vision, summaries, memory extraction) have no graph
        middleware charging them, so this handler IS their accounting — if it
        silently defaults off, their tokens are spent and never booked, and
        nothing anywhere fails.
        """
        primary = NonCallableMagicMock()
        primary.with_retry = MagicMock(return_value=primary)
        primary.ainvoke = AsyncMock(return_value=AIMessage(content="hi"))

        await ainvoke_llm(primary, [HumanMessage(content="hi")])

        callbacks = primary.ainvoke.await_args.kwargs["config"]["callbacks"]
        assert any(isinstance(handler, UsageMetadataCallbackHandler) for handler in callbacks)

    async def test_opting_out_of_auxiliary_metering_attaches_no_handler(self) -> None:
        # The graph lane passes meter_auxiliary=False because
        # LLMAccountingMiddleware already charges the call; attaching here too
        # would book it twice.
        primary = NonCallableMagicMock()
        primary.with_retry = MagicMock(return_value=primary)
        primary.ainvoke = AsyncMock(return_value=AIMessage(content="hi"))

        await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=False)

        callbacks = primary.ainvoke.await_args.kwargs["config"].get("callbacks") or []
        assert not any(isinstance(handler, UsageMetadataCallbackHandler) for handler in callbacks)

    async def test_a_result_that_carries_no_usage_at_all_is_returned_as_is(self) -> None:
        """Structured runnables return a plain schema instance — no usage
        attribute to read, and nothing to decide a replay on."""
        parsed = _Extracted(fact="remembered")
        primary = NonCallableMagicMock()
        primary.with_retry = MagicMock(return_value=primary)
        primary.ainvoke = AsyncMock(return_value=parsed)

        result = await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=False)

        assert result is parsed
        assert primary.ainvoke.await_count == 1


class TestStickyFlipReplayIsSentLikeTheFirstCall:
    """What the re-send itself carries. The replay's answer is the one the user
    gets and the one graph state meters, so anything the first call had and it
    lacks is silently dropped from the turn."""

    _FIRST = _replay_result("cold", prompt=10_000, cached=0)
    _SECOND = _replay_result("warm", prompt=10_000, cached=9_900)

    async def test_the_replay_re_sends_the_same_prompt(self, booked_replay: AsyncMock) -> None:
        """Re-sending anything else answers a different question — and the
        answer to THAT is what the user would receive."""
        primary = _replaying_primary(self._FIRST, self._SECOND)
        messages = [HumanMessage(content="hi")]

        await ainvoke_llm(primary, messages, config=_STICKY_LANE, meter_auxiliary=False)

        assert [call.args[0] for call in primary.ainvoke.await_args_list] == [messages, messages]

    async def test_the_replay_inherits_the_caller_lane_and_is_silenced(
        self, booked_replay: AsyncMock
    ) -> None:
        """The re-send must land on the same provider (that is the whole point
        of re-sending) but must not stream: both answers share one SSE stream,
        so an unsilenced replay appends a second answer to the first."""
        primary = _replaying_primary(self._FIRST, self._SECOND)

        await ainvoke_llm(
            primary, [HumanMessage(content="hi")], config=_STICKY_LANE, meter_auxiliary=False
        )

        first, replay = (call.kwargs["config"] for call in primary.ainvoke.await_args_list)
        assert replay["configurable"] == _STICKY_LANE["configurable"]
        assert replay["metadata"]["silent"] is True
        assert "silent" not in (first.get("metadata") or {})

    async def test_the_replay_gets_one_attempt_while_the_first_call_keeps_its_budget(
        self, booked_replay: AsyncMock
    ) -> None:
        """The replay is an optimisation on a latency budget — retrying it pays
        for a third request to save a cache miss. The first call is the one the
        turn depends on and keeps the caller's retry budget."""
        primary = _replaying_primary(self._FIRST, self._SECOND)

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            meter_auxiliary=False,
            max_attempts=2,
        )

        assert [
            call.kwargs["stop_after_attempt"] for call in primary.with_retry.call_args_list
        ] == [2, 1]

    @patch("app.agents.llm.client.log")
    async def test_a_failed_replay_is_warned_about_by_name(
        self, mock_log: MagicMock, booked_replay: AsyncMock
    ) -> None:
        """The first answer is already in hand, so the caller sees nothing — this
        warning is the only trace that the re-send cost a request and failed."""
        primary = _replaying_primary(self._FIRST, ConnectionError("provider down"))

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            label="the_judge",
            meter_auxiliary=False,
        )

        assert result is self._FIRST
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} sticky-flip replay failed; keeping the first response",
            agent_name="the_judge",
            error="provider down",
        )
        booked_replay.assert_not_awaited()

    @patch("app.agents.llm.client.log")
    async def test_the_discarded_answer_is_booked_against_the_calling_agent(
        self, mock_log: MagicMock, booked_replay: AsyncMock
    ) -> None:
        """``label`` is how the discarded spend is attributed; unlabelled it
        cannot be traced back to the caller that paid for it."""
        primary = _replaying_primary(self._FIRST, self._SECOND)

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            label="the_judge",
            meter_auxiliary=False,
        )

        booked_replay.assert_awaited_once()
        assert mock_log.info.call_args.kwargs["agent_name"] == "the_judge"


class TestSilenced:
    """``_silenced`` stamps the flag the SSE consumer skips message chunks on."""

    def test_the_flag_is_added_without_dropping_the_metadata_already_there(self) -> None:
        """The rest of the metadata is what the run is traced and attributed by;
        replacing the dict instead of merging into it loses all of it."""
        config = RunnableConfig(metadata={"langfuse_session_id": "s-1"}, tags=["graph"])

        silenced = _silenced(config)

        assert silenced["metadata"] == {"langfuse_session_id": "s-1", "silent": True}
        assert silenced["tags"] == ["graph"]

    def test_the_caller_config_is_left_alone(self) -> None:
        """Callers pass shared module-level configs and live graph configs — a
        stamp written in place silences every later call that reuses one."""
        config = RunnableConfig(metadata={"langfuse_session_id": "s-1"})

        _silenced(config)

        assert config["metadata"] == {"langfuse_session_id": "s-1"}

    def test_a_config_with_no_metadata_yet_gets_only_the_flag(self) -> None:
        assert _silenced(RunnableConfig())["metadata"] == {"silent": True}


class TestMeterDiscardedReplay:
    """Who pays for the answer the replay threw away.

    The discarded first invocation never lands in graph state, so
    ``LLMAccountingMiddleware`` cannot see it — this seam is its only accounting.
    """

    _DISCARDED = AIMessage(
        content="cold",
        response_metadata={"model_name": "served/model"},
        usage_metadata={
            "input_tokens": 10_000,
            "output_tokens": 40,
            "total_tokens": 10_040,
            "input_token_details": {"cache_read": 100},
            "output_token_details": {"reasoning": 7},
        },
    )

    async def test_the_whole_token_breakdown_is_booked_to_the_budget(
        self, booked_replay: AsyncMock
    ) -> None:
        """The user asked for this turn, so unlike auxiliary COGS the discarded
        request counts against their allowance — and every token class is priced
        separately, so a dropped field under-reports the spend."""
        config = RunnableConfig(configurable={"user_id": "u-1", "root_request_id": "r-1"})

        await _meter_discarded_replay(self._DISCARDED, config, "the_judge")

        assert booked_replay.await_args.kwargs == {
            "user_id": "u-1",
            "model_name": "served/model",
            "input_tokens": 10_000,
            "output_tokens": 40,
            "cached_tokens": 100,
            "reasoning_tokens": 7,
            "root_request_id": "r-1",
            "charge_to_budget": True,
        }

    async def test_a_discarded_non_message_is_not_booked(self, booked_replay: AsyncMock) -> None:
        """Structured runnables return a schema instance, which carries no usage
        to price at all."""
        await _meter_discarded_replay(_Extracted(fact="remembered"), None, "the_judge")

        booked_replay.assert_not_awaited()


# ---------------------------------------------------------------------------
# ainvoke_structured_gemini — memory-lane provider selection
# ---------------------------------------------------------------------------


class _Extracted(BaseModel):
    fact: str


class TestMemoryLaneProviderSelection:
    """The direct-Gemini memory lane is a cache-isolation optimisation, not a
    requirement. A deployment with only OPENROUTER_API_KEY — the documented
    self-host path — must still extract memories, and a Gemini outage must not
    silently drop every extraction for its duration."""

    @patch("app.agents.llm.client.ainvoke_structured", new_callable=AsyncMock)
    @patch("app.agents.llm.client.get_memory_llm")
    @patch("app.agents.llm.client.memory_lane_available", return_value=False)
    async def test_falls_back_to_the_aux_lane_when_google_is_unconfigured(
        self, mock_available: MagicMock, mock_memory_llm: MagicMock, mock_aux: AsyncMock
    ) -> None:
        mock_aux.return_value = _Extracted(fact="from-aux")
        config = RunnableConfig(configurable={"user_id": "u1"})

        result = await ainvoke_structured_gemini(
            _Extracted,
            "transcript",
            label="memory:extract",
            temperature=0.4,
            config=config,
            timeout=9.0,
        )

        assert result.fact == "from-aux"
        mock_memory_llm.assert_not_called()
        # The handover is the whole call, not just the schema: a dropped
        # argument here silently re-defaults it on the lane that actually runs.
        assert mock_aux.await_args.args[0] is _Extracted
        assert mock_aux.await_args.args[1] == "transcript"
        assert mock_aux.await_args.kwargs == {
            "label": "memory:extract",
            "temperature": 0.4,
            "config": config,
            "timeout": 9.0,
        }

    @patch("app.agents.llm.client._aux_structured_runnable")
    @patch("app.agents.llm.client.ainvoke_llm", new_callable=AsyncMock)
    @patch("app.agents.llm.client.get_memory_llm")
    @patch("app.agents.llm.client.memory_lane_available", return_value=True)
    async def test_gemini_is_preferred_and_carries_an_aux_fallback(
        self,
        mock_available: MagicMock,
        mock_memory_llm: MagicMock,
        mock_ainvoke: AsyncMock,
        mock_aux_runnable: MagicMock,
    ) -> None:
        mock_ainvoke.return_value = _Extracted(fact="from-gemini")
        config = RunnableConfig(configurable={"user_id": "u1"})
        structured = mock_memory_llm.return_value.with_structured_output.return_value

        result = await ainvoke_structured_gemini(
            _Extracted,
            "transcript",
            label="memory:extract",
            temperature=0.4,
            config=config,
            timeout=9.0,
        )

        assert result.fact == "from-gemini"
        mock_memory_llm.assert_called_once()
        assert mock_memory_llm.call_args.kwargs["temperature"] == 0.4
        assert mock_memory_llm.return_value.with_structured_output.call_args.args[0] is _Extracted
        # The handover is the whole call, not just the runnable: a dropped
        # argument here silently re-defaults it on the lane that actually runs.
        assert mock_ainvoke.await_args.args == (structured, "transcript")
        kwargs = dict(mock_ainvoke.await_args.kwargs)
        fallback = kwargs.pop("fallback")
        assert kwargs == {"config": config, "label": "memory:extract", "timeout": 9.0}
        # A Gemini outage has somewhere to go: ainvoke_llm gets a real fallback
        # factory instead of the None that dropped every extraction — and the
        # aux runnable it builds carries this call's schema, temperature and
        # config rather than a defaulted set.
        assert fallback() is mock_aux_runnable.return_value
        assert mock_aux_runnable.call_args.args == (_Extracted, 0.4, config)

    @patch("app.agents.llm.client.get_helper_llm")
    @patch("app.agents.llm.client.get_memory_llm")
    @patch("app.agents.llm.client.memory_lane_available", return_value=True)
    async def test_gemini_outage_is_served_by_the_aux_lane(
        self,
        mock_available: MagicMock,
        mock_memory_llm: MagicMock,
        mock_helper: MagicMock,
    ) -> None:
        failing = NonCallableMagicMock()
        failing.with_retry = MagicMock(return_value=failing)
        failing.ainvoke = AsyncMock(side_effect=ConnectionError("gemini down"))
        mock_memory_llm.return_value.with_structured_output.return_value = failing

        aux = NonCallableMagicMock()
        aux.with_retry = MagicMock(return_value=aux)
        aux.ainvoke = AsyncMock(return_value=_Extracted(fact="from-aux"))
        mock_helper.return_value.model_copy.return_value.with_structured_output.return_value = aux

        result = await ainvoke_structured_gemini(_Extracted, "transcript", label="memory:extract")

        assert result.fact == "from-aux"


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
    async def test_chatbot_runs_on_the_helper_model(
        self, mock_get_helper: MagicMock, mock_ainvoke: AsyncMock
    ) -> None:
        mock_model = MagicMock()
        mock_get_helper.return_value = mock_model
        mock_ainvoke.return_value = AIMessage(content="default response")

        messages = [HumanMessage(content="hello")]
        result = await chatbot(messages)

        mock_get_helper.assert_called_once()
        mock_ainvoke.assert_called_once_with(mock_model, messages, label="chatbot")
        assert result["messages"][0].content == "default response"

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_no_provider_is_raised_not_degraded(
        self, mock_get_helper: MagicMock, mock_log: MagicMock
    ) -> None:
        """Callers own how they degrade — chatbot never invents a friendly
        placeholder answer, because a swallowed failure reads as a real reply."""
        mock_get_helper.side_effect = LLMNotConfiguredError("no providers")

        with pytest.raises(LLMNotConfiguredError):
            await chatbot([HumanMessage(content="hello")])
        mock_log.error.assert_called_once()

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_provider_error_is_logged_and_reraised(
        self, mock_get_helper: MagicMock, mock_ainvoke: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_get_helper.return_value = MagicMock()
        mock_ainvoke.side_effect = ConnectionError("provider down")

        with pytest.raises(ConnectionError):
            await chatbot([HumanMessage(content="hello")])
        mock_log.error.assert_called_once()

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_helper_llm")
    async def test_chatbot_programming_bug_propagates_unlogged(
        self, mock_get_helper: MagicMock, mock_ainvoke: AsyncMock, mock_log: MagicMock
    ) -> None:
        # Bare RuntimeError is a programming bug, not an operational failure —
        # it is not caught at all, so it carries no operational error event.
        mock_get_helper.return_value = MagicMock()
        mock_ainvoke.side_effect = RuntimeError("event loop is closed")

        with pytest.raises(RuntimeError, match="event loop is closed"):
            await chatbot([HumanMessage(content="hello")])
        mock_log.error.assert_not_called()


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

    async def test_a_missing_count_books_zero_beside_a_present_one(self) -> None:
        """One absent token key must book 0, not a placeholder — a stand-in
        charges tokens that never existed on every such call."""
        handler = self._handler(gemini={"output_tokens": 20})

        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.0)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        assert rec.call_args.kwargs["input_tokens"] == 0
        assert rec.call_args.kwargs["output_tokens"] == 20

        handler = self._handler(gemini={"input_tokens": 100})
        with patch("app.agents.llm.client.record_llm_call", new=AsyncMock(return_value=0.0)) as rec:
            await _record_auxiliary_usage(handler, "memory_extraction", "user-1")

        assert rec.call_args.kwargs["input_tokens"] == 100
        assert rec.call_args.kwargs["output_tokens"] == 0

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

    async def test_runs_on_the_capped_helper_re_pointed_at_the_aux_model(self) -> None:
        """Both halves of this lane at once: the runnable is built FROM
        ``get_helper_llm`` (so the 8k output cap still applies) and then
        re-pointed at ``AUX_MODEL_NAME`` (so the call lands in its own cache
        namespace). Losing the first re-reserves 64k per helper call; losing
        the second puts aux blocks back in the conversation's namespace."""
        structured = MagicMock(name="structured_runnable")
        aux = MagicMock(name="aux_model")
        aux.with_structured_output = MagicMock(return_value=structured)
        helper = MagicMock()
        helper.model_copy = MagicMock(return_value=aux)

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
        assert helper.model_copy.call_args.kwargs["update"] == {"model_name": AUX_MODEL_NAME}
        assert aux.with_structured_output.call_args.args[0] is self._Schema
        assert mock_invoke.call_args.args[0] is structured
        assert result.answer == "42"

    async def test_the_label_and_config_reach_the_invoke(self) -> None:
        """``label`` names the call in the COGS event and ``config`` carries the
        user the spend is attributed to; losing either drops the attribution."""
        helper = MagicMock()
        helper.model_copy = MagicMock(return_value=MagicMock())
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

    async def test_the_prompt_and_timeout_reach_the_invoke(self) -> None:
        """The prompt is the call; the timeout is the ceiling the caller chose.

        A dropped timeout silently reverts to the module default, which is what
        an interactive caller with a tight budget is trying to avoid.
        """
        helper = MagicMock()
        helper.model_copy = MagicMock(return_value=MagicMock())
        prompt = [HumanMessage(content="classify this")]

        with (
            patch("app.agents.llm.client.get_helper_llm", return_value=helper),
            patch(
                "app.agents.llm.client.ainvoke_llm",
                new=AsyncMock(return_value=self._Schema(answer="ok")),
            ) as mock_invoke,
        ):
            await ainvoke_structured(self._Schema, prompt, label="classifier", timeout=12.0)

        assert mock_invoke.call_args.args[1] is prompt
        assert mock_invoke.call_args.kwargs["timeout"] == 12.0

    async def test_the_aux_lane_runs_on_its_own_sticky_session(self) -> None:
        """A suffixed session id, bound after ``with_structured_output``.

        Sharing the conversation's id re-pins its provider from a background
        one-shot; binding before the structured rebuild loses the key entirely,
        because ``bind_tools`` drops the outer binding's kwargs.
        """
        bound = MagicMock(name="bound_runnable")
        structured = MagicMock(name="structured_runnable")
        structured.bind = MagicMock(return_value=bound)
        aux = MagicMock(name="aux_model")
        aux.with_structured_output = MagicMock(return_value=structured)
        helper = MagicMock()
        helper.model_copy = MagicMock(return_value=aux)
        config = RunnableConfig(configurable={"session_id": "conv-1"})

        with (
            patch("app.agents.llm.client.get_helper_llm", return_value=helper),
            patch(
                "app.agents.llm.client.ainvoke_llm",
                new=AsyncMock(return_value=self._Schema(answer="ok")),
            ) as mock_invoke,
        ):
            await ainvoke_structured(self._Schema, "prompt", label="judge", config=config)

        assert structured.bind.call_args.kwargs == {"session_id": "conv-1-aux"}
        assert mock_invoke.call_args.args[0] is bound


class TestStampFallback:
    """The marker that tells the rest of the system a downgrade happened.

    It is the only signal that a reply came from the fallback model rather than
    the one the user is paying for: the SSE layer surfaces it and accounting
    prices against it. A blanked key here is invisible — the answer still
    arrives, just attributed to the wrong model.
    """

    def test_a_fallback_message_is_marked_with_the_model_that_produced_it(self) -> None:
        message = AIMessage(content="hi")

        stamped = _stamp_fallback(message)

        assert stamped is message
        assert message.response_metadata["gaia_fell_back"] is True
        assert message.response_metadata["gaia_fallback_model"] == DEFAULT_MODEL_NAME

    def test_existing_response_metadata_is_kept(self) -> None:
        # The provider's own metadata rides along; stamping must add to it, not
        # replace it, or the model/usage the provider reported is lost.
        message = AIMessage(content="hi", response_metadata={"finish_reason": "stop"})

        _stamp_fallback(message)

        assert message.response_metadata["finish_reason"] == "stop"
        assert message.response_metadata["gaia_fell_back"] is True

    def test_a_result_that_is_not_a_message_passes_through_untouched(self) -> None:
        # ainvoke_llm also serves structured calls, whose result is a pydantic
        # model with no response_metadata at all.
        result = object()

        assert _stamp_fallback(result) is result


# ---------------------------------------------------------------------------
# _record_auxiliary_usage
# ---------------------------------------------------------------------------


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


class TestStickyFlipReplayNeverChangesTheAnswer:
    """The replay warms the provider's chain for the next turn; it must not
    change this turn's answer. The first invocation streams to the user, the
    replay is silenced — so returning the replay's text would persist an answer
    the user never saw and show different content on reload."""

    async def test_the_streamed_answer_is_the_one_returned(self, booked_replay: AsyncMock) -> None:
        primary = _replaying_primary(
            _replay_result("what the user watched", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=0),
            _replay_result("a different answer", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=7_900),
        )

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            meter_auxiliary=False,
        )

        assert result.content == "what the user watched"
        assert primary.ainvoke.await_count == 2

    async def test_the_discarded_replay_is_still_booked(self, booked_replay: AsyncMock) -> None:
        """Both requests were billed by the provider, so both must reach COGS —
        the graph meters the returned answer, this books the thrown-away one."""
        primary = _replaying_primary(
            _replay_result("kept", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=0),
            _replay_result("thrown away", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=7_900),
        )

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config=_STICKY_LANE,
            meter_auxiliary=False,
        )

        assert booked_replay.await_count == 1
        assert booked_replay.await_args.kwargs["cached_tokens"] == 7_900


class TestFallbackKeepsItsLanesStickySession:
    """Which sticky key the fallback binds depends on the lane it is serving.

    The graph lane must land back on the conversation's provider; an auxiliary
    one-shot must not, or a background call re-pins the conversation. Both
    resolve through one helper, so a fallback cannot silently drop the suffix.
    """

    def _bindable(self, answer: AIMessage) -> NonCallableMagicMock:
        return TestFallbackHandover._bindable_runnable(answer)

    async def test_the_graph_lane_falls_back_onto_the_conversation_session(self) -> None:
        primary = TestAinvokeLlm._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._bindable(AIMessage(content="ok"))

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            fallback=fallback,
            config=RunnableConfig(configurable={"user_id": "u1", "session_id": "conv-1"}),
            meter_auxiliary=False,
        )

        assert fallback.bind.call_args.kwargs == {"session_id": "conv-1"}

    async def test_a_run_without_a_session_binds_nothing(self) -> None:
        """No key to be sticky on — binding a placeholder would pin at random."""
        primary = TestAinvokeLlm._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._bindable(AIMessage(content="ok"))

        await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            fallback=fallback,
            config=RunnableConfig(configurable={"user_id": "u1"}),
            meter_auxiliary=False,
        )

        fallback.bind.assert_not_called()


class TestTheInvokeTimeoutIsEnforced:
    """The caller's timeout is the ceiling on a whole attempt, retries included.

    Nothing else asserts it is applied: with the ceiling dropped, a provider
    that stops responding holds the turn open until the request dies somewhere
    upstream, and the user watches a chat that never finishes.
    """

    @staticmethod
    def _hanging_primary() -> NonCallableMagicMock:
        async def _never_answers(*_args: object, **_kwargs: object) -> AIMessage:
            await asyncio.sleep(30)
            return AIMessage(content="too late")

        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(side_effect=_never_answers)
        return runnable

    async def test_a_provider_that_stops_answering_hits_the_ceiling(self) -> None:
        with pytest.raises(TimeoutError):
            await ainvoke_llm(
                self._hanging_primary(),
                [HumanMessage(content="hi")],
                label="comms_agent",
                timeout=0.05,
                meter_auxiliary=False,
            )
