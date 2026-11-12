"""The comms runner on the real comms graph and a real Postgres checkpointer, with a scripted model."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
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
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.interruption import INTERRUPTION_MARKER
from app.agents.middleware.summarization import WorkspaceArchivingSummarizationMiddleware
from app.agents.tools.core.registry import init_tool_registry
from app.constants.conversation import LOG_SEQ
from app.core.lazy_loader import providers
from app.models.agent_models import AgentRunnableConfig
from app.models.conversation_frame_models import ToolDataEvent
from app.models.conversation_log_models import (
    Batch,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StepClaim,
)
from app.services.conversation.comms_runner import CommsGraphRun, CommsGraphRunner, CommsTurn
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    CancelReason,
    Finished,
    ModelOutput,
    Replied,
    RunEvent,
    RuntimePorts,
    Streamed,
)
from app.services.conversation.step import advance
from tests.e2e._harness.graph_run import RecordingFakeModel, comms_graph, memory_engine_of
from tests.unit.services.conversation.log_helpers import logged, stop, user
from tests.unit.services.conversation.runtime_doubles import Runtime

USER = "u-1"
CONFIRM_SECONDS = 0.05
EntryT = TypeVar("EntryT")
# The text streams, the translator closes the message, the model node returns, the run ends.
ANSWER_SHAPE = [
    "streamed:response",
    "streamed:message_boundary",
    "model_output:answer",
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
async def conversation_id(manager: CheckpointerManager) -> AsyncIterator[str]:
    thread = f"convrt-runner-{uuid4().hex[:10]}"
    yield thread
    await manager.get_checkpointer().adelete_thread(thread)


def _config(conversation_id: str) -> AgentRunnableConfig:
    return cast(
        AgentRunnableConfig,
        {
            "configurable": {
                "thread_id": conversation_id,
                "conversation_id": conversation_id,
                "user_id": USER,
                "agent_name": "comms_agent",
            },
            "metadata": {"user_id": USER},
            "recursion_limit": 25,
            "agent_name": "comms_agent",
        },
    )


def runner(conversation_id: str, history: Sequence[AnyMessage] = ()) -> CommsGraphRunner:
    async def build(claim: StepClaim, batch: Batch) -> CommsTurn:
        return CommsTurn(
            config=_config(conversation_id),
            opening=[
                SystemMessage(content="STATIC PROMPT"),
                mark(SystemMessage(content="DYNAMIC CONTEXT"), DYNAMIC_CONTEXT_MARKER),
                *history,
            ],
            closing=[mark(HumanMessage(content="[clock]"), TIME_CONTEXT_MARKER)],
            state={"intent": "", "integration_usernames": {}},
        )

    return CommsGraphRunner(build, cancel_confirm_seconds=CONFIRM_SECONDS)


def batch(*entries: LoggedEntry) -> Batch:
    return Batch(start=entries[0].seq, end=entries[-1].seq, waking=entries, first_at=entries[0].at)


def claim(conversation_id: str) -> StepClaim:
    return StepClaim(conversation_id=conversation_id, user_id=USER, epoch=1)


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


@pytest.mark.service
async def test_plain_answer_streams_text_then_finishes_replied(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated("hello there")
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            events = await collect(run)
    assert shape(events) == ANSWER_SHAPE
    assert events[-1] == Finished(outcome=Replied(text="hello there"))
    assert run.task.done()
    assert humans(model.prompts[0]) == ["text of u1", "[clock]"]


@pytest.mark.service
async def test_answer_with_a_tool_card_carries_the_card_on_the_reply(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated(recall_call(), "found it")
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )
            events = await collect(run)
    cards = [
        e.payload.tool_data
        for e in events
        if isinstance(e, Streamed) and isinstance(e.payload, ToolDataEvent)
    ]
    assert shape(events)[0:3] == [
        "streamed:tool_data",
        "streamed:message_boundary",
        "model_output:tools",
    ]
    assert shape(events)[-4:] == ANSWER_SHAPE
    assert len(cards) == 1
    assert events[-1] == Finished(outcome=Replied(text="found it", tool_data=tuple(cards)))


@pytest.mark.service
async def test_summarization_is_reported_before_any_visible_output(
    manager: CheckpointerManager, conversation_id: str
) -> None:
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
        async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
            await graph.aupdate_state(_config(conversation_id), {"messages": history})
            with patched_graph(graph):
                run = await runner(conversation_id).start(
                    claim(conversation_id), batch(logged(1, user("u1"))), ()
                )
                events = await collect(run)
    assert shape(events) == ["Summarized", *ANSWER_SHAPE]
    assert events[-1] == Finished(outcome=Replied(text="fresh answer"))
    assert len(model.prompts) == 2


@pytest.mark.service
async def test_cancel_before_output_leaves_only_the_input_and_a_resend_shows_each_message_once(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated("never", "both answered", hold=[0])
    first, second = logged(1, user("u1")), logged(2, user("u2"))
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_stop_after_a_tool_call_records_the_interruption(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated(recall_call(), "unused")
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_restart_leaves_no_interruption_marker(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated(recall_call(), "unused")
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_a_swallowed_cancel_is_sent_again_until_the_run_is_dead(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated("never", hold=[0])
    saver = manager.get_checkpointer()
    real_get = saver.aget_tuple
    checking = asyncio.Event()
    swallowed: list[bool] = []

    async def pool_check_then_get(config: Any) -> Any:
        # psycopg_pool's connection check loop reads a CancelledError as a failed check and retries.
        checking.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            swallowed.append(True)
        return await real_get(config)

    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_absorbed_input_reaches_the_next_model_call(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated(recall_call(), "answered both")
    later = logged(3, user("u3"))
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )

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


@pytest.mark.service
async def test_input_absorbed_past_a_stop_never_reaches_the_model(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    model = gated(recall_call(), "answered one")
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            run = await runner(conversation_id).start(
                claim(conversation_id), batch(logged(1, user("u1"))), ()
            )

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


# --- the step driving this runner: the step scenarios a scripted model can play -------------


async def _quick_tick() -> None:
    await asyncio.sleep(0.01)


def stepping(rt: Runtime, conversation_id: str) -> RuntimePorts:
    """Return the scenario doubles' ports with this runner in place of the scripted one."""
    return replace(rt.ports, runner=runner(conversation_id), tick=_quick_tick)


