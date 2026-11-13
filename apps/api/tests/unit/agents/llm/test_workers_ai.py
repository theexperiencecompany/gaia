"""ChatWorkersAI against Workers AI's real stream shape, replayed over a scripted HTTP wire."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

import httpx
from langchain_core.messages import AIMessageChunk, BaseMessageChunk, HumanMessage
from pydantic import SecretStr
import pytest

from app.agents.llm.workers_ai import ChatWorkersAI

_MODEL = "@cf/deepseek-ai/deepseek-v4.1-flash-1017"


def _frame(
    delta: dict[str, Any], *, prompt: int, completion: int, finish: str | None = None
) -> bytes:
    """One SSE frame as Workers AI sends it: every frame carries a usage block."""
    body = {
        "object": "chat.completion.chunk",
        "model": _MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    }
    return f"data: {json.dumps(body)}\n\n".encode()


#: Captured live 2026-11-13 (reasoning text elided): per-frame counts, then
#: three closing frames, the last of which restates the call's total (33 in / 24 out).
_TEXT_REPLY = [
    _frame({"role": "assistant", "content": ""}, prompt=33, completion=0),
    _frame({"reasoning_content": "The user says pong."}, prompt=0, completion=20),
    _frame({"content": "p"}, prompt=0, completion=2),
    _frame({"content": "ong"}, prompt=0, completion=2, finish="stop"),
    _frame({}, prompt=0, completion=0, finish="stop"),
    _frame({}, prompt=33, completion=24, finish="stop"),
]

_TOOL_CALL_REPLY = [
    _frame({"role": "assistant", "content": ""}, prompt=288, completion=0),
    _frame(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": ""},
                }
            ]
        },
        prompt=0,
        completion=18,
    ),
    _frame(
        {"tool_calls": [{"index": 0, "function": {"arguments": '{"city": "Paris"}'}}]},
        prompt=0,
        completion=12,
    ),
    _frame({}, prompt=0, completion=2, finish="tool_calls"),
    _frame({}, prompt=0, completion=0, finish="tool_calls"),
    _frame({}, prompt=288, completion=32, finish="tool_calls"),
]

#: OpenAI's own shape: usage once, on a closing frame with no choices.
_SINGLE_USAGE_REPLY = [
    b'data: {"object": "chat.completion.chunk", "model": "m", "choices": '
    b'[{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}]}\n\n',
    b'data: {"object": "chat.completion.chunk", "model": "m", "choices": [], "usage": '
    b'{"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}\n\n',
]


def _reply(frames: list[bytes]) -> Callable[[httpx.Request], httpx.Response]:
    def _handler(_request: httpx.Request) -> httpx.Response:
        body = b"".join(frames) + b"data: [DONE]\n\n"
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return _handler


def _model(frames: list[bytes]) -> ChatWorkersAI:
    transport = httpx.MockTransport(_reply(frames))
    return ChatWorkersAI(
        model=_MODEL,
        api_key=SecretStr("k"),
        base_url="https://api.cloudflare.com/client/v4/accounts/a/ai/v1",
        streaming=True,
        stream_usage=True,
        max_retries=0,
        http_client=httpx.Client(transport=transport),
        http_async_client=httpx.AsyncClient(transport=transport),
    )


def _merge(chunks: list[BaseMessageChunk]) -> AIMessageChunk:
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert isinstance(merged, AIMessageChunk)
    return merged


async def _astreamed(frames: list[bytes]) -> AIMessageChunk:
    return _merge([chunk async for chunk in _model(frames).astream([HumanMessage("hi")])])


def _streamed(frames: list[bytes]) -> AIMessageChunk:
    return _merge(list(_model(frames).stream([HumanMessage("hi")])))


class TestUsageIsTheCallsTotal:
    async def test_a_streamed_reply_bills_the_closing_total_once(self) -> None:
        merged = await _astreamed(_TEXT_REPLY)

        assert merged.usage_metadata is not None
        assert (merged.usage_metadata["input_tokens"], merged.usage_metadata["output_tokens"]) == (
            33,
            24,
        )

    def test_the_sync_stream_bills_the_closing_total_once(self) -> None:
        merged = _streamed(_TEXT_REPLY)

        assert merged.usage_metadata is not None
        assert merged.usage_metadata["total_tokens"] == 57

    async def test_a_tool_call_turn_bills_the_closing_total_once(self) -> None:
        merged = await _astreamed(_TOOL_CALL_REPLY)

        assert merged.usage_metadata is not None
        assert (merged.usage_metadata["input_tokens"], merged.usage_metadata["output_tokens"]) == (
            288,
            32,
        )

    async def test_a_stream_reporting_usage_once_is_unchanged(self) -> None:
        merged = await _astreamed(_SINGLE_USAGE_REPLY)

        assert merged.usage_metadata is not None
        assert merged.usage_metadata["total_tokens"] == 6
        assert merged.content == "hi"


class TestFinishReasonIsReportedOnce:
    @pytest.mark.parametrize(
        ("frames", "reason"), [(_TEXT_REPLY, "stop"), (_TOOL_CALL_REPLY, "tool_calls")]
    )
    async def test_the_repeated_closing_reason_merges_to_one(
        self, frames: list[bytes], reason: str
    ) -> None:
        merged = await _astreamed(frames)

        assert merged.response_metadata["finish_reason"] == reason

    def test_the_sync_stream_merges_it_to_one_too(self) -> None:
        assert _streamed(_TEXT_REPLY).response_metadata["finish_reason"] == "stop"


class TestTheReplyItselfIsUntouched:
    async def test_text_arrives_whole(self) -> None:
        assert (await _astreamed(_TEXT_REPLY)).content == "pong"

    async def test_the_tool_call_arrives_whole(self) -> None:
        merged = await _astreamed(_TOOL_CALL_REPLY)

        assert [(c["name"], c["args"], c["id"]) for c in merged.tool_calls] == [
            ("get_weather", {"city": "Paris"}, "call-1")
        ]
