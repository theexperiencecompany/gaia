"""The conversation runtime wired end to end on real Mongo, Redis and Postgres, with a scripted model.

Production ports throughout (the Mongo log, the comms graph runner, the Redis frames stream,
the effects that kick steps), except the turn builder, which skips the user's memory and
context slots, and the instant reaction, which is never asked for.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, TypeVar, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from redis.asyncio import Redis

from app.agents.context.slots import TIME_CONTEXT_MARKER, PromptSlot, mark, slot_of
from app.agents.core.background import executor_runner, todo_run, todo_run_delivery
from app.agents.core.background.executor_queue import (
    PreparedQueuedTask,
    build_lock_value,
    try_acquire_lock,
)
from app.agents.core.background.executor_runner import deliver_to_executor
from app.agents.core.background.session import ExecutorRun
from app.agents.core.background.todo_run import TodoRunRequest, run_todo_on_executor
from app.agents.core.background.todo_run_delivery import report_form_of
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import GraphManager
from app.agents.tools.core.registry import init_tool_registry
from app.agents.tools.run_record import append_call
from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.chat import ConversationSource
from app.constants.graphs import GraphName
from app.constants.todos import TodoWakeKind
from app.core.lazy_loader import providers
from app.db.redis import redis_cache
from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.agent_config import AgentConfigurable, StepTurnRef
from app.models.agent_models import AgentRunnableConfig
from app.models.conversation_frame_models import EntryFrame, ToolDataEvent, WorkDeltaFrame
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Batch,
    DisplayState,
    Entry,
    IntegrationConnected,
    LoggedEntry,
    Notice,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StepClaim,
    StopRequested,
    TodoRun,
    TodoWoke,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_send_models import SendMessageRequest
from app.models.message_models import ReplyToMessageData
from app.models.playbook_models import PlaybookDocument, ToolStep
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.todo_wake_models import TodoRunWake
from app.models.tool_data_models import ToolDataEntry
from app.models.user_models import AuthenticatedUser
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
from app.schemas.browser import NewHandoff
from app.services import analytics_service
from app.services.browser.handoff import create_pending_handoff
from app.services.browser.handoff_buttons import decide_handoff_by_button
from app.services.conversation.bot_followers import list_active_bot_conversations
from app.services.conversation.comms_runner import (
    CommsGraphRunner,
    CommsTurn,
    CommsTurnBuilder,
)
from app.services.conversation.comms_turn import build_comms_turn, step_turn_ref
from app.services.conversation.composition import RuntimeEffects, running_steps
from app.services.conversation.event_stream import (
    RedisStreamFrames,
    StreamedFrame,
    follow,
    read_frames,
    replay_from_log,
)
from app.services.conversation.integration_log import (
    continue_after_connect,
    record_integration_needed,
)
from app.services.conversation.log import Accepted, accept
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.send import send_message, submit_message
from app.services.conversation.step import advance
from app.services.conversation.sweeper import sweep_conversations
from app.services.conversation.work_deltas import WorkDeltas
from app.services.conversation.work_log import (
    WorkReport,
    record_approval_decided,
    record_approval_requested,
    record_user_stop,
    record_work_finished,
    record_work_started,
    running_step_task,
)
from app.services.delivery.chat_channel import ChatChannel
from app.services.workflow.conversation_service import log_playbook_run
from app.services.workflow.execution_service import WorkflowFireOverlapped, WorkflowTurnFailed
from app.workers.tasks import workflow_tasks
from app.workers.tasks.workflow_tasks import (
    _Fire,
    _reserve_conversation,
    _run_and_record_success,
    execute_workflow_as_chat,
)
from shared.py.analytics.catalog.agents import AgentRunStarted
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.workflows import WorkflowExecuted
from shared.py.analytics.context import (
    analytics_context,
    current_analytics_context,
    worker_context,
)
from shared.py.wide_events import _spawned_tasks
from tests.e2e._harness.graph_run import comms_graph
from tests.integration.real.test_comms_runner_real import (
    TEST_ATTRIBUTION,
    GatedModel,
    gated,
    humans,
    patched_graph,
)
from tests.unit.services.conversation.runtime_doubles import ScriptedApprovals

EntryT = TypeVar("EntryT")
_SETTLE_SECONDS = 30.0
_CONFIRM_SECONDS = 0.05


class _Effects(RuntimeEffects):
    """The production effects, recording cancels; kicks can be held so a test lines inputs up first."""

    def __init__(
        self,
        log: MongoConversationLog,
        frames: RedisStreamFrames,
        ports: Callable[[], RuntimePorts],
    ) -> None:
        super().__init__(log, frames, ports)
        self.cancelled: list[tuple[str, ...]] = []
        self.hold_kicks = False

    async def kick(self, conversation_id: str, user_id: str) -> None:
        if not self.hold_kicks:
            await super().kick(conversation_id, user_id)

    async def cancel_work(
        self, conversation_id: str, user_id: str, task_ids: tuple[str, ...]
    ) -> None:
        self.cancelled.append(task_ids)
        await super().cancel_work(conversation_id, user_id, task_ids)

    async def start_ack(self, conversation_id: str, user_id: str, message_id: str) -> None:
        return None


@dataclass
class Rig:
    """One step-run conversation on the production ports."""

    conversation_id: str
    user_id: str
    ports: RuntimePorts
    effects: _Effects
    turns: list[tuple[StepClaim, Batch]] = field(default_factory=list)

    async def send(self, message_id: str, text: str) -> int:
        sent = await send_message(
            self.conversation_id,
            AuthenticatedUser(user_id=self.user_id),
            SendMessageRequest(message_id=message_id, text=text),
            ConversationSource.WEB,
        )
        return sent.accepted.seq

    async def settle(self) -> None:
        """Wait until no step runs here; a step's appends may kick another, so wait again."""
        async with asyncio.timeout(_SETTLE_SECONDS):
            while steps := running_steps():
                await asyncio.wait(steps)

    async def entries(self) -> list[LoggedEntry]:
        return list(await self.ports.log.read_after(self.conversation_id, self.user_id, 0))

    async def of(self, kind: type[EntryT]) -> list[EntryT]:
        return [e.entry for e in await self.entries() if isinstance(e.entry, kind)]

    async def answered(self) -> list[tuple[ReplyOutcome, tuple[str, ...]]]:
        return [(s.outcome, s.answers) for s in await self.of(ReplySettled)]

    def step(self) -> StepTurnRef:
        """Return what the attempt running now hands the work it dispatches."""
        claim, batch = self.turns[-1]
        return step_turn_ref(claim, batch)

    async def start_work(self, task_id: str) -> bool:
        """Do what call_executor does inside the attempt running now."""
        return await record_work_started(self.step(), self.conversation_id, self.user_id, task_id)


