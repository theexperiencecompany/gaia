"""OpenAI Responses API shaping for the scripted LLM stub: what ``client.responses.create`` reads.

Pure stdlib. A streamed reply is ``response.created``, the text as
``response.output_text.delta`` events, then ``response.completed`` carrying the
whole response and its usage; each SSE event names its type in ``event:`` and
in the data, the way OpenAI sends them. Text only: the stub scripts no tool
calls on this API (directives.resolve_text_response refuses them).
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import count
import json
import time
from typing import Any
from uuid import uuid4

from directives import SayResponse
from wire import ScriptedFault, estimate_tokens, split_pieces

_STREAM_PIECES = 3


def _usage(prompt_tokens: int, text: str) -> dict[str, Any]:
    output_tokens = estimate_tokens(text)
    return {
        "input_tokens": prompt_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": prompt_tokens + output_tokens,
    }


def _message_item(item_id: str, text: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
    }


def _response(
    response_id: str,
    model: str,
    created_at: int,
    *,
    status: str,
    output: list[dict[str, Any]],
    usage: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "model": model,
        "status": status,
        "output": output,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "metadata": {},
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": usage,
    }


def build_response(model: str, response: SayResponse, prompt_tokens: int) -> dict[str, Any]:
    """Non-streaming ``response`` object with one assistant message."""
    return _response(
        f"resp_stub_{uuid4().hex}",
        model,
        int(time.time()),
        status="completed",
        output=[_message_item(f"msg_stub_{uuid4().hex}", response.text)],
        usage=_usage(prompt_tokens, response.text),
    )


def stream_events(
    model: str, response: SayResponse, prompt_tokens: int
) -> Iterator[dict[str, Any]]:
    """Responses streaming events: created, the text deltas, completed (or a break on a fail)."""
    response_id = f"resp_stub_{uuid4().hex}"
    item_id = f"msg_stub_{uuid4().hex}"
    created_at = int(time.time())
    sequence = count()
    yield {
        "type": "response.created",
        "sequence_number": next(sequence),
        "response": _response(
            response_id, model, created_at, status="in_progress", output=[], usage=None
        ),
    }
    for piece in split_pieces(response.text, _STREAM_PIECES):
        yield {
            "type": "response.output_text.delta",
            "sequence_number": next(sequence),
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "delta": piece,
            "logprobs": [],
        }
    if response.fail is not None:
        # Raising inside the body generator drops the connection mid-response.
        raise ScriptedFault(response.fail)
    yield {
        "type": "response.completed",
        "sequence_number": next(sequence),
        "response": _response(
            response_id,
            model,
            created_at,
            status="completed",
            output=[_message_item(item_id, response.text)],
            usage=_usage(prompt_tokens, response.text),
        ),
    }


def response_sse_lines(model: str, response: SayResponse, prompt_tokens: int) -> Iterator[str]:
    """Serialize the streaming events as SSE, each named by its type."""
    for event in stream_events(model, response, prompt_tokens):
        yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
