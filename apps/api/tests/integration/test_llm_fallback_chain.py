"""
Integration tests for the LLM Provider Fallback Chain.

Tests the real routing, provider selection, and fallback logic in
app.agents.llm.client — mocking only external LLM API calls at the I/O
boundary. Covers:
- Provider priority ordering
- Preferred provider selection
- Fallback on primary failure (invoke_with_fallback)
- All-providers-fail error propagation
- Free LLM chain construction
- Model pricing lookup
- Token cost calculation
"""

from __future__ import annotations

from typing import Any
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
)
from app.config.model_pricing import (
    DEFAULT_PRICING,
    ModelPricing,
    calculate_token_cost,
    get_model_pricing,
)
from app.constants.llm import (
    DEFAULT_GEMINI_FREE_MODEL_NAME,
    OPENROUTER_BASE_URL,
)
from app.core.lazy_loader import MissingKeyStrategy, ProviderRegistry


def _make_mock_llm(name: str = "mock_llm") -> MagicMock:
    """Create a mock LLM with configurable_alternatives and configurable_fields."""
    mock = MagicMock()
    mock.configurable_alternatives.return_value = mock
    mock.configurable_fields.return_value = mock
    mock.__class__.__name__ = name
    return mock


def _make_async_llm(response_content: str = "ok") -> AsyncMock:
    """Create an async-invocable mock LLM."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content=response_content)
    llm.__class__ = type("MockLLM", (), {"__name__": "MockLLM"})
    return llm


@pytest.mark.integration
class TestProviderPriorityOrdering:
    """Verify provider ordering follows PROVIDER_PRIORITY and respects preferences."""

    def test_default_priority_order(self) -> None:
        """Without a preferred provider, ordering follows PROVIDER_PRIORITY (gemini > openai > openrouter)."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openai = _make_mock_llm("openai")
        mock_openrouter = _make_mock_llm("openrouter")

        available = {
            "openai": mock_openai,
            "gemini": mock_gemini,
            "openrouter": mock_openrouter,
        }

        ordered = _get_ordered_providers(
            available, preferred_provider=None, fallback_enabled=True
        )

        assert len(ordered) == 3
        assert ordered[0]["name"] == "gemini"
        assert ordered[1]["name"] == "openai"
        assert ordered[2]["name"] == "openrouter"

    def test_preferred_provider_goes_first(self) -> None:
        """When a preferred_provider is given and available, it leads the list."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openai = _make_mock_llm("openai")

        available = {"openai": mock_openai, "gemini": mock_gemini}

        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        assert ordered[0]["name"] == "openai"
        assert ordered[1]["name"] == "gemini"

    def test_preferred_provider_no_fallback(self) -> None:
        """With fallback disabled and a valid preferred provider, only that provider is returned."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openai = _make_mock_llm("openai")

        available = {"openai": mock_openai, "gemini": mock_gemini}

        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=False
        )

        assert len(ordered) == 1
        assert ordered[0]["name"] == "openai"

    def test_preferred_provider_not_available_fallback_enabled(self) -> None:
        """If preferred provider is not in available set, fallback fills the list from priority."""
        mock_gemini = _make_mock_llm("gemini")
        available = {"gemini": mock_gemini}

        ordered = _get_ordered_providers(
            available, preferred_provider="openai", fallback_enabled=True
        )

        assert len(ordered) == 1
        assert ordered[0]["name"] == "gemini"

    def test_no_providers_available_returns_empty(self) -> None:
        """Empty available dict yields empty ordered list."""
        ordered = _get_ordered_providers(
            {}, preferred_provider=None, fallback_enabled=True
        )
        assert ordered == []

    def test_fallback_disabled_no_preferred_still_returns_priority_order(self) -> None:
        """With fallback_enabled=False but no preferred provider, ordered list still populated from priority."""
        mock_openai = _make_mock_llm("openai")
        available = {"openai": mock_openai}

        # When no ordered (preferred) providers, fallback_enabled=False still adds from priority
        # because the condition is `if fallback_enabled or not ordered`
        ordered = _get_ordered_providers(
            available, preferred_provider=None, fallback_enabled=False
        )

        assert len(ordered) == 1
        assert ordered[0]["name"] == "openai"