class RigFactory(Protocol):
    """Builds a conversation answered by model, holding history as the entries migration leaves it."""

    def __call__(
        self,
        model: GatedModel,
        history: Sequence[dict[str, str]] = (),
        build_turn: CommsTurnBuilder | None = None,
    ) -> Awaitable[Rig]: ...


def _run_config(conversation_id: str, user_id: str) -> AgentRunnableConfig:
    return cast(
        AgentRunnableConfig,
        {
            "configurable": {
                "thread_id": conversation_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "agent_name": "comms_agent",
            },
            "metadata": {"user_id": user_id},
            "recursion_limit": 25,
            "agent_name": "comms_agent",
        },
    )


def _turn_builder(
    turns: list[tuple[StepClaim, Batch]], user_id: str
) -> Callable[[StepClaim, Batch], Awaitable[CommsTurn]]:
    async def build(claim: StepClaim, batch: Batch) -> CommsTurn:
        turns.append((claim, batch))
        config = _run_config(claim.conversation_id, user_id)
        config["configurable"]["conversation_step"] = step_turn_ref(claim, batch)
        return CommsTurn(
            config=config,
            opening=[SystemMessage(content="STATIC PROMPT")],
            closing=[mark(HumanMessage(content="[clock]"), TIME_CONTEXT_MARKER)],
            state={"intent": "", "integration_usernames": {}},
            attribution=TEST_ATTRIBUTION,
            run_started=AgentRunStarted(
                agent="comms", mode="interactive", conversation_id=claim.conversation_id
            ),
        )

    return build


async def _quick_tick() -> None:
    await asyncio.sleep(0.01)


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
async def rig_for(
    manager: CheckpointerManager,
    make_conversation: Callable[..., Awaitable[str]],
    user_id: str,
    real_redis: Redis,
) -> AsyncIterator[RigFactory]:
    """Build a step-run conversation whose comms graph answers with model."""
    async with AsyncExitStack() as stack:

        async def build(
            model: GatedModel,
            history: Sequence[dict[str, str]] = (),
            build_turn: CommsTurnBuilder | None = None,
        ) -> Rig:
            conversation_id = f"convrt-{uuid4().hex[:10]}"
            await make_conversation(user_id, conversation_id, messages=list(history))
            turns: list[tuple[StepClaim, Batch]] = []
            log = MongoConversationLog(conversation_log_repository, _now)
            frames = RedisStreamFrames()
            holder: list[RuntimePorts] = []
            effects = _Effects(log, frames, lambda: holder[0])
            ports = RuntimePorts(
                log=log,
                runner=CommsGraphRunner(
                    build_turn or _turn_builder(turns, user_id),
                    cancel_confirm_seconds=_CONFIRM_SECONDS,
                ),
                frames=frames,
                effects=effects,
                approvals=ScriptedApprovals(),
                clock=_now,
                tick=_quick_tick,
            )
            holder.append(ports)
            install_runtime_ports(ports)
            graph = await stack.enter_async_context(
                comms_graph([], model=model, checkpointer_manager=manager)
            )
            stack.enter_context(patched_graph(graph))
            # The harness swaps in a fake Redis; this suite runs on the real one.
            stack.enter_context(patch.object(redis_cache, "redis", real_redis))
            return Rig(conversation_id, user_id, ports, effects, turns)

        yield build
        for task in running_steps():
            task.cancel()


def _during(model: GatedModel, call: int, action: Callable[[], Awaitable[object]]) -> None:
    model._during[call] = action


@pytest.mark.service
async def test_a_message_sent_before_the_reply_commits_gets_one_reply_using_both(
    rig_for: RigFactory,
) -> None:
    model = gated("never shown", "booked at $900", hold=[0])
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.send("m2", "actually make it $900"))
    await rig.send("m1", "book it for $600")
    await rig.settle()
    assert [reply.text for reply in await rig.of(Reply)] == ["booked at $900"]
    assert await rig.answered() == [(ReplyOutcome.ANSWERED, ("m1", "m2"))]
    assert humans(model.prompts[1]).count("actually make it $900") == 1


@pytest.mark.service
async def test_a_side_question_during_work_is_answered_while_the_work_runs(
    rig_for: RigFactory,
) -> None:
    model = gated("on it", "it is noon")
    rig = await rig_for(model)
    started: list[bool] = []

    async def dispatch() -> None:
        started.append(await rig.start_work("t1"))

    _during(model, 0, dispatch)
    await rig.send("m1", "find me flights")
    await rig.settle()
    await rig.send("m2", "what time is it?")
    await rig.settle()
    state = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    assert started == [True]
    assert [work.task_id for work in state.work] == ["t1"]
    assert [reply.text for reply in await rig.of(Reply)] == ["on it", "it is noon"]
    assert await rig.answered() == [
        (ReplyOutcome.ANSWERED, ("m1",)),
        (ReplyOutcome.ANSWERED, ("m2",)),
    ]


@pytest.mark.service
async def test_stop_mid_work_cancels_that_work_and_wakes_nothing(
    rig_for: RigFactory,
) -> None:
    model = gated("on it")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "find me flights")
    await rig.settle()
    await record_user_stop(rig.conversation_id, rig.user_id, "s1")
    await rig.settle()
    state = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    assert rig.effects.cancelled == [("t1",)]
    assert state.work == ()
    assert len(await rig.of(StopRequested)) == 1
    assert len(await rig.of(Reply)) == 1


@pytest.mark.service
async def test_work_started_after_a_stop_in_its_own_attempt_is_refused(
    rig_for: RigFactory,
) -> None:
    model = gated("stopped")
    rig = await rig_for(model)
    started: list[bool] = []

    async def stop_then_dispatch() -> None:
        await record_user_stop(rig.conversation_id, rig.user_id, "s1")
        started.append(await rig.start_work("t2"))

    _during(model, 0, stop_then_dispatch)
    await rig.send("m1", "send the report")
    await rig.settle()
    state = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    assert started == [False]
    assert state.work == ()


