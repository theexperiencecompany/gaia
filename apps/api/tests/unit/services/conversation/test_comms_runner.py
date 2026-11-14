"""The comms runner on the real comms graph and an in-memory checkpointer, with a scripted model."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any, TypeVar, cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr
import pytest

from app.agents.context.slots import DYNAMIC_CONTEXT_MARKER, TIME_CONTEXT_MARKER, mark
from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.interruption import INTERRUPTION_MARKER
from app.agents.core.messages import MessageAttachments, MessageScope
from app.agents.core.nodes.drain_conversation_log import close_feed, open_feed
from app.agents.middleware.summarization import WorkspaceArchivingSummarizationMiddleware
from app.agents.tools.core.registry import init_tool_registry
from app.constants.conversation import LOG_SEQ
from app.constants.graphs import GraphName
from app.core.lazy_loader import providers
from app.models.agent_config import StepTurnRef
from app.models.agent_models import AgentRunnableConfig
from app.models.calendar_models import GoogleCalendarEventDateTime
from app.models.conversation_frame_models import ResponseEvent, ToolDataEvent
from app.models.conversation_log_models import (
    Batch,
    LoggedEntry,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
)
from app.models.message_models import SelectedCalendarEventData
from app.services.conversation.comms_events import CommsEventMapper
from app.services.conversation.comms_runner import (
    CommsGraphRun,
    CommsGraphRunner,
    CommsTurn,
    reframed_messages,
    step_turn_ref,
)
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    CancelReason,
    Finished,
    ModelOutput,
    Replied,
    RunEvent,
    RuntimePorts,
    StepLimitReached,
    Streamed,
)
from app.services.conversation.step import advance
from shared.py.analytics.catalog.agents import AgentRunStarted
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext
from shared.py.conversation_wire import ReplyOutcome, ReplyToMessageData
from tests.e2e._harness.graph_run import RecordingFakeModel, comms_graph, memory_engine_of
from tests.unit.services.conversation.log_helpers import (
    fired,
    logged,
    notice,
    stop,
    user,
    workflow_run,
)
from tests.unit.services.conversation.runtime_doubles import Runtime

USER = "507f1f77bcf86cd799439011"
CONFIRM_SECONDS = 0.05
EntryT = TypeVar("EntryT")
# The text streams, the translator closes the message, the model node returns, the answer is
# final once the follow-up pass starts, its suggestions stream, the run ends.
ANSWER_SHAPE = [
    "streamed:response",
    "streamed:message_boundary",
    "model_output:answer",
    "Answered",
    "streamed:follow_up_actions",
    "finished:Replied",
]


class GatedModel(RecordingFakeModel):
    """Answers call i with replies[i]; a call in hold never returns until cancelled."""

    _replies: list[BaseMessage] = PrivateAttr(default_factory=list)
    _hold: set[int] = PrivateAttr(default_factory=set)
    _entered: dict[int, asyncio.Event] = PrivateAttr(default_factory=dict)
    # Run while call i is in flight, before it answers.
    _during: dict[int, Callable[[], Awaitable[object]]] = PrivateAttr(default_factory=dict)

    def entered(self, call: int) -> asyncio.Event:
        return self._entered.setdefault(call, asyncio.Event())

    async def _agenerate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        call = len(self._prompts)
        self._prompts.append(list(messages))
        self.entered(call).set()
        if call in self._during:
            await self._during[call]()
        if call in self._hold:
            await asyncio.Event().wait()
        return ChatResult(generations=[ChatGeneration(message=self._replies[call])])


def gated(*replies: BaseMessage | str, hold: Sequence[int] = ()) -> GatedModel:
    model = GatedModel(responses=[AIMessage(content="unused")], profile={"max_input_tokens": 10**6})
    model._replies = [AIMessage(content=r) if isinstance(r, str) else r for r in replies]
    model._hold = set(hold)
    return model


def recall_call(call_id: str = "call_recall") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "search_memory", "args": {"query": "q"}, "id": call_id}],
    )


@pytest.fixture(autouse=True)
def _tool_registry() -> None:
    """Register the real tool registry: tool cards resolve their categories through it."""
    if not providers.is_initialized("tool_registry"):
        init_tool_registry()


@pytest.fixture
def conversation_id() -> str:
    return f"convrt-runner-{uuid4().hex[:10]}"


def _config(
    conversation_id: str, recursion_limit: int = 25, step: StepTurnRef | None = None
) -> AgentRunnableConfig:
    step_ref = {} if step is None else {"conversation_step": step}
    return cast(
        AgentRunnableConfig,
        {
            "configurable": {
                "conversation_id": conversation_id,
                "user_id": USER,
                "agent_name": "comms_agent",
                **step_ref,
            },
            "metadata": {"user_id": USER},
            "recursion_limit": recursion_limit,
            "agent_name": "comms_agent",
        },
    )


#: What a scripted turn is attributed to: a user's web message.
TEST_ATTRIBUTION = Attribution(
    actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
)


def runner(
    conversation_id: str,
    history: Sequence[AnyMessage] = (),
    recursion_limit: int = 25,
    step: StepTurnRef | None = None,
) -> CommsGraphRunner:
    async def build(claim: StepClaim, batch: Batch) -> CommsTurn:
        return CommsTurn(
            config=_config(conversation_id, recursion_limit, step),
            opening=[
                SystemMessage(content="STATIC PROMPT"),
                mark(SystemMessage(content="DYNAMIC CONTEXT"), DYNAMIC_CONTEXT_MARKER),
                *history,
            ],
            closing=[mark(HumanMessage(content="[clock]"), TIME_CONTEXT_MARKER)],
            state={"intent": "", "integration_usernames": {}},
            analytics=AnalyticsContext(attribution=TEST_ATTRIBUTION),
            run_started=AgentRunStarted(
                agent="comms", mode="interactive", conversation_id=claim.conversation_id
            ),
        )

    return CommsGraphRunner(build, cancel_confirm_seconds=CONFIRM_SECONDS)


def batch(*entries: LoggedEntry) -> Batch:
    return Batch(start=entries[0].seq, end=entries[-1].seq, waking=entries, first_at=entries[0].at)


def claim(conversation_id: str, user_id: str = USER) -> StepClaim:
    return StepClaim(conversation_id=conversation_id, user_id=user_id, epoch=1)


async def _ignore(_event: RunEvent) -> None:
    return None


async def collect(
    run: CommsGraphRun, on_event: Callable[[RunEvent], Awaitable[None]] = _ignore
) -> list[RunEvent]:
    events: list[RunEvent] = []
    async for event in run.events():
        events.append(event)
        await on_event(event)
    return events


def shape(events: Sequence[RunEvent]) -> list[str]:
    def one(event: RunEvent) -> str:
        match event:
            case Streamed(payload=payload):
                return f"streamed:{payload.type.value}"
            case ModelOutput(has_tool_calls=tools):
                return f"model_output:{'tools' if tools else 'answer'}"
            case Finished(outcome=outcome):
                return f"finished:{type(outcome).__name__}"
        return type(event).__name__

    return [one(event) for event in events]


def humans(prompt: Sequence[BaseMessage]) -> list[str]:
    return [str(m.content) for m in prompt if isinstance(m, HumanMessage)]


async def thread_of(graph: CompiledAgentGraph, conversation_id: str) -> list[AnyMessage]:
    snapshot = await graph.aget_state({"configurable": {"thread_id": conversation_id}})
    return list((snapshot.values or {}).get("messages", []))


def patched_graph(graph: CompiledAgentGraph) -> Any:
    return patch.object(GraphManager, "get_graph", AsyncMock(return_value=graph))


async def test_plain_answer_streams_text_then_finishes_replied(conversation_id: str) -> None:
    model = gated("hello there")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            events = await collect(run)
    assert shape(events) == ANSWER_SHAPE
    assert events[-1] == Finished(outcome=Replied(text="hello there"))
    assert run.task.done()
    assert humans(model.prompts[0]) == ["text of u1", "[clock]"]


async def test_a_run_that_fails_before_it_streams_raises_through_its_events(
    conversation_id: str,
) -> None:
    """Regression: a failure outside the stream (here the run's analytics lifecycle) left events() waiting forever."""
    model = gated("never")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id, user_id="not-an-object-id"), batch(logged(1, user("u1"))), ()
            )
            async with asyncio.timeout(10):
                with pytest.raises(ValueError, match="ObjectId"):
                    await collect(run)
    assert run.task.done()
    assert model.prompts == []