@pytest.mark.integration
class TestProviderInitialization:
    """Verify init_llm selects the correct provider and returns a model instance."""

    def test_init_llm_returns_primary_when_single_provider(self) -> None:
        """With only one provider available, init_llm returns it directly (no alternatives wrapper)."""
        mock_instance = _make_mock_llm("gemini")

        with patch(
            "app.agents.llm.client._get_available_providers",
            return_value={"gemini": mock_instance},
        ):
            result = init_llm()

        # Single provider -> returned directly, not wrapped with configurable_alternatives
        assert result is mock_instance

    def test_init_llm_returns_configurable_with_multiple_providers(self) -> None:
        """With multiple providers, init_llm wraps them with configurable_alternatives."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openai = _make_mock_llm("openai")

        available = {"gemini": mock_gemini, "openai": mock_openai}

        with patch(
            "app.agents.llm.client._get_available_providers", return_value=available
        ):
            init_llm()

        # Primary is gemini, and configurable_alternatives is called with openai
        mock_gemini.configurable_alternatives.assert_called_once()
        call_kwargs = mock_gemini.configurable_alternatives.call_args[1]
        assert "openai" in call_kwargs

    def test_init_llm_preferred_provider_openai(self) -> None:
        """Requesting openai as preferred provider makes it the primary."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openai = _make_mock_llm("openai")

        available = {"gemini": mock_gemini, "openai": mock_openai}

        with patch(
            "app.agents.llm.client._get_available_providers", return_value=available
        ):
            init_llm(preferred_provider="openai")

        # openai should be primary — its configurable_alternatives should be called
        mock_openai.configurable_alternatives.assert_called_once()

    def test_init_llm_invalid_provider_raises_value_error(self) -> None:
        """Requesting a non-existent provider raises ValueError."""
        with pytest.raises(
            ValueError, match="Invalid preferred_provider 'nonexistent'"
        ):
            init_llm(preferred_provider="nonexistent")

    def test_init_llm_no_providers_raises_runtime_error(self) -> None:
        """When no providers are configured, init_llm raises RuntimeError."""
        with patch("app.agents.llm.client._get_available_providers", return_value={}):
            with pytest.raises(
                RuntimeError, match="No LLM providers are properly configured"
            ):
                init_llm()

    def test_init_llm_preferred_unavailable_no_fallback_uses_priority(self) -> None:
        """Preferred provider unavailable with fallback disabled still returns from priority order.

        The `_get_ordered_providers` logic has `if fallback_enabled or not ordered`,
        meaning when no preferred provider matched and ordered is empty, it falls
        through to priority-based ordering regardless of fallback_enabled.
        """
        mock_gemini = _make_mock_llm("gemini")

        with patch(
            "app.agents.llm.client._get_available_providers",
            return_value={"gemini": mock_gemini},
        ):
            result = init_llm(preferred_provider="openai", fallback_enabled=False)

        # Since openai is not available and ordered is empty, gemini fills in
        assert result is mock_gemini


