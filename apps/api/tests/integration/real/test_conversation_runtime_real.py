"""The conversation runtime wired end to end on real Mongo, Redis and Postgres, with a scripted model.

Production ports throughout (the Mongo log, the comms graph runner, the Redis frames stream,
the effects that kick steps), except the turn builder, which skips the user's memory and
context slots, and the instant reaction, which is never asked for.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, TypeVar, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest
from redis.asyncio import Redis

from app.agents.context.slots import TIME_CONTEXT_MARKER, mark
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import GraphManager
from app.constants.chat import ConversationSource
from app.constants.graphs import GraphName
from app.db.redis import redis_cache
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.agent_config import StepTurnRef
from app.models.agent_models import AgentRunnableConfig
from app.models.conversation_frame_models import EntryFrame, ToolDataEvent, WorkDeltaFrame
from app.models.conversation_log_models import (
    ApprovalDecided,
    Batch,
    DisplayState,
    IntegrationConnected,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StepClaim,
    StopRequested,
    WorkFinished,
    WorkOutcome,
)
from app.models.conversation_send_models import SendMessageRequest
from app.models.tool_data_models import ToolDataEntry
from app.models.user_models import AuthenticatedUser
from app.services.conversation.comms_runner import CommsGraphRunner, CommsTurn
from app.services.conversation.comms_turn import step_turn_ref
from app.services.conversation.composition import RuntimeEffects, running_steps
from app.services.conversation.event_stream import (
    RedisStreamFrames,
    StreamedFrame,
    follow,
    read_frames,
)
from app.services.conversation.integration_log import (
    continue_after_connect,
    record_integration_needed,
)
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.send import send_message, submit_message
from app.services.conversation.step import advance
from app.services.conversation.sweeper import sweep_conversations
from app.services.conversation.work_deltas import WorkDeltas
from app.services.conversation.work_log import (
    record_approval_decided,
    record_approval_requested,
    record_user_stop,
    record_work_finished,
    record_work_started,
)
from shared.py.wide_events import _spawned_tasks
from tests.e2e._harness.graph_run import comms_graph
from tests.integration.real.test_comms_runner_real import (
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
        self, model: GatedModel, history: Sequence[dict[str, str]] = ()
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

        async def build(model: GatedModel, history: Sequence[dict[str, str]] = ()) -> Rig:
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
                    _turn_builder(turns, user_id), cancel_confirm_seconds=_CONFIRM_SECONDS
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
        rig.conversation_id, rig.user_id, "t1", WorkOutcome.DONE, "3 flights found"
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
    await record_approval_requested(rig.conversation_id, rig.user_id, "t1", "a1")
    waiting = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    await record_approval_decided(rig.conversation_id, rig.user_id, "a1", "approve")
    await record_approval_decided(rig.conversation_id, rig.user_id, "a1", "approve")
    decided = await rig.ports.log.state(rig.conversation_id, rig.user_id)
    assert [work.pending_approvals for work in waiting.work] == [frozenset({"a1"})]
    assert waiting.display is DisplayState.AWAITING_APPROVAL
    assert [work.pending_approvals for work in decided.work] == [frozenset()]
    assert len(await rig.of(ApprovalDecided)) == 1


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
        rig.conversation_id, rig.user_id, "t1", WorkOutcome.DONE, "3 flights found", cards
    )
    await rig.settle()
    streamed = await read_frames(rig.conversation_id, "0", block_ms=1)
    work = [s.frame for s in streamed if isinstance(s.frame, WorkDeltaFrame)]
    shown = [f.payload.tool_data["tool_name"] for f in work if isinstance(f.payload, ToolDataEvent)]
    task_reply = [reply for reply in await rig.of(Reply) if reply.reply_id == "t1"]
    assert [(f.task_id, f.index) for f in work] == [("t1", 0), ("t1", 1), ("t1", 2), ("t1", 3)]
    assert shown == ["search_flights", "flight_list", "price_chart", "booking"]
    assert [(r.text, r.tool_data) for r in task_reply] == [("3 flights found", cards)]
