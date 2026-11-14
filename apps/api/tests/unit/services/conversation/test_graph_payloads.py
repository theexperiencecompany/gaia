"""payloads_for_stream_event never releases comms text it later takes back."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.agents.tools.core.registry import ToolRegistry
from app.models.conversation_frame_models import (
    MessageBoundaryEvent,
    ResponseEvent,
    StreamPayload,
)
from app.models.stream_events import MessageBoundaryPayload
from app.services.conversation.graph_payloads import GraphStreamState, payloads_for_stream_event
from app.services.conversation.reply_text import ReplyText
from app.utils.errors import ShownReplyRetriedError

_NODE_RUN = {"langgraph_checkpoint_ns": "agent:1"}


@pytest.fixture(autouse=True)
def _core_tools() -> Iterator[None]:
    """Name the hand-off's card from GAIA's real core tool registry."""
    registry = ToolRegistry()
    registry.setup()
    with patch(
        "app.utils.agent_utils.get_tool_registry", new_callable=AsyncMock, return_value=registry
    ):
        yield


async def _payloads(state: GraphStreamState, *events: tuple[object, ...]) -> list[StreamPayload]:
    return [
        payload
        for event in events
        async for payload in payloads_for_stream_event(event, state, True, None, None)
    ]


def _chunk(message_id: str, text: str) -> tuple[object, ...]:
    return ((), "messages", (AIMessageChunk(id=message_id, content=text), _NODE_RUN))


def _node_end(message: AIMessage) -> tuple[object, ...]:
    return ((), "updates", {"agent": {"messages": [message]}})


async def test_a_preamble_before_a_hand_off_stays_said() -> None:
    state = GraphStreamState()
    handoff = AIMessage(
        id="m1",
        content="Let me look into that.",
        tool_calls=[{"name": "handoff", "args": {"task": "x"}, "id": "c1"}],
    )
    payloads = await _payloads(state, _chunk("m1", "Let me look into that."), _node_end(handoff))
    shown = ReplyText()
    for payload in payloads:
        if isinstance(payload, ResponseEvent | MessageBoundaryEvent):
            shown = shown.take(payload)
    assert shown.text == "Let me look into that."
    assert payloads[-1] == MessageBoundaryEvent(
        message_boundary=MessageBoundaryPayload(message_id="m1")
    )


async def test_a_model_call_retried_after_its_text_showed_fails_instead_of_taking_it_back() -> None:
    state = GraphStreamState()
    assert await _payloads(state, _chunk("m1", "Your flight ")) == [
        ResponseEvent(response="Your flight ")
    ]
    with pytest.raises(ShownReplyRetriedError) as retried:
        await _payloads(state, _chunk("m2", "Your flight leaves"))
    assert retried.value.meta == {"abandoned_message_id": "m1"}


async def test_a_model_call_retried_before_any_text_showed_streams_the_new_attempt() -> None:
    state = GraphStreamState()
    # An emoji alone may end as a reaction, so nothing of the first attempt was released.
    assert await _payloads(state, _chunk("m1", "\U0001f44d")) == []
    assert await _payloads(state, _chunk("m2", "Sure, done.")) == [
        ResponseEvent(response="Sure, done.")
    ]
