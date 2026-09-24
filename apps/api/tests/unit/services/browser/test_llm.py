"""Tests for the browser LLM factory — Jev is the only browser model."""

from __future__ import annotations

from browser_use import ChatOpenAI
import pytest

from app.agents.llm.dev_lane import CustomEndpoint
from app.config.settings import DevelopmentSettings, settings
from app.constants.llm import DEV_LLM_BROWSER_HEADERS, DevLLMApi, ReasoningLevel
from app.services.browser import llm as llm_mod
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
        assert result.text_model.reasoning_models == [settings.BROWSER_USE_JEV_TEXT_MODEL]
        assert result.text_model.reasoning_effort == "minimal"
        assert result.text_model.max_completion_tokens == 4096
        assert result.text_model.api_key == "sk-or-x"

    def test_without_the_openrouter_key_it_refuses_with_the_reason(self, monkeypatch):
        monkeypatch.setattr("app.services.browser.llm.settings.OPENROUTER_API_KEY", None)

        with pytest.raises(BrowserUnavailableError) as exc_info:
            build_browser_llm()

        assert str(exc_info.value) == (
            "OPENROUTER_API_KEY is not set; Jev decisions and the text model both need it."
        )

    def test_no_toggle_can_turn_jev_off(self):
        assert "BROWSER_USE_JEV_ENABLED" not in DevelopmentSettings.model_fields
        assert "BROWSER_USE_VISION" not in DevelopmentSettings.model_fields


_ENDPOINT = CustomEndpoint(
    base_url="https://dev-llm.test/v1",
    api_key="sk-dev",
    model="gpt-6-luna",
    api=DevLLMApi.CHAT_COMPLETIONS,
)


@pytest.fixture
def custom_lane(monkeypatch):
    monkeypatch.setattr(llm_mod, "custom_lane_forced", lambda: True)
    monkeypatch.setattr(llm_mod, "custom_endpoint", lambda: _ENDPOINT)
    # Jev's own decisions still go through OpenRouter; only the text helper moves.
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "sk-or-x")


class TestTheTextHelperOnTheForcedDevLane:
    def test_the_text_helper_talks_to_the_dev_endpoint_with_its_own_key_and_model(
        self, custom_lane
    ):
        text_model = build_browser_llm().text_model

        assert isinstance(text_model, ChatOpenAI)
        assert text_model.model == "gpt-6-luna"
        assert text_model.api_key == "sk-dev"
        assert text_model.base_url == "https://dev-llm.test/v1"
        # The model is named a reasoning model, so the effort is actually sent.
        assert text_model.reasoning_models == ["gpt-6-luna"]
        assert text_model.reasoning_effort == "low"
        assert text_model.max_completion_tokens == 4096

    def test_the_text_helper_presents_a_browser_user_agent_to_the_dev_endpoint(self, custom_lane):
        text_model = build_browser_llm().text_model

        assert text_model.default_headers == DEV_LLM_BROWSER_HEADERS


@pytest.mark.parametrize("lane", ["openrouter", "custom"])
def test_the_text_helpers_output_cap_and_effort_are_the_modules_not_the_librarys(
    monkeypatch, request, lane
):
    # browser_use's defaults happen to equal ours today; a plan answer cut at a
    # smaller library default is the failure the explicit cap exists to prevent.
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "sk-or-x")
    if lane == "custom":
        request.getfixturevalue("custom_lane")
    monkeypatch.setattr(llm_mod, "_TEXT_MAX_COMPLETION_TOKENS", 8192)
    monkeypatch.setattr(llm_mod, "_TEXT_REASONING", ReasoningLevel.OFF)

    text_model = build_browser_llm().text_model

    assert text_model.max_completion_tokens == 8192
    assert text_model.reasoning_effort == "none"


def test_the_writers_calls_are_metered_to_the_user_the_run_works_for(monkeypatch):
    monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "sk-or-x")
    real_build = llm_mod.build_jev_chat_model
    metered_to: list[str | None] = []

    def recording_build(*, text_model, user_id=None):
        metered_to.append(user_id)
        return real_build(text_model=text_model, user_id=user_id)

    monkeypatch.setattr(llm_mod, "build_jev_chat_model", recording_build)

    build_browser_llm(user_id="user-7")

    assert metered_to == ["user-7"]
