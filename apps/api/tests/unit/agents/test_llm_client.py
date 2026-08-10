"""Unit tests for the LLM client layer.

Covers:
- init_llm: provider selection, fallback logic, free-model path, error handling
- _get_available_providers: registry lookups
- _get_ordered_providers: priority ordering with/without preferred provider
- _create_configurable_llm: primary-only vs. primary+alternatives
- get_default_llm / _build_default_llm: the default model for auxiliary tasks
- with_llm_retry: the canonical retry wrapper policy
- ainvoke_llm: the single invoke primitive — retry, fallback to default,
  fail-loud, per-call timeout, auxiliary metering
- _stamp_fallback / _resolve_fallback: fallback materialization + downgrade stamp
- _with_usage_handler: usage-handler config merging (never mutates the caller's)
- _record_auxiliary_usage: auxiliary COGS metering
- chatbot: default-model one-shot path, error handling
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock, call, patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
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
    _record_auxiliary_usage,
    _resolve_fallback,
    _stamp_fallback,
    _with_usage_handler,
    ainvoke_llm,
    get_default_llm,
    init_llm,
    register_llm_providers,
    with_llm_retry,
)
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, LLMNotConfiguredError
from app.constants.llm import (
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    LLM_INVOKE_TIMEOUT_SECONDS,
    LLM_RETRY_MAX_ATTEMPTS,
    OPENROUTER_MAX_OUTPUT_TOKENS,
)
from app.constants.log_tags import LogTag

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

    @patch("app.agents.llm.client.providers")
    def test_all_providers_mapped_to_their_registry_keys(self, mock_providers: MagicMock) -> None:
        instances = {name: _make_fake_provider(name) for name in ("gemini", "openrouter", "custom")}

        def _get(key: str) -> MagicMock | None:
            return {
                "gemini_llm": instances["gemini"],
                "openrouter_llm": instances["openrouter"],
                "custom_llm": instances["custom"],
            }.get(key)

        mock_providers.get.side_effect = _get

        result = _get_available_providers()

        # Every provider name resolves to its exact registry entry — a typo in
        # any of the three mapping keys must not silently drop a provider.
        assert list(result.keys()) == ["gemini", "openrouter", "custom"]
        for name, instance in instances.items():
            assert result[name] is instance

    @patch("app.agents.llm.client.providers")
    def test_falsy_instance_is_still_an_available_provider(
        self, mock_providers: MagicMock
    ) -> None:
        # The registry check is `is not None`, not truthiness — a registered
        # instance must not be dropped just because its __bool__ is False.
        mock_providers.get.side_effect = lambda key: 0 if key == "gemini_llm" else None

        assert _get_available_providers() == {"gemini": 0}


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
        # Each entry carries its exact instance — a dropped/None instance is
        # a silent misconfiguration that surfaces only when the model runs.
        assert ordered[0]["instance"] is available["openrouter"]
        assert ordered[1]["instance"] is available["gemini"]

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
        assert ordered[0]["instance"] is available["openai"]
        assert ordered[1]["instance"] is available["openrouter"]
        assert ordered[2]["instance"] is available["gemini"]

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

    def test_empty_string_preferred_is_not_treated_as_a_provider(self) -> None:
        # The guard is `preferred_provider and ...` — a falsy value must not
        # enter the preferred branch even when it IS a key of the available map.
        available: dict[str, Any] = {
            "": _make_fake_provider("empty"),
            "gemini": _make_fake_provider("gemini"),
        }
        ordered = _get_ordered_providers(available, preferred_provider="", fallback_enabled=True)

        assert [p["name"] for p in ordered] == ["gemini"]

    def test_available_providers_map_not_mutated(self) -> None:
        # The preferred-provider pop must hit the internal copy, not the
        # caller's dict — the copy is the whole point of `.copy()`.
        available: dict[str, Any] = {
            "openai": _make_fake_provider("openai"),
            "gemini": _make_fake_provider("gemini"),
        }
        _get_ordered_providers(available, preferred_provider="openai", fallback_enabled=True)

        assert list(available.keys()) == ["openai", "gemini"]


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

        result = _create_configurable_llm(primary, [alt1, alt2])  # type: ignore[arg-type, list-item]

        assert result is primary["instance"].configurable_alternatives.return_value
        primary["instance"].configurable_alternatives.assert_called_once()
        call = primary["instance"].configurable_alternatives.call_args
        # The provider selector field is passed positionally and must identify
        # the configurable namespace every alternative shares.
        assert call.args[0].id == "provider"
        kwargs = call.kwargs
        # Alternatives map by exact name to their exact instances.
        assert kwargs["openai"] is alt1["instance"]
        assert kwargs["openrouter"] is alt2["instance"]
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
        with pytest.raises(
            ValueError,
            match=r"Invalid preferred_provider 'cerebras'\. "
            r"Valid providers are: \['gemini', 'openrouter', 'custom'\]",
        ):
            init_llm(preferred_provider="cerebras")

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_available_providers")
    def test_empty_string_preferred_skips_provider_validation(
        self, mock_available: MagicMock, mock_log: MagicMock
    ) -> None:
        # "" is falsy, so the validation guard must NOT fire — the call proceeds
        # to the provider registry and fails there instead (a ValueError here
        # would mean the guard wrongly treated "" as a provider name).
        mock_available.return_value = {}

        with pytest.raises(
            RuntimeError, match=r"No LLM providers are properly configured\.$"
        ):
            init_llm(preferred_provider="")

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_available_providers")
    def test_no_providers_raises_runtime_error(
        self, mock_available: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_available.return_value = {}

        with pytest.raises(
            RuntimeError, match=r"No LLM providers are properly configured\.$"
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

        with pytest.raises(RuntimeError, match="fallback is disabled"):
            init_llm(preferred_provider="openrouter", fallback_enabled=False)

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_preferred_provider_unavailable_fallback_failed_message(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_available.return_value = {"gemini": _make_fake_provider("gemini")}
        mock_ordered.return_value = []

        with pytest.raises(RuntimeError, match="fallback is failed"):
            init_llm(preferred_provider="openrouter", fallback_enabled=True)

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

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_returns_the_created_configurable_llm(
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

        assert init_llm() is mock_create.return_value

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_logs_selected_model_metadata(
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

        init_llm()

        mock_log.set.assert_called_once_with(
            llm={"model": DEFAULT_GEMINI_MODEL_NAME, "provider": "gemini", "is_free": False}
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_logs_unknown_provider_name_as_model(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        # PROVIDER_MODELS.get(name, name): a provider not in the models map
        # logs its own name, never a None model.
        primary = _make_llm_provider("openai")
        mock_available.return_value = {"openai": primary["instance"]}
        mock_ordered.return_value = [primary]
        mock_create.return_value = MagicMock()

        init_llm()

        mock_log.set.assert_called_once_with(
            llm={"model": "openai", "provider": "openai", "is_free": False}
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_fallback_enabled_slices_alternatives(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("gemini")
        alt1 = _make_llm_provider("openrouter")
        alt2 = _make_llm_provider("custom")
        mock_available.return_value = {
            "gemini": primary["instance"],
            "openrouter": alt1["instance"],
            "custom": alt2["instance"],
        }
        mock_ordered.return_value = [primary, alt1, alt2]
        mock_create.return_value = MagicMock()

        init_llm()

        # Everything after the primary is an alternative, in priority order.
        mock_create.assert_called_once_with(primary, [alt1, alt2])

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client._create_configurable_llm")
    @patch("app.agents.llm.client._get_ordered_providers")
    @patch("app.agents.llm.client._get_available_providers")
    def test_fallback_disabled_drops_all_alternatives(
        self,
        mock_available: MagicMock,
        mock_ordered: MagicMock,
        mock_create: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        primary = _make_llm_provider("gemini")
        alt = _make_llm_provider("openrouter")
        mock_available.return_value = {"gemini": primary["instance"], "openrouter": alt["instance"]}
        mock_ordered.return_value = [primary, alt]
        mock_create.return_value = MagicMock()

        init_llm(fallback_enabled=False)

        mock_create.assert_called_once_with(primary, [])


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

        with pytest.raises(
            LLMNotConfiguredError, match=r"Default LLM not configured\. Set OPENROUTER_API_KEY\.$"
        ):
            get_default_llm()

    @patch("app.agents.llm.client._sim_llm")
    @patch("app.agents.llm.client.settings")
    def test_sim_mode_returns_stub_client(
        self, mock_settings: MagicMock, mock_sim_llm: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = True
        mock_settings.GOOGLE_API_KEY = None

        assert get_default_llm() is mock_sim_llm.return_value
        mock_sim_llm.assert_called_once_with(DEFAULT_LLM_TEMPERATURE)

    @patch("app.agents.llm.client._sim_llm")
    @patch("app.agents.llm.client.settings")
    def test_sim_mode_passes_temperature_to_stub(
        self, mock_settings: MagicMock, mock_sim_llm: MagicMock
    ) -> None:
        mock_settings.GAIA_SIM_MODE = True

        assert get_default_llm(temperature=0.7) is mock_sim_llm.return_value
        mock_sim_llm.assert_called_once_with(0.7)


class TestBuildDefaultLlm:
    @pytest.fixture(autouse=True)
    def _fresh_cache(self):
        # _build_default_llm is cached per temperature; isolate each test.
        _build_default_llm.cache_clear()
        yield
        _build_default_llm.cache_clear()

    @patch("app.agents.llm.client.ChatOpenRouter")
    @patch("app.agents.llm.client.settings")
    def test_exact_construction_and_profile(
        self, mock_settings: MagicMock, mock_chat_openrouter: MagicMock
    ) -> None:
        mock_settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
        llm = MagicMock()
        mock_chat_openrouter.return_value = llm

        assert _build_default_llm(0.7) is llm

        mock_chat_openrouter.assert_called_once_with(
            model=DEFAULT_MODEL_NAME,
            temperature=0.7,
            streaming=True,
            stream_usage=True,
            max_tokens=OPENROUTER_MAX_OUTPUT_TOKENS,
            api_key="or-key",
        )
        # Fractional-window middleware reads the profile at graph-build time —
        # without it the default model cannot serve as the fallback.
        assert llm.profile == {"max_input_tokens": DEFAULT_MAX_TOKENS}


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

    @patch("app.agents.llm.client._record_auxiliary_usage")
    @patch("app.agents.llm.client.UsageMetadataCallbackHandler")
    async def test_primary_invoked_with_usage_handler_config(
        self, mock_handler_cls: MagicMock, mock_record: AsyncMock
    ) -> None:
        handler = MagicMock()
        mock_handler_cls.return_value = handler
        messages = [HumanMessage(content="hi")]
        primary = self._runnable(result=AIMessage(content="ok"))

        await ainvoke_llm(
            primary, messages, config={"configurable": {"user_id": "user-42"}}, label="my-label"
        )

        mock_handler_cls.assert_called_once_with()
        primary.ainvoke.assert_awaited_once_with(
            messages, config={"configurable": {"user_id": "user-42"}, "callbacks": [handler]}
        )
        mock_record.assert_awaited_once_with(handler, "my-label", "user-42")

    @patch("app.agents.llm.client._record_auxiliary_usage")
    @patch("app.agents.llm.client.UsageMetadataCallbackHandler")
    async def test_metering_without_user_id_records_none(
        self, mock_handler_cls: MagicMock, mock_record: AsyncMock
    ) -> None:
        handler = MagicMock()
        mock_handler_cls.return_value = handler

        await ainvoke_llm(self._runnable(result=AIMessage(content="ok")), [HumanMessage(content="hi")])

        mock_record.assert_awaited_once_with(handler, "model", None)

    @patch("app.agents.llm.client._record_auxiliary_usage")
    @patch("app.agents.llm.client.UsageMetadataCallbackHandler")
    async def test_metering_user_id_coerced_to_str(
        self, mock_handler_cls: MagicMock, mock_record: AsyncMock
    ) -> None:
        handler = MagicMock()
        mock_handler_cls.return_value = handler

        await ainvoke_llm(
            self._runnable(result=AIMessage(content="ok")),
            [HumanMessage(content="hi")],
            config={"configurable": {"user_id": 42}},
        )

        mock_record.assert_awaited_once_with(handler, "model", "42")

    @patch("app.agents.llm.client._record_auxiliary_usage")
    @patch("app.agents.llm.client.UsageMetadataCallbackHandler")
    async def test_metering_happens_when_call_fails(
        self, mock_handler_cls: MagicMock, mock_record: AsyncMock
    ) -> None:
        # A failed call burned tokens on every attempt — the spend is recorded
        # in `finally`, not only on success.
        handler = MagicMock()
        mock_handler_cls.return_value = handler
        primary = self._runnable(side_effect=ConnectionError("provider down"))

        with pytest.raises(ConnectionError):
            await ainvoke_llm(primary, [HumanMessage(content="hi")])

        mock_record.assert_awaited_once_with(handler, "model", None)

    async def test_max_attempts_forwarded_to_retry_wrapper(self) -> None:
        primary = self._runnable(result=AIMessage(content="ok"))

        await ainvoke_llm(primary, [HumanMessage(content="hi")], max_attempts=5)

        primary.with_retry.assert_called_once_with(
            retry_if_exception_type=LLM_RETRYABLE_EXCEPTIONS,
            stop_after_attempt=5,
            wait_exponential_jitter=True,
        )

    @patch("app.agents.llm.client._record_auxiliary_usage")
    @patch("app.agents.llm.client.UsageMetadataCallbackHandler")
    async def test_fallback_invoked_with_usage_handler_and_result_stamped(
        self, mock_handler_cls: MagicMock, mock_record: AsyncMock
    ) -> None:
        handler = MagicMock()
        mock_handler_cls.return_value = handler
        primary = self._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._runnable(result=AIMessage(content="fallback-ok"))
        config = {"configurable": {"user_id": "user-42"}}

        result = await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback, config=config)

        assert result.content == "fallback-ok"
        # The fallback attempt is metered with the same handler as the primary.
        fallback.ainvoke.assert_awaited_once_with(
            [HumanMessage(content="hi")], config={"configurable": {"user_id": "user-42"}, "callbacks": [handler]}
        )
        # Downstream layers surface the downgrade via the stamp.
        assert result.response_metadata == {
            "gaia_fell_back": True,
            "gaia_fallback_model": DEFAULT_MODEL_NAME,
        }

    @patch("app.agents.llm.client.log")
    async def test_fallback_logs_the_call_label(self, mock_log: MagicMock) -> None:
        # The downgrade event must carry the CALLER's label — a hardcoded None
        # would make auxiliary spend un-attributable in the logs.
        primary = self._runnable(side_effect=ConnectionError("provider down"))
        fallback = self._runnable(result=AIMessage(content="fallback-ok"))

        await ainvoke_llm(primary, [HumanMessage(content="hi")], fallback=fallback, label="my-label")

        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} llm call failed; falling back to the default model",
            llm={"label": "my-label", "error_type": "ConnectionError", "fell_back": True},
            error="provider down",
        )

    @patch("app.agents.llm.client.asyncio.timeout")
    async def test_timeout_value_passed_through(self, mock_timeout: MagicMock) -> None:
        mock_timeout.return_value = MagicMock()

        await ainvoke_llm(self._runnable(result=AIMessage(content="ok")), [HumanMessage(content="hi")])
        mock_timeout.assert_called_with(LLM_INVOKE_TIMEOUT_SECONDS)

        await ainvoke_llm(
            self._runnable(result=AIMessage(content="ok")), [HumanMessage(content="hi")], timeout=42.0
        )
        mock_timeout.assert_called_with(42.0)

        await ainvoke_llm(
            self._runnable(result=AIMessage(content="ok")), [HumanMessage(content="hi")], timeout=None
        )
        mock_timeout.assert_called_with(None)

    @patch("app.agents.llm.client._record_auxiliary_usage")
    @patch("app.agents.llm.client.asyncio.timeout")
    async def test_timeout_expiry_propagates_and_still_meters(
        self, mock_timeout: MagicMock, mock_record: AsyncMock
    ) -> None:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(side_effect=TimeoutError("expired"))
        mock_timeout.return_value = ctx
        primary = self._runnable(result=AIMessage(content="ok"))

        with pytest.raises(TimeoutError, match="expired"):
            await ainvoke_llm(primary, [HumanMessage(content="hi")])

        primary.ainvoke.assert_not_called()
        mock_record.assert_awaited_once()


# ---------------------------------------------------------------------------
# with_llm_retry
# ---------------------------------------------------------------------------


class TestWithLlmRetry:
    def test_wraps_runnable_with_canonical_policy(self) -> None:
        runnable = NonCallableMagicMock()
        runnable.with_retry.return_value = MagicMock()

        result = with_llm_retry(runnable)

        assert result is runnable.with_retry.return_value
        runnable.with_retry.assert_called_once_with(
            retry_if_exception_type=LLM_RETRYABLE_EXCEPTIONS,
            stop_after_attempt=LLM_RETRY_MAX_ATTEMPTS,
            wait_exponential_jitter=True,
        )

    def test_custom_max_attempts(self) -> None:
        runnable = NonCallableMagicMock()

        with_llm_retry(runnable, max_attempts=1)

        runnable.with_retry.assert_called_once_with(
            retry_if_exception_type=LLM_RETRYABLE_EXCEPTIONS,
            stop_after_attempt=1,
            wait_exponential_jitter=True,
        )


# ---------------------------------------------------------------------------
# _stamp_fallback
# ---------------------------------------------------------------------------


class TestStampFallback:
    def test_stamps_dict_metadata(self) -> None:
        msg = AIMessage(content="x", response_metadata={"model": "m"})

        result = _stamp_fallback(msg)

        assert result is msg
        assert msg.response_metadata["gaia_fell_back"] is True
        assert msg.response_metadata["gaia_fallback_model"] == DEFAULT_MODEL_NAME
        assert msg.response_metadata["model"] == "m"  # untouched

    def test_ignores_non_dict_metadata(self) -> None:
        class Result:
            def __init__(self) -> None:
                self.response_metadata = ["not", "a", "dict"]

        result = Result()

        assert _stamp_fallback(result) is result
        assert result.response_metadata == ["not", "a", "dict"]

    def test_ignores_result_without_metadata(self) -> None:
        result = object()

        assert _stamp_fallback(result) is result

    def test_non_message_result_passthrough(self) -> None:
        result = {"parsed": 42}

        assert _stamp_fallback(result) is result
        assert result == {"parsed": 42}


# ---------------------------------------------------------------------------
# _resolve_fallback
# ---------------------------------------------------------------------------


class TestResolveFallback:
    def test_runnable_passthrough_wrapped_in_retry(self) -> None:
        runnable = NonCallableMagicMock()
        with patch("app.agents.llm.client.with_llm_retry") as mock_retry:
            mock_retry.return_value = MagicMock()

            result = _resolve_fallback(runnable, "label-x", ConnectionError("boom"))

        mock_retry.assert_called_once_with(runnable)
        assert result is mock_retry.return_value

    def test_factory_called_and_result_wrapped(self) -> None:
        runnable = NonCallableMagicMock()
        factory = MagicMock(return_value=runnable)
        with patch("app.agents.llm.client.with_llm_retry") as mock_retry:
            mock_retry.return_value = MagicMock()

            result = _resolve_fallback(factory, "label-x", ConnectionError("boom"))

        factory.assert_called_once_with()
        mock_retry.assert_called_once_with(runnable)
        assert result is mock_retry.return_value

    def test_callable_runnable_not_called_as_factory(self) -> None:
        # A Runnable subclass that is also callable must NOT be invoked — the
        # isinstance check exists precisely for that class of fallback.
        runnable = MagicMock()
        runnable.__class__ = Runnable
        with patch("app.agents.llm.client.with_llm_retry") as mock_retry:
            mock_retry.return_value = MagicMock()

            _resolve_fallback(runnable, "label-x", ConnectionError("boom"))

        runnable.assert_not_called()
        mock_retry.assert_called_once_with(runnable)

    def test_none_fallback_reraises_same_error(self) -> None:
        primary_error = ConnectionError("boom")

        with pytest.raises(ConnectionError) as exc_info:
            _resolve_fallback(None, "label-x", primary_error)

        assert exc_info.value is primary_error

    def test_factory_returning_none_reraises(self) -> None:
        primary_error = ConnectionError("boom")

        with pytest.raises(ConnectionError) as exc_info:
            _resolve_fallback(lambda: None, "label-x", primary_error)

        assert exc_info.value is primary_error

    @patch("app.agents.llm.client.log")
    def test_logs_downgrade_with_exact_fields(self, mock_log: MagicMock) -> None:
        with patch("app.agents.llm.client.with_llm_retry") as mock_retry:
            mock_retry.return_value = MagicMock()

            _resolve_fallback(NonCallableMagicMock(), "my-label", TimeoutError("slow"))

        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} llm call failed; falling back to the default model",
            llm={"label": "my-label", "error_type": "TimeoutError", "fell_back": True},
            error="slow",
        )


# ---------------------------------------------------------------------------
# _with_usage_handler
# ---------------------------------------------------------------------------


class TestWithUsageHandler:
    def test_none_config_creates_callbacks_list(self) -> None:
        handler = MagicMock()

        result = _with_usage_handler(None, handler)

        assert result == {"callbacks": [handler]}

    def test_config_without_callbacks(self) -> None:
        handler = MagicMock()
        config = {"configurable": {"user_id": "u1"}}

        result = _with_usage_handler(config, handler)

        assert result == {"configurable": {"user_id": "u1"}, "callbacks": [handler]}
        assert result is not config

    def test_list_callbacks_appended_not_mutated(self) -> None:
        handler = MagicMock()
        existing = [MagicMock()]
        config = {"callbacks": existing}

        result = _with_usage_handler(config, handler)

        assert result["callbacks"] == [existing[0], handler]
        assert result["callbacks"] is not existing
        assert config["callbacks"] is existing
        assert existing == [existing[0]]

    def test_manager_callbacks_copied_not_mutated(self) -> None:
        handler = MagicMock()
        manager = MagicMock()
        copy = MagicMock()
        manager.copy.return_value = copy
        config = {"callbacks": manager}

        result = _with_usage_handler(config, handler)

        assert result["callbacks"] is copy
        manager.copy.assert_called_once_with()
        copy.add_handler.assert_called_once_with(handler, inherit=True)
        manager.add_handler.assert_not_called()
        assert config["callbacks"] is manager


# ---------------------------------------------------------------------------
# _record_auxiliary_usage — auxiliary COGS metering
# ---------------------------------------------------------------------------


class TestRecordAuxiliaryUsage:
    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_records_usage_with_exact_fields(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_record_llm_call.return_value = 0.0123
        handler = MagicMock()
        handler.usage_metadata = {
            "model-a": {
                "input_tokens": 100,
                "output_tokens": 50,
                "input_token_details": {"cache_read": 20},
            }
        }

        await _record_auxiliary_usage(handler, "my-label", "user-42")

        mock_record_llm_call.assert_awaited_once_with(
            user_id="user-42",
            model_name="model-a",
            input_tokens=100,
            output_tokens=50,
            cached_tokens=20,
            charge_to_budget=False,
        )
        mock_log.warning.assert_not_called()
        mock_log.info.assert_called_once_with(
            "llm_call",
            llm_event="llm_call",
            background=True,
            agent_name="my-label",
            model="model-a",
            user_id="user-42",
            input_tokens=100,
            cached_tokens=20,
            output_tokens=50,
            cost_usd=0.0123,
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_zero_tokens_skipped_but_later_models_recorded(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        # A zero-token model must be `continue`d past, not stop the whole loop —
        # a following real model is still spend that must be recorded.
        handler = MagicMock()
        handler.usage_metadata = {
            "model-zero": {"input_tokens": 0, "output_tokens": 0},
            "model-real": {"input_tokens": 10, "output_tokens": 5},
        }

        await _record_auxiliary_usage(handler, "my-label", "user-42")

        mock_record_llm_call.assert_awaited_once_with(
            user_id="user-42",
            model_name="model-real",
            input_tokens=10,
            output_tokens=5,
            cached_tokens=0,
            charge_to_budget=False,
        )
        mock_log.info.assert_called_once()
        mock_log.warning.assert_not_called()

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_missing_and_string_tokens_coerce_to_zero(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        # A missing output_tokens key must default to 0 (not 1) and a string
        # token count must be coerced to int — usage dicts are not contractually
        # shaped.
        handler = MagicMock()
        handler.usage_metadata = {"model-a": {"input_tokens": "5"}}

        await _record_auxiliary_usage(handler, "my-label", "user-42")

        mock_record_llm_call.assert_awaited_once_with(
            user_id="user-42",
            model_name="model-a",
            input_tokens=5,
            output_tokens=0,
            cached_tokens=0,
            charge_to_budget=False,
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_input_only_and_output_only_usage_recorded(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.usage_metadata = {
            "model-in": {"input_tokens": 5, "output_tokens": 0},
            "model-out": {"output_tokens": 7},
        }

        await _record_auxiliary_usage(handler, "my-label", "user-42")

        assert mock_record_llm_call.await_count == 2
        mock_record_llm_call.assert_has_awaits(
            [
                call(
                    user_id="user-42",
                    model_name="model-in",
                    input_tokens=5,
                    output_tokens=0,
                    cached_tokens=0,
                    charge_to_budget=False,
                ),
                call(
                    user_id="user-42",
                    model_name="model-out",
                    input_tokens=0,
                    output_tokens=7,
                    cached_tokens=0,
                    charge_to_budget=False,
                ),
            ]
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_string_tokens_are_int_coerced(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.usage_metadata = {
            "model-a": {
                "input_tokens": "100",
                "output_tokens": "50",
                "input_token_details": {"cache_read": "20"},
            }
        }

        await _record_auxiliary_usage(handler, "my-label", "user-42")

        mock_record_llm_call.assert_awaited_once_with(
            user_id="user-42",
            model_name="model-a",
            input_tokens=100,
            output_tokens=50,
            cached_tokens=20,
            charge_to_budget=False,
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_no_user_id_warns_and_still_records(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.usage_metadata = {"model-a": {"input_tokens": 10, "output_tokens": 0}}

        await _record_auxiliary_usage(handler, "label-x", None)

        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} auxiliary llm spend not metered — no user_id in "
            "config.configurable (threading gap?)",
            llm={"label": "label-x", "model": "model-a"},
        )
        mock_record_llm_call.assert_awaited_once_with(
            user_id=None,
            model_name="model-a",
            input_tokens=10,
            output_tokens=0,
            cached_tokens=0,
            charge_to_budget=False,
        )

    @patch("app.agents.llm.client.log")
    @patch("app.agents.llm.client.record_llm_call")
    async def test_multiple_models_recorded_per_model(
        self, mock_record_llm_call: AsyncMock, mock_log: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.usage_metadata = {
            "model-a": {"input_tokens": 1, "output_tokens": 2},
            "model-b": {"input_tokens": 3, "output_tokens": 4},
        }

        await _record_auxiliary_usage(handler, "label-x", "u1")

        assert mock_record_llm_call.await_count == 2
        assert mock_log.info.call_count == 2
        mock_record_llm_call.assert_awaited_with(
            user_id="u1",
            model_name="model-b",
            input_tokens=3,
            output_tokens=4,
            cached_tokens=0,
            charge_to_budget=False,
        )


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
        mock_get_default.side_effect = LLMNotConfiguredError("no providers")

        result = await chatbot([HumanMessage(content="hello")])

        assert isinstance(result["messages"][0], AIMessage)
        assert "trouble processing" in result["messages"][0].content

    @patch("app.agents.llm.chatbot.log")
    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_default_llm")
    async def test_chatbot_provider_error_returns_fallback_message(
        self, mock_get_default: MagicMock, mock_ainvoke: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.side_effect = ConnectionError("provider down")

        result = await chatbot([HumanMessage(content="hello")])

        assert "trouble processing" in result["messages"][0].content

    @patch("app.agents.llm.chatbot.ainvoke_llm")
    @patch("app.agents.llm.chatbot.get_default_llm")
    async def test_chatbot_programming_bug_propagates(
        self, mock_get_default: MagicMock, mock_ainvoke: AsyncMock
    ) -> None:
        # Bare RuntimeError is a programming bug, not an operational failure —
        # it must fail loud instead of degrading to the friendly message.
        mock_get_default.return_value = MagicMock()
        mock_ainvoke.side_effect = RuntimeError("event loop is closed")

        with pytest.raises(RuntimeError, match="event loop is closed"):
            await chatbot([HumanMessage(content="hello")])