@pytest.mark.service
async def test_a_result_landing_with_a_new_ask_is_delivered_in_the_same_reply(
    rig_for: RigFactory,
) -> None:
    model = gated("searching", "3 flights found, and I am booking the hotel")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "find me flights")
    await rig.settle()
    rig.effects.hold_kicks = True
    await record_work_finished(
        rig.conversation_id, rig.user_id, "t1", WorkOutcome.DONE, WorkReport("3 flights found")
    )
    await rig.send("m2", "also book a hotel")
    rig.effects.hold_kicks = False
    await advance(rig.ports, rig.conversation_id, rig.user_id)
    replies = await rig.of(Reply)
    shown = "\n".join(humans(model.prompts[1]))
    assert [reply.reply_id for reply in replies][1:] == ["t1"]
    assert len(replies) == 2
    assert "3 flights found" in shown
    assert "also book a hotel" in shown
    assert {"m1", "m2"} <= set((await rig.answered())[-1][1])


async def _frames_until_settled(rig: Rig) -> list[StreamedFrame]:
    seen: list[StreamedFrame] = []
    async for streamed in follow(rig.ports.log, rig.conversation_id, rig.user_id, "0"):
        if streamed is None:
            continue
        seen.append(streamed)
        if isinstance(streamed.frame, EntryFrame) and isinstance(
            streamed.frame.entry, ReplySettled
        ):
            return seen
    return seen


def _live(frames: Sequence[StreamedFrame]) -> list[tuple[str | None, dict[str, object]]]:
    """Return the frames read off the stream with their ids; a log replay depends on when a client connected."""
    return [(f.stream_id, f.frame.model_dump(mode="json")) for f in frames if f.stream_id]


@pytest.mark.service
async def test_two_clients_on_one_conversation_see_the_same_frames(
    rig_for: RigFactory,
) -> None:
    rig = await rig_for(gated("hello there"))
    first = asyncio.create_task(_frames_until_settled(rig))
    second = asyncio.create_task(_frames_until_settled(rig))
    await asyncio.sleep(0)
    await rig.send("m1", "hi")
    async with asyncio.timeout(_SETTLE_SECONDS):
        a, b = await asyncio.gather(first, second)
    await rig.settle()
    assert _live(a) == _live(b)
    kinds = [frame["kind"] for _, frame in _live(a)]
    assert "reply_delta" in kinds
    assert kinds[-1] == "entry"


@pytest.mark.service
async def test_a_client_resuming_from_a_seq_replays_what_it_missed(
    rig_for: RigFactory,
) -> None:
    rig = await rig_for(gated("hello there"))
    await rig.send("m1", "hi")
    await rig.settle()
    resumed = [streamed.frame for streamed in await _frames_until_settled(rig)]
    entries = [frame.entry.kind.value for frame in resumed if isinstance(frame, EntryFrame)]
    assert entries[:3] == ["user_message", "reply", "reply_settled"]


@pytest.mark.service
async def test_a_step_killed_mid_thinking_is_answered_after_the_sweep(
    rig_for: RigFactory, real_redis: Redis
) -> None:
    model = gated("never shown", "here you go", hold=[0])
    rig = await rig_for(model)
    await rig.send("m1", "what's on today?")
    async with asyncio.timeout(_SETTLE_SECONDS):
        await model.entered(0).wait()
    killed = running_steps()
    for step in killed:
        step.cancel()
    await asyncio.wait(killed)
    # The dead process's liveness lapses; nothing else of it survives.
    for key in await real_redis.keys("conv:alive:*"):
        await real_redis.delete(key)
    await sweep_conversations()
    await rig.settle()
    assert [reply.text for reply in await rig.of(Reply)] == ["here you go"]
    assert (await rig.answered())[-1] == (ReplyOutcome.ANSWERED, ("m1",))


@pytest.mark.service
async def test_the_sweep_reports_work_whose_executor_died_in_the_tasks_own_reply(
    rig_for: RigFactory,
) -> None:
    model = gated("working on it", "sorry, that stopped before it finished")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t9"))
    await rig.send("m1", "clean my inbox")
    await rig.settle()
    await sweep_conversations()
    await rig.settle()
    finished = await rig.of(WorkFinished)
    assert [(f.task_id, f.outcome) for f in finished] == [("t9", WorkOutcome.LOST)]
    assert (await rig.of(Reply))[-1].reply_id == "t9"


@pytest.mark.service
async def test_connecting_an_integration_continues_the_work_waiting_on_it(
    rig_for: RigFactory,
) -> None:
    model = gated("connect Gmail first", "done, the email is sent")
    rig = await rig_for(model)
    _during(
        model,
        0,
        lambda: record_integration_needed(
            rig.step(), rig.conversation_id, rig.user_id, "gmail", "Gmail"
        ),
    )
    await rig.send("m1", "email Sam the report")
    await rig.settle()
    await asyncio.gather(*_spawned_tasks, return_exceptions=True)
    woken = await continue_after_connect(rig.user_id, "gmail")
    await rig.settle()
    await asyncio.gather(*_spawned_tasks, return_exceptions=True)
    assert woken == 1
    assert await continue_after_connect(rig.user_id, "gmail") == 0
    assert len(await rig.of(IntegrationConnected)) == 1
    assert any("just connected Gmail" in text for text in humans(model.prompts[1]))
    assert [reply.text for reply in await rig.of(Reply)][-1] == "done, the email is sent"


@pytest.mark.service
async def test_an_approval_holds_the_work_until_the_user_decides(
    rig_for: RigFactory,
) -> None:
    model = gated("on it")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "send the invoice")
    await rig.settle()
    await record_approval_requested(
        rig.conversation_id, rig.user_id, "t1", "a1", summary="Send the invoice", expires_at=None
    )
    waiting = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    await record_approval_decided(rig.conversation_id, rig.user_id, "a1", "approve")
    await record_approval_decided(rig.conversation_id, rig.user_id, "a1", "approve")
    decided = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    assert [work.pending_approvals for work in waiting.work] == [frozenset({"a1"})]
    assert waiting.display is DisplayState.AWAITING_APPROVAL
    assert [work.pending_approvals for work in decided.work] == [frozenset()]
    assert len(await rig.of(ApprovalDecided)) == 1
    assert [(a.summary, a.expires_at) for a in await rig.of(ApprovalRequested)] == [
        ("Send the invoice", None)
    ]


