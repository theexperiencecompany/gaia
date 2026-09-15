"""What the user sees across a HIL pause — the frames on the stream, not the approval semantics (see test_hil_barrier_e2e.py / test_hil_spawn_e2e.py for those)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis
from langgraph.store.memory import InMemoryStore
import pytest

from app.agents.core.background.executor_runner import QUEUED_EXECUTOR_TASK_NAME
from app.agents.core.background.redis_writer import STREAM_PUBLISH_TASK_NAME
from app.agents.core.background.session import teardown_session
from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME, HIL_DECIDED_UNRESUMED_GRACE_SECONDS
from app.constants.memory import ReconcileOutcome
from app.constants.streaming import WS_EVENT_EXECUTOR_CANCELLED
from app.core.stream_manager import stream_manager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.users import user_repository
from app.memory.ingestion import RetainedMemory
from app.models.chat_models import ToolDataEntry
from app.models.hil_models import (
    HILApprovalRecord,
    HILApprovalStatus,
    HILApprovalUpdate,
    HILMode,
    HILPreferences,
)
from app.models.memory_models import MemoryEntry
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream as chat_stream
from app.services.hil import resolution
from app.utils import background_tasks
from app.workers.tasks.hil_sweep_tasks import sweep_hil_approvals
from tests.e2e._harness.transcript import Frame, Transcript
from tests.e2e.test_agent_chain import call, streaming_model

pytestmark = pytest.mark.e2e

USER: AuthenticatedUser = {
    "user_id": "u-hil-stream",
    "email": "hil-stream@test.local",
    "name": "Test User",
}

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"

#: Pure and real: returns real mermaid source, so "reached the stream" is
#: asserted on CONTENT — a denial, a gate error, or a missing user_id would
#: otherwise also produce a perfectly joinable string.
GATED_TOOL = "create_flowchart"
GATED_ARGS = {"description": "how an approved action reaches the user", "direction": "LR"}
#: Emitted by the executor's model, so it is the id the card and the result are
#: joined by, and the id ``claim_tool_output`` claims.
GATED_CALL_ID = "tc_gated"


def executor_script() -> list[Any]:
    """Retrieve the gated tool, call it, then answer.

    Three model calls, and the third is only reached after the approval resumes
    the run — so a resume that never happens shows up as a missing final answer
    rather than as a silently shorter stream.
    """
    return [
        call("retrieve_tools", {"exact_tool_names": [GATED_TOOL]}, call_id="tc_retrieve"),
        call(GATED_TOOL, GATED_ARGS, call_id=GATED_CALL_ID),
        "Drew the flowchart.",
    ]


def comms_script() -> list[Any]:
    return [call("call_executor", {"task": "draw the flowchart"}, call_id="tc_exec"), "On it."]


def assert_real_tool_output(output: str) -> None:
    """Assert output is create_flowchart's real return, not a stand-in.

    create_flowchart interpolates its own args into what it returns. A HIL
    denial (DENIED_TEMPLATE), gate failure (GATE_ERROR_TEMPLATE), unbound-tool
    correction, or missing user_id would each still produce a joinable string.
    """
    assert GATED_ARGS["description"] in output, (
        f"the stream must carry the tool's REAL output, got {output[:300]!r}"
    )
    assert f"direction: {GATED_ARGS['direction']}" in output, (
        f"the real output must carry the call's own arguments, got {output[:300]!r}"
    )


# ---------------------------------------------------------------------------
# The Mongo stand-in for approval records
# ---------------------------------------------------------------------------


class InMemoryApprovals:
    """The hil_approvals collection, in a dict.

    Mongo is the only reason these scenarios would otherwise need live infra, and
    the record store is not what is under test here — the frames are. Every method
    below mirrors the real repository's contract exactly, including the two that
    carry a guarantee: create_if_absent is a no-op on a duplicate id (a resume
    replay must not re-publish the card) and mark_decided transitions only from
    pending (a racing decision must lose). Those same two guarantees are proven
    against real Mongo in tests/contracts and tests/unit/services/hil.
    """

    def __init__(self) -> None:
        self.records: dict[str, HILApprovalRecord] = {}

    async def create_if_absent(self, record: HILApprovalRecord) -> bool:
        if record.approval_id in self.records:
            return False
        self.records[record.approval_id] = record.model_copy(deep=True)
        return True

    async def get(self, approval_id: str) -> HILApprovalRecord | None:
        record = self.records.get(approval_id)
        return record.model_copy(deep=True) if record else None

    async def mark_decided(
        self,
        approval_id: str,
        status: HILApprovalStatus,
        *,
        feedback: str | None,
        scope: str,
        decided_by: str | None,
    ) -> bool:
        record = self.records.get(approval_id)
        if record is None or record.status != "pending":
            return False
        self.records[approval_id] = record.model_copy(
            update={
                "status": status,
                "feedback": feedback,
                "scope": scope,
                "decided_by": decided_by,
                "decided_at": datetime.now(UTC),
            }
        )
        return True

    async def update(self, approval_id: str, update: HILApprovalUpdate) -> Any:
        record = self.records.get(approval_id)
        if record is None:
            return None
        fields = update.model_dump(exclude_unset=True)
        self.records[approval_id] = record.model_copy(update=fields)
        return self.records[approval_id]

    async def list_expired_pending(self) -> list[HILApprovalRecord]:
        now = datetime.now(UTC)
        return [r for r in self.records.values() if r.status == "pending" and r.expires_at < now]

    async def list_decided_unresumed(
        self, statuses: list[str], grace_seconds: float
    ) -> list[HILApprovalRecord]:
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        return [
            r
            for r in self.records.values()
            if r.status in statuses
            and r.resumed_at is None
            and r.resume_item is not None
            and r.decided_at is not None
            and r.decided_at < cutoff
        ]

    async def list_pending_for_conversation(self, conversation_id: str) -> list[HILApprovalRecord]:
        return sorted(
            (
                r
                for r in self.records.values()
                if r.conversation_id == conversation_id and r.status == "pending"
            ),
            key=lambda r: r.created_at,
        )

    async def list_parked_subagents_for_conversation(
        self, conversation_id: str
    ) -> list[HILApprovalRecord]:
        return sorted(
            (
                r
                for r in self.records.values()
                if r.conversation_id == conversation_id
                and r.subagent_thread_id is not None
                and r.subagent_collected_at is None
            ),
            key=lambda r: r.created_at,
        )

    # -- test-side queries --------------------------------------------------

    def only_record(self) -> HILApprovalRecord:
        assert len(self.records) == 1, (
            f"expected exactly one approval record, got {list(self.records)}"
        )
        return next(iter(self.records.values()))

    def for_tool(self, tool_name: str) -> HILApprovalRecord:
        """Return the single approval for tool_name; fail loud on zero or several."""
        matches = [r for r in self.records.values() if r.tool_name == tool_name]
        assert len(matches) == 1, (
            f"expected exactly one approval for {tool_name!r}, got "
            f"{[(r.tool_name, r.status) for r in self.records.values()]}"
        )
        return matches[0]

    def for_call(self, tool_call_id: str) -> HILApprovalRecord:
        """Return the approval for one specific call — the only way to tell apart two gated calls of the same tool, which for_tool cannot."""
        matches = [r for r in self.records.values() if r.tool_call_id == tool_call_id]
        assert len(matches) == 1, (
            f"expected exactly one approval for call {tool_call_id!r}, got "
            f"{[(r.tool_call_id, r.tool_name, r.status) for r in self.records.values()]}"
        )
        return matches[0]

    def statuses(self) -> dict[str, str]:
        """Tool name -> recorded status, for asserting a whole batch at once."""
        return {r.tool_name: r.status for r in self.records.values()}


# ---------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------


@dataclass
class HilWorld:
    """One conversation, its streams, and the approval store behind it."""

    conversation_id: str
    comms_stream_id: str
    approvals: InMemoryApprovals
    #: Every ``executor.stream_started`` broadcast — the ONLY way a client learns
    #: which stream a resumed run publishes on, so it is also how this test finds
    #: the streams to read.
    started_streams: list[str] = field(default_factory=list)
    #: Every ``executor.cancelled`` broadcast — the client's only notice of a
    #: cancel it did not initiate, and the only thing that finalizes a card the
    #: cancel path never settles on the stream.
    cancelled_broadcasts: list[dict[str, Any]] = field(default_factory=list)
    overrides_set: list[tuple[str, str, bool | None]] = field(default_factory=list)
    delivered: list[tuple[str, str]] = field(default_factory=list)

    #: Streams opened by a chat turn, oldest first. More than one when a later
    #: turn (a cancellation, say) arrives while an earlier one is parked.
    comms_streams: list[str] = field(default_factory=list)

    def stream_ids(self) -> list[str]:
        return [self.comms_stream_id, *self.comms_streams, *self.started_streams]

    async def frames(self) -> list[Frame]:
        """Every frame on every stream of this conversation, in stream order.

        The user's timeline spans streams: a resume publishes on a NEW stream id
        (prepare_run_from_item), and the client follows it via the
        executor.stream_started event. Asserting on one stream alone would
        read a duplicate as an absence, or an absence as a duplicate.
        """
        await drain_publishes()
        collected: list[Frame] = []
        for stream_id in self.stream_ids():
            chunks = [chunk async for chunk in stream_manager.subscribe_stream(stream_id)]
            collected.extend(Transcript.from_sse("".join(chunks)).frames())
        return collected

    async def approval_cards(self) -> list[dict[str, Any]]:
        """Every approval_request card the user was shown, in order."""
        cards: list[dict[str, Any]] = []
        for frame in await self.frames():
            if frame.kind != "tool_data":
                continue
            entries = frame.data if isinstance(frame.data, list) else [frame.data]
            for entry in entries:
                if isinstance(entry, dict) and entry.get("tool_name") == APPROVAL_REQUEST_TOOL_NAME:
                    cards.append(entry["data"])
        return cards

    async def decide(
        self,
        kind: resolution.DecisionKind,
        *,
        scope: str = "once",
        tool: str | None = None,
        call_id: str | None = None,
    ) -> HILApprovalRecord:
        """Answer a pending approval, and wait out the run it wakes.

        The same code path every decision source (buttons, bot, conversational
        resolver) funnels through. tool selects which approval when a turn
        gated several calls, call_id when two are the same tool; otherwise the
        turn must have exactly one.
        """
        if call_id is not None:
            record = self.approvals.for_call(call_id)
        elif tool is not None:
            record = self.approvals.for_tool(tool)
        else:
            record = self.approvals.only_record()
        await resolution.resolve_approval(
            approval_id=record.approval_id, user_id=str(USER["user_id"]), kind=kind, scope=scope
        )
        await drain_resumes()
        reloaded = await self.approvals.get(record.approval_id)
        assert reloaded is not None
        return reloaded

    async def cards_for(self, gated_tool_name: str) -> list[str]:
        """Return the card statuses the user saw for one gated tool, in order."""
        return [
            card["status"]
            for card in await self.approval_cards()
            if card["gated_tool_name"] == gated_tool_name
        ]

    def overrides_for(self, tool_name: str) -> list[bool | None]:
        """Every preference write-back for one tool — [] when untouched."""
        return [ask for _user, tool, ask in self.overrides_set if tool == tool_name]

    async def tool_output_ids(self) -> list[str]:
        """Every tool_output frame's id, in order and WITH repeats.

        A list, not a set and not a lookup: the frontend renders one card per
        id, so a second frame for an id it has already filled in is a duplicate
        card. Transcript.result_for cannot express this — it returns the
        first match and discards the rest.
        """
        return [
            str(frame.data["tool_call_id"])
            for frame in await self.frames()
            if frame.kind == "tool_output"
        ]

    async def outputs_for(self, tool_call_id: str) -> list[str]:
        """Every tool_output carrying this id — a LIST, so duplicates show up.

        Transcript.result_for returns the first match and discards the rest,
        which cannot express "exactly once"; that blindness is how the last
        duplicate-card bug hid.
        """
        return [
            frame.data["output"]
            for frame in await self.frames()
            if frame.kind == "tool_output" and frame.data.get("tool_call_id") == tool_call_id
        ]


def _tasks_named(*names: str) -> list[asyncio.Task[object]]:
    """Live background tasks carrying any of names.

    Filtering by name rather than draining the whole keep-alive set: that set
    also holds work which outlives a single turn, so awaiting all of it would
    hang here forever instead of failing a test.
    """
    wanted = set(names)
    return [t for t in background_tasks._background_tasks if t.get_name() in wanted]


async def drain_publishes() -> None:
    """Wait out the fire-and-forget XADDs the background writer scheduled.

    make_redis_stream_writer is a sync callable that schedules each publish
    through spawn_background_task, so reading the log without waiting reads a
    truncated stream.
    """
    while pending := _tasks_named(STREAM_PUBLISH_TASK_NAME):
        await asyncio.gather(*pending, return_exceptions=True)


async def drain_resumes() -> None:
    """Wait out the executor runs resolve_approval dispatched.

    _dispatch_resume spawns the resumed run with asyncio.create_task and
    returns immediately — the decision endpoint does not wait for the action. A
    test that does not wait here reads the stream before the approved tool has
    run and would assert zero results as "exactly zero duplicates".
    """
    while resolution._resume_tasks:
        await asyncio.gather(*list(resolution._resume_tasks), return_exceptions=True)
    await drain_publishes()


async def drain_background_runs() -> None:
    """Wait out every executor task still in flight, whatever spawned it.

    Loops until both the spawn_background_task set and HIL's resume set are
    empty — a run in either can spawn into the other. Load-bearing for
    isolation: hil_world's patches are process-wide, so a leftover run
    executes against the next test's store (this file's only flake).
    """
    while pending := [
        *_tasks_named(STREAM_PUBLISH_TASK_NAME, QUEUED_EXECUTOR_TASK_NAME),
        *resolution._resume_tasks,
    ]:
        await asyncio.gather(*pending, return_exceptions=True)


@asynccontextmanager
async def hil_world(
    *,
    mode: HILMode,
    tool_overrides: dict[str, bool],
    comms: Sequence[Any] | None = None,
    executor: Sequence[Any] | None = None,
) -> AsyncIterator[HilWorld]:
    """Build a live conversation with HIL configured, held open across a pause.

    Held open on purpose: a resume re-enters the SAME executor graph, on the
    same in-memory checkpoint and scripted model, as a running process would.
    Every dependency patched below is an external service (Mongo, WebSocket,
    ChromaDB, Postgres) — never a step in the flow under test.
    """
    conversation_id = str(uuid4())
    comms_stream_id = str(uuid4())
    approvals = InMemoryApprovals()
    world = HilWorld(
        conversation_id=conversation_id,
        comms_stream_id=comms_stream_id,
        approvals=approvals,
    )

    stored_user = MagicMock()
    stored_user.hil_preferences = HILPreferences(
        mode=mode,
        tool_overrides=tool_overrides,
    ).model_dump()

    async def _set_override(user_id: str, tool_name: str, ask: bool | None) -> None:
        """Persist the override the way Mongo would, not just record it.

        Load-bearing: an always_tool approval writes this mid-turn, and the
        node immediately replays and re-resolves that tool's policy — a
        no-op recorder would leave it gated on the replay.
        """
        world.overrides_set.append((user_id, tool_name, ask))
        overrides = stored_user.hil_preferences["tool_overrides"]
        if ask is None:
            overrides.pop(tool_name, None)
        else:
            overrides[tool_name] = ask

    async def _broadcast(user_id: str, payload: dict[str, Any]) -> None:
        if payload.get("type") == "executor.stream_started":
            world.started_streams.append(str(payload["stream_id"]))
        elif payload.get("type") == WS_EVENT_EXECUTOR_CANCELLED:
            world.cancelled_broadcasts.append(payload)

    async def _deliver(
        _run: Any,
        text: str,
        result_type: str,
        _note: str,
        *,
        tool_data: list[ToolDataEntry] | None,
    ) -> tuple[str, str]:
        world.delivered.append((text, result_type))
        return text, "executor-message-1"

    memory = MagicMock()
    memory.retain_single = AsyncMock(
        return_value=RetainedMemory(
            entry=MemoryEntry(id="mem-hil", content="test memory", category_path="general"),
            outcome=ReconcileOutcome.NEW,
        )
    )
    memory.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))

    patches = [
        patch.object(hil_approval_repository, "create_if_absent", new=approvals.create_if_absent),
        patch.object(hil_approval_repository, "get", new=approvals.get),
        patch.object(hil_approval_repository, "mark_decided", new=approvals.mark_decided),
        patch.object(hil_approval_repository, "update", new=approvals.update),
        patch.object(
            hil_approval_repository, "list_expired_pending", new=approvals.list_expired_pending
        ),
        patch.object(
            hil_approval_repository, "list_decided_unresumed", new=approvals.list_decided_unresumed
        ),
        patch.object(
            hil_approval_repository,
            "list_pending_for_conversation",
            new=approvals.list_pending_for_conversation,
        ),
        patch.object(
            hil_approval_repository,
            "list_parked_subagents_for_conversation",
            new=approvals.list_parked_subagents_for_conversation,
        ),
        patch.object(user_repository, "get", new=AsyncMock(return_value=stored_user)),
        patch.object(user_repository, "set_hil_tool_override", new=_set_override),
        patch("app.services.hil.bridge.notify_approval_pending", new=AsyncMock()),
        patch.object(websocket_manager, "broadcast_to_user", new=_broadcast),
        patch.object(
            build_graph_module, "get_tools_store", AsyncMock(return_value=InMemoryStore())
        ),
        patch.object(build_graph_module, "get_checkpointer_manager", AsyncMock(return_value=None)),
        patch(
            f"{FOLLOW_UP_NODE}.ainvoke_structured",
            new=AsyncMock(return_value=FollowUpActions(actions=[])),
        ),
        patch(
            f"{FOLLOW_UP_NODE}.get_user_integration_capabilities",
            new=AsyncMock(return_value={"tool_names": []}),
        ),
        patch("app.agents.tools.memory_tools.memory_engine", memory),
        patch("app.agents.core.nodes.memory_node.memory_engine", memory),
        patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
        patch.object(
            conversation_repository, "append_message_tool_data", new=AsyncMock(return_value=True)
        ),
        patch("app.agents.core.background.executor_runner.deliver_result", new=_deliver),
        patch(
            "app.services.files.FileService.list_conversation_files",
            new=AsyncMock(return_value=[]),
        ),
    ]

    try:
        async with AsyncExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            comms_graph = await stack.enter_async_context(
                build_graph_module.build_comms_graph(
                    chat_llm=streaming_model(comms or comms_script()), in_memory_checkpointer=True
                )
            )
            executor_graph = await stack.enter_async_context(
                build_graph_module.build_executor_graph(
                    chat_llm=streaming_model(executor or executor_script()),
                    in_memory_checkpointer=True,
                )
            )
            graphs = {"comms_agent": comms_graph, "executor_agent": executor_graph}
            stack.enter_context(
                patch.object(
                    GraphManager,
                    "get_graph",
                    new=AsyncMock(side_effect=lambda name="default_graph": graphs[name]),
                )
            )
            try:
                yield world
            finally:
                # A leaked busy lock survives 30 minutes silently, queuing the
                # next test's executor onto its own stream — freed before the
                # drain so nothing new can be handed it.
                await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
                # Both inside the patch scope deliberately: an escaping run
                # executes against the next test's store/models, and a leaked
                # session keeps that stream's claims alive.
                await drain_background_runs()
                for stream_id in world.stream_ids():
                    teardown_session(stream_id)
    finally:
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")


async def run_turn(world: HilWorld, prompt: str, *, follow_up: bool = False) -> None:
    """Drive one full chat turn through the real orchestrator.

    follow_up opens a second stream for a later turn in the same
    conversation — a real client does exactly that, and the first turn's stream
    is already closed by the time a parked run is cancelled.
    """
    stream_id = str(uuid4()) if follow_up else world.comms_stream_id
    if follow_up:
        world.comms_streams.append(stream_id)
    await stream_manager.start_stream(
        stream_id=stream_id,
        conversation_id=world.conversation_id,
        user_id=str(USER["user_id"]),
    )
    await chat_stream.run_chat_stream_background(
        stream_id=stream_id,
        body=MessageRequestWithHistory(
            message=prompt,
            messages=[{"role": "user", "content": prompt}],
            conversation_id=world.conversation_id,
        ),
        user=USER,
        conversation_id=world.conversation_id,
    )
    await drain_publishes()


def expire(world: HilWorld) -> None:
    """Move the turn's approval past its deadline.

    The window is six hours, so the clock cannot be waited out; the sweep's own
    expires_at predicate is what is under test, not the passage of time.
    """
    record = world.approvals.only_record()
    world.approvals.records[record.approval_id] = record.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)}
    )


async def sweep() -> str:
    """Run the ARQ cron task and wait out whatever it re-dispatched.

    The worker's own entry point, not sweep_approvals directly, so the task
    wrapper's return string is covered too — it is what shows up in worker logs
    as the only record that a sweep did anything.
    """
    counts = await sweep_hil_approvals({})
    await drain_resumes()
    return counts


@pytest.fixture(autouse=True)
def _registry(real_tool_registry: Any) -> None:
    """Real tool categories — every tool_data frame resolves through them."""


@pytest.fixture(autouse=True)
async def fake_redis() -> AsyncIterator[Any]:
    """Create a fresh in-process Redis with real Streams per test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    original = redis_cache.redis
    # fakeredis is structurally compatible but not a nominal subtype of the
    # redis-py async client the attribute is annotated with.
    redis_cache.redis = cast(Any, client)
    yield client
    redis_cache.redis = original
    await client.flushall()
    await client.connection_pool.disconnect()