@pytest.mark.integration
class TestFreeLLMMode:
    """Verify init_llm(use_free=True) and get_free_llm_chain()."""

    def test_init_llm_use_free_returns_openrouter_model(self) -> None:
        """use_free=True returns a ChatOpenAI pointed at OpenRouter with the free model."""
        with patch("app.agents.llm.client.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "test-key"
            mock_settings.FRONTEND_URL = "https://test.example.com"

            with patch("app.agents.llm.client.ChatOpenAI") as mock_chat:
                mock_chat.return_value = _make_mock_llm("free_llm")
                init_llm(use_free=True)

                mock_chat.assert_called_once()
                call_kwargs = mock_chat.call_args[1]
                assert call_kwargs["model"] == DEFAULT_GEMINI_FREE_MODEL_NAME
                assert call_kwargs["base_url"] == OPENROUTER_BASE_URL
                assert call_kwargs["streaming"] is False

    def test_init_llm_use_free_no_key_raises(self) -> None:
        """use_free=True without OPENROUTER_API_KEY raises RuntimeError."""
        with patch("app.agents.llm.client.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = None

            with pytest.raises(RuntimeError, match="OpenRouter API key not configured"):
                init_llm(use_free=True)

    def test_get_free_llm_chain_with_both_keys(self) -> None:
        """get_free_llm_chain returns two LLMs when both OpenRouter and Google keys exist."""
        with patch("app.agents.llm.client.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "or-key"
            mock_settings.GOOGLE_API_KEY = "google-key"
            mock_settings.FRONTEND_URL = "https://test.example.com"

            with (
                patch("app.agents.llm.client.ChatOpenAI") as mock_openai,
                patch("app.agents.llm.client.ChatGoogleGenerativeAI") as mock_gemini,
            ):
                mock_openai.return_value = _make_mock_llm("openrouter")
                mock_gemini.return_value = _make_mock_llm("gemini")

                chain = get_free_llm_chain()

                assert len(chain) == 2

    def test_get_free_llm_chain_openrouter_only(self) -> None:
        """get_free_llm_chain returns one LLM when only OpenRouter key exists."""
        with patch("app.agents.llm.client.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = "or-key"
            mock_settings.GOOGLE_API_KEY = None
            mock_settings.FRONTEND_URL = "https://test.example.com"

            with patch("app.agents.llm.client.ChatOpenAI") as mock_openai:
                mock_openai.return_value = _make_mock_llm("openrouter")
                chain = get_free_llm_chain()
                assert len(chain) == 1

    def test_get_free_llm_chain_no_keys_raises(self) -> None:
        """get_free_llm_chain with no API keys raises RuntimeError."""
        with patch("app.agents.llm.client.settings") as mock_settings:
            mock_settings.OPENROUTER_API_KEY = None
            mock_settings.GOOGLE_API_KEY = None

            with pytest.raises(RuntimeError, match="No free LLM providers configured"):
                get_free_llm_chain()


@pytest.mark.integration
class TestInvokeWithFallback:
    """Test the invoke_with_fallback function that tries LLMs in sequence."""

    async def test_first_llm_succeeds(self) -> None:
        """When the first LLM succeeds, its response is returned and the second is never called."""
        llm1 = _make_async_llm("response from llm1")
        llm2 = _make_async_llm("response from llm2")

        messages = [HumanMessage(content="hello")]
        result = await invoke_with_fallback([llm1, llm2], messages)

        assert result.content == "response from llm1"
        llm1.ainvoke.assert_awaited_once()
        llm2.ainvoke.assert_not_awaited()

    async def test_fallback_on_primary_failure(self) -> None:
        """When the first LLM raises, the second is tried and its response returned."""
        llm1 = _make_async_llm()
        llm1.ainvoke.side_effect = Exception("API rate limit exceeded")

        llm2 = _make_async_llm("fallback response")

        messages = [HumanMessage(content="hello")]
        result = await invoke_with_fallback([llm1, llm2], messages)

        assert result.content == "fallback response"
        llm1.ainvoke.assert_awaited_once()
        llm2.ainvoke.assert_awaited_once()

    async def test_all_providers_fail_raises_runtime_error(self) -> None:
        """When all LLMs in the chain fail, a RuntimeError is raised with the last error."""
        llm1 = _make_async_llm()
        llm1.ainvoke.side_effect = Exception("provider 1 down")

        llm2 = _make_async_llm()
        llm2.ainvoke.side_effect = Exception("provider 2 down")

        messages = [HumanMessage(content="hello")]

        with pytest.raises(
            RuntimeError, match="All LLM providers failed.*provider 2 down"
        ):
            await invoke_with_fallback([llm1, llm2], messages)

        llm1.ainvoke.assert_awaited_once()
        llm2.ainvoke.assert_awaited_once()

    async def test_single_provider_failure_raises(self) -> None:
        """A single-provider chain that fails raises RuntimeError."""
        llm1 = _make_async_llm()
        llm1.ainvoke.side_effect = ConnectionError("connection refused")

        messages = [HumanMessage(content="hello")]

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await invoke_with_fallback([llm1], messages)

    async def test_config_forwarded_to_llm(self) -> None:
        """The optional RunnableConfig is forwarded to each LLM invoke call."""
        llm1 = _make_async_llm("ok")
        config = {"configurable": {"thread_id": "test-thread"}}

        messages = [HumanMessage(content="hello")]
        await invoke_with_fallback([llm1], messages, config=config)

        llm1.ainvoke.assert_awaited_once_with(messages, config=config)

    async def test_third_provider_succeeds_after_two_failures(self) -> None:
        """Chain of three: first two fail, third succeeds."""
        llm1 = _make_async_llm()
        llm1.ainvoke.side_effect = Exception("llm1 error")

        llm2 = _make_async_llm()
        llm2.ainvoke.side_effect = Exception("llm2 error")

        llm3 = _make_async_llm("llm3 success")

        messages = [HumanMessage(content="hello")]
        result = await invoke_with_fallback([llm1, llm2, llm3], messages)

        assert result.content == "llm3 success"
        llm1.ainvoke.assert_awaited_once()
        llm2.ainvoke.assert_awaited_once()
        llm3.ainvoke.assert_awaited_once()


@pytest.mark.integration
class TestCreateConfigurableLLM:
    """Test _create_configurable_llm wiring."""

    def test_no_alternatives_returns_primary_directly(self) -> None:
        """With no alternatives, the primary instance is returned unwrapped."""
        mock_instance = _make_mock_llm("primary")
        primary = {"name": "gemini", "instance": mock_instance}

        result = _create_configurable_llm(primary, alternatives=[])

        assert result is mock_instance
        mock_instance.configurable_alternatives.assert_not_called()

    def test_with_alternatives_calls_configurable_alternatives(self) -> None:
        """With alternatives, configurable_alternatives is called on the primary."""
        mock_primary = _make_mock_llm("primary")
        mock_alt = _make_mock_llm("alt")

        primary = {"name": "gemini", "instance": mock_primary}
        alternatives = [{"name": "openai", "instance": mock_alt}]

        _create_configurable_llm(primary, alternatives)

        mock_primary.configurable_alternatives.assert_called_once()
        call_kwargs = mock_primary.configurable_alternatives.call_args[1]
        assert "openai" in call_kwargs
        assert call_kwargs["openai"] is mock_alt


@pytest.mark.integration
class TestModelPricing:
    """Test model pricing lookup and token cost calculation."""

    async def test_get_model_pricing_returns_default_on_missing_model(self) -> None:
        """When model_service returns None, DEFAULT_PRICING is used."""
        with patch(
            "app.config.model_pricing.get_model_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            pricing = await get_model_pricing("nonexistent-model")

        assert pricing == DEFAULT_PRICING

    async def test_get_model_pricing_returns_model_data(self) -> None:
        """When model_service returns a model with pricing, those values are used."""
        mock_model = MagicMock()
        mock_model.pricing_per_1k_input_tokens = 0.005
        mock_model.pricing_per_1k_output_tokens = 0.015

        with patch(
            "app.config.model_pricing.get_model_by_id",
            new_callable=AsyncMock,
            return_value=mock_model,
        ):
            pricing = await get_model_pricing("gpt-4o")

        assert pricing == ModelPricing(
            input_cost_per_1k=0.005, output_cost_per_1k=0.015
        )

    async def test_get_model_pricing_handles_exception_gracefully(self) -> None:
        """On exception from the model service, DEFAULT_PRICING is returned."""
        with patch(
            "app.config.model_pricing.get_model_by_id",
            new_callable=AsyncMock,
            side_effect=Exception("db error"),
        ):
            pricing = await get_model_pricing("gpt-4o")

        assert pricing == DEFAULT_PRICING

    async def test_calculate_token_cost_arithmetic(self) -> None:
        """Verify token cost calculation is correct for known inputs."""
        with patch(
            "app.config.model_pricing.get_model_pricing",
            new_callable=AsyncMock,
            return_value=ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03),
        ):
            cost = await calculate_token_cost(
                "test-model", input_tokens=2000, output_tokens=1000
            )

        assert cost["input_cost"] == 0.02  # 2000/1000 * 0.01
        assert cost["output_cost"] == 0.03  # 1000/1000 * 0.03
        assert cost["total_cost"] == 0.05

    async def test_calculate_token_cost_zero_tokens(self) -> None:
        """Zero tokens should yield zero cost."""
        with patch(
            "app.config.model_pricing.get_model_pricing",
            new_callable=AsyncMock,
            return_value=DEFAULT_PRICING,
        ):
            cost = await calculate_token_cost(
                "test-model", input_tokens=0, output_tokens=0
            )

        assert cost["input_cost"] == 0.0
        assert cost["output_cost"] == 0.0
        assert cost["total_cost"] == 0.0


@pytest.mark.integration
class TestProviderConstants:
    """Verify the provider configuration constants are consistent."""

    def test_provider_priority_maps_to_valid_providers(self) -> None:
        """Every provider in PROVIDER_PRIORITY must have a corresponding entry in PROVIDER_MODELS."""
        for priority, provider_name in PROVIDER_PRIORITY.items():
            assert provider_name in PROVIDER_MODELS, (
                f"PROVIDER_PRIORITY[{priority}] = '{provider_name}' "
                f"not found in PROVIDER_MODELS"
            )

    def test_default_priority_is_gemini(self) -> None:
        """Priority 1 (the default) should be gemini."""
        assert PROVIDER_PRIORITY[1] == "gemini"

    def test_provider_models_have_expected_keys(self) -> None:
        """PROVIDER_MODELS must contain gemini, openai, and openrouter."""
        assert "gemini" in PROVIDER_MODELS
        assert "openai" in PROVIDER_MODELS
        assert "openrouter" in PROVIDER_MODELS


@pytest.mark.integration
class TestGetAvailableProviders:
    """Test _get_available_providers retrieves from the lazy provider registry."""

    def _build_registry(self, present_providers: dict[str, Any]) -> ProviderRegistry:
        """Build a ProviderRegistry with all three LLM slots registered.

        Providers listed in `present_providers` get a real loader that returns
        the given instance. Missing providers get a loader that returns None
        (simulating missing API key via WARN strategy).
        """
        registry = ProviderRegistry()
        all_slots = {
            "openai_llm": present_providers.get("openai_llm"),
            "gemini_llm": present_providers.get("gemini_llm"),
            "openrouter_llm": present_providers.get("openrouter_llm"),
        }
        for name, instance in all_slots.items():
            if instance is not None:
                registry.register(
                    name,
                    loader_func=lambda inst=instance: inst,
                    required_keys=["fake-key"],
                    strategy=MissingKeyStrategy.WARN,
                )
            else:
                # Register with a missing key so .get() returns None
                registry.register(
                    name,
                    loader_func=lambda: None,
                    required_keys=[None],
                    strategy=MissingKeyStrategy.WARN,
                )
        return registry

    def test_returns_only_registered_providers(self) -> None:
        """Only providers whose keys are configured appear in the result."""
        mock_openai_llm = _make_mock_llm("openai_llm")
        registry = self._build_registry({"openai_llm": mock_openai_llm})

        with patch("app.agents.llm.client.providers", registry):
            available = _get_available_providers()

        assert "openai" in available
        assert "gemini" not in available
        assert "openrouter" not in available

    def test_returns_empty_when_no_providers_have_keys(self) -> None:
        """When all providers have missing keys, available dict is empty."""
        registry = self._build_registry({})

        with patch("app.agents.llm.client.providers", registry):
            available = _get_available_providers()

        assert available == {}
