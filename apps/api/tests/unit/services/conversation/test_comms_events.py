"""Graph stream events to step events: typed payloads from the shared translator, the summary call, the outcome."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.tools.core.registry import init_tool_registry
from app.constants.chat import ConversationSource
from app.constants.comms import REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from app.core.lazy_loader import providers
from app.db.repositories.short_links import short_link_repository
from app.models.conversation_frame_models import (
    MessageBoundaryEvent,
    ResponseEvent,
    ToolDataEvent,
)
from app.models.short_link_models import RecordTarget, ShortLinkTargetType
from app.services.conversation import graph_payloads
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
)
from app.services.links.placeholders import link_placeholder
from app.services.links.urls import build_url
from app.utils import agent_utils
from shared.py.conversation_wire import ToolDataEntry

WEB_RUN: RunnableConfig = {"configurable": {"conversation_source": ConversationSource.WEB.value}}
TELEGRAM_RUN: RunnableConfig = {
    "configurable": {"conversation_source": ConversationSource.TELEGRAM.value}
}


def silent_call(node: str = "agent") -> GraphEvent:
    chunk = AIMessageChunk(content="summary text", id="sum")
    return ((), "messages", (chunk, {"silent": True, "langgraph_node": node}))


def answer(text: str) -> GraphEvent:
    return ((), "updates", {"agent": {"messages": [AIMessage(content=text, id="m1")]}})


async def test_a_hooks_raw_tool_payload_reaches_the_step_as_a_card() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    events = await mapper.map(((), "custom", {"email_fetch_data": [{"id": "e1"}]}))
    (card,) = [
        e.payload.tool_data
        for e in events
        if isinstance(e, Streamed) and isinstance(e.payload, ToolDataEvent)
    ]
    assert (card["tool_name"], card["data"]) == ("email_fetch_data", [{"id": "e1"}])


async def test_the_silent_call_before_the_answer_is_the_summary_and_is_reported_once() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    assert await mapper.map(silent_call()) == [Summarized()]
    assert await mapper.map(silent_call()) == []


async def test_a_silent_call_after_the_answer_is_follow_up_work_not_a_summary() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    await mapper.map(answer("done"))
    assert await mapper.map(silent_call("follow_up_actions")) == []


async def test_an_answer_streams_its_text_then_reports_the_model_output() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
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
    assert (await mapper.finish()) == [Finished(outcome=Replied(text="hello"))]


async def test_a_namespaced_update_is_not_the_comms_model_returning() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    nested: GraphEvent = (
        ("child:1",),
        "updates",
        {"agent": {"messages": [AIMessage(content="x")]}},
    )
    assert ModelOutput(has_tool_calls=False) not in await mapper.map(nested)


async def test_only_the_model_nodes_own_output_streams_as_written_by_the_model() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    by_tool = await mapper.map(((), "custom", {"email_fetch_data": [{"id": "e1"}]}))
    by_model = await mapper.map(answer("hi"))

    assert [e.by_model for e in by_tool if isinstance(e, Streamed)] == [False]
    assert {e.by_model for e in by_model if isinstance(e, Streamed)} == {True}


def updated(message: AIMessage) -> GraphEvent:
    return ((), "updates", {"agent": {"messages": [message]}})


def ending(name: str, text: str = "", **args: object) -> GraphEvent:
    call = {"name": name, "args": args, "id": f"call_{name}"}
    return updated(AIMessage(content=text, tool_calls=[call], id="m1"))


@pytest.mark.parametrize(
    ("event", "outcome"),
    [
        (ending(REACT_TOOL_NAME, emoji="👍", message_id=1), Reacted(emoji="👍")),
        (ending(STAY_SILENT_TOOL_NAME, reason="nothing to add", message_ids=[1]), Silent()),
        (
            ending(REACT_TOOL_NAME, "glad it worked", emoji="👍", message_id=1),
            Replied(text="glad it worked"),
        ),
    ],
)
async def test_a_turn_ending_call_is_the_answer_and_its_outcome(
    event: GraphEvent, outcome: RunOutcome
) -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    assert ModelOutput(has_tool_calls=False) in await mapper.map(event)
    assert (await mapper.finish())[-1] == Finished(outcome=outcome)


@pytest.mark.parametrize(
    ("config", "emoji"),
    [(TELEGRAM_RUN, "🔎"), (TELEGRAM_RUN, "💩"), (WEB_RUN, "🖕")],
    ids=[
        "outside-telegrams-set",
        "offensive-on-telegram",
        "offensive-on-web",
    ],
)
async def test_a_reaction_the_surface_refuses_does_not_end_the_turn(
    config: RunnableConfig, emoji: str
) -> None:
    mapper = CommsEventMapper("u-1", config)
    assert ModelOutput(has_tool_calls=True) in await mapper.map(
        ending(REACT_TOOL_NAME, emoji=emoji, message_id=1)
    )
    finished = (await mapper.finish())[-1]
    assert isinstance(finished, Finished)
    assert not isinstance(finished.outcome, Reacted)


@pytest.mark.parametrize("emoji", ["👀", "❤️"], ids=["in-set", "in-set-with-fe0f"])
async def test_a_reaction_in_telegrams_set_ends_a_telegram_turn(emoji: str) -> None:
    mapper = CommsEventMapper("u-1", TELEGRAM_RUN)
    await mapper.map(ending(REACT_TOOL_NAME, emoji=emoji, message_id=1))
    assert (await mapper.finish())[-1] == Finished(outcome=Reacted(emoji=emoji))


@pytest.mark.parametrize(
    "event",
    [
        ending(REACT_TOOL_NAME, emoji="ok", message_id=1),
        updated(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": REACT_TOOL_NAME, "args": {"emoji": "👍", "message_id": 1}, "id": "a"},
                    {"name": "search_memory", "args": {"query": "q"}, "id": "b"},
                ],
                id="m1",
            )
        ),
    ],
    ids=["refused-emoji", "beside-work"],
)
async def test_a_turn_ending_call_the_graph_does_not_end_on_is_work(event: GraphEvent) -> None:
    # The work call's card resolves its category through the real registry.
    if not providers.is_initialized("tool_registry"):
        init_tool_registry()
    mapper = CommsEventMapper("u-1", WEB_RUN)
    assert ModelOutput(has_tool_calls=True) in await mapper.map(event)
    finished = (await mapper.finish())[-1]
    assert isinstance(finished, Finished)
    assert not isinstance(finished.outcome, Reacted)


async def test_a_reply_written_as_a_tag_is_text() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    await mapper.map(answer("<❤️>"))
    assert (await mapper.finish())[-1] == Finished(outcome=Replied(text="<❤️>"))


async def test_the_answer_is_reported_final_when_the_follow_up_pass_starts() -> None:
    """Regression (live test): the step learned of the answer only after the follow-up model call."""
    mapper = CommsEventMapper("u-1", WEB_RUN)
    await mapper.map(answer("hello"))
    started = await mapper.map(((), "custom", {"main_response_complete": True}))
    suggested = await mapper.map(((), "custom", {"follow_up_actions": ["Ask more"]}))
    assert [event for event in started if isinstance(event, Answered)] == [
        Answered(outcome=Replied(text="hello"))
    ]
    assert (await mapper.finish())[-1] == Finished(
        outcome=Replied(text="hello", follow_up_actions=("Ask more",))
    )
    assert not [event for event in suggested if isinstance(event, Answered)]


async def test_a_subagents_completion_marker_is_not_the_comms_answer() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    await mapper.map(answer("hello"))
    nested = await mapper.map((("tools:1",), "custom", {"main_response_complete": True}))
    assert not [event for event in nested if isinstance(event, Answered)]


def token(text: str) -> GraphEvent:
    chunk = AIMessageChunk(content=text, id="m1")
    return ((), "messages", (chunk, {"langgraph_node": "agent"}))


def card_event() -> GraphEvent:
    return ((), "custom", {"email_fetch_data": [{"id": "e1"}]})


async def shown_card(mapper: CommsEventMapper) -> ToolDataEntry:
    """Stream the hook's card and return it as shown: a card the model did not write."""
    (event,) = await mapper.map(card_event())
    assert isinstance(event, Streamed) and isinstance(event.payload, ToolDataEvent)
    assert event.by_model is False
    assert (event.payload.tool_data["tool_name"], event.payload.tool_data["data"]) == (
        "email_fetch_data",
        [{"id": "e1"}],
    )
    return event.payload.tool_data


