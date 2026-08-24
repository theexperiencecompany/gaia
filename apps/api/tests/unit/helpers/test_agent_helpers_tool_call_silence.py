"""Comms text that accompanies a tool call must never reach the user.

The comms prompt's "MOMENT 1: SILENT" rule was the only thing stopping the model
from narrating its own handoff, and models ignore it: in production the comms
agent answered "yeah, i can set all that up. let me get the tasks created…" with
a ``call_executor`` tool call attached, then answered again with the real
acknowledgement once the tool returned. The user got two replies.

The driver is what has to enforce it, and the enforcement point is NOT the
individual chunk. On the OpenAI/OpenRouter wire the text deltas arrive BEFORE
the tool-call deltas of the same message, carrying no tool-call marker at all —
so a per-chunk guard suppresses nothing. That is why these tests drive a real
``ChatOpenRouter`` against a real (loopback) SSE server emitting the real delta
order, through a real LangGraph with ``stream_mode=["messages", "updates"]``:
anything less faithful cannot tell a working guard from a decorative one.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_openrouter import ChatOpenRouter
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import SecretStr
import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from app.helpers.agent_helpers import execute_graph_streaming

PREAMBLE = "yeah, i can set all that up. let me get the tasks created"
ACK = "yeah, all of it's being set up now."


def _delta(**delta: Any) -> str:
    frame = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    return f"data: {json.dumps(frame)}\n\n"


#: Turn 1 — the exact production shape: two text deltas, then the tool call.
TURN_WITH_PREAMBLE = [
    _delta(role="assistant", content=""),
    _delta(content=PREAMBLE[:20]),
    _delta(content=PREAMBLE[20:]),
    _delta(
        tool_calls=[
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "call_executor", "arguments": ""},
            }
        ]
    ),
    _delta(tool_calls=[{"index": 0, "function": {"arguments": '{"task":"x"}'}}]),
]

#: Turn 2 — the real acknowledgement, no tool call.
TURN_WITH_ACK = [_delta(role="assistant", content=""), _delta(content=ACK)]


class _ScriptedWire:
    """A loopback OpenAI-compatible endpoint that replays scripted SSE turns."""

    def __init__(self, turns: list[list[str]]) -> None:
        self._turns = turns
        self._served = 0
        wire = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                index = min(wire._served, len(wire._turns) - 1)
                wire._served += 1
                for frame in wire._turns[index]:
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


class _GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _build_graph(base_url: str, nudges: int = 0) -> Any:
    """``agent → (tools → agent)* → END``, driven by a real streaming wire client.

    ``nudges`` mirrors the real graph's ``nudge_continue`` node: a tool-free
    reply is sent back for one more pass instead of ending the run, which is the
    only way a single turn produces two assistant messages the user keeps.
    """
    llm = ChatOpenRouter(model="m", api_key=SecretStr("k"), base_url=base_url, streaming=True)
    remaining = {"nudges": nudges}

    async def agent(state: _GraphState) -> _GraphState:
        return {"messages": [await llm.ainvoke(state["messages"])]}

    async def tools(state: _GraphState) -> _GraphState:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        call = last.tool_calls[0]
        return {"messages": [ToolMessage(content="Task accepted.", tool_call_id=call["id"])]}

    async def nudge(state: _GraphState) -> _GraphState:
        remaining["nudges"] -= 1
        return {"messages": [HumanMessage(content="keep going")]}

    def route(state: _GraphState) -> str:
        if getattr(state["messages"][-1], "tool_calls", None):
            return "tools"
        return "nudge" if remaining["nudges"] > 0 else END

    builder = StateGraph(_GraphState)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools)
    builder.add_node("nudge", nudge)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route, {"tools": "tools", "nudge": "nudge", END: END})
    builder.add_edge("tools", "agent")
    builder.add_edge("nudge", "agent")
    return builder.compile()


@pytest.fixture
def suppressed_seams() -> Iterator[None]:
    """Silence the two seams a bare driver run cannot reach: the cancellation
    flag (Redis) and tool-card formatting (the ChromaDB tool registry)."""
    with (
        patch("app.helpers.agent_helpers.stream_manager") as manager,
        patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new_callable=AsyncMock,
            return_value={"tool_name": "tool_calls_data", "data": {}},
        ),
    ):
        manager.is_cancelled = AsyncMock(return_value=False)
        yield


async def _drive(base_url: str) -> list[str]:
    graph = _build_graph(base_url)
    config: Any = {"agent_name": "comms_agent", "configurable": {"user_id": "u1"}}
    stream: AsyncGenerator[str, None] = execute_graph_streaming(
        graph, {"messages": [("user", "set all this up")]}, config
    )
    return [frame async for frame in stream]


def _responses(frames: list[str]) -> list[str]:
    """The assistant text the client actually received, frame by frame."""
    out = []
    for frame in frames:
        if not frame.startswith("data: "):
            continue
        payload = frame[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        data = json.loads(payload)
        if "response" in data:
            out.append(data["response"])
    return out


def _boundaries(frames: list[str]) -> list[dict[str, Any]]:
    out = []
    for frame in frames:
        if not frame.startswith("data: "):
            continue
        payload = frame[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        data = json.loads(payload)
        if "message_boundary" in data:
            out.append(data["message_boundary"])
    return out


def _complete_message(frames: list[str]) -> str:
    marker = next(f for f in frames if f.startswith("nostream: "))
    return str(json.loads(marker.removeprefix("nostream: "))["complete_message"])


@pytest.mark.regression
async def test_a_handoff_preamble_is_never_persisted(suppressed_seams: None) -> None:
    """The turn's reply is the acknowledgement alone.

    In production this was persisted as the preamble glued to the ack, and the
    user saw both as separate messages on Telegram.
    """
    with _ScriptedWire([TURN_WITH_PREAMBLE, TURN_WITH_ACK]) as wire:
        frames = await _drive(wire.base_url)

    assert _complete_message(frames) == ACK


async def test_each_assistant_message_ends_with_a_boundary_frame(
    suppressed_seams: None,
) -> None:
    """The stream says which message just ended and whether its text was a
    preamble, so a live consumer can retract what it already showed.

    The retraction is what makes this workable: the wire hands over the preamble
    before it hands over the tool call, so the text is unavoidably already on the
    client. Suppressing it there instead would mean withholding every token of
    every reply until its message ended.
    """
    with _ScriptedWire([TURN_WITH_PREAMBLE, TURN_WITH_ACK]) as wire:
        frames = await _drive(wire.base_url)

    boundaries = _boundaries(frames)
    assert [b["discarded"] for b in boundaries] == [True, False]
    assert all(b["message_id"] for b in boundaries)


async def test_the_discard_arrives_before_the_replacement_text(
    suppressed_seams: None,
) -> None:
    """Ordering is the whole contract: a consumer must be told to drop the
    preamble before the real reply starts arriving, or it has no way to tell
    which text belongs to which message."""
    with _ScriptedWire([TURN_WITH_PREAMBLE, TURN_WITH_ACK]) as wire:
        frames = await _drive(wire.base_url)

    kinds = [
        "discard" if '"discarded": true' in f else "text" if '"response"' in f else "other"
        for f in frames
    ]
    assert kinds.index("discard") < len(kinds) - 1 - kinds[::-1].index("text")
    # And the preamble did stream first — this is a retraction, not a suppression.
    assert kinds.index("text") < kinds.index("discard")


async def test_tool_progress_still_streams_for_a_discarded_message(
    suppressed_seams: None,
) -> None:
    """Silencing the narration must not silence the tool card — the user has to
    see that something is happening."""
    with _ScriptedWire([TURN_WITH_PREAMBLE, TURN_WITH_ACK]) as wire:
        frames = await _drive(wire.base_url)

    assert any("tool_data" in f for f in frames)


async def test_a_tool_free_reply_streams_unchanged(suppressed_seams: None) -> None:
    """The guard must not cost an ordinary answer its token streaming."""
    with _ScriptedWire([TURN_WITH_ACK]) as wire:
        frames = await _drive(wire.base_url)

    assert _responses(frames) == [ACK]
    assert _boundaries(frames) == [] or _boundaries(frames)[0]["discarded"] is False
    assert _complete_message(frames) == ACK


async def test_two_kept_messages_are_joined_by_the_break_sentinel(
    suppressed_seams: None,
) -> None:
    """Two assistant messages in one turn are two bubbles, not one glued
    sentence — "fixing it." followed by "fixing it now" was persisted as
    "fixing it.fixing it now". The boundary between them is the sentinel every
    consumer already splits on.
    """
    second = "and it's done."
    with _ScriptedWire(
        [
            TURN_WITH_PREAMBLE,
            TURN_WITH_ACK,
            [_delta(role="assistant", content=""), _delta(content=second)],
        ]
    ) as wire:
        graph = _build_graph(wire.base_url, nudges=1)
        config: Any = {"agent_name": "comms_agent", "configurable": {"user_id": "u1"}}
        frames = [
            frame
            async for frame in execute_graph_streaming(
                graph, {"messages": [("user", "go")]}, config
            )
        ]

    assert _complete_message(frames) == f"{ACK}{NEW_MESSAGE_BREAKER}{second}"
