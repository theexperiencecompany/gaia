"""OpenAI/OpenRouter-compatible response shaping for the scripted LLM stub.

Pure stdlib. Builds the exact JSON shapes the ``langchain-openrouter`` client
(via the ``openrouter`` SDK) deserializes: a ``chat.completion`` object for
non-streaming requests, and ``chat.completion.chunk`` objects for streaming.

Streaming note: the SDK reads standard OpenAI SSE — each event is a
``data: {chunk}`` line and the stream ends with ``data: [DONE]``. The SDK wraps
each parsed chunk itself, so the stub emits plain OpenAI chunks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
import json
import re
import time
from typing import Any
from uuid import uuid4

from directives import Response, ToolCallResponse


class ScriptedFault(RuntimeError):
    """A [[fail:...]] directive firing: breaks the streamed response mid-flight."""


# Split streamed payloads across a few chunks so the stub exercises the client's
# delta-assembly path (tool-call argument concatenation, content joining).
_STREAM_PIECES = 3
# The usual rough size of a token, so sim replies report the non-zero usage a
# real provider does and GAIA meters them as it meters production calls.
_CHARS_PER_TOKEN = 4


def _now() -> int:
    return int(time.time())


def _completion_id() -> str:
    return f"chatcmpl-stub-{uuid4().hex}"


def _tool_call_id() -> str:
    return f"call_stub_{uuid4().hex[:24]}"


def _tool_call_block(response: ToolCallResponse, *, call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": response.name,
            "arguments": json.dumps(response.args, ensure_ascii=False),
        },
    }


def estimate_tokens(text: str) -> int:
    """Approximate token count of text, at least 1."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def prompt_tokens(messages: list[dict[str, Any]]) -> int:
    """Approximate prompt size of a request's messages, the input side of its usage."""
    return estimate_tokens(json.dumps(messages, ensure_ascii=False))


def _usage(prompt_tokens: int, response: Response) -> dict[str, int]:
    """OpenAI usage block: the request's size in, the scripted reply's size out."""
    if isinstance(response, ToolCallResponse):
        output = response.text + response.name + json.dumps(response.args, ensure_ascii=False)
    else:
        output = response.text
    completion_tokens = estimate_tokens(output)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def build_chat_completion(model: str, response: Response, prompt_tokens: int) -> dict[str, Any]:
    """Non-streaming ``chat.completion`` payload."""
    if isinstance(response, ToolCallResponse):
        message = {
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [_tool_call_block(response, call_id=_tool_call_id())],
        }
        finish_reason = "tool_calls"
    else:
        message = {"role": "assistant", "content": response.text}
        finish_reason = "stop"

    return {
        "id": _completion_id(),
        "object": "chat.completion",
        "created": _now(),
        "model": model,
        "system_fingerprint": None,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": message,
                "logprobs": None,
            }
        ],
        "usage": _usage(prompt_tokens, response),
    }


def _chunk(
    model: str, completion_id: str, created: int, delta: dict[str, Any], finish_reason: str | None
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _words(text: str) -> list[str]:
    """Split text into words, each keeping the whitespace after it, so the pieces rejoin exactly."""
    words = re.findall(r"\S+\s*", text)
    leading = text[: len(text) - len(text.lstrip())]
    return [leading + words[0], *words[1:]] if words else [text]


def _split(text: str, pieces: int) -> list[str]:
    if not text:
        return [""]
    size = max(1, -(-len(text) // pieces))  # ceil division
    return [text[i : i + size] for i in range(0, len(text), size)]


def _content_pieces(text: str, pace_ms: int) -> list[str]:
    """Split text a word per chunk when paced, else into a few even pieces."""
    return _words(text) if pace_ms else _split(text, _STREAM_PIECES)


def stream_chunks(model: str, response: Response, prompt_tokens: int) -> Iterator[dict[str, Any]]:
    """OpenAI-style streaming chunks, opener → deltas → terminator → usage-only chunk."""
    completion_id = _completion_id()
    created = _now()

    yield _chunk(model, completion_id, created, {"role": "assistant"}, None)

    if isinstance(response, ToolCallResponse):
        for piece in _content_pieces(response.text, response.pace_ms) if response.text else ():
            yield _chunk(model, completion_id, created, {"content": piece}, None)
        call_id = _tool_call_id()
        arguments = json.dumps(response.args, ensure_ascii=False)
        yield _chunk(
            model,
            completion_id,
            created,
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": response.name, "arguments": ""},
                    }
                ]
            },
            None,
        )
        for piece in _split(arguments, _STREAM_PIECES):
            yield _chunk(
                model,
                completion_id,
                created,
                {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]},
                None,
            )
        finish_reason = "tool_calls"
    else:
        for piece in _content_pieces(response.text, response.pace_ms):
            yield _chunk(model, completion_id, created, {"content": piece}, None)
        if response.fail is not None:
            # Raising inside the body generator makes uvicorn drop the connection
            # mid-response — the client sees exactly a provider stream breaking.
            raise ScriptedFault(response.fail)
        finish_reason = "stop"

    yield _chunk(model, completion_id, created, {}, finish_reason)
    # What stream_options.include_usage asks for: a final chunk with no choices.
    yield {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [],
        "usage": _usage(prompt_tokens, response),
    }


async def sse_lines(model: str, response: Response, prompt_tokens: int) -> AsyncIterator[str]:
    """Serialize streaming chunks as SSE ``data:`` lines terminated by ``[DONE]``, paced if asked."""
    pace_s = response.pace_ms / 1000
    for chunk in stream_chunks(model, response, prompt_tokens):
        if pace_s and chunk["choices"] and "content" in chunk["choices"][0]["delta"]:
            await asyncio.sleep(pace_s)
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
