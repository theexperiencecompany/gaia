"""Tests for browser LLM factory — provider routing, key resolution, vision."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser.exceptions import BrowserUnavailableError


@pytest.fixture(autouse=True)
def _custom_lane_off_by_default(monkeypatch):
    """Default the browser LLM to the EXPLICIT lane so provider/model tests are
    deterministic — the dev .env's DEV_LLM_* would otherwise leak in and make the
    browser inherit the custom lane. Tests that want the custom lane set it back on.
    """
    monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_BASE_URL", None)
    monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_API_KEY", None)
    monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_MODEL", None)
    # Pin an explicit browser key so provider/model tests exercise the explicit
    # lane; inheritance/propagation tests set this back to None.
    monkeypatch.setattr(
        "app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", "explicit-test-key"
    )


pytestmark = pytest.mark.unit


def _fake_browser_use_modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Install fake browser_use modules so local imports inside build_browser_llm succeed."""

    mocks: dict[str, MagicMock] = {}

    # top-level browser_use with ChatAnthropic / ChatGoogle / ChatOpenAI
    top = types.ModuleType("browser_use")
    top.ChatAnthropic = MagicMock(return_value="anthropic-llm")
    top.ChatGoogle = MagicMock(return_value="google-llm")
    top.ChatOpenAI = MagicMock(return_value="openai-llm")
    monkeypatch.setitem(sys.modules, "browser_use", top)
    mocks["ChatAnthropic"] = top.ChatAnthropic
    mocks["ChatGoogle"] = top.ChatGoogle
    mocks["ChatOpenAI"] = top.ChatOpenAI

    # deepseek chat module: browser_use.llm.deepseek.chat
    llm_mod = types.ModuleType("browser_use.llm")
    deepseek_mod = types.ModuleType("browser_use.llm.deepseek")
    deepseek_chat = types.ModuleType("browser_use.llm.deepseek.chat")
    deepseek_chat.ChatDeepSeek = MagicMock(return_value="deepseek-llm")
    monkeypatch.setitem(sys.modules, "browser_use.llm", llm_mod)
    monkeypatch.setitem(sys.modules, "browser_use.llm.deepseek", deepseek_mod)
    monkeypatch.setitem(sys.modules, "browser_use.llm.deepseek.chat", deepseek_chat)
    mocks["ChatDeepSeek"] = deepseek_chat.ChatDeepSeek

    return mocks