async def test_answer_with_a_tool_card_carries_the_card_on_the_reply(conversation_id: str) -> None:
    model = gated(recall_call(), "found it")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            events = await collect(run)
    streamed_cards = [
        (e.payload.tool_data, e.by_model)
        for e in events
        if isinstance(e, Streamed) and isinstance(e.payload, ToolDataEvent)
    ]
    cards = [card for card, _by_model in streamed_cards]
    assert shape(events)[0:3] == [
        "streamed:tool_data",
        "streamed:message_boundary",
        "model_output:tools",
    ]
    assert shape(events)[-len(ANSWER_SHAPE) :] == ANSWER_SHAPE
    # The model's call card, then the card the running tool shows.
    assert [(card["tool_name"], by_model) for card, by_model in streamed_cards] == [
        ("tool_calls_data", True),
        ("memory_data", False),
    ]
    assert events[-1] == Finished(outcome=Replied(text="found it", tool_data=tuple(cards)))


async def test_summarization_is_reported_before_any_visible_output(conversation_id: str) -> None:
    history = [
        message
        for turn in range(12)
        for message in (
            HumanMessage(content=f"old ask {turn} " * 400, id=f"old-ask-{turn}"),
            AIMessage(content=f"old answer {turn} " * 400, id=f"old-answer-{turn}"),
        )
    ]
    model = gated("SUMMARY OF THE OLD TURNS", "fresh answer")
    # Only the decision to summarize is forced; the summary call itself is the real middleware's.
    trigger_once = MagicMock(side_effect=[True, *[False] * 5])
    with patch.object(
        WorkspaceArchivingSummarizationMiddleware, "_should_trigger_summarization", trigger_once
    ):
        async with comms_graph([], model=model) as graph:
            await graph.aupdate_state(
                {"configurable": {"thread_id": conversation_id}}, {"messages": history}
            )
            with patched_graph(graph):
                run = await runner(conversation_id).start(
                    claim(conversation_id), batch(logged(1, user("u1"))), ()
                )
                events = await collect(run)
    assert shape(events) == ["Summarized", *ANSWER_SHAPE]
    assert events[-1] == Finished(outcome=Replied(text="fresh answer"))
    assert len(model.prompts) == 2