async def _legacy_turn(rig: Rig, said: str) -> None:
    """Run one turn the way the legacy stream path did: the comms graph straight on the conversation's thread."""
    graph = await GraphManager.get_graph(GraphName.COMMS)
    await graph.ainvoke(
        {"messages": [HumanMessage(content=said)], "intent": "", "integration_usernames": {}},
        _run_config(rig.conversation_id, rig.user_id),
    )


@pytest.mark.service
async def test_a_conversation_from_before_the_step_continues_on_it_with_its_history(
    rig_for: RigFactory,
) -> None:
    model = gated("Paris is lovely in May", "May 12 to 19 then")
    rig = await rig_for(
        model,
        history=[
            {"type": "user", "response": "when should I visit Paris?", "message_id": "old-u"},
            {"type": "bot", "response": "Paris is lovely in May", "message_id": "old-b"},
        ],
    )
    await _legacy_turn(rig, "when should I visit Paris?")
    with (
        patch("app.services.conversation.send.enforce_cost_budget", new_callable=AsyncMock),
        patch("app.services.conversation.send.capture"),
    ):
        accepted = await submit_message(
            rig.conversation_id,
            AuthenticatedUser(user_id=rig.user_id),
            SendMessageRequest(message_id="m1", text="book a week then"),
            ConversationSource.WEB,
        )
    await rig.settle()
    shown = model.prompts[1]
    assert accepted.seq == 3
    assert [reply.text for reply in await rig.of(Reply)] == ["May 12 to 19 then"]
    assert await rig.answered() == [(ReplyOutcome.ANSWERED, ("m1",))]
    assert humans(shown).count("when should I visit Paris?") == 1
    assert [str(m.content) for m in shown if isinstance(m, AIMessage)] == ["Paris is lovely in May"]
    assert humans(shown).count("book a week then") == 1


def _card(tool_name: str) -> ToolDataEntry:
    return {"tool_name": tool_name, "data": {"n": 1}, "timestamp": "2026-11-13T00:00:00+00:00"}


@pytest.mark.service
async def test_executor_cards_stream_as_work_deltas_and_land_on_the_tasks_reply(
    rig_for: RigFactory,
) -> None:
    model = gated("searching", "3 flights found")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "find me flights")
    await rig.settle()
    raw = [_card("search_flights"), _card("flight_list")]
    deltas = WorkDeltas(rig.conversation_id, "t1")
    deltas({"tool_data": raw[0]})
    deltas({"reasoning": {"content": "thinking"}})
    deltas({"tool_data": [raw[1], _card("price_chart")]})
    await deltas.drain()
    resumed = WorkDeltas(rig.conversation_id, "t1")
    resumed({"tool_data": _card("booking")})
    await resumed.drain()
    cards = (_card("search_flights"), _card("flight_list"), _card("price_chart"), _card("booking"))
    await record_work_finished(
        rig.conversation_id,
        rig.user_id,
        "t1",
        WorkOutcome.DONE,
        WorkReport("3 flights found", cards),
    )
    await rig.settle()
    streamed = await read_frames(rig.conversation_id, "0", block_ms=1)
    work = [s.frame for s in streamed if isinstance(s.frame, WorkDeltaFrame)]
    shown = [f.payload.tool_data["tool_name"] for f in work if isinstance(f.payload, ToolDataEvent)]
    task_reply = [reply for reply in await rig.of(Reply) if reply.reply_id == "t1"]
    assert [(f.task_id, f.index) for f in work] == [("t1", 0), ("t1", 1), ("t1", 2), ("t1", 3)]
    assert shown == ["search_flights", "flight_list", "price_chart", "booking"]
    assert [(r.text, r.tool_data) for r in task_reply] == [("3 flights found", cards)]


@pytest.mark.service
async def test_a_messages_attached_files_are_listed_to_the_model(
    rig_for: RigFactory, mongo_db: AsyncIOMotorDatabase[dict[str, object]]
) -> None:
    model = gated("that invoice is due Friday")
    rig = await rig_for(model)
    await mongo_db["files"].insert_one(
        {
            "file_id": "f-1",
            "user_id": rig.user_id,
            "conversation_id": rig.conversation_id,
            "filename": "invoice-march.pdf",
            "type": "application/pdf",
            "size": 10,
            "url": "https://files.example/f-1",
            "description": "An invoice for March, due Friday",
            "created_at": _now(),
        }
    )
    message = UserMessage(
        id="m1", text="when is this due?", surface=ConversationSource.WEB, file_ids=("f-1",)
    )
    await accept(rig.ports, rig.conversation_id, rig.user_id, message)
    await rig.settle()
    said = [text for text in humans(model.prompts[0]) if "when is this due?" in text]
    assert len(said) == 1
    assert "invoice-march.pdf" in said[0]
    assert "An invoice for March, due Friday" in said[0]


@pytest.mark.service
async def test_work_handed_to_running_work_is_logged_and_stopped_with_it(
    rig_for: RigFactory,
) -> None:
    model = gated("on it", "added that too")
    rig = await rig_for(model)
    joined: list[bool] = []

    async def hand_over() -> None:
        step = rig.step()
        joined.append(
            await record_work_started(step, rig.conversation_id, rig.user_id, "t2", joins="t1")
        )

    _during(model, 0, lambda: rig.start_work("t1"))
    _during(model, 1, hand_over)
    await rig.send("m1", "find me flights")
    await rig.settle()
    await rig.send("m2", "and a hotel")
    await rig.settle()
    state = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    started = await rig.of(WorkStarted)
    await record_user_stop(rig.conversation_id, rig.user_id, "s1")
    await rig.settle()
    assert joined == [True]
    assert [(w.task_id, w.joins) for w in started] == [("t1", None), ("t2", "t1")]
    assert [(w.task_id, w.answers, w.joined) for w in state.work] == [("t1", ("m1", "m2"), ("t2",))]
    assert rig.effects.cancelled == [("t1", "t2")]


@pytest.mark.service
async def test_a_ledger_approval_is_held_by_the_step_task_running_in_the_conversation(
    rig_for: RigFactory, real_redis: Redis
) -> None:
    model = gated("on it")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "send the invoice")
    await rig.settle()
    before_lock = await running_step_task(rig.conversation_id, rig.user_id)
    await real_redis.set(f"{EXECUTOR_BUSY_PREFIX}{rig.conversation_id}", "stream-1:t1")
    held_by = await running_step_task(rig.conversation_id, rig.user_id)
    await real_redis.set(f"{EXECUTOR_BUSY_PREFIX}{rig.conversation_id}", "stream-2:t-legacy")
    legacy = await running_step_task(rig.conversation_id, rig.user_id)
    assert (before_lock, held_by, legacy) == (None, "t1", None)


