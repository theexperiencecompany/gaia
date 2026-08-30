"""
Integration tests for the LLM Provider Fallback Chain.

Tests the real routing, provider selection, and fallback logic in
app.agents.llm.client — mocking only external LLM API calls at the I/O
boundary. Covers:
- Provider priority ordering
- Preferred provider selection
- Configurable-alternatives wiring
- Model pricing lookup
- Token cost calculation
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
import pytest

from app.agents.llm.client import (
    PROVIDER_MODELS,
    PROVIDER_PRIORITY,
    _create_configurable_llm,
    _get_available_providers,
    _get_ordered_providers,
    ainvoke_llm,
    init_llm,
    register_llm_providers,
)
from app.config.model_pricing import (
    DEFAULT_PRICING,
    ModelPricing,
    get_model_pricing,
)
from app.config.settings import settings
from app.constants.llm import DEFAULT_LLM_PROVIDER
from app.core.lazy_loader import MissingKeyStrategy, ProviderRegistry


def _make_mock_llm(name: str = "mock_llm") -> MagicMock:
    """Create a mock LLM with configurable_alternatives and configurable_fields."""
    mock = MagicMock()
    mock.configurable_alternatives.return_value = mock
    mock.configurable_fields.return_value = mock
    mock.__class__.__name__ = name
    return mock


@pytest.mark.integration
class TestProviderPriorityOrdering:
    """Verify provider ordering follows PROVIDER_PRIORITY and respects preferences."""

    def test_default_priority_order(self) -> None:
        """Without a preferred provider, ordering follows PROVIDER_PRIORITY
        (openrouter > gemini — the default provider leads)."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openrouter = _make_mock_llm("openrouter")

        available = {
            "gemini": mock_gemini,
            "openrouter": mock_openrouter,
        }

        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=True)

        assert len(ordered) == 2
        assert ordered[0]["name"] == "openrouter"
        assert ordered[1]["name"] == "gemini"

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
        ordered = _get_ordered_providers({}, preferred_provider=None, fallback_enabled=True)
        assert ordered == []

    def test_fallback_disabled_no_preferred_still_returns_priority_order(self) -> None:
        """With fallback_enabled=False but no preferred provider, ordered list still populated from priority."""
        mock_openrouter = _make_mock_llm("openrouter")
        available = {"openrouter": mock_openrouter}

        # When no ordered (preferred) providers, fallback_enabled=False still adds from priority
        # because the condition is `if fallback_enabled or not ordered`
        ordered = _get_ordered_providers(available, preferred_provider=None, fallback_enabled=False)

        assert len(ordered) == 1
        assert ordered[0]["name"] == "openrouter"


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
        mock_openrouter = _make_mock_llm("openrouter")

        available = {"gemini": mock_gemini, "openrouter": mock_openrouter}

        with patch("app.agents.llm.client._get_available_providers", return_value=available):
            init_llm()

        # Primary is openrouter (priority 1), and configurable_alternatives is
        # called on it with gemini as the alternative.
        mock_openrouter.configurable_alternatives.assert_called_once()
        call_kwargs = mock_openrouter.configurable_alternatives.call_args[1]
        assert call_kwargs["default_key"] == "openrouter"
        assert "gemini" in call_kwargs

    def test_init_llm_preferred_provider_openrouter(self) -> None:
        """Requesting openrouter as preferred provider makes it the primary."""
        mock_gemini = _make_mock_llm("gemini")
        mock_openrouter = _make_mock_llm("openrouter")

        available = {"gemini": mock_gemini, "openrouter": mock_openrouter}

        with patch("app.agents.llm.client._get_available_providers", return_value=available):
            init_llm(preferred_provider="openrouter")

        # openrouter should be primary — its configurable_alternatives should be called
        mock_openrouter.configurable_alternatives.assert_called_once()

    def test_init_llm_invalid_provider_raises_value_error(self) -> None:
        """Requesting a non-existent provider raises ValueError."""
        with pytest.raises(ValueError, match="Invalid preferred_provider 'nonexistent'"):
            init_llm(preferred_provider="nonexistent")

    def test_init_llm_no_providers_raises_runtime_error(self) -> None:
        """When no providers are configured, init_llm raises RuntimeError."""
        with patch("app.agents.llm.client._get_available_providers", return_value={}):
            with pytest.raises(RuntimeError, match="No LLM providers are properly configured"):
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
            result = init_llm(preferred_provider="openrouter", fallback_enabled=False)

        # Since openrouter is not available and ordered is empty, gemini fills in
        assert result is mock_gemini


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
    """Pricing resolves from the in-code table — no database involved."""

    async def test_get_model_pricing_returns_default_on_unknown_model(self) -> None:
        assert get_model_pricing("nonexistent-model") == DEFAULT_PRICING

    async def test_get_model_pricing_returns_the_tables_rate(self) -> None:
        pricing = get_model_pricing("gemini-3.1-flash-lite")

        assert pricing == ModelPricing(
            input_cost_per_1k=0.0001,
            output_cost_per_1k=0.0004,
            cached_input_cost_per_1k=0.000025,
        )