async def test_cancel_before_output_leaves_only_the_input_and_a_resend_shows_each_message_once(
    conversation_id: str,
) -> None:
    model = gated("never", "both answered", hold=[0])
    first, second = logged(1, user("u1")), logged(2, user("u2"))
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            comms = runner(conversation_id)
            run = await comms.start(claim(conversation_id), batch(first), ())
            consumer = asyncio.create_task(collect(run))
            await model.entered(0).wait()
            await run.cancel(CancelReason.RESTART)
            assert run.task.done()
            consumer.cancel()
            left = await thread_of(graph, conversation_id)
            assert not any(isinstance(m, AIMessage) for m in left)
            assert humans(left) == ["text of u1", "[clock]"]

            rerun = await comms.start(claim(conversation_id), batch(first, second), ())
            events = await collect(rerun)
    assert events[-1] == Finished(outcome=Replied(text="both answered"))
    shown = humans(model.prompts[1])
    assert shown.count("text of u1") == 1
    assert shown.count("text of u2") == 1
    assert INTERRUPTION_MARKER not in shown


async def test_stop_after_a_tool_call_records_the_interruption(conversation_id: str) -> None:
    model = gated(recall_call(), "unused")
    async with comms_graph([], model=model) as graph:
        memory_engine_of(graph).recall = AsyncMock(
            side_effect=lambda *a, **k: asyncio.Event().wait()
        )
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            seen: list[RunEvent] = []
            async for event in run.events():
                seen.append(event)
                if isinstance(event, ModelOutput):
                    break
            await run.cancel(CancelReason.STOP)
            left = await thread_of(graph, conversation_id)
    assert shape(seen)[-1] == "model_output:tools"
    assert run.task.done()
    # The tool call reaches the checkpoint only if the graph committed it before the cancel; either way none dangles.
    calls = {c["id"] for m in left if isinstance(m, AIMessage) for c in m.tool_calls}
    answered_calls = {m.tool_call_id for m in left if isinstance(m, ToolMessage)}
    assert calls == answered_calls
    assert str(left[-1].content) == INTERRUPTION_MARKER