# ---------------------------------------------------------------------------
# Scenario 4 — always_allow short-circuits the gate
# ---------------------------------------------------------------------------


class TestAlwaysAllowShortCircuits:
    async def test_no_approval_frame_is_published_and_the_tool_runs_inline(self) -> None:
        """The tool carries an explicit always-ask override — only always_allow's mode winning over it can make this pass."""
        async with hil_world(mode="always_allow", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")

            assert await world.approval_cards() == [], (
                "always_allow must publish no approval card at all"
            )
            assert world.approvals.records == {}, (
                "always_allow must not record an approval request either"
            )
            outputs = await world.outputs_for(GATED_CALL_ID)
            assert len(outputs) == 1, f"expected one result frame, got {len(outputs)}"
            assert_real_tool_output(outputs[0])


# ---------------------------------------------------------------------------
# Scenario 1 — the resumed result reaches the stream exactly once
# ---------------------------------------------------------------------------


class TestResumedResultReachesTheStreamOnce:
    async def test_the_turn_parks_with_a_pending_card_and_no_result(self) -> None:
        """Precondition for the exactly-once claim below: an unpaused run would trivially satisfy "one result" too, and that would be a HIL failure."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")

            cards = await world.approval_cards()
            assert [card["status"] for card in cards] == ["pending"], (
                f"the user must see exactly one pending card, got {cards}"
            )
            assert cards[0]["gated_tool_name"] == GATED_TOOL
            assert cards[0]["tool_call_id"] == GATED_CALL_ID, (
                "the card is joined to its tool call by the id the frontend joins on"
            )
            assert await world.outputs_for(GATED_CALL_ID) == [], (
                "nothing may reach the stream as a result before the user decides"
            )
            record = world.approvals.only_record()
            assert record.status == "pending"
            assert record.resume_item is not None, (
                "a pause with no re-dispatch context can never be resumed by any decision"
            )

    async def test_after_approval_the_result_lands_exactly_once_with_real_output(self) -> None:
        """Guards two shipped bugs: a suppressed result (claim taken pre-pause) and a duplicate card (05c14b3b7, 1bdc0e6a7); counted across every stream, not a single first-match lookup."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")
            assert await world.outputs_for(GATED_CALL_ID) == []

            record = await world.decide("approve")

            assert record.status == "approved"
            outputs = await world.outputs_for(GATED_CALL_ID)
            assert len(outputs) == 1, (
                f"the approved action's result must reach the user exactly once, got "
                f"{len(outputs)} across streams {world.stream_ids()}"
            )
            assert_real_tool_output(outputs[0])

            assert await world.tool_output_ids() == ["tc_exec", "tc_retrieve", GATED_CALL_ID], (
                "every result the turn produced must reach the user exactly once, in order: "
                "the delegation ack and the pre-pause retrieval on the comms stream, the "
                f"approved action on the resumed one — got {await world.tool_output_ids()}"
            )

    async def test_the_card_settles_and_the_run_finishes_on_the_resumed_stream(self) -> None:
        """prepare_run_from_item mints a fresh queued_* stream and broadcasts executor.stream_started — the client's only way to find where the turn moved."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")
            await world.decide("approve")

            assert len(world.started_streams) == 1, (
                f"the resume must announce exactly one new stream, got {world.started_streams}"
            )
            assert world.started_streams[0] != world.comms_stream_id, (
                "the resumed run publishes on its own stream, not the closed comms one"
            )
            statuses = [card["status"] for card in await world.approval_cards()]
            assert statuses == ["pending", "approved"], (
                f"the card must settle from pending to approved, got {statuses}"
            )
            assert world.delivered and world.delivered[0][1] == "final", (
                f"the resumed run must finish its turn, got {world.delivered}"
            )

    async def test_approve_and_stop_asking_records_the_preference_and_still_runs_once(
        self,
    ) -> None:
        """The gate writes the always_tool override before handling the call, so a failing tool still leaves the preference set."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")

            await world.decide("approve", scope="always_tool")

            assert world.overrides_set == [(str(USER["user_id"]), GATED_TOOL, False)], (
                "approving with always_tool must clear the tool's ask-override so the "
                f"user is never asked again, got {world.overrides_set}"
            )
            outputs = await world.outputs_for(GATED_CALL_ID)
            assert len(outputs) == 1, f"the action still runs exactly once, got {len(outputs)}"
            assert_real_tool_output(outputs[0])

    async def test_a_denied_action_produces_a_refusal_and_never_the_real_output(self) -> None:
        """A denial produces exactly one frame too — only content, not count, distinguishes a refusal from an approval."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")

            record = await world.decide("deny")

            assert record.status == "denied"
            outputs = await world.outputs_for(GATED_CALL_ID)
            assert len(outputs) == 1, f"expected one frame for the refused call, got {outputs}"
            assert GATED_ARGS["description"] not in outputs[0], (
                f"a denied action must never have produced its real output: {outputs[0][:300]!r}"
            )
            assert "the action was not performed" in outputs[0].lower(), (
                f"the refusal must say the action did not happen, got {outputs[0][:300]!r}"
            )
            statuses = [card["status"] for card in await world.approval_cards()]
            assert statuses == ["pending", "denied"], (
                f"the card must settle from pending to denied, got {statuses}"
            )


# ---------------------------------------------------------------------------
# Scenario 1b — an UNGATED sibling of a gated call, across the pause
# ---------------------------------------------------------------------------

#: Real, and its one outbound HTTP call is the only thing doubled — so the tool's
#: body, its stream frames and its rate-limit accounting are all genuine, and the
#: double is a counter, because "how many times did it happen" is the claim.
SIBLING_TOOL = "get_weather"
SIBLING_ARGS = {"location": "Mumbai,IN"}
SIBLING_CALL_ID = "tc_sibling"


def sibling_executor_script() -> list[Any]:
    """One AI message carrying BOTH calls — the shape a model emits for "check the weather and draw me a flowchart"."""
    return [
        call(
            "retrieve_tools",
            {"exact_tool_names": [SIBLING_TOOL, GATED_TOOL]},
            call_id="tc_retrieve",
        ),
        [
            call(SIBLING_TOOL, SIBLING_ARGS, call_id=SIBLING_CALL_ID),
            call(GATED_TOOL, GATED_ARGS, call_id=GATED_CALL_ID),
        ],
        "Checked the weather and drew the flowchart.",
    ]


@asynccontextmanager
async def sibling_world() -> AsyncIterator[tuple[HilWorld, list[str]]]:
    """Yield a turn whose one AI message carries an ungated call and a gated one, plus the ungated tool's execution log.

    Only get_weather's outbound HTTP call is doubled — the tool's body, its
    stream frames and its rate-limit accounting are all genuine; the double
    is a counter, since "how many times did it happen" is the claim.
    """
    calls: list[str] = []

    async def _weather(location: str) -> dict[str, Any]:
        calls.append(location)
        return {"temperature": "31C", "conditions": "humid"}

    # Patched where used, not defined: weather_tool imports user_weather by
    # value, so patching the source module only takes effect before the
    # tool's first import — works once per session, silently no-ops after.
    with patch("app.agents.tools.weather_tool.user_weather", new=_weather):
        async with hil_world(
            mode="always_ask",
            tool_overrides={GATED_TOOL: True, SIBLING_TOOL: False},
            executor=sibling_executor_script(),
        ) as world:
            yield world, calls


class TestUngatedSiblingAcrossThePause:
    async def test_each_card_still_fills_in_exactly_once(self) -> None:
        """claim_tool_output is per-stream, so the pause splitting this turn across two streams is what keeps the replayed node from doubling a card."""
        async with sibling_world() as (world, _calls):
            await run_turn(world, "check the weather and draw me a flowchart")
            await world.decide("approve")

            ids = await world.tool_output_ids()
            # Sorted, not ordered: the replayed node's two results are written by
            # the same node in one step and their relative order on the wire is
            # not a contract. Their COUNT is.
            assert sorted(ids) == sorted(
                ["tc_exec", "tc_retrieve", SIBLING_CALL_ID, GATED_CALL_ID]
            ), f"each of the turn's results must reach the user exactly once, got {ids}"

    async def test_the_ungated_sibling_body_runs_only_once(self) -> None:
        """Regression: has_pausing_sibling only guarded AUTO mode, so an allow-policy sibling replayed invisibly once durability="exit" discarded LangGraph's own replay protection."""
        async with sibling_world() as (world, calls):
            await run_turn(world, "check the weather and draw me a flowchart")
            assert calls == [SIBLING_ARGS["location"]], (
                f"the ungated sibling runs, once, before the pause, got {calls}"
            )

            await world.decide("approve")

            assert calls == [SIBLING_ARGS["location"]], (
                "the ungated sibling must not run a second time when the approved "
                f"call resumes, got {calls}"
            )