class TestBuildBrowserLlm:
    def _set_provider(
        self,
        monkeypatch,
        provider,
        model="test-model",
        api_key="test-key",
        base_url=None,
        schema_in_prompt=False,
        reasoning_effort=None,
    ):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", provider)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_MODEL", model)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", api_key)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_BASE_URL", base_url)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_SCHEMA_IN_PROMPT", schema_in_prompt
        )
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_REASONING_EFFORT", reasoning_effort
        )

    def test_anthropic(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "anthropic")
        from app.services.browser.llm import build_browser_llm

        result = build_browser_llm()
        assert result == "anthropic-llm"
        mocks["ChatAnthropic"].assert_called_once_with(model="test-model", api_key="test-key")

    def test_anthropic_case_insensitive(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "ANTHROPIC")
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatAnthropic"].assert_called_once()

    def test_google(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "google")
        from app.services.browser.llm import build_browser_llm

        result = build_browser_llm()
        assert result == "google-llm"
        mocks["ChatGoogle"].assert_called_once_with(model="test-model", api_key="test-key")

    def test_deepseek_without_base_url(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "deepseek", base_url=None)
        from app.services.browser.llm import build_browser_llm

        result = build_browser_llm()
        assert result == "deepseek-llm"
        mocks["ChatDeepSeek"].assert_called_once_with(model="test-model", api_key="test-key")

    def test_deepseek_with_base_url(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "deepseek", base_url="https://custom.deepseek.com")
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatDeepSeek"].assert_called_once_with(
            model="test-model", api_key="test-key", base_url="https://custom.deepseek.com"
        )

    def test_openai_without_base_url(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "openai", base_url=None)
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatOpenAI"].assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url=None,
            add_schema_to_system_prompt=False,
            dont_force_structured_output=False,
        )

    def test_openai_with_base_url(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "openai", base_url="https://my.openai.com/v1")
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatOpenAI"].assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="https://my.openai.com/v1",
            add_schema_to_system_prompt=False,
            dont_force_structured_output=False,
        )

    def test_schema_in_prompt_switches_off_response_format(self, monkeypatch):
        """Endpoints whose vendors report supports_structured_outputs=false (e.g.
        Merge Gateway's zai/glm-*) 400 on a json_schema response_format. The flag
        moves the schema into the system prompt instead."""
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(
            monkeypatch, "openai", base_url="https://gw.example/v1", schema_in_prompt=True
        )
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatOpenAI"].assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="https://gw.example/v1",
            add_schema_to_system_prompt=True,
            dont_force_structured_output=True,
        )

    def test_reasoning_effort_names_the_model_so_it_reaches_the_wire(self, monkeypatch):
        """Browser-Use forwards `reasoning_effort` only for models whose NAME is in
        `reasoning_models` — a substring match, not a capability lookup. Without
        naming our own model there, a thinking model thinks unthrottled."""
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(
            monkeypatch, "openai", base_url="https://gw.example/v1", reasoning_effort="low"
        )
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        kwargs = mocks["ChatOpenAI"].call_args.kwargs
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["reasoning_models"] == ["test-model"]

    def test_no_reasoning_effort_leaves_the_kwargs_off(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "openai", base_url=None)
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        kwargs = mocks["ChatOpenAI"].call_args.kwargs
        assert "reasoning_effort" not in kwargs
        assert "reasoning_models" not in kwargs

    def test_openrouter_uses_default_base_url(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "openrouter", base_url=None)
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatOpenAI"].assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            add_schema_to_system_prompt=False,
            dont_force_structured_output=False,
        )

    def test_openrouter_custom_base_url_overrides(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "openrouter", base_url="https://custom.openrouter.ai/v1")
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatOpenAI"].assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="https://custom.openrouter.ai/v1",
            add_schema_to_system_prompt=False,
            dont_force_structured_output=False,
        )

    def test_missing_api_key_raises(self, monkeypatch):
        _fake_browser_use_modules(monkeypatch)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "anthropic"
        )
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_MODEL", "m")
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.OPENAI_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.OPENROUTER_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.GOOGLE_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_BASE_URL", None)
        # no browser key, no custom lane, no OPENROUTER key → nothing to inherit
        from app.services.browser.llm import build_browser_llm

        with pytest.raises(BrowserUnavailableError, match="API key"):
            build_browser_llm()

    def test_unknown_provider_raises(self, monkeypatch):
        _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "unknown_provider")
        from app.services.browser.llm import build_browser_llm

        with pytest.raises(BrowserUnavailableError, match="Unknown browser LLM provider"):
            build_browser_llm()

class TestResolveUseVision:
    async def test_vision_disabled_returns_false(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", False)
        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is False

    async def test_text_only_provider_returns_false(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "deepseek"
        )
        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is False

    async def test_text_only_provider_case_insensitive(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "DeepSeek"
        )
        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is False

    async def test_openrouter_delegates_to_catalog_true(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "openrouter"
        )
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_MODEL", "deepseek/deepseek-chat"
        )
        fake_catalog = AsyncMock()
        fake_catalog.accepts_images = AsyncMock(return_value=True)
        fake_module = types.ModuleType("app.agents.llm.model_catalog")
        fake_module.get_openrouter_catalog = AsyncMock(return_value=fake_catalog)
        monkeypatch.setitem(sys.modules, "app.agents.llm.model_catalog", fake_module)

        from app.services.browser.llm import resolve_use_vision as ruv

        result = await ruv()
        assert result is True
        fake_catalog.accepts_images.assert_awaited_once_with("deepseek/deepseek-chat")

    async def test_openrouter_delegates_to_catalog_false(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "openrouter"
        )
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_MODEL", "some/text-model"
        )
        fake_catalog = AsyncMock()
        fake_catalog.accepts_images = AsyncMock(return_value=False)
        fake_module = types.ModuleType("app.agents.llm.model_catalog")
        fake_module.get_openrouter_catalog = AsyncMock(return_value=fake_catalog)
        monkeypatch.setitem(sys.modules, "app.agents.llm.model_catalog", fake_module)

        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is False

    async def test_non_openrouter_non_text_returns_true(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "google")
        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is True

    async def test_openai_returns_true_when_vision_on(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "openai")
        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is True

    async def test_anthropic_returns_true_when_vision_on(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "anthropic"
        )
        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is True


