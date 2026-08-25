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

from langchain_core.callbacks import (
    AsyncCallbackHandler,
    BaseCallbackHandler,
    UsageMetadataCallbackHandler,
)
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr
import pytest

# Importing the patch module normalises ChatOpenRouter's stream at import time.
from app.patches import openrouter_cumulative_usage_patch as _patch
from shared.py.wide_events import log, log_context

assert _patch is not None  # imported for its side effect: the patch applies at import
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

#: finish_reason and a usage snapshot on the SAME chunk — the only shape where
#: normalisation rebuilds a chunk that also carries generation_info.
FINISH_WITH_USAGE: list[str] = [
    _chunk(delta={"role": "assistant", "content": ""}),
    _chunk(delta={"content": "hi"}, usage=_usage(89, 1)),
    _chunk(delta={}, finish="stop", usage=_usage(89, 10)),
]


class _ScriptedWire:
    """A loopback OpenAI-compatible endpoint replaying one scripted SSE turn per request."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = frames
        self.requests_served = 0
        #: The decoded body of the most recent request — what the wrapper
        #: actually forwarded to the provider.
        self.last_request: dict[str, Any] = {}
        wire = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                wire.last_request = json.loads(body) if body else {}
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


class _TokenRecorder(AsyncCallbackHandler, BaseCallbackHandler):
    """Records every ``on_llm_new_token`` the wrapper drives, sync or async."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def on_llm_new_token(self, token: str, *, chunk: Any = None, **kwargs: Any) -> None:
        self.calls.append((token, chunk))

    async def on_llm_new_token_async(self, token: str, **kwargs: Any) -> None:
        raise AssertionError("langchain dispatches the sync name on async handlers too")


class TestTheTokenCallback:
    """``BaseChatModel`` fires ``on_llm_new_token`` with the chunk the wrapper
    just yielded, so a consumer watching the callback must see the SAME
    normalised numbers the merged message reports. This is the live path — the
    wrapper is handed no run_manager of its own (langchain-core 1.4.8 calls
    ``_stream``/``_astream`` as ``(messages, stop=stop, **kwargs)``), so
    normalising the chunk is the only thing making the two views agree."""

    @pytest.mark.asyncio
    async def test_the_callback_carries_the_delta_not_the_snapshot(self) -> None:
        """A consumer summing the callback must land on the wire total, not the
        inflated one this patch exists to remove."""
        recorder = _TokenRecorder()
        streamed = 0
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            async for _chunk_out in _client(wire.base_url).astream(
                "hi", config={"callbacks": [recorder]}
            ):
                streamed += 1

        assert recorder.calls, "the token callback must fire"
        total_input = 0
        for _token, chunk in recorder.calls:
            usage = chunk.message.usage_metadata if chunk is not None else None
            if usage:
                total_input += usage["input_tokens"]
        assert total_input == WIRE_INPUT

    def test_the_sync_callback_carries_the_delta_too(self) -> None:
        """``_stream``'s twin — the sync graph path goes through it."""
        recorder = _TokenRecorder()
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            list(_client(wire.base_url).stream("hi", config={"callbacks": [recorder]}))

        assert recorder.calls, "the token callback must fire"
        total_input = sum(
            (chunk.message.usage_metadata or {}).get("input_tokens", 0)
            for _token, chunk in recorder.calls
            if chunk is not None
        )
        assert total_input == WIRE_INPUT


class TestWhatReachesUpstream:
    """The wrapper stands between the caller and the real generator; anything it
    forgets to forward is a silently ignored request."""

    @pytest.mark.asyncio
    async def test_stop_sequences_reach_the_provider(self) -> None:
        """Dropped, the model runs past the caller's stop sequence and the extra
        text is both billed and shown."""
        with _ScriptedWire(SINGLE_USAGE_FRAME) as wire:
            await _client(wire.base_url).ainvoke("hi", stop=["\n\nHuman:"])

        assert wire.last_request["stop"] == ["\n\nHuman:"]

    @pytest.mark.asyncio
    async def test_extra_model_kwargs_reach_the_provider(self) -> None:
        """`**kwargs` carries per-call overrides — temperature, response_format,
        tool definitions. Dropping them silently ignores the caller."""
        with _ScriptedWire(SINGLE_USAGE_FRAME) as wire:
            await _client(wire.base_url).ainvoke("hi", temperature=0.123)

        assert wire.last_request["temperature"] == 0.123

    def test_stop_sequences_reach_the_provider_on_the_sync_path(self) -> None:
        with _ScriptedWire(SINGLE_USAGE_FRAME) as wire:
            _client(wire.base_url).invoke("hi", stop=["\n\nHuman:"])

        assert wire.last_request["stop"] == ["\n\nHuman:"]

    def test_extra_model_kwargs_reach_the_provider_on_the_sync_path(self) -> None:
        with _ScriptedWire(SINGLE_USAGE_FRAME) as wire:
            _client(wire.base_url).invoke("hi", temperature=0.123)

        assert wire.last_request["temperature"] == 0.123