async def test_restart_leaves_no_interruption_marker(conversation_id: str) -> None:
    model = gated(recall_call(), "unused")
    async with comms_graph([], model=model) as graph:
        memory_engine_of(graph).recall = AsyncMock(
            side_effect=lambda *a, **k: asyncio.Event().wait()
        )
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            async for event in run.events():
                if isinstance(event, ModelOutput):
                    break
            await run.cancel(CancelReason.RESTART)
            left = await thread_of(graph, conversation_id)
    assert INTERRUPTION_MARKER not in [str(m.content) for m in left]


async def test_a_swallowed_cancel_is_sent_again_until_the_run_is_dead(conversation_id: str) -> None:
    model = gated("never", hold=[0])
    checking = asyncio.Event()
    swallowed: list[bool] = []

    async with comms_graph([], model=model) as graph:
        saver = graph.checkpointer
        real_get = saver.aget_tuple

        async def pool_check_then_get(config: Any) -> Any:
            # psycopg_pool's connection check loop reads a CancelledError as a failed check and retries.
            checking.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                swallowed.append(True)
            return await real_get(config)

        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            # Armed after start's own state read; the run task has not stepped yet.
            with patch.object(saver, "aget_tuple", pool_check_then_get):
                await checking.wait()
                await run.cancel(CancelReason.RESTART)
    assert swallowed == [True]
    # The first cancel was swallowed: the run carried on into the model call.
    assert model.entered(0).is_set()
    assert run.task.done()


async def test_absorbed_input_reaches_the_next_model_call(conversation_id: str) -> None:
    model = gated(recall_call(), "answered both")
    later = logged(3, user("u3"))
    first = batch(logged(1, user("u1")))
    step = step_turn_ref(claim(conversation_id), first)
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id, step=step).start(claim(conversation_id), first, ())

            async def absorb_on_tool_call(event: RunEvent) -> None:
                if event == ModelOutput(has_tool_calls=True):
                    await run.absorb([later])

            events = await collect(run, absorb_on_tool_call)
            left = await thread_of(graph, conversation_id)
    assert isinstance(events[-1], Finished)
    assert events[-1].outcome == Replied(text="answered both", tool_data=ANY)
    assert "text of u3" not in humans(model.prompts[0])
    assert humans(model.prompts[1]).count("text of u3") == 1
    joined = [m for m in left if m.additional_kwargs.get(LOG_SEQ) == 3]
    assert [m.id for m in joined] == ["log:u3"]
    # Work the run dispatches from now on answers the joiner too.
    assert step == {"epoch": 1, "batch_start": 1, "cause_through": 3, "answers": ["u1", "u3"]}


async def test_input_absorbed_past_a_stop_never_reaches_the_model(conversation_id: str) -> None:
    model = gated(recall_call(), "answered one")
    first = batch(logged(1, user("u1")))
    step = step_turn_ref(claim(conversation_id), first)
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id, step=step).start(claim(conversation_id), first, ())

            async def absorb_on_tool_call(event: RunEvent) -> None:
                if event == ModelOutput(has_tool_calls=True):
                    await run.absorb(
                        [logged(2, user("u2")), logged(3, stop("s3", 2)), logged(4, user("u4"))]
                    )
                    await run.absorb([logged(5, user("u5"))])

            await collect(run, absorb_on_tool_call)
    shown = humans(model.prompts[1])
    assert shown.count("text of u2") == 1
    assert "text of u4" not in shown
    assert "text of u5" not in shown
    assert step == {"epoch": 1, "batch_start": 1, "cause_through": 2, "answers": ["u1", "u2"]}


async def test_a_stop_absorbed_alone_joins_nothing_to_the_step(conversation_id: str) -> None:
    model = gated(recall_call(), "answered one")
    first = batch(logged(1, user("u1")))
    step = step_turn_ref(claim(conversation_id), first)
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id, step=step).start(claim(conversation_id), first, ())

            async def absorb_on_tool_call(event: RunEvent) -> None:
                if event == ModelOutput(has_tool_calls=True):
                    await run.absorb([logged(2, stop("s2", 1)), logged(3, user("u3"))])

            await collect(run, absorb_on_tool_call)
    assert "text of u3" not in humans(model.prompts[1])
    assert step == {"epoch": 1, "batch_start": 1, "cause_through": 1, "answers": ["u1"]}


