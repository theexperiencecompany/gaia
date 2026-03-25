"""Unit tests for the LLM client layer.

Covers:
- init_llm: provider selection, fallback logic, free-model path, error handling
- _get_available_providers: registry lookups
- _get_ordered_providers: priority ordering with/without preferred provider
- _create_configurable_llm: primary-only vs. primary+alternatives
- get_free_llm_chain: OpenRouter / Gemini fallback chain
- invoke_with_fallback: success, partial failure with fallback, total failure
- chatbot: free-llm path, paid-llm path, error handling
"""

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.llm.client import (
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    get_free_llm_chain,
    init_llm,
    invoke_with_fallback,
    register_llm_providers,
)
from app.agents.llm.chatbot import chatbot
from app.agents.core.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_provider(name: str = "fake") -> MagicMock:
    """Return a MagicMock that quacks enough like a BaseChatModel."""
    mock = MagicMock()
    mock.configurable_alternatives.return_value = mock
    mock.ainvoke = AsyncMock(return_value=AIMessage(content=f"response-from-{name}"))
    return mock


def _make_llm_provider(name: str) -> Dict[str, Any]:
    return {"name": name, "instance": _make_fake_provider(name)}


# ---------------------------------------------------------------------------
# _get_available_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAvailableProviders:
    @patch("app.agents.llm.client.providers")
    def test_all_providers_available(self, mock_providers: MagicMock) -> None:
        openai_inst = _make_fake_provider("openai")
        gemini_inst = _make_fake_provider("gemini")
        openrouter_inst = _make_fake_provider("openrouter")

        def _get(key: str) -> Optional[MagicMock]:
            return {
                "openai_llm": openai_inst,
                "gemini_llm": gemini_inst,
                "openrouter_llm": openrouter_inst,
            }.get(key)

        mock_providers.get.side_effect = _get

        result = _get_available_providers()

        assert "openai" in result
        assert "gemini" in result
        assert "openrouter" in result
        assert result["openai"] is openai_inst

    @patch("app.agents.llm.client.providers")
    def test_no_providers_available(self, mock_providers: MagicMock) -> None:
        mock_providers.get.return_value = None

        result = _get_available_providers()

        assert result == {}

    @patch("app.agents.llm.client.providers")
    def test_partial_providers_available(self, mock_providers: MagicMock) -> None:
        gemini_inst = _make_fake_provider("gemini")

        def _get(key: str) -> Optional[MagicMock]:
            if key == "gemini_llm":
                return gemini_inst
            return None

        mock_providers.get.side_effect = _get

        result = _get_available_providers()

        assert list(result.keys()) == ["gemini"]