# ---------------------------------------------------------------------------
# Scenario 2 — cancellation while an approval sits parked
# ---------------------------------------------------------------------------


def cancelling_comms_script() -> list[Any]:
    """Two turns on one thread: delegate, then stop it.

    Driven through cancel_executor rather than by calling the service
    directly, because the tool is what a user's "stop that" actually reaches and
    it is the only caller of cancel_conversation_approvals.
    """
    return [
        call("call_executor", {"task": "draw the flowchart"}, call_id="tc_exec"),
        "On it.",
        call("cancel_executor", {"task_ids": []}, call_id="tc_cancel"),
        "Stopped.",
    ]


class TestCancellationWhileParked:
    async def test_the_parked_approval_is_closed_and_can_no_longer_restart_the_run(
        self,
    ) -> None:
        """cancel_executor drops the busy lock but not the approval record, which outlives it — closed without resuming, since no run is left to wake."""
        async with hil_world(
            mode="always_ask",
            tool_overrides={GATED_TOOL: True},
            comms=cancelling_comms_script(),
        ) as world:
            await run_turn(world, "draw me a flowchart")
            assert world.approvals.only_record().status == "pending"

            await run_turn(world, "actually, stop that", follow_up=True)

            record = world.approvals.only_record()
            assert record.status == "abandoned", (
                f"a cancelled run's pending approval must be closed, got {record.status}"
            )
            assert record.feedback == resolution.CANCELLED_FEEDBACK
            assert record.resume_item is None, (
                "the re-dispatch context must be dropped, or the sweep's crashed-resume "
                "pass would bring the cancelled run back"
            )

            # Two different guards refuse it: approve fails on the missing
            # re-dispatch context (checked before the transition), deny fails
            # because the record is no longer pending. Both leave the run dead.
            with pytest.raises(resolution.ApprovalNotResumableError):
                await resolution.resolve_approval(
                    approval_id=record.approval_id,
                    user_id=str(USER["user_id"]),
                    kind="approve",
                )
            with pytest.raises(resolution.ApprovalRequestNotFoundError):
                await resolution.resolve_approval(
                    approval_id=record.approval_id,
                    user_id=str(USER["user_id"]),
                    kind="deny",
                )
            assert world.approvals.only_record().status == "abandoned", (
                "neither late decision may overwrite the cancellation"
            )
            assert world.started_streams == [], (
                f"nothing may restart the cancelled run, got {world.started_streams}"
            )
            assert await world.outputs_for(GATED_CALL_ID) == [], (
                "the cancelled action must never have run"
            )

    async def test_the_user_is_told_and_the_card_never_settles_on_the_stream(self) -> None:
        """Cancel is announced out-of-band via executor.cancelled on the WebSocket — the card's last SSE state stays "pending", never a resolved frame."""
        async with hil_world(
            mode="always_ask",
            tool_overrides={GATED_TOOL: True},
            comms=cancelling_comms_script(),
        ) as world:
            await run_turn(world, "draw me a flowchart")
            await run_turn(world, "actually, stop that", follow_up=True)

            assert [card["status"] for card in await world.approval_cards()] == ["pending"], (
                "no resolved card is published for a cancelled approval — the "
                "executor.cancelled WebSocket event is the only signal"
            )
            assert world.cancelled_broadcasts, (
                "the client must be told an agent-initiated cancel happened, or its "
                "approval card and loading state stay stuck forever"
            )


