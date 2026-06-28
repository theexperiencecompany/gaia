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
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.llm.chatbot import chatbot
from app.agents.llm.client import (
    _LLM_RETRYABLE_EXCEPTIONS,
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    ainvoke_llm,
    get_default_llm,
    init_llm,
    register_llm_providers,
)

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


@pytest.mark.unit
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


# ---------------------------------------------------------------------------
# _get_ordered_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrderedProviders:
    def test_default_priority_order(self) -> None:
        available: dict[str, Any] = {
            "gemini": _make_fake_provider("gemini"),
            "openrouter": _make_fake_provider("openrouter"),
        }
        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=True)

        # Should follow PROVIDER_PRIORITY: 1=gemini, 2=openrouter
        names = [p["name"] for p in ordered]
        assert names == ["gemini", "openrouter"]

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
        assert names[1:] == ["gemini", "openrouter"]

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
        assert names == ["gemini", "openrouter"]

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


@pytest.mark.unit
class TestGetDefaultLlm:
    @patch("app.agents.llm.client.ChatGoogleGenerativeAI")
    @patch("app.agents.llm.client.settings")
    def test_returns_gemini(self, mock_settings: MagicMock, mock_chat_google: MagicMock) -> None:
        mock_settings.GOOGLE_API_KEY = "google-key"  # pragma: allowlist secret
        mock_chat_google.return_value = MagicMock()

        assert get_default_llm() is mock_chat_google.return_value
        mock_chat_google.assert_called_once()

    @patch("app.agents.llm.client.settings")
    def test_no_google_key_raises(self, mock_settings: MagicMock) -> None:
        mock_settings.GOOGLE_API_KEY = None

        with pytest.raises(RuntimeError, match="Default LLM not configured"):
            get_default_llm()


# ---------------------------------------------------------------------------
# ainvoke_llm — the single LLM invocation primitive (retry + fallback)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAinvokeLlm:
    @staticmethod
    def _runnable(side_effect: Any = None, result: Any = None) -> MagicMock:
        # with_llm_retry calls runnable.with_retry(...) -> return self so the mock
        # .ainvoke is what actually runs (the real retry is LangChain's concern).
        runnable = MagicMock()
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
        fallback = MagicMock()
        fallback.ainvoke = AsyncMock(return_value=AIMessage(content="fallback-ok"))

        result = await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback)

        assert result.content == "fallback-ok"

    async def test_reraises_provider_error_when_no_fallback(self) -> None:
        primary = self._runnable(side_effect=ConnectionError("provider down"))
        with pytest.raises(ConnectionError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")])

    async def test_programming_error_propagates_not_downgraded(self) -> None:
        primary = self._runnable(side_effect=ValueError("a real bug"))
        fallback = MagicMock()
        fallback.ainvoke = AsyncMock(return_value=AIMessage(content="must-not-be-used"))

        with pytest.raises(ValueError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback)
        fallback.ainvoke.assert_not_called()


# ---------------------------------------------------------------------------
# register_llm_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterLlmProviders:
    @patch("app.agents.llm.client.init_openrouter_llm")
    @patch("app.agents.llm.client.init_gemini_llm")
    def test_calls_all_init_functions(
        self,
        mock_gemini: MagicMock,
        mock_openrouter: MagicMock,
    ) -> None:
        register_llm_providers()

        mock_gemini.assert_called_once()
        mock_openrouter.assert_called_once()


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstants:
    def test_provider_models_keys(self) -> None:
        assert set(PROVIDER_MODELS.keys()) == {"gemini", "openrouter"}

    def test_provider_priority_values(self) -> None:
        assert set(PROVIDER_PRIORITY.values()) == {"gemini", "openrouter"}

    def test_provider_priority_is_ordered(self) -> None:
        sorted_keys = sorted(PROVIDER_PRIORITY.keys())
        providers_in_order = [PROVIDER_PRIORITY[k] for k in sorted_keys]
        assert providers_in_order == ["gemini", "openrouter"]

    def test_retryable_exceptions_contains_expected_types(self) -> None:
        from google.api_core.exceptions import (
            DeadlineExceeded,
            InternalServerError,
            ResourceExhausted,
            ServiceUnavailable,
        )

        # Gemini (google-api-core) + stdlib transient types must all be retryable.
        # The tuple is provider-agnostic, so it is a superset (also covers the
        # OpenRouter SDK transient errors) — assert containment, not equality.
        expected = {
            ResourceExhausted,
            ServiceUnavailable,
            DeadlineExceeded,
            InternalServerError,
            ConnectionError,
            TimeoutError,
        }
        assert expected.issubset(set(_LLM_RETRYABLE_EXCEPTIONS))

    def test_retryable_exceptions_isinstance_check(self) -> None:
        from google.api_core.exceptions import ResourceExhausted

        exc = ResourceExhausted("rate limited")
        assert isinstance(exc, _LLM_RETRYABLE_EXCEPTIONS)

    def test_non_retryable_exception_not_in_tuple(self) -> None:
        assert not isinstance(ValueError("bad"), _LLM_RETRYABLE_EXCEPTIONS)
        assert not isinstance(KeyError("missing"), _LLM_RETRYABLE_EXCEPTIONS)


# ---------------------------------------------------------------------------
# chatbot (from chatbot.py)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChatbot:
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_default_llm")
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
    @patch("app.agents.llm.chatbot.get_default_llm")
    async def test_chatbot_no_provider_returns_fallback_message(
        self, mock_get_default: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_get_default.side_effect = RuntimeError("no providers")

        result = await chatbot([HumanMessage(content="hello")])

        assert isinstance(result["messages"][0], AIMessage)
        assert "trouble processing" in result["messages"][0].content

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_default_llm")
    async def test_chatbot_invoke_error_returns_fallback_message(
        self, mock_get_default: MagicMock, mock_ainvoke: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.side_effect = RuntimeError("provider error")

        result = await chatbot([HumanMessage(content="hello")])

        assert "trouble processing" in result["messages"][0].content
