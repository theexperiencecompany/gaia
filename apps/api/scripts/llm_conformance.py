"""Call every configured LLM provider for real and fail when one behaves differently from what the code assumes.

Run before changing a model or a provider: mise llm:conformance [provider ...]. It needs
real keys and makes about ten small calls per provider, so it is no CI lane. Each
provider prints one table; any FAIL or unreachable provider exits 1.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import NoReturn

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessageChunk
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_openai import ChatOpenAI
import openai
from openrouter.errors import TooManyRequestsResponseError
from pydantic import BaseModel, Field

from app.agents.llm.client import (
    LLMInvokeOptions,
    ainvoke_llm,
    chat_model,
    one_shot_client,
    one_shot_route,
    provider_configured,
    structured_runnable,
)
from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS, MalformedStructuredOutputError
from app.agents.llm.workers_ai import ChatWorkersAI
from app.constants.llm import LLMProviderName, ModelUse
from app.constants.providers import LLM_MODEL_PROFILES, LLM_PROVIDER_PRIORITY
from app.services.llm_metering import classify_error_family

_CHECK_TIMEOUT_SECONDS = 90
_CAP = 20
_SENTENCE = "The quarterly report shows revenue grew twelve percent while costs fell by three."
_ASK_SENTENCE = (
    f"Call the tool with headline set to exactly this sentence, word for word: '{_SENTENCE}' "
    "and tags set to exactly these five: a, b, c, d, e."
)
_ASK_OK = "Reply with the single word: ok"
_LABEL = "llm_conformance"
_UNMETERED = LLMInvokeOptions(max_attempts=1, meter_auxiliary=False)
#: Stream finish reasons a provider may close with; a repeated one merges into none of these.
_FINISH_REASONS = frozenset({"stop", "tool_calls", "length", "end_turn"})


class Headline(BaseModel):
    """A headline and its tags."""

    headline: str = Field(max_length=_CAP, description="The headline")
    tags: list[str] = Field(max_length=2, description="The tags")


class Verdict(BaseModel):
    """Whether a number is even."""

    is_even: bool = Field(description="True when the number is even")


@tool
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return city


@dataclass(frozen=True)
class Result:
    """One check's outcome: what the code assumes, what the provider did, and whether they agree."""

    check: str
    expected: str
    observed: str
    #: None marks an observation nothing in the code depends on.
    passed: bool | None


def _cut(headline: str) -> bool:
    """Whether a headline is the sentence cut off at the cap, not an answer the model shortened."""
    return len(headline) == _CAP and _SENTENCE.startswith(headline)


def _merged(chunks: list[BaseMessageChunk]) -> AIMessageChunk:
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert isinstance(merged, AIMessageChunk)
    return merged


def _input_tokens(message: AIMessage) -> int:
    return message.usage_metadata["input_tokens"] if message.usage_metadata else 0


async def _reply(model: BaseChatModel) -> Result:
    reply = await model.ainvoke(_ASK_OK)
    usage = reply.usage_metadata
    ok = bool(reply.text.strip()) and usage is not None and usage["output_tokens"] > 0
    observed = f"text={bool(reply.text.strip())}, usage={usage is not None}"
    return Result("plain reply", "text and token usage", observed, ok)


async def _stream(model: BaseChatModel) -> Result:
    streaming = model.model_copy(update={"stream_usage": True})
    whole = await model.ainvoke(_ASK_OK)
    merged = _merged([chunk async for chunk in streaming.astream(_ASK_OK)])
    finish = str(merged.response_metadata.get("finish_reason", "")).lower()
    same_usage = _input_tokens(merged) == _input_tokens(whole) > 0
    observed = (
        f"input tokens {_input_tokens(merged)} streamed vs {_input_tokens(whole)} whole, "
        f"finish_reason={finish!r}"
    )
    return Result(
        "streamed reply",
        "usage counted once, one finish_reason",
        observed,
        same_usage and finish in _FINISH_REASONS,
    )


async def _tool_call(model: BaseChatModel) -> Result:
    reply = await model.bind_tools([get_weather]).ainvoke(
        "What is the weather in Paris? Use the tool."
    )
    calls = [(call["name"], sorted(call["args"])) for call in reply.tool_calls]
    return Result(
        "tool call", "get_weather(city)", str(calls), calls == [("get_weather", ["city"])]
    )