# ---------------------------------------------------------------------------
# Scenario 3 — the expiry sweep
# ---------------------------------------------------------------------------


class TestApprovalExpiry:
    async def test_a_stale_approval_times_out_and_the_run_is_told_it_expired(self) -> None:
        """expires_at is moved into the past rather than waited out — the window is six hours, and the sweep's predicate, not the clock, is under test."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")
            expire(world)

            counts = await sweep()

            assert counts == "expired=1 redispatched=0", (
                f"the sweep must report the one expiry it performed, got {counts!r}"
            )
            record = world.approvals.only_record()
            assert record.status == "timeout"
            assert record.decided_by is None, "nobody decided this one; the clock did"

            statuses = [card["status"] for card in await world.approval_cards()]
            assert statuses == ["pending", "timeout"], (
                f"the user's card must settle from pending to timeout, got {statuses}"
            )
            outputs = await world.outputs_for(GATED_CALL_ID)
            assert len(outputs) == 1, f"expected one frame for the expired call, got {outputs}"
            assert GATED_ARGS["description"] not in outputs[0], (
                f"an expired action must never have run: {outputs[0][:300]!r}"
            )
            assert "the action was not performed" in outputs[0].lower(), (
                f"the model must be told the action did not happen, got {outputs[0][:300]!r}"
            )
            assert "expired" in outputs[0].lower(), (
                f"and that it expired rather than being refused, got {outputs[0][:300]!r}"
            )

    async def test_an_approval_that_is_not_yet_stale_survives_the_sweep_untouched(self) -> None:
        """Boundary for the test above: expires_at is left alone, so the approval — still inside its six-hour window — must survive the sweep untouched."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")

            counts = await sweep()

            assert counts == "expired=0 redispatched=0", (
                f"a live approval is not the sweep's to touch, got {counts!r}"
            )
            record = world.approvals.only_record()
            assert record.status == "pending", (
                f"the approval must still be waiting on its user, got {record.status}"
            )
            assert record.resume_item is not None, "and must still be resumable"
            assert [card["status"] for card in await world.approval_cards()] == ["pending"], (
                "no resolved card may be published for an approval nobody has answered"
            )

            decided = await world.decide("approve")

            assert decided.status == "approved", "the untouched approval is still answerable"
            assert len(await world.outputs_for(GATED_CALL_ID)) == 1


