"""Tests for browser LLM factory — provider routing, key resolution, vision."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser.exceptions import BrowserUnavailableError

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


class TestProviderFallbackKeys:
    def test_returns_settings_values(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.OPENAI_API_KEY", "openai-key")
        monkeypatch.setattr("app.services.browser.llm.settings.OPENROUTER_API_KEY", "or-key")
        monkeypatch.setattr("app.services.browser.llm.settings.GOOGLE_API_KEY", "google-key")
        from app.services.browser.llm import _provider_fallback_keys

        result = _provider_fallback_keys()
        assert result["openai"] == "openai-key"
        assert result["openrouter"] == "or-key"
        assert result["google"] == "google-key"
        assert "deepseek" not in result


class TestResolveApiKey:
    def test_override_wins(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", "override-key"
        )
        monkeypatch.setattr("app.services.browser.llm.settings.OPENAI_API_KEY", "openai-key")
        from app.services.browser.llm import _resolve_api_key

        assert _resolve_api_key("openai") == "override-key"
        assert _resolve_api_key("google") == "override-key"

    def test_falls_back_to_provider_key(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.OPENAI_API_KEY", "openai-key")
        monkeypatch.setattr("app.services.browser.llm.settings.OPENROUTER_API_KEY", "or-key")
        monkeypatch.setattr("app.services.browser.llm.settings.GOOGLE_API_KEY", "google-key")
        from app.services.browser.llm import _resolve_api_key

        assert _resolve_api_key("openai") == "openai-key"
        assert _resolve_api_key("openrouter") == "or-key"
        assert _resolve_api_key("google") == "google-key"

    def test_unknown_provider_returns_none(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", None)
        from app.services.browser.llm import _resolve_api_key

        assert _resolve_api_key("deepseek") is None
        assert _resolve_api_key("unknown") is None


class TestBuildBrowserLlm:
    def _set_provider(
        self,
        monkeypatch,
        provider,
        model="test-model",
        api_key="test-key",
        base_url=None,
        schema_in_prompt=False,
    ):
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", provider)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_MODEL", model)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", api_key)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_BASE_URL", base_url)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_SCHEMA_IN_PROMPT", schema_in_prompt
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
        # anthropic has no fallback key mapping, so _resolve_api_key returns None
        from app.services.browser.llm import build_browser_llm

        with pytest.raises(BrowserUnavailableError, match="API key"):
            build_browser_llm()

    def test_unknown_provider_raises(self, monkeypatch):
        _fake_browser_use_modules(monkeypatch)
        self._set_provider(monkeypatch, "unknown_provider")
        from app.services.browser.llm import build_browser_llm

        with pytest.raises(BrowserUnavailableError, match="Unknown browser LLM provider"):
            build_browser_llm()

    def test_fallback_key_used_when_no_override(self, monkeypatch):
        mocks = _fake_browser_use_modules(monkeypatch)
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_PROVIDER", "openai")
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_MODEL", "m")
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_API_KEY", None)
        monkeypatch.setattr("app.services.browser.llm.settings.OPENAI_API_KEY", "fallback-openai")
        monkeypatch.setattr("app.services.browser.llm.settings.BROWSER_USE_LLM_BASE_URL", None)
        monkeypatch.setattr(
            "app.services.browser.llm.settings.BROWSER_USE_LLM_SCHEMA_IN_PROMPT", False
        )
        from app.services.browser.llm import build_browser_llm

        build_browser_llm()
        mocks["ChatOpenAI"].assert_called_once_with(
            model="m",
            api_key="fallback-openai",
            base_url=None,
            add_schema_to_system_prompt=False,
            dont_force_structured_output=False,
        )


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