async def _empty_tools(model: BaseChatModel) -> Result:
    expected = "answers" if isinstance(model, ChatWorkersAI) else "(not relied on)"
    try:
        reply = await model.bind_tools([]).ainvoke(_ASK_OK)
    except LLM_FALLBACK_EXCEPTIONS as error:
        passed = False if isinstance(model, ChatWorkersAI) else None
        return Result("empty tool list", expected, f"rejected: {type(error).__name__}", passed)
    answered = bool(reply.text.strip())
    passed = answered if isinstance(model, ChatWorkersAI) else None
    return Result("empty tool list", expected, "answers" if answered else "empty reply", passed)


async def _structured(model: BaseChatModel) -> Result:
    answer = await structured_runnable(model, Verdict).ainvoke("Is 4 an even number?")
    observed = f"is_even={answer.is_even}"
    return Result("structured output", "is_even=True", observed, answer.is_even is True)


async def _held_cap(model: BaseChatModel) -> Result:
    """A held schema: the reply must come back whole and fail our own check, never cut to fit."""
    try:
        answer = await structured_runnable(model, Headline, held=True).ainvoke(_ASK_SENTENCE)
    except MalformedStructuredOutputError:
        return Result("held schema, maxLength", "not cut at the cap", "whole, sent back", True)
    observed = f"{len(answer.headline)} characters, {len(answer.tags)} tags"
    return Result(
        "held schema, maxLength", "not cut at the cap", observed, not _cut(answer.headline)
    )


async def _forced_cap(model: BaseChatModel) -> Result:
    """A forced tool call that is not strict, which Workers AI has cut too (2026-11-24, after a strict one)."""
    reply = await model.bind_tools([Headline], tool_choice=True).ainvoke(_ASK_SENTENCE)
    if not reply.tool_calls:
        return Result("forced tool, maxLength", "not cut at the cap", "no tool call", False)
    headline = str(reply.tool_calls[0]["args"].get("headline", ""))
    observed = f"{len(headline)} characters"
    return Result("forced tool, maxLength", "not cut at the cap", observed, not _cut(headline))


def _simulated_429(provider: LLMProviderName) -> Exception:
    """Build the error provider's own SDK raises on a 429; none can be provoked on demand."""
    if provider is LLMProviderName.OPENROUTER:
        return TooManyRequestsResponseError.__new__(TooManyRequestsResponseError)
    if provider is LLMProviderName.GEMINI:
        return ChatGoogleGenerativeAIError("429 RESOURCE_EXHAUSTED (simulated)")
    request = httpx.Request("POST", "https://simulated.invalid/chat/completions")
    return openai.RateLimitError(
        "simulated 429", response=httpx.Response(429, request=request), body=None
    )


def _raise(error: Exception) -> NoReturn:
    raise error


async def _rate_limit_fallback(provider: LLMProviderName) -> Result:
    check, expected = "429, then fallback", "another provider answers"
    error = _simulated_429(provider)
    route = one_shot_route(ModelUse.HELPER, provider)
    if route is None:
        return Result(check, expected, "no other provider is configured", False)
    primary = RunnableLambda(lambda _prompt: _raise(error))
    try:
        reply = await ainvoke_llm(
            primary,
            _ASK_OK,
            fallback=lambda: one_shot_client(
                *route, use=ModelUse.HELPER, temperature=0.0, reasoning=None
            ),
            label=_LABEL,
            options=_UNMETERED,
        )
    except LLM_FALLBACK_EXCEPTIONS as failed:
        observed = f"{route[0].value} failed too: {type(failed).__name__}"
        return Result(check, expected, observed, False)
    answered = isinstance(reply, AIMessage) and bool(reply.text.strip())
    observed = f"{route[0].value} answered; the 429 counts as {classify_error_family(error)}"
    return Result(check, expected, observed, answered and route[0] is not provider)


def _raw(model: ChatWorkersAI) -> ChatOpenAI:
    """Return plain ChatOpenAI aimed at Workers AI: the wire without the adapter."""
    return ChatOpenAI(
        model=model.model_name,
        api_key=model.openai_api_key,
        base_url=model.openai_api_base,
        reasoning_effort=model.reasoning_effort,
        max_completion_tokens=model.max_tokens,
        max_retries=0,
    )


_QUIRK_GONE = " (Workers AI stopped doing this: the adapter rule for it can be deleted)"