@pytest.mark.service
async def test_a_pinned_tool_and_a_replied_to_message_reframe_the_turn_as_a_chat_send_did(
    rig_for: RigFactory,
) -> None:
    model = gated("drafting it now")
    rig = await rig_for(model)
    await send_message(
        rig.conversation_id,
        AuthenticatedUser(user_id=rig.user_id),
        SendMessageRequest(
            message_id="m1",
            text="reply to this one",
            selected_tool="gmail",
            tool_category="email",
            reply_to_message=ReplyToMessageData(
                id="old-b", content="Sam asked about Friday", role="assistant"
            ),
        ),
        ConversationSource.WEB,
    )
    await rig.settle()
    [said] = [text for text in humans(model.prompts[0]) if "reply to this one" in text]
    [message] = await rig.of(UserMessage)
    assert 'earlier message: "Sam asked about Friday"' in said
    assert "Gmail" in said
    assert (message.reply_to, message.selected_tool) == ("old-b", "gmail")


@pytest.mark.service
async def test_a_restarted_bot_finds_the_conversation_whose_work_is_still_running(
    rig_for: RigFactory, mongo_db: AsyncIOMotorDatabase[dict[str, object]]
) -> None:
    model = gated("on it", "here are your flights")
    rig = await rig_for(model)
    await mongo_db["conversations"].update_one(
        {"conversation_id": rig.conversation_id}, {"$set": {"source": "telegram"}}
    )
    platform_user = f"tg-{uuid4().hex[:8]}"
    await bot_session_repository.claim_session(
        session_key=f"telegram:{platform_user}:{platform_user}",
        platform="telegram",
        platform_user_id=platform_user,
        channel_id=None,
        candidate_conversation_id=rig.conversation_id,
        timestamp=_now().isoformat(),
    )
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "find me flights")
    await rig.settle()
    [active] = [
        a
        for a in await list_active_bot_conversations("telegram")
        if a.conversation_id == rig.conversation_id
    ]
    await record_work_finished(
        rig.conversation_id, rig.user_id, "t1", WorkOutcome.DONE, WorkReport("3 flights")
    )
    await rig.settle()
    after = await rig.ports.log.read_after(rig.conversation_id, rig.user_id, active.after_seq)
    assert (active.platform_user_id, active.is_dm) == (platform_user, True)
    assert [type(e.entry).__name__ for e in after if not isinstance(e.entry, WorkStarted)][:2] == [
        "WorkFinished",
        "Reply",
    ]
    assert all(
        a.conversation_id != rig.conversation_id
        for a in await list_active_bot_conversations("telegram")
    )


@pytest.mark.service
async def test_the_production_turn_builder_frames_the_message_with_prompt_context_and_clock(
    rig_for: RigFactory,
) -> None:
    model = gated("it is noon")
    rig = await rig_for(model, build_turn=build_comms_turn)
    await rig.send("m1", "what time is it?")
    await rig.settle()
    prompt = model.prompts[0]
    system = "\n".join(str(m.content) for m in prompt if isinstance(m, SystemMessage))
    shown = humans(prompt)
    asked = shown.index("what time is it?")
    assert "Tasks in flight" in system
    assert PromptSlot.DYNAMIC_STABLE in {slot_of(m) for m in prompt}
    assert any(m.additional_kwargs.get(TIME_CONTEXT_MARKER) for m in prompt[asked + 1 :])
    assert shown.count("what time is it?") == 1
    assert [reply.text for reply in await rig.of(Reply)] == ["it is noon"]


@pytest.mark.service
async def test_a_comms_run_on_the_step_emits_run_started_once_attributed_to_the_message_it_answers(
    rig_for: RigFactory,
) -> None:
    model = gated("it is noon")
    rig = await rig_for(model, build_turn=build_comms_turn)
    runs: list[tuple[str, Attribution]] = []

    def record(_user: object, event: ServerEvent, **_kwargs: object) -> None:
        if event.event.startswith("agent:run"):
            runs.append((event.event, current_analytics_context().attribution))

    # The kick inherits the sender's context; the run must be attributed to the message instead.
    with (
        patch.object(analytics_service, "capture", side_effect=record),
        analytics_context(worker_context(Trigger.SCHEDULE)),
    ):
        await rig.send("m1", "what time is it?")
        await rig.settle()
    by_user_on_web = Attribution(
        actor=Actor.AGENT, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
    )
    assert runs == [
        ("agent:run_started", by_user_on_web),
        ("agent:run_completed", by_user_on_web),
    ]


@pytest.mark.service
async def test_a_handoff_decided_by_its_button_continues_the_conversation(
    rig_for: RigFactory,
) -> None:
    model = gated("Signing in now", "Continuing, and skipping the upvote")
    rig = await rig_for(model)
    _during(model, 0, lambda: rig.start_work("t1"))
    await rig.send("m1", "log in and upvote the post")
    await rig.settle()
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-1",
            user_id=rig.user_id,
            conversation_id=rig.conversation_id,
            reason="Sign in",
            reply_to=rig.conversation_id,
        ),
    )
    decided = await decide_handoff_by_button(
        "h1", HandoffDecision.CONTINUE, rig.user_id, "skip the upvote"
    )
    await rig.settle()
    assert decided is HandoffStatus.COMPLETED
    said = [m.text for m in await rig.of(UserMessage)]
    assert said[-1] == "[From the browser handoff card] continue: skip the upvote"
    assert [r.text for r in await rig.of(Reply)][-1] == "Continuing, and skipping the upvote"
    assert humans(model.prompts[1]).count(said[-1]) == 1


# ---- work started outside a step ----


@dataclass
class _Spawned:
    """The carry runs deliver_to_executor started, finished as their executor would when told to."""

    rig: Rig
    finish_with: str | None = None
    task_ids: list[str] = field(default_factory=list)
    finishing: list[asyncio.Task[None]] = field(default_factory=list)

    def spawn(self, prepared: PreparedQueuedTask, conversation_id: str) -> None:
        task_id = prepared.run.task_id
        assert task_id is not None and prepared.run.work_logged
        self.task_ids.append(task_id)
        if self.finish_with is not None:
            finished = record_work_finished(
                conversation_id,
                self.rig.user_id,
                task_id,
                WorkOutcome.DONE,
                WorkReport(self.finish_with),
            )
            self.finishing.append(asyncio.ensure_future(finished))


