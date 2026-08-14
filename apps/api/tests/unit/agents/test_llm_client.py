"""Unit tests for the LLM client layer.

Covers:
- init_llm: provider selection, fallback logic, free-model path, error handling
- _get_available_providers: registry lookups
- _get_ordered_providers: priority ordering with/without preferred provider
- _create_configurable_llm: primary-only vs. primary+alternatives
- get_default_llm: the default model for auxiliary tasks
- ainvoke_llm: the single invoke primitive — retry, fallback to default, fail-loud
- chatbot: default-model one-shot path, error handling
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
import pytest

from app.agents.llm.chatbot import chatbot
from app.agents.llm.client import (
    LLM_RETRYABLE_EXCEPTIONS,
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _build_default_llm,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    ainvoke_llm,
    ainvoke_structured_gemini,
    get_default_llm,
    init_llm,
    register_llm_providers,
)
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, LLMNotConfiguredError
from app.constants.llm import DEFAULT_MODEL_NAME
from app.core.lazy_loader import ProviderRegistry

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

    @pytest.mark.regression
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


# ---------------------------------------------------------------------------
# ainvoke_llm — the sticky-flip replay's discarded first invocation
# ---------------------------------------------------------------------------


def _usage_message(content: str, *, prompt: int, cached: int) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": 5,
            "total_tokens": prompt + 5,
            "input_token_details": {"cache_read": cached},
        },
    )


class TestStickyFlipReplayAccounting:
    """When a graph call's prompt cache misses, ``ainvoke_llm`` re-sends and
    RETURNS the replay — the first invocation never lands in graph state, so
    ``LLMAccountingMiddleware`` (which meters from the state message) can never
    see it. The provider billed it, so ``ainvoke_llm`` meters it itself."""

    @staticmethod
    def _flipping_primary() -> NonCallableMagicMock:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            side_effect=[
                _usage_message("cold", prompt=10_000, cached=0),
                _usage_message("warm", prompt=10_000, cached=9_900),
            ]
        )
        return runnable

    @pytest.mark.regression
    @patch("app.agents.llm.client.record_graph_model_call", new_callable=AsyncMock)
    async def test_discarded_first_invocation_is_metered(self, mock_record: AsyncMock) -> None:
        mock_record.return_value = (
            {
                "input_tokens": 10_000,
                "output_tokens": 5,
                "cached_tokens": 0,
                "reasoning_tokens": 0,
            },
            0.004,
        )
        primary = self._flipping_primary()

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            config={"configurable": {"user_id": "u1", "model_name": "m", "root_request_id": "r1"}},
            meter_auxiliary=False,
        )

        assert result.content == "warm"
        mock_record.assert_awaited_once()
        metered_message, configurable = mock_record.await_args.args
        assert metered_message.content == "cold"
        assert configurable["root_request_id"] == "r1"

    @patch("app.agents.llm.client.record_graph_model_call", new_callable=AsyncMock)
    async def test_no_replay_means_no_extra_metering(self, mock_record: AsyncMock) -> None:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(
            return_value=_usage_message("warm", prompt=10_000, cached=9_900)
        )

        await ainvoke_llm(runnable, [HumanMessage(content="hi")], meter_auxiliary=False)

        assert runnable.ainvoke.await_count == 1
        mock_record.assert_not_awaited()

    @patch("app.agents.llm.client.record_graph_model_call", new_callable=AsyncMock)
    async def test_auxiliary_lane_is_left_to_its_usage_handler(
        self, mock_record: AsyncMock
    ) -> None:
        """``UsageMetadataCallbackHandler`` sums BOTH invocations, so metering
        the discarded one here too would double-bill auxiliary COGS."""
        primary = self._flipping_primary()

        await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=True)

        assert primary.ainvoke.await_count == 2
        mock_record.assert_not_awaited()


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

        result = await ainvoke_structured_gemini(_Extracted, "transcript", label="memory:extract")

        assert result.fact == "from-aux"
        mock_memory_llm.assert_not_called()
        assert mock_aux.await_args.args[0] is _Extracted
        assert mock_aux.await_args.kwargs["label"] == "memory:extract"

    @patch("app.agents.llm.client.ainvoke_llm", new_callable=AsyncMock)
    @patch("app.agents.llm.client.get_memory_llm")
    @patch("app.agents.llm.client.memory_lane_available", return_value=True)
    async def test_gemini_is_preferred_and_carries_an_aux_fallback(
        self, mock_available: MagicMock, mock_memory_llm: MagicMock, mock_ainvoke: AsyncMock
    ) -> None:
        mock_ainvoke.return_value = _Extracted(fact="from-gemini")

        result = await ainvoke_structured_gemini(_Extracted, "transcript", label="memory:extract")

        assert result.fact == "from-gemini"
        mock_memory_llm.assert_called_once()
        # A Gemini outage has somewhere to go: ainvoke_llm gets a real fallback
        # factory instead of the None that dropped every extraction.
        assert mock_ainvoke.await_args.kwargs["fallback"] is not None

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