async def test_frames_owed_at_the_end_of_the_stream_reach_the_step_before_finished(
    conversation_id: str,
) -> None:
    owed = Streamed(payload=ResponseEvent(response="owed tail"))
    real_finish = CommsEventMapper.finish

    def finish_owing(mapper: CommsEventMapper) -> list[RunEvent]:
        return [owed, *real_finish(mapper)]

    async with comms_graph([], model=gated("hello there")) as graph:
        with patched_graph(graph), patch.object(CommsEventMapper, "finish", finish_owing):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            events = await collect(run)
    assert events[-2:] == [owed, Finished(outcome=Replied(text="hello there"))]


def test_a_step_ref_answers_only_what_the_user_or_a_workflow_sent() -> None:
    waking = batch(logged(4, user("u4")), logged(5, notice("n5")), logged(6, fired("f6")))
    ref = step_turn_ref(StepClaim(conversation_id="c1", user_id=USER, epoch=7), waking)
    assert ref == {"epoch": 7, "batch_start": 4, "cause_through": 6, "answers": ["u4", "f6"]}


CALENDAR_EVENT = SelectedCalendarEventData(
    id="ev1",
    summary="Standup",
    description="daily",
    start=GoogleCalendarEventDateTime(dateTime="2026-11-14T09:00:00Z"),
    end=GoogleCalendarEventDateTime(dateTime="2026-11-14T09:15:00Z"),
)
QUOTED = ReplyToMessageData(id="m0", content="earlier", role="assistant")


@pytest.mark.parametrize(
    ("carried", "attachments"),
    [
        (
            {"file_ids": ("f1", "f2")},
            MessageAttachments(currently_uploaded_file_ids=["f1", "f2"]),
        ),
        (
            {"selected_tool": "gmail_send", "tool_category": "gmail"},
            MessageAttachments(
                selected_tool="gmail_send", tool_category="gmail", currently_uploaded_file_ids=[]
            ),
        ),
        (
            {"selected_workflow": workflow_run().workflow},
            MessageAttachments(
                selected_workflow=workflow_run().workflow, currently_uploaded_file_ids=[]
            ),
        ),
        (
            {"selected_calendar_event": CALENDAR_EVENT},
            MessageAttachments(
                selected_calendar_event=CALENDAR_EVENT, currently_uploaded_file_ids=[]
            ),
        ),
        (
            {"reply_to_message": QUOTED},
            MessageAttachments(reply_to_message=QUOTED, currently_uploaded_file_ids=[]),
        ),
    ],
    ids=["files", "tool", "workflow", "calendar-event", "reply"],
)
async def test_a_message_carrying_more_than_text_is_reframed_with_what_it_carries(
    carried: dict[str, object], attachments: MessageAttachments
) -> None:
    message = UserMessage.model_validate({**user("u1").model_dump(), **carried})
    plain = user("u2")
    framing = AsyncMock(return_value="reframed")
    with patch("app.services.conversation.comms_runner.human_content", framing):
        said = await reframed_messages(claim("c1"), [logged(1, message), logged(2, plain)])
    assert said == {"u1": "reframed"}
    framing.assert_awaited_once_with(
        MessageScope(user_id=USER, conversation_id="c1"), attachments, "text of u1"
    )


async def test_a_workflow_fire_reads_as_its_run_request_with_its_trigger() -> None:
    entry = fired("f1")
    framing = AsyncMock(return_value="run it")
    with patch("app.services.conversation.comms_runner.human_content", framing):
        said = await reframed_messages(claim("c1"), [logged(1, entry)])
    assert said == {"f1": "run it"}
    framing.assert_awaited_once_with(
        MessageScope(user_id=USER, conversation_id="c1"),
        MessageAttachments(
            selected_workflow=entry.run.workflow,
            trigger_context=entry.run.trigger.model_dump(),
        ),
        "Execute workflow: Morning brief",
    )


# --- the step driving this runner: the step scenarios a scripted model can play -------------


async def _quick_tick() -> None:
    await asyncio.sleep(0.01)


