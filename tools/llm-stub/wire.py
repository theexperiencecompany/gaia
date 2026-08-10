"""OpenAI/OpenRouter-compatible response shaping for the scripted LLM stub.

Pure stdlib. Builds the exact JSON shapes the ``langchain-openrouter`` client
(via the ``openrouter`` SDK) deserializes: a ``chat.completion`` object for
non-streaming requests, and ``chat.completion.chunk`` objects for streaming.

Streaming note: the SDK reads standard OpenAI SSE — each event is a
``data: {chunk}`` line and the stream ends with ``data: [DONE]``. The SDK wraps
each parsed chunk itself, so the stub emits plain OpenAI chunks.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import time
from typing import Any
from uuid import uuid4

from directives import Response, ToolCallResponse

# Split streamed payloads across a few chunks so the stub exercises the client's
# delta-assembly path (tool-call argument concatenation, content joining).
_STREAM_PIECES = 3


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


def build_chat_completion(model: str, response: Response) -> dict[str, Any]:
    """Non-streaming ``chat.completion`` payload."""
    if isinstance(response, ToolCallResponse):
        message = {
            "role": "assistant",
            "content": None,
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
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
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


def _split(text: str, pieces: int) -> list[str]:
    if not text:
        return [""]
    size = max(1, -(-len(text) // pieces))  # ceil division
    return [text[i : i + size] for i in range(0, len(text), size)]


def stream_chunks(model: str, response: Response) -> Iterator[dict[str, Any]]:
    """OpenAI-style streaming chunks, opener → deltas → terminator."""
    completion_id = _completion_id()
    created = _now()

    yield _chunk(model, completion_id, created, {"role": "assistant"}, None)

    if isinstance(response, ToolCallResponse):
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
        for piece in _split(response.text, _STREAM_PIECES):
            yield _chunk(model, completion_id, created, {"content": piece}, None)
        finish_reason = "stop"

    yield _chunk(model, completion_id, created, {}, finish_reason)


def sse_lines(model: str, response: Response) -> Iterator[str]:
    """Serialize streaming chunks as SSE ``data:`` lines terminated by ``[DONE]``."""
    for chunk in stream_chunks(model, response):
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
