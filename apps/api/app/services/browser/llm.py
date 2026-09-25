"""The browser run's two chat models: the agent's reasoning model and Jev's tiny text model.

Both are Browser-Use chat models (OpenAI wire, which OpenRouter and the dev
endpoint both speak), and every call either makes is recorded into the run's
ledger. The browser_use import is local since the package is heavy and only a
real browser task needs it.
"""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import TYPE_CHECKING, Literal, TypeVar, overload

from pydantic import BaseModel
from pydantic_core import CoreSchema, core_schema

from app.agents.llm.dev_lane import custom_endpoint, custom_lane_forced
from app.agents.llm.lane import AgentRole, resolve_lane
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_AGENT_HEDGE_SECONDS,
    BROWSER_AGENT_LLM_TIMEOUT_SECONDS,
    BROWSER_AGENT_OPENROUTER_KEY_MISSING,
    BROWSER_AGENT_REASONING_EFFORT,
    JEV_TEXT_HEDGE_SECONDS,
    JEV_TEXT_OPENROUTER_KEY_MISSING,
)
from app.constants.llm import (
    DEV_LLM_BROWSER_HEADERS,
    OPENAI_REASONING_EFFORT,
    OPENROUTER_REASONING_EFFORT,
    LLMProviderName,
    ReasoningLevel,
)
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.hedge import first_answer
from app.services.browser.ledger import CallComponent, ModelCall, RunLedger

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel
    from browser_use.llm.messages import BaseMessage
    from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar("T", bound=BaseModel)

# OpenRouter is OpenAI-wire-compatible; Browser-Use talks to it via ChatOpenAI.
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# The cap covers reasoning tokens too: at 1024 a plan answer was cut mid-string.
_TEXT_MAX_COMPLETION_TOKENS = 4096
# Minimal effort answered a URL prompt in 1.3-2.1s, every reply valid (measured 2026-09-22).
_TEXT_REASONING = ReasoningLevel.LIGHT
# An agent step writes a whole action list plus its memory under flash mode.
_AGENT_MAX_COMPLETION_TOKENS = 8192

_Effort = Literal["none", "minimal", "low"]


class MeteredChatModel:
    """A Browser-Use chat model that hedges its slow tail and records each call into the run ledger.

    A call not answered within hedge_after seconds gets an identical second
    request, and the first answer wins: a provider's occasional multi-minute
    stall costs hedge_after plus a normal call instead of a step timeout.
    """

    _verified_api_keys = True

    def __init__(
        self, inner: BaseChatModel, ledger: RunLedger, component: CallComponent, hedge_after: float
    ) -> None:
        self._inner = inner
        self._ledger = ledger
        self._component = component
        self._hedge_after = hedge_after
        self.model = inner.model

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def model_name(self) -> str:
        return self._inner.model

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: object) -> CoreSchema:
        del source_type, handler
        return core_schema.any_schema()

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: None = None, **kwargs: object
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T], **kwargs: object
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: object
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        started = perf_counter()
        result = await first_answer(
            lambda: self._inner.ainvoke(messages, output_format, **kwargs),
            hedge_after=self._hedge_after,
            deadline=BROWSER_AGENT_LLM_TIMEOUT_SECONDS,
        )
        usage = result.usage
        self._ledger.add(
            ModelCall(
                component=self._component,
                provider=self._inner.provider,
                model=self._inner.model,
                latency_ms=round((perf_counter() - started) * 1000),
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            )
        )
        return result


def _openai_wire_model(
    *,
    model: str,
    api_key: str,
    base_url: str,
    default_headers: Mapping[str, str] | None,
    max_completion_tokens: int,
    reasoning_effort: _Effort,
) -> BaseChatModel:
    """Build the one kind of chat model a browser run uses, sending reasoning_effort to model.

    Every argument is required: Browser-Use's own defaults for the cap and the
    effort are real values, and one silently standing in for ours is a bug.
    """
    from browser_use import ChatOpenAI  # noqa: PLC0415 -- heavy optional dep

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        default_headers=default_headers,
        max_completion_tokens=max_completion_tokens,
        reasoning_models=[model],
        reasoning_effort=reasoning_effort,
    )


async def build_agent_llm(user_id: str | None, ledger: RunLedger) -> MeteredChatModel:
    """Return the reasoning model the Browser-Use agent runs on: the user's executor lane, at low effort."""
    lane, _plan = await resolve_lane(user_id, AgentRole.EXECUTOR)
    if lane.provider is LLMProviderName.CUSTOM:
        endpoint = custom_endpoint()
        model = _openai_wire_model(
            model=endpoint.model,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            default_headers=DEV_LLM_BROWSER_HEADERS,
            max_completion_tokens=_AGENT_MAX_COMPLETION_TOKENS,
            reasoning_effort=BROWSER_AGENT_REASONING_EFFORT,
        )
    elif lane.provider is LLMProviderName.OPENROUTER and lane.model:
        if not settings.OPENROUTER_API_KEY:
            raise BrowserUnavailableError(BROWSER_AGENT_OPENROUTER_KEY_MISSING)
        model = _openai_wire_model(
            model=lane.model,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=_OPENROUTER_BASE_URL,
            default_headers=None,
            max_completion_tokens=_AGENT_MAX_COMPLETION_TOKENS,
            reasoning_effort=BROWSER_AGENT_REASONING_EFFORT,
        )
    else:
        raise BrowserUnavailableError(
            f"The browser agent runs on an OpenAI-wire lane; {lane.provider} is not one."
        )
    return MeteredChatModel(model, ledger, CallComponent.AGENT, BROWSER_AGENT_HEDGE_SECONDS)


def build_text_model(ledger: RunLedger) -> MeteredChatModel:
    """Return Jev's text helper: the forced dev lane's endpoint, else BROWSER_USE_JEV_TEXT_MODEL over OpenRouter."""
    if custom_lane_forced():
        endpoint = custom_endpoint()
        model = _openai_wire_model(
            model=endpoint.model,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            default_headers=DEV_LLM_BROWSER_HEADERS,
            max_completion_tokens=_TEXT_MAX_COMPLETION_TOKENS,
            reasoning_effort=OPENAI_REASONING_EFFORT[_TEXT_REASONING],
        )
    else:
        if not settings.OPENROUTER_API_KEY:
            raise BrowserUnavailableError(JEV_TEXT_OPENROUTER_KEY_MISSING)
        model = _openai_wire_model(
            model=settings.BROWSER_USE_JEV_TEXT_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=_OPENROUTER_BASE_URL,
            default_headers=None,
            max_completion_tokens=_TEXT_MAX_COMPLETION_TOKENS,
            reasoning_effort=OPENROUTER_REASONING_EFFORT[_TEXT_REASONING],
        )
    return MeteredChatModel(model, ledger, CallComponent.TEXT, JEV_TEXT_HEDGE_SECONDS)