async def _raw_stream(model: ChatWorkersAI) -> Result:
    chunks = [chunk async for chunk in _raw(model).astream(_ASK_OK, stream_usage=True)]
    usage_frames = sum(1 for chunk in chunks if chunk.usage_metadata is not None)
    finishes = sum(1 for chunk in chunks if chunk.response_metadata.get("finish_reason"))
    quirk = usage_frames > 1 and finishes > 1
    observed = f"{usage_frames} usage frames, {finishes} finish_reasons"
    return Result(
        "raw wire: stream",
        "usage on many frames, finish_reason repeated",
        observed if quirk else observed + _QUIRK_GONE,
        quirk,
    )


async def _raw_forced_cap(model: ChatWorkersAI) -> Result:
    strict = _raw(model).bind_tools([Headline], tool_choice=True, strict=True)
    reply = await strict.ainvoke(_ASK_SENTENCE)
    headline = str(reply.tool_calls[0]["args"].get("headline", "")) if reply.tool_calls else ""
    observed = f"{len(headline)} characters"
    return Result(
        "raw wire: strict tool, maxLength",
        f"cut at {_CAP} characters",
        observed if _cut(headline) else observed + _QUIRK_GONE,
        _cut(headline),
    )


async def _raw_empty_tools(model: ChatWorkersAI) -> Result:
    check, expected = "raw wire: empty tool list", "rejected with a 400"
    try:
        await _raw(model).bind_tools([]).ainvoke(_ASK_OK)
    except openai.BadRequestError:
        return Result(check, expected, expected, True)
    return Result(check, expected, "accepted" + _QUIRK_GONE, False)


_CHECKS: tuple[Callable[[BaseChatModel], Awaitable[Result]], ...] = (
    _reply,
    _stream,
    _tool_call,
    _empty_tools,
    _structured,
    _held_cap,
    _forced_cap,
)
_WORKERS_AI_CHECKS: tuple[Callable[[ChatWorkersAI], Awaitable[Result]], ...] = (
    _raw_stream,
    _raw_forced_cap,
    _raw_empty_tools,
)


async def _run(name: str, check: Awaitable[Result]) -> Result:
    """Await one check under its deadline; a provider error is the check's failure, not a crash."""
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            return await check
    except (*LLM_FALLBACK_EXCEPTIONS, AssertionError) as error:
        return Result(name, "", f"{type(error).__name__}: {str(error)[:120]}", False)


def _helper_model(provider: LLMProviderName) -> str | None:
    return LLM_MODEL_PROFILES[provider].for_use(ModelUse.HELPER) or chat_model(provider)


async def _check_provider(provider: LLMProviderName, model_name: str) -> list[Result]:
    model = one_shot_client(
        provider, model_name, use=ModelUse.HELPER, temperature=0.0, reasoning=None
    )
    first = await _run(_reply.__name__, _reply(model))
    if not first.passed:
        return [Result("reachable", "answers a plain call", first.observed, False)]
    results = [first]
    for check in _CHECKS[1:]:
        results.append(await _run(check.__name__, check(model)))
    results.append(await _run(_rate_limit_fallback.__name__, _rate_limit_fallback(provider)))
    if isinstance(model, ChatWorkersAI):
        for raw_check in _WORKERS_AI_CHECKS:
            results.append(await _run(raw_check.__name__, raw_check(model)))
    return results


def _mark(passed: bool | None) -> str:
    if passed is None:
        return "INFO"
    return "PASS" if passed else "FAIL"


def _print_table(provider: LLMProviderName, model_name: str, results: list[Result]) -> None:
    print(f"\n{provider.value}  ({model_name})")
    check_width = max(len(result.check) for result in results)
    expected_width = max(len(result.expected) for result in results)
    for result in results:
        print(
            f"  {_mark(result.passed)}  {result.check:<{check_width}}  "
            f"expected: {result.expected:<{expected_width}}  observed: {result.observed}"
        )


async def _main(only: list[LLMProviderName]) -> int:
    failed = 0
    skipped: list[str] = []
    for provider in LLM_PROVIDER_PRIORITY:
        if only and provider not in only:
            continue
        model_name = _helper_model(provider) if provider_configured(provider) else None
        if model_name is None:
            skipped.append(provider.value)
            continue
        results = await _check_provider(provider, model_name)
        _print_table(provider, model_name, results)
        failed += sum(1 for result in results if result.passed is False)
    print(f"\nnot configured, skipped: {', '.join(skipped) or 'none'}")
    print(f"{failed} failed" if failed else "every configured provider behaves as the code assumes")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "providers",
        nargs="*",
        type=LLMProviderName,
        help="providers to check (default: every configured one)",
    )
    raise SystemExit(asyncio.run(_main(parser.parse_args().providers)))