async def test_a_reply_carries_the_cards_its_run_showed() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    card = await shown_card(mapper)
    await mapper.map(answer("here"))
    assert (await mapper.finish())[-1] == Finished(outcome=Replied(text="here", tool_data=(card,)))


async def test_a_reaction_beside_cards_is_a_reply_of_the_cards_alone() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    card = await shown_card(mapper)
    await mapper.map(ending(REACT_TOOL_NAME, emoji="👍", message_id=1))
    assert (await mapper.finish())[-1] == Finished(outcome=Replied(text="", tool_data=(card,)))


async def test_a_run_that_never_answered_ends_silent() -> None:
    assert await CommsEventMapper("u-1", WEB_RUN).finish() == [Finished(outcome=Silent())]


async def test_a_model_turn_that_calls_tools_is_not_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_utils, "get_tool_registry", AsyncMock())
    mapper = CommsEventMapper("u-1", WEB_RUN)
    calling = AIMessage(
        content="checking", id="m1", tool_calls=[{"name": "", "args": {}, "id": "c1"}]
    )
    events = await mapper.map(((), "updates", {"agent": {"messages": [calling]}}))
    assert events[-1] == ModelOutput(has_tool_calls=True)
    assert (await mapper.finish())[-1] == Finished(outcome=Silent())


