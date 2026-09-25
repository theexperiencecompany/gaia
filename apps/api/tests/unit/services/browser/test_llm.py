"""The browser run's two chat models: which endpoint each talks to, at what effort, and that every call is metered and hedged."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, TypeVar

from browser_use import ChatOpenAI
from browser_use.llm.messages import BaseMessage, UserMessage
from pydantic import BaseModel
import pytest

from app.agents.llm.dev_lane import CustomEndpoint
from app.agents.llm.lane import AgentRole
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_AGENT_OPENROUTER_KEY_MISSING,
    JEV_TEXT_OPENROUTER_KEY_MISSING,
)
from app.constants.llm import DEV_LLM_BROWSER_HEADERS, DevLLMApi, LLMProviderName
from app.services.browser import llm as llm_mod
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.ledger import CallComponent, RunLedger
from app.services.browser.llm import MeteredChatModel, build_agent_llm, build_text_model

pytestmark = pytest.mark.unit

_T = TypeVar("_T")

_ENDPOINT = CustomEndpoint(
    base_url="https://dev-llm.test/v1",
    api_key="sk-dev",
    model="gpt-6-luna",
    api=DevLLMApi.CHAT_COMPLETIONS,
)
_USER = "user-1"
_OPENROUTER_KEY = "sk-or-x"
_OPENROUTER_URL = "https://openrouter.ai/api/v1"
_LANE_MODEL = "vendor/model-x"


def _inner(model: MeteredChatModel) -> ChatOpenAI:
    inner = model._inner
    assert isinstance(inner, ChatOpenAI)
    return inner


def _on_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the dev lane: the executor lane resolves to CUSTOM and the text helper follows it."""
    monkeypatch.setattr(llm_mod, "custom_lane_forced", lambda: True)
    monkeypatch.setattr(llm_mod, "custom_endpoint", lambda: _ENDPOINT)
    _lane(monkeypatch, LLMProviderName.CUSTOM, None)


def _on_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "custom_lane_forced", lambda: False)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", _OPENROUTER_KEY)
    _lane(monkeypatch, LLMProviderName.OPENROUTER, _LANE_MODEL)


def _lane(monkeypatch: pytest.MonkeyPatch, provider: LLMProviderName, model: str | None) -> None:
    """Serve the lane as _USER's executor lane; any other user or role gets a lane the agent refuses."""

    async def resolve(user_id: str | None, role: AgentRole) -> tuple[Any, None]:
        if (user_id, role) != (_USER, AgentRole.EXECUTOR):
            return SimpleNamespace(provider=LLMProviderName.GEMINI, model="gemini-x"), None
        return SimpleNamespace(provider=provider, model=model), None

    monkeypatch.setattr(llm_mod, "resolve_lane", resolve)


async def _agent(ledger: RunLedger) -> MeteredChatModel:
    return await build_agent_llm(_USER, ledger)


async def _text(ledger: RunLedger) -> MeteredChatModel:
    return build_text_model(ledger)


_Build = Callable[[RunLedger], Awaitable[MeteredChatModel]]


@pytest.mark.parametrize(
    ("setup", "build", "expected"),
    [
        pytest.param(
            _on_dev,
            _agent,
            (
                "gpt-6-luna",
                "sk-dev",
                "https://dev-llm.test/v1",
                DEV_LLM_BROWSER_HEADERS,
                8192,
                "low",
            ),
            id="agent-on-the-dev-endpoint",
        ),
        pytest.param(
            _on_openrouter,
            _agent,
            (_LANE_MODEL, _OPENROUTER_KEY, _OPENROUTER_URL, None, 8192, "low"),
            id="agent-on-the-users-openrouter-lane",
        ),
        pytest.param(
            _on_dev,
            _text,
            (
                "gpt-6-luna",
                "sk-dev",
                "https://dev-llm.test/v1",
                DEV_LLM_BROWSER_HEADERS,
                4096,
                "low",
            ),
            id="text-on-the-dev-endpoint",
        ),
        pytest.param(
            _on_openrouter,
            _text,
            (
                settings.BROWSER_USE_JEV_TEXT_MODEL,
                _OPENROUTER_KEY,
                _OPENROUTER_URL,
                None,
                4096,
                "minimal",
            ),
            id="text-on-openrouter",
        ),
    ],
)
async def test_each_model_talks_to_its_lanes_endpoint_with_its_cap_and_effort(
    monkeypatch: pytest.MonkeyPatch,
    setup: Callable[[pytest.MonkeyPatch], None],
    build: _Build,
    expected: tuple[str, str, str, object, int, str],
) -> None:
    """The dev endpoint (gpt-6-luna) rejects "minimal", so only OpenRouter's text model runs at it."""
    setup(monkeypatch)

    model = await build(RunLedger())

    inner = _inner(model)
    model_name, api_key, base_url, headers, cap, effort = expected
    assert (inner.model, inner.api_key, inner.base_url) == (model_name, api_key, base_url)
    assert inner.default_headers == headers
    assert inner.max_completion_tokens == cap
    # Listed as a reasoning model, or Browser-Use never sends the effort at all.
    assert (inner.reasoning_models, inner.reasoning_effort) == ([model_name], effort)
    assert model.model == model_name