# D1/D2 — two gated calls in one AI message, decided differently. The tool
# node runs calls sequentially: gate A pauses first, and every decision
# replays the whole node from the top.

GATE_A_TOOL = SIBLING_TOOL
GATE_A_CALL_ID = "tc_gate_a"
GATE_B_TOOL = GATED_TOOL
GATE_B_CALL_ID = "tc_gate_b"


def two_gated_calls_script() -> list[Any]:
    return [
        call(
            "retrieve_tools",
            {"exact_tool_names": [GATE_A_TOOL, GATE_B_TOOL]},
            call_id="tc_retrieve",
        ),
        [
            call(GATE_A_TOOL, SIBLING_ARGS, call_id=GATE_A_CALL_ID),
            call(GATE_B_TOOL, GATED_ARGS, call_id=GATE_B_CALL_ID),
        ],
        "Checked the weather and drew the flowchart.",
    ]


@asynccontextmanager
async def two_gate_world() -> AsyncIterator[tuple[HilWorld, list[str]]]:
    """Build a turn with two gated calls in one AI message, plus gate A's run counter."""
    calls: list[str] = []

    async def _weather(location: str) -> dict[str, Any]:
        calls.append(location)
        return {"temperature": "31C", "conditions": "humid"}

    # Patched where it is USED: ``weather_tool`` binds ``user_weather`` by value
    # at import, so patching the source module no-ops after the first test.
    with patch("app.agents.tools.weather_tool.user_weather", new=_weather):
        async with hil_world(
            mode="always_ask",
            tool_overrides={GATE_A_TOOL: True, GATE_B_TOOL: True},
            executor=two_gated_calls_script(),
        ) as world:
            yield world, calls


