"""A regenerated reply must reach the client as ONE reply, not two.

The style guard cannot suppress the draft — the wire has already streamed every
token of it by the time there is a complete message to score. So it retracts:
the same ``message_boundary`` frame with ``discarded: true`` that the handoff
preamble uses, written mid-node between the draft's tokens and the rewrite's.

Getting the ORDER wrong is the whole risk, and it is invisible to a unit test of
the middleware alone: bots hold "the text since the last boundary" with no
message id anywhere, so a retraction arriving after the replacement text drops
the replacement too. That is why this drives the real driver over a real
streaming client against a real (loopback) SSE server — the frame order the
client sees is the thing under test, and only the wire can produce it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
import json
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage
from langchain_openrouter import ChatOpenRouter
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import SecretStr
import pytest

from app.agents.middleware.style_guard import StyleGuardMiddleware
from app.helpers.agent_helpers import execute_graph_streaming

from .test_agent_helpers_tool_call_silence import _delta, _ScriptedWire

#: Three tells in one short reply: the antithesis, an em dash, a closing hook.
DIRTY = "it's not a feature, it's a switching cost — that's the point.\n\nwant me to draft that?"
CLEAN = "that's a switching cost, and it's the point. i can draft it."

TURN_DIRTY = [_delta(role="assistant", content=""), _delta(content=DIRTY)]
TURN_CLEAN = [_delta(role="assistant", content=""), _delta(content=CLEAN)]


class _GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _build_graph(base_url: str) -> Any:
    """One agent node, wrapped in the real style guard, on a real wire client."""
    llm = ChatOpenRouter(model="m", api_key=SecretStr("k"), base_url=base_url, streaming=True)
    guard = StyleGuardMiddleware()

    async def handler(request: ModelRequest) -> ModelResponse:
        return ModelResponse(result=[await llm.ainvoke(request.messages)])

    async def agent(state: _GraphState) -> _GraphState:
        request = ModelRequest(
            model=llm,
            messages=list(state["messages"]),
            tools=[],
            state={"messages": list(state["messages"])},
            runtime=None,
        )
        response = await guard.awrap_model_call(request, handler)
        final = response.result[0]
        assert isinstance(final, AIMessage)
        return {"messages": [final]}

    builder = StateGraph(_GraphState)
    builder.add_node("agent", agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    return builder.compile()


@pytest.fixture
def suppressed_seams() -> Iterator[None]:
    """Silence the seams a bare driver run cannot reach: the cancellation flag
    (Redis) and the retracted draft's budget write (Redis + pricing)."""
    with (
        patch("app.helpers.agent_helpers.stream_manager") as manager,
        patch(
            "app.agents.middleware.style_guard.record_llm_call",
            new_callable=AsyncMock,
            return_value=0.0,
        ),
    ):
        manager.is_cancelled = AsyncMock(return_value=False)
        yield


async def _drive(base_url: str) -> list[str]:
    graph = _build_graph(base_url)
    config: Any = {"agent_name": "comms_agent", "configurable": {"user_id": "u1"}}
    stream: AsyncGenerator[str, None] = execute_graph_streaming(
        graph, {"messages": [("user", "why does it matter?")]}, config
    )
    return [frame async for frame in stream]


def _wire_log(frames: list[str]) -> list[tuple[str, Any]]:
    """The frames a client acts on, in order: text, boundaries, and the save."""
    log: list[tuple[str, Any]] = []
    for frame in frames:
        if frame.startswith("nostream: "):
            log.append(("save", json.loads(frame.removeprefix("nostream: "))["complete_message"]))
            continue
        if not frame.startswith("data: "):
            continue
        payload = frame[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        data = json.loads(payload)
        if "response" in data:
            log.append(("text", data["response"]))
        elif "message_boundary" in data:
            log.append(("boundary", data["message_boundary"]))
    return log


@pytest.mark.unit
async def test_the_draft_is_retracted_before_the_rewrite_streams(
    suppressed_seams: None,
) -> None:
    """draft text → discard(draft) → rewrite text → keep(rewrite) → save(rewrite).

    Any other order breaks a bot: it holds the text since the last boundary with
    no message id, so a discard landing after the rewrite's text takes the
    rewrite down with it.
    """
    with _ScriptedWire([TURN_DIRTY, TURN_CLEAN]) as wire:
        frames = await _drive(wire.base_url)

    kinds = [kind for kind, _ in _wire_log(frames)]
    log = _wire_log(frames)

    assert kinds == ["text", "boundary", "text", "boundary", "save"]
    assert log[0][1] == DIRTY
    assert log[1][1]["discarded"] is True
    assert log[2][1] == CLEAN
    assert log[3][1]["discarded"] is False
    # The retraction and the keep name DIFFERENT messages — a shared id would
    # make the discard apply to the reply the user is meant to keep.
    assert log[1][1]["message_id"] != log[3][1]["message_id"]


@pytest.mark.unit
async def test_only_the_rewrite_is_persisted(suppressed_seams: None) -> None:
    """The retracted draft is off the user's screen; leaving it in the saved
    turn would put it straight back on the next page load."""
    with _ScriptedWire([TURN_DIRTY, TURN_CLEAN]) as wire:
        frames = await _drive(wire.base_url)

    saved = next(value for kind, value in _wire_log(frames) if kind == "save")
    assert saved == CLEAN


@pytest.mark.unit
async def test_a_clean_reply_streams_once_with_no_retraction(
    suppressed_seams: None,
) -> None:
    """The guard must cost an already-clean reply nothing: one model call, one
    bubble, no retraction frame."""
    with _ScriptedWire([TURN_CLEAN]) as wire:
        frames = await _drive(wire.base_url)

    log = _wire_log(frames)
    assert [kind for kind, _ in log] == ["text", "boundary", "save"]
    assert log[1][1]["discarded"] is False
    assert log[2][1] == CLEAN
