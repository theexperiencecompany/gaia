"""Tests for the browser LLM factory — Jev is the only browser model."""

from __future__ import annotations

from browser_use import ChatOpenAI
import pytest

from app.config.settings import DevelopmentSettings, settings
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.jev import JevChatModel
from app.services.browser.llm import build_browser_llm

pytestmark = pytest.mark.unit


class TestJevIsTheBrowserModel:
    def test_the_browser_model_is_always_jev(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.OPENROUTER_API_KEY", "sk-or-x")

        result = build_browser_llm()

        assert isinstance(result, JevChatModel)
        assert isinstance(result.text_model, ChatOpenAI)
        assert result.text_model.model == settings.BROWSER_USE_JEV_TEXT_MODEL
        assert result.text_model.base_url == "https://openrouter.ai/api/v1"

    def test_without_the_openrouter_key_it_refuses_with_the_reason(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.OPENROUTER_API_KEY", None)

        with pytest.raises(BrowserUnavailableError) as exc_info:
            build_browser_llm()

        assert "OPENROUTER_API_KEY" in str(exc_info.value)

    def test_no_toggle_can_turn_jev_off(self):
        assert "BROWSER_USE_JEV_ENABLED" not in DevelopmentSettings.model_fields
        assert "BROWSER_USE_VISION" not in DevelopmentSettings.model_fields