@pytest.mark.parametrize(
    ("build", "missing"),
    [(_agent, BROWSER_AGENT_OPENROUTER_KEY_MISSING), (_text, JEV_TEXT_OPENROUTER_KEY_MISSING)],
    ids=["agent", "text"],
)
async def test_without_the_openrouter_key_each_model_refuses_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, build: _Build, missing: str
) -> None:
    _on_openrouter(monkeypatch)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)

    with pytest.raises(BrowserUnavailableError) as refused:
        await build(RunLedger())

    assert str(refused.value) == missing


async def test_a_lane_that_does_not_speak_the_openai_wire_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _lane(monkeypatch, LLMProviderName.GEMINI, "gemini-x")

    with pytest.raises(BrowserUnavailableError, match="OpenAI-wire lane"):
        await build_agent_llm(_USER, RunLedger())


class _Plan(BaseModel):
    url: str


class _Completion:
    def __init__(self, text: str, usage: SimpleNamespace | None) -> None:
        self.completion = text
        self.usage = usage


def _usage(prompt_tokens: int, completion_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


class _Inner:
    provider = "openai"
    name = "fake"
    model = "model-x"

    def __init__(self, usage: SimpleNamespace | None) -> None:
        self.usage = usage
        self.received: list[tuple[object, object, dict[str, object]]] = []

    async def ainvoke(
        self, messages: list[object], output_format: object = None, **kwargs: object
    ) -> _Completion:
        self.received.append((messages, output_format, kwargs))
        return _Completion("ok", self.usage)


def _metered(inner: _Inner, ledger: RunLedger) -> MeteredChatModel:
    return MeteredChatModel(inner, ledger, CallComponent.TEXT, hedge_after=5)  # type: ignore[arg-type]  # a duck-typed chat model


async def test_every_call_is_recorded_into_the_run_ledger_with_its_tokens_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(llm_mod, "perf_counter", lambda: next(ticks))
    seen: list[object] = []
    ledger = RunLedger(on_call=seen.append)
    model = _metered(_Inner(_usage(120, 7)), ledger)

    result = await model.ainvoke([])

    assert result.completion == "ok"
    [call] = ledger.calls
    assert (call.component, call.provider, call.model) == (CallComponent.TEXT, "openai", "model-x")
    assert (call.input_tokens, call.output_tokens, call.latency_ms) == (120, 7, 2500)
    assert seen == [call]


async def test_a_reply_without_usage_is_recorded_as_zero_tokens() -> None:
    inner = _Inner(usage=None)
    ledger = RunLedger()

    await _metered(inner, ledger).ainvoke([])

    [call] = ledger.calls
    assert (call.input_tokens, call.output_tokens) == (0, 0)


async def test_the_call_reaches_the_provider_exactly_as_the_agent_made_it() -> None:
    inner = _Inner(_usage(120, 7))
    messages: list[BaseMessage] = [UserMessage(content="open the page")]

    await _metered(inner, RunLedger()).ainvoke(messages, _Plan, session_id="s-1")

    assert inner.received == [(messages, _Plan, {"session_id": "s-1"})]


class _Provider:
    """Stands in for ChatOpenAI's network call: the first request stalls, later ones answer, unless all stall."""

    def __init__(self, *, stall_every_call: bool = False) -> None:
        self.stall_every_call = stall_every_call
        self.requests = 0

    async def __call__(
        self, messages: list[object], output_format: object = None, **kwargs: object
    ) -> _Completion:
        self.requests += 1
        if self.stall_every_call or self.requests == 1:
            await asyncio.Event().wait()
        return _Completion("ok", _usage(3, 2))


async def _settle(coro: Awaitable[_T]) -> asyncio.Future[_T]:
    """Run coro to completion or fail the test if it is still hanging after two seconds."""
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=2)
    if not done:
        task.cancel()
        pytest.fail("the model call hung instead of hedging or giving up")
    return task


@pytest.mark.parametrize(
    ("build", "hedge_setting", "component"),
    [
        (_agent, "BROWSER_AGENT_HEDGE_SECONDS", CallComponent.AGENT),
        (_text, "JEV_TEXT_HEDGE_SECONDS", CallComponent.TEXT),
    ],
    ids=["agent", "text"],
)
async def test_a_stalled_call_is_hedged_after_the_models_own_delay_and_metered_once(
    monkeypatch: pytest.MonkeyPatch, build: _Build, hedge_setting: str, component: CallComponent
) -> None:
    _on_openrouter(monkeypatch)
    monkeypatch.setattr(llm_mod, hedge_setting, 0.01)
    provider = _Provider()
    monkeypatch.setattr(ChatOpenAI, "ainvoke", provider)
    ledger = RunLedger()
    model = await build(ledger)

    task = await _settle(model.ainvoke([]))

    assert task.result().completion == "ok"
    assert provider.requests == 2
    [call] = ledger.calls
    assert (call.component, call.input_tokens, call.output_tokens) == (component, 3, 2)


async def test_a_call_nothing_answers_gives_up_at_the_llm_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _on_openrouter(monkeypatch)
    monkeypatch.setattr(llm_mod, "BROWSER_AGENT_HEDGE_SECONDS", 0.01)
    monkeypatch.setattr(llm_mod, "BROWSER_AGENT_LLM_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(ChatOpenAI, "ainvoke", _Provider(stall_every_call=True))
    ledger = RunLedger()
    model = await build_agent_llm(_USER, ledger)

    task = await _settle(model.ainvoke([]))

    assert isinstance(task.exception(), TimeoutError)
    assert ledger.calls == []