@pytest.mark.service
async def test_step_one_message_gets_one_reply(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    rt = Runtime()
    model = gated("hello there")
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await kinds(rt, conversation_id) == ["user_message", "reply", "reply_settled"]
    assert [e.text for e in await logged_entries(rt, conversation_id, Reply)] == ["hello there"]
    assert await answered(rt, conversation_id) == [(ReplyOutcome.ANSWERED, ("u1",))]


@pytest.mark.service
async def test_step_second_message_before_commit_restarts_into_one_reply(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    rt = Runtime()
    model = gated("never", "both answered", hold=[0])
    model._during[0] = lambda: accept(rt.ports, conversation_id, USER, user("u2"))
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_step_message_during_a_tool_call_is_absorbed_into_the_same_reply(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    rt = Runtime()
    model = gated(recall_call(), "answered both")
    model._during[0] = lambda: accept(rt.ports, conversation_id, USER, user("u2"))
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_step_stop_while_thinking_records_the_interruption_and_writes_no_reply(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    rt = Runtime()
    model = gated("never", hold=[0])
    model._during[0] = lambda: accept(rt.ports, conversation_id, USER, stop("s"))
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
            left = await thread_of(graph, conversation_id)
    assert await kinds(rt, conversation_id) == ["user_message", "stop_requested"]
    assert (await rt.log.state(conversation_id, USER)).stopped_through == 1
    assert [str(m.content) for m in left].count(INTERRUPTION_MARKER) == 1


@pytest.mark.service
async def test_step_stop_then_a_new_message_shows_the_stop_once_and_answers_the_new_message(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    rt = Runtime()
    model = gated("never", "hello", hold=[0])

    async def stop_then_ask() -> None:
        await accept(rt.ports, conversation_id, USER, stop("s"))
        await accept(rt.ports, conversation_id, USER, user("u3"))

    model._during[0] = stop_then_ask
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
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


@pytest.mark.service
async def test_step_a_model_that_raises_before_commit_leaves_a_failed_bubble(
    manager: CheckpointerManager, conversation_id: str
) -> None:
    rt = Runtime()
    model = gated("never")

    async def model_down() -> None:
        raise RuntimeError("model down")

    model._during[0] = model_down
    async with comms_graph([], model=model, checkpointer_manager=manager) as graph:
        with patched_graph(graph):
            await accept(rt.ports, conversation_id, USER, user("u1"))
            await advance(stepping(rt, conversation_id), conversation_id, USER)
    assert await kinds(rt, conversation_id) == ["user_message", "reply", "reply_settled"]
    assert await answered(rt, conversation_id) == [(ReplyOutcome.FAILED, ("u1",))]