def stepping(rt: Runtime, conversation_id: str) -> RuntimePorts:
    """Return the scenario doubles' ports with this runner in place of the scripted one."""
    return replace(rt.ports, runner=runner(conversation_id), tick=_quick_tick)


async def test_step_one_message_gets_one_reply(conversation_id: str) -> None:
    rt = Runtime()
    model = gated("hello there")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await kinds(rt, conversation_id) == ["user_message", "reply", "reply_settled"]
    assert [e.text for e in await logged_entries(rt, conversation_id, Reply)] == ["hello there"]
    assert await answered(rt, conversation_id) == [(ReplyOutcome.ANSWERED, ("u1",))]


async def test_step_second_message_before_commit_restarts_into_one_reply(
    conversation_id: str,
) -> None:
    rt = Runtime()
    model = gated("never", "both answered", hold=[0])
    model._during[0] = lambda: accept(rt.ports, conversation_id, USER, user("u2"))
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await kinds(rt, conversation_id) == [
        "user_message",
        "user_message",
        "reply",
        "reply_settled",
    ]
    assert await answered(rt, conversation_id) == [(ReplyOutcome.ANSWERED, ("u1", "u2"))]
    shown = humans(model.prompts[1])
    assert (shown.count("text of u1"), shown.count("text of u2")) == (1, 1)
    assert INTERRUPTION_MARKER not in shown


async def test_step_message_during_a_tool_call_is_absorbed_into_the_same_reply(
    conversation_id: str,
) -> None:
    rt = Runtime()
    model = gated(recall_call(), "answered both")
    model._during[0] = lambda: accept(rt.ports, conversation_id, USER, user("u2"))
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await answered(rt, conversation_id) == [(ReplyOutcome.ANSWERED, ("u1", "u2"))]
    assert "text of u2" not in humans(model.prompts[0])
    assert humans(model.prompts[1]).count("text of u2") == 1


async def logged_entries(rt: Runtime, conversation_id: str, kind: type[EntryT]) -> list[EntryT]:
    return [
        item.entry
        for item in await rt.log.read_after(conversation_id, USER, 0)
        if isinstance(item.entry, kind)
    ]


async def kinds(rt: Runtime, conversation_id: str) -> list[str]:
    return [item.entry.kind.value for item in await rt.log.read_after(conversation_id, USER, 0)]


async def answered(rt: Runtime, conversation_id: str) -> list[tuple[ReplyOutcome, tuple[str, ...]]]:
    return [
        (item.outcome, item.answers)
        for item in await logged_entries(rt, conversation_id, ReplySettled)
    ]


async def test_step_stop_while_thinking_records_the_interruption_and_writes_no_reply(
    conversation_id: str,
) -> None:
    rt = Runtime()
    model = gated("never", hold=[0])
    model._during[0] = lambda: accept(rt.ports, conversation_id, USER, stop("s"))
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
            left = await thread_of(graph, conversation_id)
    assert await kinds(rt, conversation_id) == ["user_message", "stop_requested"]
    assert (await rt.log.state(conversation_id, USER)).stopped_through == 1
    assert [str(m.content) for m in left].count(INTERRUPTION_MARKER) == 1


async def test_step_stop_then_a_new_message_shows_the_stop_once_and_answers_the_new_message(
    conversation_id: str,
) -> None:
    rt = Runtime()
    model = gated("never", "hello", hold=[0])

    async def stop_then_ask() -> None:
        await accept(rt.ports, conversation_id, USER, stop("s"))
        await accept(rt.ports, conversation_id, USER, user("u3"))

    model._during[0] = stop_then_ask
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await answered(rt, conversation_id) == [(ReplyOutcome.ANSWERED, ("u3",))]
    assert [e.text for e in await logged_entries(rt, conversation_id, Reply)] == ["hello"]
    shown = humans(model.prompts[1])
    assert (
        shown.count("text of u1"),
        shown.count(INTERRUPTION_MARKER),
        shown.count("text of u3"),
    ) == (1, 1, 1)


async def test_step_a_model_that_raises_before_commit_leaves_a_failed_bubble(
    conversation_id: str,
) -> None:
    rt = Runtime()
    model = gated("never")

    async def model_down() -> None:
        raise RuntimeError("model down")

    model._during[0] = model_down
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await kinds(rt, conversation_id) == ["user_message", "reply", "reply_settled"]
    assert await answered(rt, conversation_id) == [(ReplyOutcome.FAILED, ("u1",))]


