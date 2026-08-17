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

from typing import Any
from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock, patch

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
import pytest

from app.agents.llm.chatbot import chatbot
from app.agents.llm.client import (
    LLM_RETRYABLE_EXCEPTIONS,
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    STICKY_FALLBACK_KEY,
    _build_default_llm,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    _record_auxiliary_usage,
    ainvoke_llm,
    ainvoke_structured,
    ainvoke_structured_gemini,
    get_default_llm,
    has_sticky_fallback,
    init_llm,
    register_llm_providers,
)
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, LLMNotConfiguredError
from app.constants.llm import (
    AUX_MODEL_NAME,
    DEFAULT_MODEL_NAME,
    STICKY_FLIP_RETRY_MIN_INPUT,
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
        assert fallback.bind.call_args.kwargs == {"session_id": "conv-1"}
        assert fallback.ainvoke.call_args.args[0] is messages
        forwarded = fallback.ainvoke.call_args.kwargs["config"]
        assert forwarded["configurable"]["session_id"] == "conv-1"
        # The auxiliary meter rides along on the fallback attempt too — its
        # tokens are as real as the primary's.
        assert any(
            isinstance(handler, UsageMetadataCallbackHandler) for handler in forwarded["callbacks"]
        )

    @patch("app.agents.llm.client.log")
    async def test_a_provider_failure_stamps_the_run_as_fallen_back(
        self, mock_log: MagicMock
    ) -> None:
        """Sticky: later calls in this run must not alternate back to the
        primary, which resets the provider's per-model prompt cache each time."""
        primary = TestAinvokeLlm._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._bindable_runnable(AIMessage(content="fallback-ok"))
        config = RunnableConfig(configurable={"user_id": "u1"})

        assert not has_sticky_fallback(config)
        await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback, config=config)

        assert config["configurable"][STICKY_FALLBACK_KEY] is True
        assert has_sticky_fallback(config)

    def test_a_run_with_no_configurable_has_not_fallen_back(self) -> None:
        """Plenty of callers invoke with no config at all — the check answers
        for them instead of blowing up on the missing section."""
        assert not has_sticky_fallback(None)
        assert not has_sticky_fallback(RunnableConfig())

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


class TestStickyFlipReplayThresholds:
    """The cold-cache replay fires on a big prompt whose cache came back cold,
    and on nothing else: a re-send costs a whole extra request."""

    @staticmethod
    def _usage_result(content: str, *, prompt: int, cached: int) -> AIMessage:
        return AIMessage(
            content=content,
            usage_metadata={
                "input_tokens": prompt,
                "output_tokens": 5,
                "total_tokens": prompt + 5,
                "input_token_details": {"cache_read": cached},
            },
        )

    def _replaying_primary(self, first: AIMessage, second: AIMessage) -> NonCallableMagicMock:
        runnable = NonCallableMagicMock()
        runnable.with_retry = MagicMock(return_value=runnable)
        runnable.ainvoke = AsyncMock(side_effect=[first, second])
        return runnable

    async def test_a_prompt_exactly_at_the_input_floor_is_replayed(self) -> None:
        """The floor is inclusive — a prompt that just reaches it still counts."""
        primary = self._replaying_primary(
            self._usage_result("cold", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=0),
            self._usage_result("warm", prompt=STICKY_FLIP_RETRY_MIN_INPUT, cached=7_900),
        )

        result = await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=False)

        assert result.content == "warm"
        assert primary.ainvoke.await_count == 2

    async def test_a_hit_rate_exactly_at_the_floor_is_not_replayed(self) -> None:
        """At the floor the cache is warm enough; re-sending would just pay twice."""
        prompt = 10_000
        primary = self._replaying_primary(
            self._usage_result("warm", prompt=prompt, cached=int(prompt * 0.92)),
            self._usage_result("unused", prompt=prompt, cached=prompt),
        )

        result = await ainvoke_llm(primary, [HumanMessage(content="hi")], meter_auxiliary=False)

        assert result.content == "warm"
        assert primary.ainvoke.await_count == 1

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

    @patch("app.agents.llm.client.ainvoke_llm", new_callable=AsyncMock)
    @patch("app.agents.llm.client.get_memory_llm")
    @patch("app.agents.llm.client.memory_lane_available", return_value=True)
    async def test_gemini_is_preferred_and_carries_an_aux_fallback(
        self, mock_available: MagicMock, mock_memory_llm: MagicMock, mock_ainvoke: AsyncMock
    ) -> None:
        mock_ainvoke.return_value = _Extracted(fact="from-gemini")

        result = await ainvoke_structured_gemini(
            _Extracted, "transcript", label="memory:extract", temperature=0.4
        )

        assert result.fact == "from-gemini"
        mock_memory_llm.assert_called_once()
        assert mock_memory_llm.call_args.kwargs["temperature"] == 0.4
        assert mock_memory_llm.return_value.with_structured_output.call_args.args[0] is _Extracted
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