@pytest.mark.unit
class TestBrowserInheritsCustomLane:
    def _set(self, monkeypatch, **kw):
        for k, v in kw.items():
            monkeypatch.setattr(f"app.services.browser.llm.settings.{k}", v)

    def test_inherits_dev_llm_when_no_browser_key(self, monkeypatch):
        """No browser-specific key + custom lane set → browser rides comms' lane.

        This is the fix for the silent outage: browser and comms shared one
        (dead) key, but the browser kept a redundant copy. Now there is one
        source of truth, so a stale key can't kill the browser while chat works.
        """
        from app.services.browser.llm import _resolve_browser_lane

        self._set(
            monkeypatch,
            BROWSER_USE_LLM_API_KEY=None,
            DEV_LLM_BASE_URL="https://gw/v1",
            DEV_LLM_API_KEY="shared-key",
            DEV_LLM_MODEL="zai/glm-5.3-flash",
        )
        provider, model, api_key, base_url = _resolve_browser_lane()
        assert (provider, model, api_key, base_url) == (
            "openai",
            "zai/glm-5.3-flash",
            "shared-key",
            "https://gw/v1",
        )

    def test_explicit_browser_key_still_wins(self, monkeypatch):
        from app.services.browser.llm import _resolve_browser_lane

        self._set(
            monkeypatch,
            BROWSER_USE_LLM_API_KEY="browser-only",
            BROWSER_USE_LLM_PROVIDER="google",
            BROWSER_USE_LLM_MODEL="gemini-x",
            BROWSER_USE_LLM_BASE_URL=None,
            DEV_LLM_BASE_URL="https://gw/v1",
            DEV_LLM_API_KEY="shared-key",
            DEV_LLM_MODEL="zai/glm-5.3-flash",
        )
        provider, model, api_key, _ = _resolve_browser_lane()
        assert (provider, model, api_key) == ("google", "gemini-x", "browser-only")


@pytest.mark.unit
class TestBrowserPropagatesCommsLaneEverywhere:
    def _set(self, monkeypatch, **kw):
        for k, v in kw.items():
            monkeypatch.setattr(f"app.services.browser.llm.settings.{k}", v)

    def test_prod_inherits_openrouter_and_default_model(self, monkeypatch):
        """No custom lane, no browser key → browser rides comms' prod lane:
        OpenRouter + the default chat model + OPENROUTER_API_KEY."""
        from app.constants.llm import DEFAULT_MODEL_NAME
        from app.services.browser.llm import _resolve_browser_lane

        self._set(
            monkeypatch,
            BROWSER_USE_LLM_API_KEY=None,
            DEV_LLM_BASE_URL=None,
            DEV_LLM_API_KEY=None,
            DEV_LLM_MODEL=None,
            OPENROUTER_API_KEY="or-key",
        )
        provider, model, api_key, base_url = _resolve_browser_lane()
        assert (provider, model, api_key, base_url) == (
            "openrouter",
            DEFAULT_MODEL_NAME,
            "or-key",
            None,
        )


@pytest.mark.unit
class TestVisionFollowsResolvedModel:
    async def test_text_only_inherited_model_disables_vision(self, monkeypatch):
        """A text-only model inherited from comms (deepseek via the custom lane,
        routed as provider 'openai') must turn vision OFF by itself, not error."""
        import sys
        import types

        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_BASE_URL", "https://gw/v1")
        monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_API_KEY", "k")
        monkeypatch.setattr(
            "app.services.browser.llm.settings.DEV_LLM_MODEL", "deepseek/deepseek-v4-flash-0731"
        )
        cat = AsyncMock()
        cat.accepts_images = AsyncMock(return_value=False)
        mod = types.ModuleType("app.agents.llm.model_catalog")
        mod.get_openrouter_catalog = AsyncMock(return_value=cat)
        monkeypatch.setitem(sys.modules, "app.agents.llm.model_catalog", mod)

        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is False
        cat.accepts_images.assert_awaited_once_with("deepseek/deepseek-v4-flash-0731")

    async def test_vision_model_inherited_keeps_vision_on(self, monkeypatch):
        import sys
        import types

        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_VISION", True)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_BASE_URL", "https://gw/v1")
        monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_API_KEY", "k")
        monkeypatch.setattr("app.services.browser.llm.settings.DEV_LLM_MODEL", "zai/glm-5.3-flash")
        cat = AsyncMock()
        cat.accepts_images = AsyncMock(return_value=True)
        mod = types.ModuleType("app.agents.llm.model_catalog")
        mod.get_openrouter_catalog = AsyncMock(return_value=cat)
        monkeypatch.setitem(sys.modules, "app.agents.llm.model_catalog", mod)

        from app.services.browser.llm import resolve_use_vision

        assert await resolve_use_vision() is True