# ---------------------------------------------------------------------------
# _get_ordered_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrderedProviders:
    def test_default_priority_order(self) -> None:
        available: Dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider=None, fallback_enabled=True
        )

        # Should follow PROVIDER_PRIORITY: 1=gemini, 2=openai, 3=openrouter
        names = [p["name"] for p in ordered]
        assert names == ["gemini", "openai", "openrouter"]

    def test_preferred_provider_is_first(self) -> None:
        available: Dict[str, Any] = {
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
        assert names[1:] == ["gemini", "openrouter"]

    def test_preferred_provider_not_available_fallback_enabled(self) -> None:
        available: Dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        # openai not available, fallback picks gemini
        names = [p["name"] for p in ordered]
        assert names == ["gemini"]

    def test_preferred_provider_not_available_fallback_disabled(self) -> None:
        available: Dict[str, Any] = {
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
        available: Dict[str, Any] = {
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
        available: Dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider=None, fallback_enabled=False
        )

        # No preferred, ordered is empty, so all providers by priority added
        names = [p["name"] for p in ordered]
        assert names == ["gemini", "openai"]

    def test_empty_available(self) -> None:
        ordered = _get_ordered_providers(
            {}, preferred_provider=None, fallback_enabled=True
        )

        assert ordered == []

    def test_no_duplicate_when_preferred_is_also_in_priority(self) -> None:
        available: Dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
            "openai": _make_fake_provider("openai"),
        }
        ordered = _get_ordered_providers(
            available, preferred_provider="gemini", fallback_enabled=True
        )

        names = [p["name"] for p in ordered]
        # gemini first (preferred), openai from priority; gemini not duplicated
        assert names == ["gemini", "openai"]


# ---------------------------------------------------------------------------
# _create_configurable_llm
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
class TestInitLlm:
    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.settings")
    @patch("app.agents.llm.client.ChatOpenAI")
    def test_use_free_returns_openrouter_model(
        self, mock_chat_openai: MagicMock, mock_settings: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = "test-key"  # pragma: allowlist secret
        mock_settings.FRONTEND_URL = "http://localhost:3000"
        mock_chat_openai.return_value = MagicMock()

        result = init_llm(use_free=True)

        mock_chat_openai.assert_called_once()
        call_kwargs = mock_chat_openai.call_args.kwargs
        assert call_kwargs["streaming"] is False
        assert "models" in call_kwargs["extra_body"]
        assert result is mock_chat_openai.return_value

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.settings")
    def test_use_free_no_api_key_raises(
        self, mock_settings: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = None

        with pytest.raises(RuntimeError, match="OpenRouter API key not configured"):
            init_llm(use_free=True)

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

        with pytest.raises(
            RuntimeError, match="No LLM providers are properly configured"
        ):
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
            init_llm(preferred_provider="openai", fallback_enabled=False)

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
        primary = _make_llm_provider("openai")
        mock_available.return_value = {"openai": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="openai", fallback_enabled=False)

        # With fallback disabled, alternatives list should be empty
        mock_create.assert_called_once_with(primary, [])

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_provider_openai(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("openai")
        mock_available.return_value = {"openai": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm(preferred_provider="openai")

        mock_ordered.assert_called_once_with(
            mock_available.return_value, "openai", True
        )

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

        mock_ordered.assert_called_once_with(
            mock_available.return_value, "gemini", True
        )

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

        mock_ordered.assert_called_once_with(
            mock_available.return_value, "openrouter", True
        )


# ---------------------------------------------------------------------------
# get_free_llm_chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetFreeLlmChain:
    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.ChatOpenAI")
    @patch("app.agents.llm.client.settings")
    def test_both_providers_available(
        self,
        mock_settings: MagicMock,
        mock_chat_openai: MagicMock,
        mock_chat_google: MagicMock,
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_settings.GOOGLE_API_KEY = "google-key"  # pragma: allowlist secret
        mock_settings.FRONTEND_URL = "http://localhost:3000"
        mock_chat_openai.return_value = MagicMock()
        mock_chat_google.return_value = MagicMock()

        chain = get_free_llm_chain()

        assert len(chain) == 2
        mock_chat_openai.assert_called_once()
        mock_chat_google.assert_called_once()

    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.ChatOpenAI")
    @patch("app.agents.llm.client.settings")
    def test_only_openrouter(
        self,
        mock_settings: MagicMock,
        mock_chat_openai: MagicMock,
        mock_chat_google: MagicMock,
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        mock_settings.GOOGLE_API_KEY = None
        mock_settings.FRONTEND_URL = "http://localhost:3000"
        mock_chat_openai.return_value = MagicMock()

        chain = get_free_llm_chain()

        assert len(chain) == 1
        mock_chat_openai.assert_called_once()
        mock_chat_google.assert_not_called()

    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.ChatOpenAI")
    @patch("app.agents.llm.client.settings")
    def test_only_google(
        self,
        mock_settings: MagicMock,
        mock_chat_openai: MagicMock,
        mock_chat_google: MagicMock,
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = None
        mock_settings.GOOGLE_API_KEY = "google-key"  # pragma: allowlist secret
        mock_chat_openai.return_value = MagicMock()
        mock_chat_google.return_value = MagicMock()

        chain = get_free_llm_chain()

        assert len(chain) == 1
        mock_chat_google.assert_called_once()

    @patch("app.agents.llm.client.settings")
    def test_no_providers_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.OPENROUTER_API_KEY = None
        mock_settings.GOOGLE_API_KEY = None

        with pytest.raises(RuntimeError, match="No free LLM providers configured"):
            get_free_llm_chain()


# ---------------------------------------------------------------------------
# invoke_with_fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvokeWithFallback:
    async def test_first_llm_succeeds(self) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(return_value=AIMessage(content="fallback"))

        result = await invoke_with_fallback([llm1, llm2], [HumanMessage(content="hi")])

        assert result.content == "ok"
        llm2.ainvoke.assert_not_called()

    @patch("app.agents.llm.client.log")
    async def test_first_fails_second_succeeds(self, mock_log: MagicMock) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(side_effect=Exception("rate limit"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(return_value=AIMessage(content="fallback-ok"))

        result = await invoke_with_fallback([llm1, llm2], [HumanMessage(content="hi")])

        assert result.content == "fallback-ok"

    @patch("app.agents.llm.client.log")
    async def test_all_fail_raises_runtime_error(self, mock_log: MagicMock) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(side_effect=Exception("error1"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(side_effect=Exception("error2"))

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await invoke_with_fallback([llm1, llm2], [HumanMessage(content="hi")])

    async def test_single_llm_success(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="single"))

        result = await invoke_with_fallback([llm], [HumanMessage(content="hi")])

        assert result.content == "single"

    @patch("app.agents.llm.client.log")
    async def test_single_llm_failure(self, mock_log: MagicMock) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=ValueError("bad"))

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await invoke_with_fallback([llm], [HumanMessage(content="hi")])

    async def test_passes_config_through(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
        config = {"configurable": {"thread_id": "t1"}}

        await invoke_with_fallback([llm], [HumanMessage(content="hi")], config=config)  # type: ignore[arg-type]

        llm.ainvoke.assert_called_once()
        _, kwargs = llm.ainvoke.call_args
        assert kwargs["config"] == config

    @patch("app.agents.llm.client.log")
    async def test_three_llms_first_two_fail(self, mock_log: MagicMock) -> None:
        llm1 = MagicMock()
        llm1.ainvoke = AsyncMock(side_effect=Exception("fail1"))
        llm2 = MagicMock()
        llm2.ainvoke = AsyncMock(side_effect=Exception("fail2"))
        llm3 = MagicMock()
        llm3.ainvoke = AsyncMock(return_value=AIMessage(content="third-ok"))

        result = await invoke_with_fallback(
            [llm1, llm2, llm3], [HumanMessage(content="hi")]
        )

        assert result.content == "third-ok"


# ---------------------------------------------------------------------------
# register_llm_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterLlmProviders:
    @patch("app.agents.llm.client.init_openrouter_llm")
    @patch("app.agents.llm.client.init_gemini_llm")
    @patch("app.agents.llm.client.init_openai_llm")
    def test_calls_all_init_functions(
        self,
        mock_openai: MagicMock,
        mock_gemini: MagicMock,
        mock_openrouter: MagicMock,
    ) -> None:
        register_llm_providers()

        mock_openai.assert_called_once()
        mock_gemini.assert_called_once()
        mock_openrouter.assert_called_once()


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstants:
    def test_provider_models_keys(self) -> None:
        assert set(PROVIDER_MODELS.keys()) == {"gemini", "openai", "openrouter"}

    def test_provider_priority_values(self) -> None:
        assert set(PROVIDER_PRIORITY.values()) == {"gemini", "openai", "openrouter"}

    def test_provider_priority_is_ordered(self) -> None:
        sorted_keys = sorted(PROVIDER_PRIORITY.keys())
        providers_in_order = [PROVIDER_PRIORITY[k] for k in sorted_keys]
        assert providers_in_order == ["gemini", "openai", "openrouter"]


# ---------------------------------------------------------------------------
# chatbot (from chatbot.py)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChatbot:
    @patch("app.agents.llm.chatbot.invoke_with_fallback")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_chatbot_free_llm_path(
        self,
        mock_get_chain: MagicMock,
        mock_invoke: AsyncMock,
    ) -> None:
        mock_chain = [MagicMock()]
        mock_get_chain.return_value = mock_chain
        mock_invoke.return_value = AIMessage(content="free response")

        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=True)

        mock_get_chain.assert_called_once()
        mock_invoke.assert_called_once_with(mock_chain, state.messages)
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "free response"

    @patch("app.agents.llm.chatbot.init_llm")
    async def test_chatbot_paid_llm_path(self, mock_init_llm: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="paid response"))
        mock_init_llm.return_value = mock_llm

        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=False)

        mock_init_llm.assert_called_once_with(use_free=False)
        mock_llm.ainvoke.assert_called_once_with(state.messages)
        assert result["messages"][0].content == "paid response"

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_chatbot_error_returns_fallback_message(
        self,
        mock_get_chain: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_get_chain.side_effect = RuntimeError("no providers")

        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=True)

        assert len(result["messages"]) == 1
        assert "trouble processing" in result["messages"][0].content
        assert isinstance(result["messages"][0], AIMessage)

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.init_llm")
    async def test_chatbot_paid_llm_error_returns_fallback(
        self,
        mock_init_llm: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_init_llm.side_effect = RuntimeError("no providers")

        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=False)

        assert "trouble processing" in result["messages"][0].content

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.invoke_with_fallback")
    @patch("app.agents.llm.chatbot.get_free_llm_chain")
    async def test_chatbot_invoke_fallback_error(
        self,
        mock_get_chain: MagicMock,
        mock_invoke: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        mock_get_chain.return_value = [MagicMock()]
        mock_invoke.side_effect = RuntimeError("all failed")

        state = State(messages=[HumanMessage(content="hello")])

        result = await chatbot(state, use_free_llm=True)

        assert "trouble processing" in result["messages"][0].content