class TestTwoGatedCallsInOneTurn:
    """Two destructive actions in one AI message — the case HIL is designed for.

    policy.has_pausing_sibling: several destructive actions in one turn are
    confirmed together. Both reach the gate in one node pass (verified:
    middleware:get_weather then middleware:create_flowchart, two pending
    records).

    Needed two fixes: _dispatch_resume's bare Command(resume=...) is
    rejected once a thread holds more than one pending interrupt, so it now
    targets the interrupt carrying its own approval_id; and LangGraph emits
    one __interrupt__ event per paused task, so both ids must be
    accumulated.
    """

    async def test_both_gated_calls_are_asked_about_together(self) -> None:
        """Asserted separately so the failures below can't be misread as "the batch never formed"."""
        async with two_gate_world() as (world, calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            assert world.approvals.statuses() == {GATE_A_TOOL: "pending", GATE_B_TOOL: "pending"}, (
                f"both gated calls must be put to the user, got {world.approvals.statuses()}"
            )
            assert await world.cards_for(GATE_A_TOOL) == ["pending"]
            assert await world.cards_for(GATE_B_TOOL) == ["pending"]
            assert calls == [], "and neither may run before the user decides"

    async def test_deciding_one_of_them_actually_runs_it(self) -> None:
        """Regression: the runner kept only the last of LangGraph's per-task __interrupt__ events, leaving the other record without a resume_item (ApprovalNotResumableError)."""
        async with two_gate_world() as (world, calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            await world.decide("approve", tool=GATE_A_TOOL)

            assert calls == [SIBLING_ARGS["location"]], (
                f"the approved action runs, exactly once, got {calls}"
            )
            assert await world.cards_for(GATE_B_TOOL) == ["pending"], (
                "and the one still undecided keeps waiting on the user"
            )

    async def test_answering_both_runs_each_exactly_once(self) -> None:
        """Regression: a bare Command(resume=...) was refused by LangGraph while two interrupts were pending, permanently wedging the turn."""
        async with two_gate_world() as (world, calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            await world.decide("approve", tool=GATE_A_TOOL)
            await world.decide("approve", tool=GATE_B_TOOL)

            assert calls == [SIBLING_ARGS["location"]], (
                f"the approved action runs, exactly once, got {calls}"
            )
            assert len(await world.outputs_for(GATE_B_CALL_ID)) == 1, (
                "and so does its sibling, got "
                f"{len(await world.outputs_for(GATE_B_CALL_ID))} results"
            )

    async def test_the_turn_does_not_die_with_an_executor_error(self) -> None:
        """_execute_executor catches the LangGraph exception and returns result_type == "error", which deliver_result sends on as the turn's outcome."""
        async with two_gate_world() as (world, _calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            await world.decide("approve", tool=GATE_A_TOOL)

            errors = [text for text, kind in world.delivered if kind == "error"]
            assert errors == [], (
                "approving one of two batched approvals must not end the turn in an "
                f"executor error instead of performing the action. Delivered: {errors}"
            )

    async def test_the_user_is_never_shown_raw_framework_internals(self) -> None:
        """The leaked text named an interrupt id and linked docs.langchain.com — unlike EXECUTOR_STEP_LIMIT_MESSAGE, which turns a recursion limit into user guidance instead of a traceback."""
        async with two_gate_world() as (world, _calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            await world.decide("approve", tool=GATE_A_TOOL)

            leaked = [
                text
                for text, _kind in world.delivered
                if "docs.langchain.com" in text or "interrupt id" in text
            ]
            assert leaked == [], (
                "raw LangGraph error text must never be delivered to the user, docs "
                f"URL and all, after they approve one of two batched actions: {leaked}"
            )

    async def test_the_second_approval_is_still_answerable_afterwards(self) -> None:
        """Regression: addressing the resume positionally instead of by approval_id raised, ending the run and leaving gate B's card permanently unanswerable."""
        async with two_gate_world() as (world, calls):
            await run_turn(world, "check the weather and draw me a flowchart")
            await world.decide("approve", tool=GATE_A_TOOL)

            assert world.approvals.for_tool(GATE_B_TOOL).status == "pending"

            await world.decide("approve", tool=GATE_B_TOOL)

            assert world.approvals.for_tool(GATE_B_TOOL).status == "approved"
            # ``calls`` counts gate A only, which makes the second half of this
            # assertion the interesting one: answering B replays the node, and A
            # must not run again on the way through.
            assert calls == ["Mumbai,IN"], (
                f"answering the second approval re-ran the first action: {calls}"
            )


# ---------------------------------------------------------------------------
# D3 — "Task completed" for an action that never ran
# ---------------------------------------------------------------------------


def orphan_the_resume(world: HilWorld) -> None:
    """Make the turn's decided approval look like a crashed resume dispatch.

    Exactly the shape list_decided_unresumed hunts for: decided, past the
    grace period, still carrying resume_item, with no resumed_at stamp —
    the sweep's reason for existing.
    """
    record = world.approvals.only_record()
    world.approvals.records[record.approval_id] = record.model_copy(
        update={
            "resumed_at": None,
            "decided_at": datetime.now(UTC)
            - timedelta(seconds=HIL_DECIDED_UNRESUMED_GRACE_SECONDS + 60),
        }
    )


class TestResumeAgainstAThreadWithNoInterrupt:
    """D3: a resume that finds nothing to resume still reports success.

    LangGraph returns the thread's final state when there is no pending
    interrupt — the node body never executes (verified: result:
    {'gated_done': True} | RUNS = []). complete_message == "" then falls
    back to the literal "Task completed" (subagent_runner.py), reporting
    success for a run that did nothing.

    Reached via the sweep's crashed-resume pass, a real production path.
    RED on today's code.
    """

    async def test_a_second_resume_does_not_report_a_completed_task(self) -> None:
        """The first delivery is genuine (asserted first); the second must not falsely report a completed task for a re-dispatch that executed nothing."""
        async with hil_world(mode="always_ask", tool_overrides={GATED_TOOL: True}) as world:
            await run_turn(world, "draw me a flowchart")
            await world.decide("approve")
            assert world.delivered == [("Drew the flowchart.", "final")], (
                f"the approved turn's real answer is delivered once, got {world.delivered}"
            )
            outputs_before = await world.outputs_for(GATED_CALL_ID)
            assert len(outputs_before) == 1

            orphan_the_resume(world)
            counts = await sweep()

            assert counts == "expired=0 redispatched=1", (
                f"the sweep must re-dispatch the crashed resume, got {counts!r}"
            )
            assert len(await world.outputs_for(GATED_CALL_ID)) == 1, (
                "the re-dispatch must not re-run the action, got "
                f"{len(await world.outputs_for(GATED_CALL_ID))} results"
            )
            assert world.delivered == [("Drew the flowchart.", "final")], (
                '"Task completed" must never be delivered for a run that executed '
                "NOTHING. A resume against a thread with no pending interrupt runs no "
                "node, so complete_message is empty, the narration branch is skipped, "
                "and subagent_runner would fall back to the literal 'Task completed' — "
                "telling the user an action succeeded that never happened. Delivered: "
                f"{world.delivered}"
            )


# ---------------------------------------------------------------------------
# Scenario 6 — an ungated call beside TWO gated ones, across TWO resumes
# ---------------------------------------------------------------------------

#: Two gated calls of the SAME tool, so they are told apart by call id, not name.
FIRST_GATE_CALL_ID = "tc_first_gate"
SECOND_GATE_CALL_ID = "tc_second_gate"
FIRST_GATE_ARGS = {"description": "the first approved action", "direction": "LR"}
SECOND_GATE_ARGS = {"description": "the second approved action", "direction": "TB"}


def one_ungated_two_gated_script() -> list[Any]:
    """One AI message: a harmless call and two that need approval."""
    return [
        call(
            "retrieve_tools",
            {"exact_tool_names": [SIBLING_TOOL, GATED_TOOL]},
            call_id="tc_retrieve",
        ),
        [
            call(SIBLING_TOOL, SIBLING_ARGS, call_id=SIBLING_CALL_ID),
            call(GATED_TOOL, FIRST_GATE_ARGS, call_id=FIRST_GATE_CALL_ID),
            call(GATED_TOOL, SECOND_GATE_ARGS, call_id=SECOND_GATE_CALL_ID),
        ],
        "Checked the weather and drew both flowcharts.",
    ]


@asynccontextmanager
async def compound_world() -> AsyncIterator[tuple[HilWorld, list[str]]]:
    """Build a turn needing TWO decisions, with an ungated call running beside them."""
    calls: list[str] = []

    async def _weather(location: str) -> dict[str, Any]:
        calls.append(location)
        return {"temperature": "31C", "conditions": "humid"}

    with patch("app.agents.tools.weather_tool.user_weather", new=_weather):
        async with hil_world(
            mode="always_ask",
            tool_overrides={GATED_TOOL: True, SIBLING_TOOL: False},
            executor=one_ungated_two_gated_script(),
        ) as world:
            yield world, calls


class TestAnUngatedCallAcrossTwoResumes:
    """The compound case, and the strongest test of the checkpoint claim.

    Everything else here pauses once. This turn pauses TWICE — approving the first
    gated call resumes the run, which immediately parks again on the second — so
    the ungated call has to survive two separate resumes. One surviving resume
    could be luck in how a single checkpoint happened to land; two cannot.

    It is also the shape that regressed silently before: the sibling's second and
    third executions were invisible, because only the last replayed ToolMessage
    ever reached the stream.
    """

    async def test_the_ungated_call_runs_once_and_never_again(self) -> None:
        async with compound_world() as (world, calls):
            await run_turn(world, "check the weather and draw both flowcharts")
            assert calls == [SIBLING_ARGS["location"]], (
                f"it runs while the approvals wait, got {calls}"
            )

            await world.decide("approve", call_id=FIRST_GATE_CALL_ID)
            assert calls == [SIBLING_ARGS["location"]], (
                f"the first resume must not repeat it, got {calls}"
            )

            await world.decide("approve", call_id=SECOND_GATE_CALL_ID)
            assert calls == [SIBLING_ARGS["location"]], f"and neither must the second, got {calls}"

    async def test_each_approved_action_happens_exactly_once(self) -> None:
        # The positive control for the test above: "never again" would also pass on
        # a turn that fell over and did nothing at all.
        async with compound_world() as (world, _calls):
            await run_turn(world, "check the weather and draw both flowcharts")
            await world.decide("approve", call_id=FIRST_GATE_CALL_ID)
            await world.decide("approve", call_id=SECOND_GATE_CALL_ID)

            for call_id, args in (
                (FIRST_GATE_CALL_ID, FIRST_GATE_ARGS),
                (SECOND_GATE_CALL_ID, SECOND_GATE_ARGS),
            ):
                outputs = await world.outputs_for(call_id)
                assert len(outputs) == 1, (
                    f"{call_id} must produce exactly one result, got {len(outputs)}"
                )
                assert args["description"] in outputs[0], (
                    "and it must be that call's OWN output — two calls of the same tool "
                    f"must not be joined to each other's result, got {outputs[0][:200]!r}"
                )

    async def test_every_card_settles_exactly_once(self) -> None:
        async with compound_world() as (world, _calls):
            await run_turn(world, "check the weather and draw both flowcharts")
            await world.decide("approve", call_id=FIRST_GATE_CALL_ID)
            await world.decide("approve", call_id=SECOND_GATE_CALL_ID)

            cards = await world.approval_cards()
            settled = [c["status"] for c in cards if c["status"] != "pending"]
            assert settled == ["approved", "approved"], (
                f"one settle per approval, no more and no fewer, got {settled}"
            )

    async def test_approving_one_and_denying_the_other_applies_both(self) -> None:
        """Mixed decisions in one turn. Neither may leak onto the other."""
        async with compound_world() as (world, calls):
            await run_turn(world, "check the weather and draw both flowcharts")

            await world.decide("approve", call_id=FIRST_GATE_CALL_ID)
            await world.decide("deny", call_id=SECOND_GATE_CALL_ID)

            approved = await world.outputs_for(FIRST_GATE_CALL_ID)
            denied = await world.outputs_for(SECOND_GATE_CALL_ID)
            assert len(approved) == 1 and FIRST_GATE_ARGS["description"] in approved[0], (
                f"the approved call runs and returns its real output, got {approved}"
            )
            assert len(denied) == 1, f"the denied call still answers the model, got {denied}"
            assert SECOND_GATE_ARGS["description"] not in denied[0], (
                f"but it must NOT carry the tool's real output, got {denied[0][:200]!r}"
            )
            assert "the action was not performed" in denied[0].lower(), (
                f"and it must say the action did not happen, got {denied[0][:200]!r}"
            )
            assert calls == [SIBLING_ARGS["location"]], (
                f"the ungated call is unaffected by either decision, got {calls}"
            )

    async def test_a_denial_first_still_leaves_the_other_answerable(self) -> None:
        # Order matters: the denial resumes the run too, and a resume that consumed
        # the wrong pause would strand the remaining approval.
        async with compound_world() as (world, _calls):
            await run_turn(world, "check the weather and draw both flowcharts")

            await world.decide("deny", call_id=FIRST_GATE_CALL_ID)
            await world.decide("approve", call_id=SECOND_GATE_CALL_ID)

            outputs = await world.outputs_for(SECOND_GATE_CALL_ID)
            assert len(outputs) == 1 and SECOND_GATE_ARGS["description"] in outputs[0], (
                f"the approval that landed second must still be applied, got {outputs}"
            )

    async def test_both_approvals_are_registered_for_re_dispatch(self) -> None:
        """Regression: keeping only one of LangGraph's per-task __interrupt__ events left the other approval with no resume_item (ApprovalNotResumableError)."""
        async with compound_world() as (world, _calls):
            await run_turn(world, "check the weather and draw both flowcharts")

            for call_id in (FIRST_GATE_CALL_ID, SECOND_GATE_CALL_ID):
                record = world.approvals.for_call(call_id)
                assert record.resume_item, (
                    f"{call_id} parked without re-dispatch context, so its decision "
                    "could never be applied"
                )