async def _approve_after_the_turn(rig: Rig, spawned: _Spawned) -> int:
    """Decide a ledger approval once its turn is over, as decide_ledger does; return the decision's seq."""
    await record_approval_decided(rig.conversation_id, rig.user_id, "a1", "approve")
    with patch.object(executor_runner, "_spawn_detached_run", spawned.spawn):
        await deliver_to_executor(
            rig.conversation_id,
            AuthenticatedUser(user_id=rig.user_id),
            "APPROVAL_READY a1: the user approved Send the invoice",
        )
    decided = await rig.entries()
    return next(e.seq for e in decided if isinstance(e.entry, ApprovalDecided))


@pytest.mark.service
async def test_an_approval_decided_after_its_turn_ended_runs_its_work_under_the_step(
    rig_for: RigFactory,
) -> None:
    model = gated("I need your approval to send it", "Sent the invoice to Acme")
    rig = await rig_for(model)
    await rig.send("m1", "send the invoice")
    await rig.settle()
    spawned = _Spawned(rig, finish_with="invoice sent")
    decided_seq = await _approve_after_the_turn(rig, spawned)
    await asyncio.gather(*spawned.finishing)
    await rig.settle()
    [task_id] = spawned.task_ids
    [started] = [w for w in await rig.of(WorkStarted) if w.task_id == task_id]
    assert started.cause_through == decided_seq
    replies = await rig.of(Reply)
    assert [(r.reply_id, r.text) for r in replies][-1] == (task_id, "Sent the invoice to Acme")
    assert [r.reply_id for r in replies].count(task_id) == 1
    assert any("invoice sent" in text for text in humans(model.prompts[1]))
    # What a client (web or a bot) follows: the task's reply is entered once, never twice.
    frames = await read_frames(rig.conversation_id, "0", block_ms=1)
    opened = [
        f.frame.entry.reply_id
        for f in frames
        if isinstance(f.frame, EntryFrame) and isinstance(f.frame.entry, Reply)
    ]
    assert opened.count(task_id) == 1


@pytest.mark.service
async def test_a_stop_cancels_the_work_an_approval_started_after_its_turn(
    rig_for: RigFactory,
) -> None:
    model = gated("I need your approval to send it")
    rig = await rig_for(model)
    await rig.send("m1", "send the invoice")
    await rig.settle()
    spawned = _Spawned(rig)
    await _approve_after_the_turn(rig, spawned)
    working = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    await record_user_stop(rig.conversation_id, rig.user_id, "s1")
    await rig.settle()
    stopped = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    assert working.display is DisplayState.WORKING
    assert rig.effects.cancelled == [tuple(spawned.task_ids)]
    assert stopped.work == ()
    assert len(await rig.of(Reply)) == 1


# ---- tracked todo runs on the step ----


def _todo_doc(user_id: str, *, as_written: bool = False) -> TodoDocument:
    ref = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="thread_1") if as_written else None
    return TodoDocument.model_validate(
        {
            "id": "todo_acme",
            "user_id": user_id,
            "title": "Watch the Acme thread",
            "external_ref": ref,
        }
    )


def _fake_executor(
    report: str, *, nothing_for_user: bool = False
) -> Callable[..., Awaitable[None]]:
    """Do what the executor's finalize does for a run on the log: log how its work ended."""

    async def run(run: ExecutorRun, task: str, configurable: AgentConfigurable) -> None:
        assert run.work_logged and run.task_id is not None
        await record_work_finished(
            run.conversation_id,
            run.user.user_id,
            run.task_id,
            WorkOutcome.DONE,
            WorkReport(report, nothing_for_user=nothing_for_user),
        )

    return run


@dataclass
class _TodoDelivery:
    """The todo store and the chat-app send a finished todo run reaches, recorded."""

    sent: AsyncMock
    finished: AsyncMock


@asynccontextmanager
async def _todo_rig(
    rig_for: RigFactory,
    model: GatedModel,
    todo: TodoDocument,
    executor: Callable[..., Awaitable[None]],
) -> AsyncIterator[tuple[Rig, _TodoDelivery]]:
    rig = await rig_for(model, build_turn=build_comms_turn)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=todo.model_copy(update={"user_id": rig.user_id}))
    delivery = _TodoDelivery(
        sent=AsyncMock(return_value=ConversationSource.TELEGRAM), finished=AsyncMock()
    )
    channel = ChatChannel(
        source=ConversationSource.TELEGRAM, platform_user_id="tg_1", basis="recent_activity"
    )
    with (
        patch.object(todo_run, "run_executor_background", executor),
        patch.object(todo_run_delivery, "todo_repository", repo),
        patch.object(
            todo_run_delivery, "resolve_proactive_target", AsyncMock(return_value=channel)
        ),
        patch.object(todo_run_delivery, "deliver_result_to_platforms", delivery.sent),
        patch.object(todo_run_delivery, "record_run_finished", delivery.finished),
    ):
        yield rig, delivery


def _todo_request(rig: Rig, todo: TodoDocument) -> TodoRunRequest:
    return TodoRunRequest(
        user=AuthenticatedUser(user_id=rig.user_id),
        todo_run=TodoRun(
            todo_id=todo.id,
            run_id="run_acme",
            title=todo.title,
            trigger_type=TriggerType.TODO_TRIGGER,
            runs_once=False,
            wake=TodoRunWake(
                kind=TodoWakeKind.TRIGGER, trigger_names=["gmail"], approval_summary=None
            ),
            report_form=report_form_of(todo),
            attribution=worker_context(Trigger.INTEGRATION_TRIGGER).attribution,
        ),
        task="Check the Acme thread for a reply",
        conversation_id=rig.conversation_id,
        fresh_thread=False,
    )