@pytest.mark.integration
class TestProviderConstants:
    """Verify the provider configuration constants are consistent."""

    def test_provider_priority_maps_to_valid_providers(self) -> None:
        """Every provider in PROVIDER_PRIORITY must have a corresponding entry in PROVIDER_MODELS."""
        for priority, provider_name in PROVIDER_PRIORITY.items():
            assert provider_name in PROVIDER_MODELS, (
                f"PROVIDER_PRIORITY[{priority}] = '{provider_name}' not found in PROVIDER_MODELS"
            )

    def test_default_priority_matches_the_default_provider(self) -> None:
        """Priority 1 is the provider serving DEFAULT_MODEL_NAME — the fallback
        chain must start at the lane the app actually defaults to."""
        assert PROVIDER_PRIORITY[1] == DEFAULT_LLM_PROVIDER == "openrouter"

    def test_provider_models_have_expected_keys(self) -> None:
        """PROVIDER_MODELS must contain gemini and openrouter."""
        assert "gemini" in PROVIDER_MODELS
        assert "openrouter" in PROVIDER_MODELS


@pytest.mark.integration
class TestGetAvailableProviders:
    """Test _get_available_providers retrieves from the lazy provider registry."""

    def _build_registry(self, present_providers: dict[str, Any]) -> ProviderRegistry:
        """Build a ProviderRegistry with all LLM slots registered.

        Providers listed in `present_providers` get a real loader that returns
        the given instance. Missing providers get a loader that returns None
        (simulating missing API key via WARN strategy).
        """
        registry = ProviderRegistry()
        all_slots = {
            "openai_llm": present_providers.get("openai_llm"),
            "gemini_llm": present_providers.get("gemini_llm"),
            "openrouter_llm": present_providers.get("openrouter_llm"),
            "custom_llm": present_providers.get("custom_llm"),
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
        mock_openrouter_llm = _make_mock_llm("openrouter_llm")
        registry = self._build_registry({"openrouter_llm": mock_openrouter_llm})

        with patch("app.agents.llm.client.providers", registry):
            available = _get_available_providers()

        assert "openrouter" in available
        assert "gemini" not in available

    def test_returns_empty_when_no_providers_have_keys(self) -> None:
        """When all providers have missing keys, available dict is empty."""
        registry = self._build_registry({})

        with patch("app.agents.llm.client.providers", registry):
            available = _get_available_providers()

        assert available == {}


@pytest.mark.integration
class TestProductionProviderRegistration:
    """Drives the REAL register_llm_providers().

    `_build_registry` above always registers all four slots and varies only the
    keys, so production's actual state — custom_llm never registered, because it
    is gated on ENV=development — was unrepresentable, and the KeyError it raised
    went unseen by every tier.
    """

    @pytest.mark.regression
    def test_production_registration_leaves_provider_lookup_working(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = ProviderRegistry()
        # Registration writes to lazy_loader.providers, the lookup reads
        # client.providers; both must point at the throwaway or the global
        # singleton leaks into every later test.
        monkeypatch.setattr("app.core.lazy_loader.providers", registry)
        monkeypatch.setattr("app.agents.llm.client.providers", registry)
        monkeypatch.setattr(settings, "ENV", "production")

        register_llm_providers()

        # Literals rather than LLMProviderKey/LLMProviderName: the regression
        # gate re-runs this file against the base revision, where those enums
        # do not exist yet, and an import error there proves nothing.
        with pytest.raises(KeyError):
            registry.get("custom_llm")

        # That KeyError went straight out through init_llm and took every agent
        # graph down. Which providers stay available depends on the ambient keys
        # (CI has none), so only the never-registered slot is asserted.
        assert "custom" not in _get_available_providers()


@pytest.mark.integration
class TestAinvokeFallbackRouting:
    """End-to-end routing of ainvoke_llm from a failing primary to the default fallback."""

    @staticmethod
    def _retrying(primary: MagicMock, retried: MagicMock) -> None:
        # ainvoke_llm wraps via with_llm_retry(primary) -> primary.with_retry(...).
        primary.with_retry = MagicMock(return_value=retried)

    @staticmethod
    def _runnable() -> NonCallableMagicMock:
        # NonCallable because real Runnables aren't callable — ainvoke_llm treats
        # a callable fallback as a lazy factory.
        return NonCallableMagicMock()

    async def test_primary_failure_routes_to_default_fallback(self) -> None:
        primary = self._runnable()
        retried = self._runnable()
        # ChatGoogleGenerativeAIError (langchain-google-genai's wrapper around
        # Gemini 4xx) is a fallback exception but not a retryable one, so the
        # retry wrapper raises immediately into the fallback path.
        retried.ainvoke = AsyncMock(
            side_effect=ChatGoogleGenerativeAIError("primary provider down")
        )
        self._retrying(primary, retried)

        fallback = self._runnable()
        fallback.with_retry = MagicMock(return_value=fallback)
        fallback.ainvoke = AsyncMock(return_value=AIMessage(content="from default model"))

        result = await ainvoke_llm(
            primary,
            [HumanMessage(content="hi")],
            label="test",
            fallback=fallback,
        )

        assert result.content == "from default model"
        fallback.ainvoke.assert_awaited_once()

    async def test_primary_failure_without_fallback_propagates(self) -> None:
        primary = self._runnable()
        retried = self._runnable()
        retried.ainvoke = AsyncMock(
            side_effect=ChatGoogleGenerativeAIError("primary provider down")
        )
        self._retrying(primary, retried)

        with pytest.raises(ChatGoogleGenerativeAIError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")], label="test")