async def test_a_run_out_of_steps_ends_with_the_step_limit(conversation_id: str) -> None:
    model = gated("hello there")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id, recursion_limit=1).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            with pytest.raises(StepLimitReached, match="Recursion limit of 1"):
                await collect(run)
    assert run.task.done()


async def test_the_turn_context_is_keyed_on_the_batchs_oldest_input(conversation_id: str) -> None:
    async with comms_graph([], model=gated("hello there")) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1")), logged(2, user("u2"))), ()
            )
            await collect(run)
            left = await thread_of(graph, conversation_id)
    context_ids = [m.id for m in left if not m.additional_kwargs.get(LOG_SEQ) and m.id]
    assert context_ids[:3] == ["log:u1:turn:0", "log:u1:turn:1", "log:u1:turn:2"]


async def test_a_run_reads_the_comms_graph_and_builds_its_turn_from_the_batch(
    conversation_id: str,
) -> None:
    built: list[tuple[StepClaim, Batch]] = []
    inner = runner(conversation_id)

    async def recording_build(step_claim: StepClaim, step_batch: Batch) -> CommsTurn:
        built.append((step_claim, step_batch))
        return await inner._build_turn(step_claim, step_batch)

    first = batch(logged(1, user("u1")))
    async with comms_graph([], model=gated("hello there")) as graph:
        get_graph = AsyncMock(return_value=graph)
        mapper = MagicMock(wraps=CommsEventMapper)
        with (
            patch.object(GraphManager, "get_graph", get_graph),
            patch("app.services.conversation.comms_runner.CommsEventMapper", mapper),
        ):
            run = await CommsGraphRunner(recording_build, CONFIRM_SECONDS).start(
                claim(conversation_id), first, ()
            )
            await collect(run)
    get_graph.assert_awaited_once_with(GraphName.COMMS)
    assert built == [(claim(conversation_id), first)]
    mapper.assert_called_once_with(USER)


async def test_a_first_run_on_a_fresh_thread_says_the_stop_in_its_context(
    conversation_id: str,
) -> None:
    model = gated("after the stop")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(2, user("u2"))), [logged(1, stop("s1"))]
            )
            events = await collect(run)
    assert events[-1] == Finished(outcome=Replied(text="after the stop"))


async def test_every_absorb_reaches_the_next_model_call_until_a_stop(
    conversation_id: str,
) -> None:
    model = gated(recall_call(), "answered all")
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )

            async def absorb_twice(event: RunEvent) -> None:
                if event == ModelOutput(has_tool_calls=True):
                    await run.absorb([logged(2, user("u2"))])
                    await run.absorb([logged(3, user("u3"))])

            await collect(run, absorb_twice)
    shown = humans(model.prompts[1])
    assert (shown.count("text of u2"), shown.count("text of u3")) == (1, 1)


async def test_nothing_joins_a_run_once_it_is_being_cancelled(conversation_id: str) -> None:
    model = gated("never", hold=[0])
    first = batch(logged(1, user("u1")))
    step = step_turn_ref(claim(conversation_id), first)
    async with comms_graph([], model=model) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id, step=step).start(claim(conversation_id), first, ())
            await model.entered(0).wait()
            cancelling = asyncio.create_task(run.cancel(CancelReason.RESTART))
            await asyncio.sleep(0)
            await run.absorb([logged(2, user("u2"))])
            await cancelling
    assert step == {"epoch": 1, "batch_start": 1, "cause_through": 1, "answers": ["u1"]}


async def test_a_finished_run_closes_the_feed_it_opened(conversation_id: str) -> None:
    opened = MagicMock(wraps=open_feed)
    closed = MagicMock(wraps=close_feed)
    async with comms_graph([], model=gated("hello there")) as graph:
        with (
            patched_graph(graph),
            patch("app.services.conversation.comms_runner.open_feed", opened),
            patch("app.services.conversation.comms_runner.close_feed", closed),
        ):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            await collect(run)
    (run_id,) = opened.call_args.args
    closed.assert_called_once_with(run_id)
