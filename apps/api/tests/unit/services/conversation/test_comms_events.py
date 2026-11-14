"""Graph stream events to step events: typed payloads from the shared translator, the summary call, the outcome."""

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.models.conversation_frame_models import MessageBoundaryEvent, ResponseEvent
from app.services.conversation.comms_events import CommsEventMapper, GraphEvent
from app.services.conversation.ports import (
    Answered,
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    RunOutcome,
    Silent,
    Streamed,
    Summarized,
    ToolsRan,
)


def silent_call(node: str = "agent") -> GraphEvent:
    chunk = AIMessageChunk(content="summary text", id="sum")
    return ((), "messages", (chunk, {"silent": True, "langgraph_node": node}))


def answer(text: str) -> GraphEvent:
    return ((), "updates", {"agent": {"messages": [AIMessage(content=text, id="m1")]}})


async def test_a_hooks_raw_tool_payload_reaches_the_step_as_a_card() -> None:
    mapper = CommsEventMapper("u-1")
    events = await mapper.map(((), "custom", {"email_fetch_data": [{"id": "e1"}]}))
    (card,) = [e.payload.tool_data for e in events if isinstance(e, Streamed)]
    assert (card["tool_name"], card["data"]) == ("email_fetch_data", [{"id": "e1"}])


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


async def test_the_tools_node_returning_is_the_tool_calls_having_run() -> None:
    mapper = CommsEventMapper("u-1")
    tools: GraphEvent = ((), "updates", {"tools": {"messages": []}})
    nested: GraphEvent = (("child:1",), "updates", {"tools": {"messages": []}})

    assert await mapper.map(tools) == [ToolsRan()]
    assert await mapper.map(nested) == []


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


async def test_the_answer_is_reported_final_when_the_follow_up_pass_starts() -> None:
    """Regression (live test): the step learned of the answer only after the follow-up model call."""
    mapper = CommsEventMapper("u-1")
    await mapper.map(answer("hello"))
    started = await mapper.map(((), "custom", {"main_response_complete": True}))
    suggested = await mapper.map(((), "custom", {"follow_up_actions": ["Ask more"]}))
    assert [event for event in started if isinstance(event, Answered)] == [
        Answered(outcome=Replied(text="hello"))
    ]
    assert mapper.finish()[-1] == Finished(
        outcome=Replied(text="hello", follow_up_actions=("Ask more",))
    )
    assert not [event for event in suggested if isinstance(event, Answered)]


async def test_a_subagents_completion_marker_is_not_the_comms_answer() -> None:
    mapper = CommsEventMapper("u-1")
    await mapper.map(answer("hello"))
    nested = await mapper.map((("tools:1",), "custom", {"main_response_complete": True}))
    assert not [event for event in nested if isinstance(event, Answered)]