class TestGenerationInfoSurvivesNormalisation:
    """Normalisation rebuilds the chunk, so anything not copied onto the new one
    is dropped. ``generation_info`` is what a tracer reads off the callback chunk
    (the message's own ``response_metadata`` reaches consumers by a separate
    route, so the streamed message alone cannot show this loss)."""

    @pytest.mark.asyncio
    async def test_the_rebuilt_chunk_keeps_its_generation_info(self) -> None:
        recorder = _TokenRecorder()
        with _ScriptedWire(FINISH_WITH_USAGE) as wire:
            async for _chunk_out in _client(wire.base_url).astream(
                "hi", config={"callbacks": [recorder]}
            ):
                pass

        reasons = [
            (chunk.generation_info or {}).get("finish_reason")
            for _token, chunk in recorder.calls
            if chunk is not None
        ]
        assert "stop" in reasons


class _FakeRunManager:
    """Stands in for the manager langchain does not currently pass. Named, so the
    warning's ``run_manager_type`` has something specific to report."""


#: The whole warning, pinned: the message names the condition and the type says
#: which manager arrived. A test matching a substring passes on a mangled one.
_EXPECTED_RUN_MANAGER_WARNING = {
    "msg": "openrouter usage patch received a run_manager it does not forward",
    "run_manager_type": "_FakeRunManager",
}


class TestTheRunManagerAssumption:
    """This patch is only correct while langchain fires ``on_llm_new_token``
    itself. langchain-core 1.4.8 does — it calls ``_stream``/``_astream`` with
    no run_manager at all. If that ever changes, upstream would report the raw
    cumulative snapshot while the merged message reports the delta, and the two
    views of one turn would silently disagree."""

    @pytest.mark.asyncio
    async def test_an_ordinary_stream_is_handed_no_run_manager(self) -> None:
        """The assumption itself, checked against the installed langchain rather
        than trusted: a normal turn — sync and async — must produce no warning."""
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            client = _client(wire.base_url)
            async with log_context("patch_test"):
                async for _out in client.astream("hi"):
                    pass
                list(client.stream("hi"))
                warnings = list(log.get().get("warnings", []))

        assert warnings == [], warnings

    @pytest.mark.asyncio
    async def test_a_run_manager_reaching_the_sync_wrapper_is_reported(self) -> None:
        """The alarm, proven to ring — otherwise the check above is untestable
        theater that would stay green through the very change it guards."""
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            client = _client(wire.base_url)
            async with log_context("patch_test"):
                list(
                    _patch._stream(
                        client, [HumanMessage(content="hi")], run_manager=_FakeRunManager()
                    )
                )
                warnings = list(log.get().get("warnings", []))

        assert warnings == [_EXPECTED_RUN_MANAGER_WARNING], warnings

    @pytest.mark.asyncio
    async def test_a_run_manager_reaching_the_async_wrapper_is_reported(self) -> None:
        """Its twin — the async wrapper is the one the graph actually streams
        through, so an alarm wired to only one of them is half an alarm."""
        with _ScriptedWire(CUMULATIVE_EVERY_CHUNK) as wire:
            client = _client(wire.base_url)
            async with log_context("patch_test"):
                async for _out in _patch._astream(
                    client, [HumanMessage(content="hi")], run_manager=_FakeRunManager()
                ):
                    pass
                warnings = list(log.get().get("warnings", []))

        assert warnings == [_EXPECTED_RUN_MANAGER_WARNING], warnings


class TestThePatchIsBound:
    """apply() is what makes any of the above true of the real class."""

    def test_both_generators_are_rebound_to_the_wrapper(self) -> None:
        """The binding is put back FIRST, so this watches apply() do the work.

        Importing the module already applied it, so reading the class straight
        after a second apply() passes even when apply() wrote to some other
        attribute entirely — the wrappers were bound before it ran.
        """
        bound_stream = ChatOpenRouter._stream
        bound_astream = ChatOpenRouter._astream
        try:
            ChatOpenRouter._stream = _patch._ORIGINAL_STREAM
            ChatOpenRouter._astream = _patch._ORIGINAL_ASTREAM

            _patch.apply()

            assert ChatOpenRouter._stream is _patch._stream
            assert ChatOpenRouter._astream is _patch._astream
        finally:
            ChatOpenRouter._stream = bound_stream
            ChatOpenRouter._astream = bound_astream
