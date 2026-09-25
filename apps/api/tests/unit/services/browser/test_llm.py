"""The browser run's two chat models: which endpoint each talks to, at what effort, and that every call is metered."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from browser_use import ChatOpenAI
import pytest

from app.agents.llm.dev_lane import CustomEndpoint
from app.config.settings import settings
from app.constants.browser import BROWSER_AGENT_REASONING_EFFORT
from app.constants.llm import DEV_LLM_BROWSER_HEADERS, DevLLMApi, LLMProviderName
from app.services.browser import llm as llm_mod
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.ledger import CallComponent, RunLedger
from app.services.browser.llm import MeteredChatModel, build_agent_llm, build_text_model

pytestmark = pytest.mark.unit

_ENDPOINT = CustomEndpoint(
    base_url="https://dev-llm.test/v1",
    api_key="sk-dev",
    model="gpt-6-luna",
    api=DevLLMApi.CHAT_COMPLETIONS,
)


def _inner(model: MeteredChatModel) -> ChatOpenAI:
    inner = model._inner
    assert isinstance(inner, ChatOpenAI)
    return inner


@pytest.fixture
def custom_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "custom_lane_forced", lambda: True)
    monkeypatch.setattr(llm_mod, "custom_endpoint", lambda: _ENDPOINT)


def _lane(monkeypatch: pytest.MonkeyPatch, provider: LLMProviderName, model: str | None) -> None:
    async def resolve(user_id: str | None, role: object) -> tuple[Any, None]:
        return SimpleNamespace(provider=provider, model=model), None

    monkeypatch.setattr(llm_mod, "resolve_lane", resolve)


class TestTheTextHelper:
    def test_on_openrouter_it_runs_the_configured_text_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_mod, "custom_lane_forced", lambda: False)
        monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "sk-or-x")

        inner = _inner(build_text_model(RunLedger()))

        assert inner.model == settings.BROWSER_USE_JEV_TEXT_MODEL
        assert (inner.base_url, inner.api_key) == ("https://openrouter.ai/api/v1", "sk-or-x")
        assert inner.reasoning_models == [settings.BROWSER_USE_JEV_TEXT_MODEL]
        assert inner.max_completion_tokens == 4096

    def test_on_the_forced_dev_lane_it_talks_to_the_dev_endpoint_as_a_browser(
        self, custom_lane: None
    ) -> None:
        inner = _inner(build_text_model(RunLedger()))

        assert (inner.model, inner.api_key, inner.base_url) == (
            "gpt-6-luna",
            "sk-dev",
            "https://dev-llm.test/v1",
        )
        assert inner.default_headers == DEV_LLM_BROWSER_HEADERS
        assert inner.reasoning_models == ["gpt-6-luna"]

    def test_without_the_openrouter_key_it_refuses_with_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_mod, "custom_lane_forced", lambda: False)
        monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", None)

        with pytest.raises(BrowserUnavailableError, match="OPENROUTER_API_KEY is not set"):
            build_text_model(RunLedger())


class TestTheAgentModel:
    async def test_on_the_custom_lane_it_is_the_dev_endpoint_at_low_effort(
        self, monkeypatch: pytest.MonkeyPatch, custom_lane: None
    ) -> None:
        _lane(monkeypatch, LLMProviderName.CUSTOM, None)

        model = await build_agent_llm("user-1", RunLedger())

        inner = _inner(model)
        assert (inner.model, inner.base_url) == ("gpt-6-luna", "https://dev-llm.test/v1")
        assert inner.reasoning_effort == BROWSER_AGENT_REASONING_EFFORT
        assert model._component is CallComponent.AGENT

    async def test_on_openrouter_it_is_the_users_lane_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _lane(monkeypatch, LLMProviderName.OPENROUTER, "vendor/model-x")
        monkeypatch.setattr(llm_mod.settings, "OPENROUTER_API_KEY", "sk-or-x")

        inner = _inner(await build_agent_llm("user-1", RunLedger()))

        assert (inner.model, inner.api_key) == ("vendor/model-x", "sk-or-x")
        assert inner.reasoning_effort == BROWSER_AGENT_REASONING_EFFORT

    async def test_a_lane_that_does_not_speak_the_openai_wire_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _lane(monkeypatch, LLMProviderName.GEMINI, "gemini-x")

        with pytest.raises(BrowserUnavailableError, match="OpenAI-wire lane"):
            await build_agent_llm("user-1", RunLedger())


class _Completion:
    def __init__(self, text: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.completion = text
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )


class _Inner:
    provider = "openai"
    name = "fake"
    model = "model-x"

    async def ainvoke(
        self, messages: list[object], output_format: object = None, **kwargs: object
    ) -> _Completion:
        return _Completion("ok", 120, 7)


async def test_every_call_is_recorded_into_the_run_ledger_with_its_tokens() -> None:
    seen: list[object] = []
    ledger = RunLedger(on_call=seen.append)
    model = MeteredChatModel(_Inner(), ledger, CallComponent.TEXT, hedge_after=5)  # type: ignore[arg-type]  # a duck-typed chat model

    result = await model.ainvoke([])

    assert result.completion == "ok"
    [call] = ledger.calls
    assert (call.component, call.provider, call.model) == (CallComponent.TEXT, "openai", "model-x")
    assert (call.input_tokens, call.output_tokens) == (120, 7)
    assert seen == [call]
