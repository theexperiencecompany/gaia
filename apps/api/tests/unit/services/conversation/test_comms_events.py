"""Graph stream events to step events: typed payloads from the shared translator, the summary call, the outcome."""

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.models.conversation_frame_models import MessageBoundaryEvent, ResponseEvent
from app.services.conversation.comms_events import CommsEventMapper, GraphEvent, payload_from_frame
from app.services.conversation.ports import (
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    RunOutcome,
    Silent,
    Streamed,
    Summarized,
)


def silent_call(node: str = "agent") -> GraphEvent:
    chunk = AIMessageChunk(content="summary text", id="sum")
    return ((), "messages", (chunk, {"silent": True, "langgraph_node": node}))


def answer(text: str) -> GraphEvent:
    return ((), "updates", {"agent": {"messages": [AIMessage(content=text, id="m1")]}})


def test_a_response_frame_decodes_to_its_typed_payload() -> None:
    assert payload_from_frame('data: {"response": "hi"}\n\n') == ResponseEvent(response="hi")


@pytest.mark.parametrize(
    "frame", ['data: {"model_fallback": {"model": "x"}}\n\n', "nostream: {}", "data: [1]\n\n"]
)
def test_frames_the_conversation_stream_does_not_carry_decode_to_none(frame: str) -> None:
    assert payload_from_frame(frame) is None


async def test_the_silent_call_before_the_answer_is_the_summary_and_is_reported_once() -> None:
    mapper = CommsEventMapper("u-1")
    assert await mapper.map(silent_call()) == [Summarized()]
    assert await mapper.map(silent_call()) == []


async def test_a_silent_call_after_the_answer_is_follow_up_work_not_a_summary() -> None:
    mapper = CommsEventMapper("u-1")
    await mapper.map(answer("done"))
    assert await mapper.map(silent_call("follow_up_actions")) == []


async def test_an_answer_streams_its_text_then_reports_the_model_output() -> None:
    mapper = CommsEventMapper("u-1")
    token: GraphEvent = (
        (),
        "messages",
        (AIMessageChunk(content="hello", id="m1"), {"langgraph_node": "agent"}),
    )
    assert await mapper.map(token) == [Streamed(payload=ResponseEvent(response="hello"))]
    closing = await mapper.map(answer("hello"))
    assert isinstance(closing[0], Streamed)
    assert isinstance(closing[0].payload, MessageBoundaryEvent)
    assert closing[1:] == [ModelOutput(has_tool_calls=False)]
    assert mapper.finish() == [Finished(outcome=Replied(text="hello"))]


async def test_a_namespaced_update_is_not_the_comms_model_returning() -> None:
    mapper = CommsEventMapper("u-1")
    nested: GraphEvent = (
        ("child:1",),
        "updates",
        {"agent": {"messages": [AIMessage(content="x")]}},
    )
    assert ModelOutput(has_tool_calls=False) not in await mapper.map(nested)


@pytest.mark.parametrize(
    ("text", "outcome"),
    [("👍", Reacted(emoji="👍")), ("<SILENCE>nothing to add</SILENCE>", Silent())],
)
async def test_a_directive_answer_ends_as_a_reaction_or_silence(
    text: str, outcome: RunOutcome
) -> None:
    mapper = CommsEventMapper("u-1")
    await mapper.map(answer(text))
    assert mapper.finish()[-1] == Finished(outcome=outcome)