async def test_another_nodes_update_is_not_the_model_returning() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    events = await mapper.map(((), "updates", {"tools": {"messages": []}}))
    assert [event for event in events if isinstance(event, ModelOutput)] == []


async def test_the_answer_is_reported_final_once() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    await mapper.map(answer("hello"))
    marker: GraphEvent = ((), "custom", {"main_response_complete": True})
    first = await mapper.map(marker)
    assert [event for event in first if isinstance(event, Answered)] == [
        Answered(outcome=Replied(text="hello"))
    ]
    assert await mapper.map(marker) == []


async def test_text_still_held_when_the_stream_ends_is_streamed_before_the_outcome() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    streamed = await mapper.map(token("hi <"))
    owed = await mapper.finish()
    texts = [
        event.payload.response
        for event in [*streamed, *owed]
        if isinstance(event, Streamed) and isinstance(event.payload, ResponseEvent)
    ]
    assert "".join(texts) == "hi <"
    assert len(owed) == 2


async def test_a_card_a_running_tool_shows_is_not_the_models_own_output() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    events = await mapper.map((("tools:1",), "custom", {"email_fetch_data": [{"id": "e1"}]}))
    assert [event.by_model for event in events if isinstance(event, Streamed)] == [False]


async def test_a_tool_calls_card_is_named_for_the_runs_own_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    named = AsyncMock(return_value=None)
    monkeypatch.setattr(graph_payloads, "format_tool_call_entry", named)
    calling = AIMessage(content="", id="m1", tool_calls=[{"name": "t", "args": {}, "id": "c1"}])
    await CommsEventMapper("u-1", WEB_RUN).map(((), "updates", {"agent": {"messages": [calling]}}))
    named.assert_awaited_once_with(calling.tool_calls[0], user_id="u-1")


async def test_text_held_when_the_answer_is_final_streams_before_it() -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    # The half-written tag stays held until the answer is final.
    assert await mapper.map(token("hi <")) == [Streamed(payload=ResponseEvent(response="hi "))]
    final = await mapper.map(((), "custom", {"main_response_complete": True}))
    assert final == [
        Streamed(payload=ResponseEvent(response="<")),
        Answered(outcome=Silent()),
    ]


PLACEHOLDER = link_placeholder(RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="art_1"))
LIVE_URL = build_url("ab12cd")


@pytest.fixture
def live_link() -> Iterator[AsyncMock]:
    live = AsyncMock(return_value=SimpleNamespace(slug="ab12cd"))
    with patch.object(short_link_repository, "get_live_for_target", live):
        yield live


def streamed_text(events: list[object]) -> str:
    return "".join(
        event.payload.response
        for event in events
        if isinstance(event, Streamed) and isinstance(event.payload, ResponseEvent)
    )


async def test_a_link_held_when_the_answer_is_final_streams_as_the_users_link(
    live_link: AsyncMock,
) -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    streamed = await mapper.map(token(f"see {PLACEHOLDER}"))
    final = await mapper.map(((), "custom", {"main_response_complete": True}))
    assert streamed_text([*streamed, *final]) == f"see {LIVE_URL}"
    assert live_link.await_args.args[0] == "u-1"


async def test_a_link_held_when_the_stream_ends_streams_as_the_users_link(
    live_link: AsyncMock,
) -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    streamed = await mapper.map(token(f"see {PLACEHOLDER}"))
    owed = await mapper.finish()
    assert streamed_text([*streamed, *owed]) == f"see {LIVE_URL}"
    assert live_link.await_args.args[0] == "u-1"


async def test_the_reply_outcome_carries_its_links_resolved(live_link: AsyncMock) -> None:
    mapper = CommsEventMapper("u-1", WEB_RUN)
    await mapper.map(answer(f"see {PLACEHOLDER}"))
    assert (await mapper.finish())[-1] == Finished(outcome=Replied(text=f"see {LIVE_URL}"))
    assert live_link.await_args.args[0] == "u-1"