@pytest.mark.service
async def test_a_todo_wake_gets_one_write_up_in_its_chat_and_that_write_up_is_what_is_sent(
    rig_for: RigFactory,
) -> None:
    model = gated("Acme accepted the quote and asked for the invoice")
    todo = _todo_doc("owner")
    executor = _fake_executor("Acme replied at 10:02: quote accepted, invoice requested")
    async with _todo_rig(rig_for, model, todo, executor) as (rig, delivery):
        await run_todo_on_executor(_todo_request(rig, todo))
        await rig.settle()
    [woke] = await rig.of(TodoWoke)
    [started] = await rig.of(WorkStarted)
    replies = await rig.of(Reply)
    assert woke.run.run_id == "run_acme"
    assert started.answers == (woke.id,)
    assert [(r.reply_id, r.text) for r in replies] == [
        (started.task_id, "Acme accepted the quote and asked for the invoice")
    ]
    assert [answers for _o, answers in await rig.answered()] == [
        (f"work:{started.task_id}:finished", woke.id)
    ]
    assert any("tracked todo" in text for text in humans(model.prompts[0]))
    delivery.sent.assert_awaited_once()
    assert (
        delivery.sent.await_args.kwargs["notification_text"]
        == "Acme accepted the quote and asked for the invoice"
    )
    assert delivery.finished.await_args.args[2] == "run_acme"
    assert "result sent on telegram" in delivery.finished.await_args.args[3]


@pytest.mark.service
async def test_a_todo_run_that_found_nothing_for_the_user_settles_silent_and_sends_nothing(
    rig_for: RigFactory,
) -> None:
    model = gated()
    todo = _todo_doc("owner", as_written=True)
    executor = _fake_executor("No new mail on the thread", nothing_for_user=True)
    async with _todo_rig(rig_for, model, todo, executor) as (rig, delivery):
        await run_todo_on_executor(_todo_request(rig, todo))
        await rig.settle()
    [woke] = await rig.of(TodoWoke)
    assert model.prompts == []
    assert [(outcome, answers[-1]) for outcome, answers in await rig.answered()] == [
        (ReplyOutcome.SILENT, woke.id)
    ]
    assert [(r.text, r.tool_data) for r in await rig.of(Reply)] == [("", ())]
    delivery.sent.assert_not_awaited()
    assert "the run found nothing for the user" in delivery.finished.await_args.args[3]


@pytest.mark.service
async def test_a_playbook_replay_reads_back_from_its_conversations_log_with_its_cards(
    rig_for: RigFactory,
) -> None:
    rig = await rig_for(gated())
    # Cards resolve their categories through the real tool registry.
    if not providers.is_initialized("tool_registry"):
        init_tool_registry()
    now = datetime.now(UTC)
    playbook = PlaybookDocument(
        playbook_id="pb-1",
        workflow_id="wf-1",
        user_id=rig.user_id,
        workflow_hash="h",
        description="Fetch unread mail",
        steps=[ToolStep(id="fetch", tool="GMAIL_FETCH_EMAILS", args={})],
        result_brief="s",
        created_at=now,
        updated_at=now,
    )
    await log_playbook_run(
        rig.conversation_id, rig.user_id, _workflow(rig.user_id), "3 unread", [_CALL], playbook
    )
    replayed = await replay_from_log(rig.ports.log, rig.conversation_id, rig.user_id, 0)
    notices = [
        f.frame.entry
        for f in replayed
        if isinstance(f.frame, EntryFrame) and isinstance(f.frame.entry, Notice)
    ]
    [notice] = notices
    assert notice.text == "3 unread"
    assert [card["data"]["tool_name"] for card in notice.tool_data] == [
        "run_playbook",
        "GMAIL_FETCH_EMAILS",
    ]
    assert len(notice.tool_data) == 2
    assert running_steps() == ()


# ---- workflow fires on the step ----

_CALL = RecordedCall(tool_name="GMAIL_FETCH_EMAILS", args={"max_results": 3})


@dataclass
class _Turns:
    """Every production turn the step built, with the attempt it was built for."""

    built: list[tuple[StepClaim, Batch, CommsTurn]] = field(default_factory=list)

    async def build(self, claim: StepClaim, batch: Batch) -> CommsTurn:
        turn = await build_comms_turn(claim, batch)
        self.built.append((claim, batch, turn))
        return turn

    def configurable(self, index: int) -> AgentConfigurable:
        return self.built[index][2].config["configurable"]


def _workflow(user_id: str) -> Workflow:
    return Workflow(
        id=f"wf_{uuid4().hex[:8]}",
        user_id=user_id,
        title="Morning inbox",
        description="Summarise my unread mail",
        prompt="Fetch unread mail and summarise it",
        steps=[WorkflowStep(id="s1", title="Fetch mail", description="Read unread mail")],
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE),
    )


def _hand_off_work(
    rig: Rig, turns: _Turns, execution_id: str, outcome: WorkOutcome
) -> Callable[[], Awaitable[object]]:
    """Do what call_executor and its executor do: start work, record its call, finish it."""

    async def work() -> None:
        claim, batch, _turn = turns.built[-1]
        assert await record_work_started(
            step_turn_ref(claim, batch), rig.conversation_id, rig.user_id, "t1"
        )
        await append_call(execution_id, _CALL)
        await record_work_finished(
            rig.conversation_id, rig.user_id, "t1", outcome, WorkReport("3 unread")
        )

    return work


@asynccontextmanager
async def _fire_rig(
    rig_for: RigFactory, model: GatedModel, turns: _Turns
) -> AsyncIterator[tuple[Rig, AsyncMock]]:
    """Build a workflow conversation answered by model, with the chat-app delivery recorded."""
    rig = await rig_for(model, build_turn=turns.build)
    notified = AsyncMock()
    with (
        patch.object(
            workflow_tasks,
            "get_or_create_workflow_conversation",
            AsyncMock(return_value=rig.conversation_id),
        ),
        patch.object(workflow_tasks, "_notify_run_finished", notified),
    ):
        yield rig, notified


@pytest.mark.service
async def test_a_fire_gets_one_reply_in_its_conversation_and_the_job_sees_success_with_the_trace(
    rig_for: RigFactory,
) -> None:
    model = gated("on it", "Three unread: rent, dentist, flights")
    turns = _Turns()
    async with _fire_rig(rig_for, model, turns) as (rig, notified):
        workflow = _workflow(rig.user_id)
        model._during[0] = _hand_off_work(rig, turns, "exec_a", WorkOutcome.DONE)
        conversation_id, trace = await execute_workflow_as_chat(
            workflow,
            AuthenticatedUser(user_id=rig.user_id),
            {"trigger_type": TriggerType.SCHEDULE.value},
            reservation=":fire-a",
            execution_id="exec_a",
        )
        await rig.settle()
    assert (conversation_id, trace) == (rig.conversation_id, [_CALL])
    assert [entry.run.execution_id for entry in await rig.of(WorkflowFired)] == ["exec_a"]
    assert [r.text for r in await rig.of(Reply)] == [
        "on it",
        "Three unread: rent, dentist, flights",
    ]
    assert [answers for _outcome, answers in await rig.answered()][-1][-1] == "workflow:exec_a"
    notified.assert_awaited_once()
    assert notified.await_args.args[3] == "Three unread: rent, dentist, flights"
    fired_turn = turns.configurable(0)
    assert fired_turn["stream_id"] == "exec_a"
    assert fired_turn["executor_lock_reservation"] == ":fire-a"
    assert fired_turn["workflow_id"] == workflow.id
    assert fired_turn["execution_mode"] == "background"
    assert any("Scheduled workflow: Morning inbox" in m for m in fired_turn["user_messages"])
    assert any("Fetch mail" in text for text in humans(model.prompts[0]))


