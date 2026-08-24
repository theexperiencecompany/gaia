"""A streamed turn must be billed for the tokens the provider actually reported.

OpenAI-compatible ``usage`` frames are *cumulative snapshots of the whole
response*, not per-chunk deltas. Providers are free to repeat that snapshot on
every chunk, and some do: a live probe of the DEV_LLM lane (a deepseek-v4-flash
endpoint) returned an 8-chunk answer carrying five usage frames, all reporting
``input_tokens: 89`` and a completion count climbing 1 → 6 → 10 → 10 → 10.
``AIMessageChunk.__add__`` merges those frames with ``add_usage``, which ADDS —
so the merged message claimed 445 input and 37 output tokens for a call that
really spent 89 and 10. Everything downstream of the merge (the budget wall,
``record_llm_call``, the ``model.*`` wide event, the per-turn usage the frontend
is handed) inherits the inflated number, multiplied by however many chunks the
answer happened to arrive in.

These tests drive a real ``ChatOpenRouter`` against a real (loopback) SSE server
replaying frame shapes captured from two live providers, because the defect
lives in the merge of real chunks — a hand-built ``AIMessageChunk`` pair would
test our own idea of the wire instead of the wire.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage
from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr
import pytest

# Importing the patch module normalises ChatOpenRouter's stream at import time.
import app.patches.openrouter_cumulative_usage_patch  # noqa: F401
from app.services.llm_metering import extract_message_usage

MODEL = "deepseek-v4-flash"


def _chunk(
    *,
    delta: dict[str, Any] | None = None,
    finish: str | None = None,
    usage: dict[str, Any] | None = None,
    choices: bool = True,
) -> str:
    frame: dict[str, Any] = {
        "id": "gen-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": MODEL,
        "choices": (
            [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if choices else []
        ),
    }
    if usage is not None:
        frame["usage"] = usage
    return f"data: {json.dumps(frame)}\n\n"


def _usage(prompt: int, completion: int, *, cached: int = 0, reasoning: int = 0) -> dict[str, Any]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": cached},
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    }


#: Captured from a live DEV_LLM-lane call: the cumulative snapshot repeats on
#: five of the eight chunks. Real spend is 89 in / 10 out.
CUMULATIVE_EVERY_CHUNK: list[str] = [
    _chunk(delta={"role": "assistant", "content": ""}),
    _chunk(delta={"content": "h"}, usage=_usage(89, 1, cached=64)),
    _chunk(delta={"content": "i"}, usage=_usage(89, 6, cached=64)),
    _chunk(delta={"content": "!"}, usage=_usage(89, 10, cached=64)),
    _chunk(delta={}, usage=_usage(89, 10, cached=64)),
    _chunk(delta={}, finish="stop"),
    _chunk(delta={}, usage=_usage(89, 10, cached=64)),
    _chunk(delta={}),
]
WIRE_INPUT, WIRE_OUTPUT, WIRE_CACHED = 89, 10, 64

#: Captured from a live openrouter.ai call to deepseek/deepseek-v4-flash-0731:
#: two finish_reason chunks (the reasoning block and the content block), and the
#: usage snapshot exactly once. Nothing may change about how this one is billed.
SINGLE_USAGE_FRAME: list[str] = [
    _chunk(delta={"role": "assistant", "content": ""}),
    _chunk(delta={"reasoning": "thinking"}),
    _chunk(delta={"content": "hi"}),
    _chunk(delta={}, finish="stop"),
    _chunk(delta={}, finish="stop", usage=_usage(10, 39, reasoning=33)),
]


class _ScriptedWire:
    """A loopback OpenAI-compatible endpoint replaying one scripted SSE turn per request."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = frames
        self.requests_served = 0
        wire = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length", 0)))
                wire.requests_served += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for frame in wire._frames:
                    self.wfile.write(frame.encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/v1"

    def __enter__(self) -> _ScriptedWire:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()


def _client(base_url: str) -> ChatOpenRouter:
    return ChatOpenRouter(
        model=MODEL,
        api_key=SecretStr("k"),
        base_url=base_url,
        streaming=True,
        stream_usage=True,
    )


class TestCumulativeUsageIsNotSummed:
    """The repeated-snapshot wire shape — the one that inflates the bill."""

    @pytest.mark.asyncio
    async def test_merged_message_reports_the_wire_totals(self) -> None:
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            message = await _client(wire.base_url).ainvoke("hi")

        assert isinstance(message, AIMessage)
        usage = message.usage_metadata
        assert usage is not None
        assert usage["input_tokens"] == WIRE_INPUT
        assert usage["output_tokens"] == WIRE_OUTPUT
        assert usage["total_tokens"] == WIRE_INPUT + WIRE_OUTPUT
        assert (usage.get("input_token_details") or {}).get("cache_read") == WIRE_CACHED

    @pytest.mark.asyncio
    async def test_metering_extraction_matches_the_wire(self) -> None:
        """What ``record_llm_call`` charges the budget is what the provider reported."""
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            message = await _client(wire.base_url).ainvoke("hi")

        assert isinstance(message, AIMessage)
        assert extract_message_usage(message) == {
            "input_tokens": WIRE_INPUT,
            "output_tokens": WIRE_OUTPUT,
            "cached_tokens": WIRE_CACHED,
            "reasoning_tokens": 0,
        }

    @pytest.mark.asyncio
    async def test_usage_callback_handler_reports_the_wire_totals(self) -> None:
        """The per-turn usage handed to the frontend and logged as the turn total."""
        handler = UsageMetadataCallbackHandler()
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            await _client(wire.base_url).ainvoke("hi", config={"callbacks": [handler]})

        assert handler.usage_metadata[MODEL]["input_tokens"] == WIRE_INPUT
        assert handler.usage_metadata[MODEL]["output_tokens"] == WIRE_OUTPUT

    def test_sync_stream_reports_the_wire_totals(self) -> None:
        """``invoke_llm`` (the sync graph path) merges through ``_stream``, not ``_astream``."""
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            message = _client(wire.base_url).invoke("hi")

        assert isinstance(message, AIMessage)
        assert message.usage_metadata is not None
        assert message.usage_metadata["input_tokens"] == WIRE_INPUT
        assert message.usage_metadata["output_tokens"] == WIRE_OUTPUT

    @pytest.mark.asyncio
    async def test_streamed_chunks_sum_to_the_wire_totals(self) -> None:
        """Any consumer that adds up the streamed chunks lands on the same number."""
        total_input = 0
        total_output = 0
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            async for chunk in _client(wire.base_url).astream("hi"):
                usage = getattr(chunk, "usage_metadata", None)
                if usage:
                    total_input += usage["input_tokens"]
                    total_output += usage["output_tokens"]

        assert total_input == WIRE_INPUT
        assert total_output == WIRE_OUTPUT


class TestSingleUsageFrameIsUnchanged:
    """The openrouter.ai wire shape — already correct, and must stay correct."""

    @pytest.mark.asyncio
    async def test_single_frame_is_reported_verbatim(self) -> None:
        with _ScriptedWire(SINGLE_USAGE_FRAME) as wire:
            message = await _client(wire.base_url).ainvoke("hi")

        assert isinstance(message, AIMessage)
        assert extract_message_usage(message) == {
            "input_tokens": 10,
            "output_tokens": 39,
            "cached_tokens": 0,
            "reasoning_tokens": 33,
        }


class TestUsageStillAccumulatesAcrossCalls:
    """The normalisation is scoped to one response — two calls still add up.

    ``UsageMetadataCallbackHandler`` sums across LLM calls on purpose: that is
    how a multi-step agent turn reports its total. A fix that reached the
    handler's own addition would silently under-bill every multi-step turn.
    """

    @pytest.mark.asyncio
    async def test_two_calls_report_the_sum(self) -> None:
        handler = UsageMetadataCallbackHandler()
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            client = _client(wire.base_url)
            await client.ainvoke("hi", config={"callbacks": [handler]})
            await client.ainvoke("hi", config={"callbacks": [handler]})
            assert wire.requests_served == 2

        assert handler.usage_metadata[MODEL]["input_tokens"] == WIRE_INPUT * 2
        assert handler.usage_metadata[MODEL]["output_tokens"] == WIRE_OUTPUT * 2