@pytest.mark.service
async def test_a_run_whose_work_fails_reports_failure_and_delivers_nothing(
    rig_for: RigFactory,
) -> None:
    model = gated("on it", "That did not work")
    turns = _Turns()
    async with _fire_rig(rig_for, model, turns) as (rig, notified):
        model._during[0] = _hand_off_work(rig, turns, "exec_b", WorkOutcome.FAILED)
        with pytest.raises(WorkflowTurnFailed, match="work failed") as raised:
            await execute_workflow_as_chat(
                _workflow(rig.user_id),
                AuthenticatedUser(user_id=rig.user_id),
                {},
                reservation=":fire-b",
                execution_id="exec_b",
            )
        await rig.settle()
    assert raised.value.trace == [_CALL]
    assert raised.value.conversation_id == rig.conversation_id
    notified.assert_not_awaited()


@pytest.mark.service
async def test_a_second_fire_of_the_same_workflow_is_refused_while_the_first_is_answered(
    rig_for: RigFactory,
) -> None:
    model = gated("brief sent", hold=[0])
    turns = _Turns()
    async with _fire_rig(rig_for, model, turns) as (rig, _notified):
        workflow = _workflow(rig.user_id)
        conversation_id, lock_task = await _reserve_conversation(workflow, workflow.id)
        first = asyncio.create_task(
            execute_workflow_as_chat(
                workflow,
                AuthenticatedUser(user_id=rig.user_id),
                {},
                reservation=build_lock_value(None, lock_task),
                execution_id="exec_c",
            )
        )
        await model.entered(0).wait()
        with pytest.raises(WorkflowFireOverlapped):
            await _reserve_conversation(workflow, workflow.id)
        first.cancel()
        await asyncio.wait({first})
    assert conversation_id == rig.conversation_id
    assert not await try_acquire_lock(
        f"{EXECUTOR_BUSY_PREFIX}{conversation_id}", build_lock_value(None, "intruder")
    )
    assert len(await rig.of(WorkflowFired)) == 1


@pytest.mark.service
async def test_a_fire_during_a_users_chat_turn_is_answered_after_it_never_merged(
    rig_for: RigFactory,
) -> None:
    model = gated("it is noon", "brief sent")
    turns = _Turns()
    appended = asyncio.Event()

    async def accept_and_say(
        ports: RuntimePorts, conversation_id: str, user_id: str, entry: Entry
    ) -> Accepted:
        accepted = await accept(ports, conversation_id, user_id, entry)
        appended.set()
        return accepted

    async with _fire_rig(rig_for, model, turns) as (rig, _notified):
        workflow = _workflow(rig.user_id)
        fire_task: list[asyncio.Task[tuple[str, list[RecordedCall]]]] = []

        async def fire_mid_chat() -> None:
            fire = execute_workflow_as_chat(
                workflow,
                AuthenticatedUser(user_id=rig.user_id),
                {},
                reservation=":fire-d",
                execution_id="exec_d",
            )
            fire_task.append(asyncio.create_task(fire))
            await appended.wait()

        model._during[0] = fire_mid_chat
        with patch.object(workflow_tasks, "accept", accept_and_say):
            await rig.send("m1", "what time is it?")
            await model.entered(0).wait()
            await appended.wait()
            await fire_task[0]
        await rig.settle()
    batches = [[logged.entry.kind for logged in batch.waking] for _c, batch, _t in turns.built]
    assert batches == [["user_message"], ["workflow_fired"]]
    assert await rig.answered() == [
        (ReplyOutcome.ANSWERED, ("m1",)),
        (ReplyOutcome.ANSWERED, ("workflow:exec_d",)),
    ]
    assert "what time is it?" not in humans(model.prompts[1])[-3:]
    assert [m.id for m in await rig.of(UserMessage)] == ["m1"]


@pytest.mark.service
async def test_a_successful_fire_records_success_and_emits_workflow_executed_once(
    rig_for: RigFactory,
) -> None:
    model = gated("Your brief: all quiet")
    turns = _Turns()
    async with _fire_rig(rig_for, model, turns) as (rig, notified):
        workflow = _workflow(rig.user_id)
        fire = _Fire(
            workflow=workflow,
            workflow_id=workflow.id,
            context={},
            user=AuthenticatedUser(user_id=rig.user_id),
            reservation=":fire-e",
            execution_id="exec_e",
        )
        captured = AsyncMock()
        completed = AsyncMock()
        with (
            patch.object(workflow_tasks, "enforce_tiered_limit", AsyncMock()),
            patch.object(
                workflow_tasks.playbook_repository,
                "get_for_workflow",
                AsyncMock(return_value=None),
            ),
            patch.object(workflow_tasks.WorkflowService, "increment_execution_count", AsyncMock()),
            patch.object(workflow_tasks, "complete_execution", completed),
            patch.object(workflow_tasks, "distrust_fresh_playbook", AsyncMock()),
            patch.object(workflow_tasks, "_rearm_quietly", AsyncMock()),
            patch.object(workflow_tasks, "capture", captured),
        ):
            await _run_and_record_success(fire, TriggerType.SCHEDULE.value, "exec_e")
        await rig.settle()
    executed = [
        c.args[1] for c in captured.call_args_list if isinstance(c.args[1], WorkflowExecuted)
    ]
    assert executed == [WorkflowExecuted(workflow_id=workflow.id, trigger_type="schedule")]
    assert completed.await_args.kwargs["status"] == "success"
    assert completed.await_args.kwargs["conversation_id"] == rig.conversation_id
    notified.assert_awaited_once()
