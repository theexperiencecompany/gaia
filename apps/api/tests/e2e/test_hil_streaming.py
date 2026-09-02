"""What the USER SEES across a HIL pause — the frames, not the semantics.

``tests/e2e/test_hil_barrier_e2e.py`` and ``test_hil_spawn_e2e.py`` already
prove the approval *semantics*: did the action run, did it run once, whose
decision applied. Neither of them opens a stream. ``stream_id`` appears there
only as a config value threaded through, and no ``subscribe_stream``, no
``Transcript``, no ``tool_output`` assertion exists in either file. So the half
of HIL the user actually experiences — a card that appears, a pause, and then a
result that has to land somewhere they are watching — was untested.

What is asserted here:

* **the resumed result reaches the stream exactly once, carrying real output.**
  ``claim_tool_output`` (``background/session.py``) claims each ``tool_call_id``
  once per stream, and a resume replays the node. Two producers emitting the same
  result renders the card twice; a claim that outlives the pause suppresses the
  only copy and the card never fills in. Asserted on a LIST of ids, never through
  ``Transcript.result_for`` — that returns the first match and discards the rest,
  which is structurally blind to duplication.
* **cancellation while parked.** A pending approval that outlives its cancelled
  run is a prompt nobody can answer, and worse, one that can restart the run the
  user stopped.
* **expiry.** The sweep resolves a stale approval; the user must see the card
  settle and the model must be told the action did not happen. And the boundary:
  a not-yet-stale approval survives the same sweep untouched.
* **``always_allow`` short-circuits the gate.** No approval frame is published and
  the tool runs inline. Both halves are asserted — "it ran" alone cannot tell a
  short-circuit from a gate that paused and was auto-approved.
* **a turn that pauses more than once.** Several gated calls in one AI message,
  with an ungated one running beside them: every approval has to stay answerable,
  each action has to happen exactly once, and the ungated call has to survive
  BOTH resumes. Mixed approve/deny is covered in either order, because a resume
  that consumed the wrong pause strands whatever is left.

The framework contract underneath all of this — that LangGraph keeps the writes of
tasks which completed in an interrupting step, and what we do that can throw them
away — is pinned separately in ``tests/unit/agents/test_pause_checkpointing.py``.

Everything between the comms model and Redis is production code — the real chat
stream, the real ``call_executor``, the real background runner, the real gate, the
real ``resolution`` layer. The doubles are listed on :func:`hil_world`, and each
one is an external service (Mongo, the notifier, the narration LLM), never a step
in the flow under test.
"""

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

#: The gated tool. Pure and real: its body runs for real and returns real mermaid
#: source, so "the result reached the stream" can be asserted on the CONTENT
#: rather than on "a string arrived" — a denial, a gate error and a missing
#: ``user_id`` all produce perfectly joinable strings.
GATED_TOOL = "create_flowchart"
GATED_ARGS = {"description": "how an approved action reaches the user", "direction": "LR"}
#: Emitted by the executor's model, so it is the id the card and the result are
#: joined by, and the id ``claim_tool_output`` claims.
GATED_CALL_ID = "tc_gated"


def executor_script() -> list[Any]:
    """retrieve the gated tool, call it, then answer.

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
    """The frame carries what the tool's own body produced, not a stand-in.

    ``create_flowchart`` interpolates both of its arguments into what it returns,
    so a result containing them can only have come from the tool running. Every
    way this flow goes wrong instead produces a perfectly joinable string that a
    truthiness or ``is not None`` check would accept: a HIL denial
    (``DENIED_TEMPLATE``), a gate failure (``GATE_ERROR_TEMPLATE``), an unbound
    tool's correction, and a missing ``user_id``.
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
    """The ``hil_approvals`` collection, in a dict.

    Mongo is the only reason these scenarios would otherwise need live infra, and
    the record store is not what is under test here — the frames are. Every method
    below mirrors the real repository's contract exactly, including the two that
    carry a guarantee: ``create_if_absent`` is a no-op on a duplicate id (a resume
    replay must not re-publish the card) and ``mark_decided`` transitions only from
    ``pending`` (a racing decision must lose). Those same two guarantees are proven
    against real Mongo in ``tests/contracts`` and ``tests/unit/services/hil``.
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
        """The single approval for ``tool_name``; fails loud on zero or several."""
        matches = [r for r in self.records.values() if r.tool_name == tool_name]
        assert len(matches) == 1, (
            f"expected exactly one approval for {tool_name!r}, got "
            f"{[(r.tool_name, r.status) for r in self.records.values()]}"
        )
        return matches[0]

    def for_call(self, tool_call_id: str) -> HILApprovalRecord:
        """The approval for one specific call — the only way to tell apart two
        gated calls of the SAME tool in one turn, which ``for_tool`` cannot."""
        matches = [r for r in self.records.values() if r.tool_call_id == tool_call_id]
        assert len(matches) == 1, (
            f"expected exactly one approval for call {tool_call_id!r}, got "
            f"{[(r.tool_call_id, r.tool_name, r.status) for r in self.records.values()]}"
        )
        return matches[0]

    def statuses(self) -> dict[str, str]:
        """tool name -> recorded status, for asserting a whole batch at once."""
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
        (``prepare_run_from_item``), and the client follows it via the
        ``executor.stream_started`` event. Asserting on one stream alone would
        read a duplicate as an absence, or an absence as a duplicate.
        """
        await drain_publishes()
        collected: list[Frame] = []
        for stream_id in self.stream_ids():
            chunks = [chunk async for chunk in stream_manager.subscribe_stream(stream_id)]
            collected.extend(Transcript.from_sse("".join(chunks)).frames())
        return collected

    async def approval_cards(self) -> list[dict[str, Any]]:
        """Every ``approval_request`` card the user was shown, in order."""
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

        The production entry point every decision source funnels through — the
        approve/deny buttons, a bot's interactive component, the conversational
        resolver — so this is the same code path a click takes.

        ``tool`` selects which approval when a turn gated several calls, and
        ``call_id`` when two of them are the same tool; without either, the turn
        must have exactly one.
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
        """The card statuses the user saw for one gated tool, in order."""
        return [
            card["status"]
            for card in await self.approval_cards()
            if card["gated_tool_name"] == gated_tool_name
        ]

    def overrides_for(self, tool_name: str) -> list[bool | None]:
        """Every preference write-back for one tool — ``[]`` when untouched."""
        return [ask for _user, tool, ask in self.overrides_set if tool == tool_name]

    async def tool_output_ids(self) -> list[str]:
        """Every ``tool_output`` frame's id, in order and WITH repeats.

        A list, not a set and not a lookup: the frontend renders one card per
        id, so a second frame for an id it has already filled in is a duplicate
        card. ``Transcript.result_for`` cannot express this — it returns the
        first match and discards the rest.
        """
        return [
            str(frame.data["tool_call_id"])
            for frame in await self.frames()
            if frame.kind == "tool_output"
        ]

    async def outputs_for(self, tool_call_id: str) -> list[str]:
        """Every ``tool_output`` carrying this id — a LIST, so duplicates show up.

        ``Transcript.result_for`` returns the first match and discards the rest,
        which cannot express "exactly once"; that blindness is how the last
        duplicate-card bug hid.
        """
        return [
            frame.data["output"]
            for frame in await self.frames()
            if frame.kind == "tool_output" and frame.data.get("tool_call_id") == tool_call_id
        ]


def _tasks_named(*names: str) -> list[asyncio.Task[object]]:
    """Live background tasks carrying any of ``names``.

    Filtering by name rather than draining the whole keep-alive set: that set
    also holds work which outlives a single turn, so awaiting all of it would
    hang here forever instead of failing a test.
    """
    wanted = set(names)
    return [t for t in background_tasks._background_tasks if t.get_name() in wanted]


async def drain_publishes() -> None:
    """Wait out the fire-and-forget XADDs the background writer scheduled.

    ``make_redis_stream_writer`` is a *sync* callable that schedules each publish
    through ``spawn_background_task``. A test reading the log after the turn must
    wait, or it reads a truncated stream and asserts about timing instead of
    behaviour. Draining the canonical keep-alive set is a superset of the
    publishes, which is what "wait until the turn is quiet" wants.
    """
    while pending := _tasks_named(STREAM_PUBLISH_TASK_NAME):
        await asyncio.gather(*pending, return_exceptions=True)


async def drain_resumes() -> None:
    """Wait out the executor runs ``resolve_approval`` dispatched.

    ``_dispatch_resume`` spawns the resumed run with ``asyncio.create_task`` and
    returns immediately — the decision endpoint does not wait for the action. A
    test that does not wait here reads the stream before the approved tool has
    run and would assert zero results as "exactly zero duplicates".
    """
    while resolution._resume_tasks:
        await asyncio.gather(*list(resolution._resume_tasks), return_exceptions=True)
    await drain_publishes()


async def drain_background_runs() -> None:
    """Wait out every executor task still in flight, whatever spawned it.

    Two module-level keep-alive sets — the canonical ``spawn_background_task``
    set (publishes and queued executor runs) and HIL's own resume set — and a run
    in either can spawn into the other: a resume finalizes, hands the busy lock to
    a queued task, and that task's own finalize can queue a collection turn.
    Draining one set once is therefore not enough — this loops until both empty.

    Load-bearing for isolation, not tidiness. The patches installed by
    :func:`hil_world` are process-wide while they are active, so a run that
    outlives its own test executes against the NEXT test's approval store and
    scripted models. That showed up as this file's only flake: the following
    test's turn produced no approval record at all.
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
    """A live conversation with HIL configured, held open across a pause.

    Held open on purpose: a resume re-enters the SAME executor graph, on the same
    in-memory checkpoint and the same scripted model, exactly as a running process
    would. Building a second graph would resume a thread that does not exist.

    The doubles, and why none of them is a step in the flow under test:

    * ``hil_approval_repository`` — Mongo. Replaced by :class:`InMemoryApprovals`,
      which keeps the two contracts the flow depends on (create-once,
      decide-once).
    * ``user_repository`` — Mongo. Supplies the HIL preferences the policy reads,
      and records the ``always_tool`` override write-back.
    * ``notify_approval_pending`` — WebSocket push + Expo. Fire-and-forget beside
      the card, never part of it.
    * ``get_tools_store`` / ``get_checkpointer_manager`` — ChromaDB and Postgres.
      Binding by ``exact_tool_names`` never searches the store, so the retrieval
      hop stays real.
    * ``save_conversation_async`` / ``append_message_tool_data`` /
      ``deliver_result`` / ``list_conversation_files`` — Mongo writes and the
      executor's separate narration LLM, all downstream of the stream.
    * the memory engine and the follow-up generator — the comms graph's two
      external end-graph edges.
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

        Load-bearing, not convenience: an ``always_tool`` approval writes this
        mid-turn, and the very next thing that happens is the node REPLAYING and
        re-resolving that same tool's policy. A recorder that threw the write
        away would leave the tool still gated on the replay and quietly hide
        every consequence of it becoming un-gated.
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
                # A leaked busy lock survives 30 minutes and does not error — it
                # queues the NEXT test's executor onto its own stream id, and the
                # test then asserts an empty stream and passes for the wrong
                # reason. Freed before the drain so nothing new can be handed it.
                await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
                # Both INSIDE the patch scope, deliberately: a run that escapes
                # this block executes against the next test's approval store and
                # scripted models, and a session left in the process-wide
                # registry keeps that stream's claims alive.
                await drain_background_runs()
                for stream_id in world.stream_ids():
                    teardown_session(stream_id)
    finally:
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")


async def run_turn(world: HilWorld, prompt: str, *, follow_up: bool = False) -> None:
    """Drive one full chat turn through the real orchestrator.

    ``follow_up`` opens a second stream for a later turn in the same
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
    ``expires_at`` predicate is what is under test, not the passage of time.
    """
    record = world.approvals.only_record()
    world.approvals.records[record.approval_id] = record.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)}
    )


async def sweep() -> str:
    """Run the ARQ cron task and wait out whatever it re-dispatched.

    The worker's own entry point, not ``sweep_approvals`` directly, so the task
    wrapper's return string is covered too — it is what shows up in worker logs
    as the only record that a sweep did anything.
    """
    counts = await sweep_hil_approvals({})
    await drain_resumes()
    return counts


@pytest.fixture(autouse=True)
def _registry(real_tool_registry: Any) -> None:
    """Real tool categories — every ``tool_data`` frame resolves through them."""


@pytest.fixture(autouse=True)
async def fake_redis() -> AsyncIterator[Any]:
    """A fresh in-process Redis with real Streams per test."""
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
        """Both halves, because "it ran" alone cannot tell the two apart.

        A gate that paused and was auto-approved also ends with the tool having
        run — and would have published a card and a record on the way. The claim
        is that ``always_allow`` returns before any of that happens, so the
        absence of the card and the absence of the record are the assertion, and
        the real output is what proves the tool was not merely skipped.

        The tool carries an explicit ``always ask`` override, so the only thing
        that can make this pass is the mode itself winning over it.

        Its A/B partner is
        ``TestResumedResultReachesTheStreamOnce.test_the_turn_parks_with_a_pending_card_and_no_result``:
        same tool, same override, same harness, one word different in the
        preferences — and there a card IS published and a record IS written. The
        pair is what makes an absence here evidence rather than a blind spot.
        """
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
        """Before the decision: the user sees the ask, and nothing has run.

        The precondition for the exactly-once claim below, asserted separately
        because a run that never paused at all would satisfy "exactly one result"
        trivially — and would be a HIL failure, not a success.
        """
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
        """The claim: approve it, and the card fills in — once, with real content.

        Two failure modes this is pointed at, and both have shipped before:

        * **suppressed.** ``claim_tool_output`` claims a ``tool_call_id`` once per
          stream and a resume REPLAYS the node. If the resumed run reused the
          pre-pause stream, the claim taken before the pause would swallow the
          resumed result — the user approves an action, it executes, and the card
          never populates.
        * **doubled.** Two producers (the comms driver in ``agent_helpers`` and the
          executor's own driver in ``subagent_runner``) both see the same
          ToolMessage, and the card renders twice (05c14b3b7, 1bdc0e6a7).

        Counted over EVERY stream of the conversation and as a list, not a lookup:
        the resume publishes on a fresh stream id, so a single-stream assertion
        would read the move as an absence, and ``Transcript.result_for`` returns
        the first match and discards the rest.
        """
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
        """A resume moves the turn to a NEW stream, and the user must be told.

        ``prepare_run_from_item`` mints a fresh ``queued_*`` stream and broadcasts
        ``executor.stream_started`` — that event is the client's only way to find
        where the rest of the turn is happening. Without it the approved action
        runs into a stream nobody is watching.
        """
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
        """ "Approve, and don't ask again" is two promises, and both are on this path.

        The gate writes the ``always_tool`` override BEFORE handing the call to
        the handler, so a tool that then fails still leaves the preference set —
        the user said "stop asking about this", not "stop asking if it works".
        The action itself must still happen exactly once on this turn.
        """
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
        """The mirror image, so "exactly one result" cannot pass by accident.

        A denial still ends with exactly one frame carrying that ``tool_call_id`` —
        the gate's refusal ToolMessage — so counting alone cannot distinguish it
        from an approval. Only the CONTENT can, which is why the approval test
        asserts on the tool's own output rather than on arity.
        """
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
    """One AI message carrying BOTH calls — the shape a model emits for
    "check the weather and draw me a flowchart"."""
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
    """A turn whose one AI message carries an ungated call and a gated one.

    Yields the world and the ungated tool's execution log — the outbound HTTP
    call inside ``get_weather`` is the only thing doubled, so the tool's body,
    its stream frames and its rate-limit accounting are all genuine, and the
    double is a counter because "how many times did it happen" is the claim.
    """
    calls: list[str] = []

    async def _weather(location: str) -> dict[str, Any]:
        calls.append(location)
        return {"temperature": "31C", "conditions": "humid"}

    # Patched where it is USED, not where it is defined: ``weather_tool`` does
    # ``from app.utils.weather_utils import user_weather``, which binds by value,
    # so patching the source module only takes effect for a process that has not
    # imported the tool yet — it works in the first test of a session and
    # silently no-ops in every one after it.
    with patch("app.agents.tools.weather_tool.user_weather", new=_weather):
        async with hil_world(
            mode="always_ask",
            tool_overrides={GATED_TOOL: True, SIBLING_TOOL: False},
            executor=sibling_executor_script(),
        ) as world:
            yield world, calls


class TestUngatedSiblingAcrossThePause:
    async def test_each_card_still_fills_in_exactly_once(self) -> None:
        """The user-facing half: a replayed node must not double any card.

        The pause splits this turn across two streams and replays the node that
        produced both calls, which is the exact shape that would render a card
        twice. ``claim_tool_output`` is per-stream, so the split is what makes it
        safe — and what makes a regression here invisible to a single-stream
        assertion.
        """
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
        """An ungated sibling of a gated call must not execute twice.

        Was a defect. Each tool call is its own node task (``create_agent`` fans
        them out with ``Send``), and when one of them interrupts, LangGraph
        discards the whole step's writes and replays every task — so a sibling
        that already completed ran a second time. ``policy.has_pausing_sibling``
        exists for exactly this ("verified: one send became two") but guarded
        only AUTO mode; a call whose policy is ``allow`` never reached it.

        Confirmed on this harness before the fix: the tool's body was entered
        twice while the stream showed its card exactly once (the pre-pause
        ToolMessage never reaches the wire, the replayed one does) — so the
        second execution was INVISIBLE, the worst shape a double-execution can
        take. Blast radius was bounded to tools HIL classified as
        non-destructive, but not empty: a second API round trip and a second
        decrement of the user's rate-limit quota, every time.

        LangGraph already prevents this on its own: each tool call is its own node
        task, and the writes of the tasks that COMPLETED in an interrupting step are
        persisted, so they are not re-run on resume. We were throwing that checkpoint
        away — ``durability="exit"`` makes the run-exit save the only write there is,
        and the runner used to abandon the stream the instant it saw the pause.

        Asserted in two halves on purpose. The first pins that the sibling DID run,
        so this cannot pass by the work never happening at all; the second that the
        resume did not repeat it.
        """
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

    Driven through ``cancel_executor`` rather than by calling the service
    directly, because the tool is what a user's "stop that" actually reaches and
    it is the only caller of ``cancel_conversation_approvals``.
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
        """A cancel has to reach the approval, not just the run.

        ``cancel_executor`` stops the task and drops the busy lock, but the
        approval record is *decision* state and outlives both. Left pending, a
        later "Approve" — or the timeout sweep, with no user involved at all —
        re-dispatches the very run the user stopped, on a fresh stream the cancel
        flag does not cover. Closing the record is what makes the cancel stick.

        Deliberately closed WITHOUT resuming: there is no run left to wake, which
        is the whole difference from an abandonment.
        """
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

            # Two different guards refuse it, in this order, and the pair is what
            # proves the record is genuinely closed: the approve is stopped by the
            # missing re-dispatch context (checked BEFORE the transition, so a
            # decision that cannot be acted on never reports success), and the
            # deny gets as far as the transition and loses it, because the record
            # is no longer pending. Both leave the run dead.
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
        """What the user actually sees — and the one thing they do not.

        The cancel is announced out of band (``executor.cancelled`` over the
        WebSocket, which is how a client learns of a cancel it did not initiate
        and clears its in-flight cards). No resolved ``approval_request`` frame is
        ever published: ``cancel_conversation_approvals`` writes the record and
        stops, because the stream that carried the card is already closed and the
        run that would have published to a new one is gone. So the card's last
        SSE state stays ``pending`` and only the WebSocket event finalizes it.
        """
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
        """The sweep must resolve the record AND wake the run it stranded.

        A pending approval nobody answers holds its conversation's executor lock
        and hijacks every later message via the conversational resolver. The sweep
        resolves it as a timeout, which re-dispatches the paused thread so the
        model learns the request expired and can wrap up.

        ``expires_at`` is moved into the past rather than waited out — the window
        is six hours, and the sweep's own predicate is what is under test, not the
        clock.
        """
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
        """The boundary, without which the test above passes on a sweep that
        expires everything it can find.

        Same turn, same sweep, one difference: ``expires_at`` is left alone. The
        approval must still be answerable afterwards — the user has six hours, and
        a sweep that takes their prompt away early is worse than one that never
        runs.
        """
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


# ---------------------------------------------------------------------------
# D1 / D2 — two gated calls in ONE AI message, decided differently
# ---------------------------------------------------------------------------
#
# The shape both defects live in, and an ordinary one: "check the weather and
# draw me a flowchart" with HIL on for both. The tool node runs a message's
# calls in a sequential loop, so gate A pauses first and gate B is only reached
# once A is decided — and every decision replays the WHOLE node from the top.
#
# Both tools are real. ``get_weather``'s single outbound HTTP call is doubled
# with a counter because "how many times did it happen" is the claim;
# ``create_flowchart`` is pure and interpolates its arguments into its result,
# so "did it run" can be read off the stream.

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
    """A turn with two gated calls in one AI message, plus gate A's run counter."""
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

    ``policy.has_pausing_sibling`` states the intent outright: "several
    destructive actions in one turn are confirmed together, which is the
    behaviour worth having anyway." The gate delivers exactly that — both calls
    are asked about at once, and empirically both reach the gate in a single node
    pass (verified by instrumenting ``decide_tool_call``: one turn produces
    ``middleware:get_weather`` then ``middleware:create_flowchart``, and two
    ``pending`` records).

    Answering them took two fixes. ``resolution._dispatch_resume`` sends a bare
    ``Command(resume={...})``, which LangGraph rejects once a thread holds more
    than one pending interrupt — ``subagent_runner._address_resume`` now aims it
    at the interrupt carrying its own ``approval_id``. And the pause reports one
    ``__interrupt__`` event PER paused task, so both ids have to be accumulated;
    keeping only one left the other record without ``resume_item``, permanently
    un-decidable.
    """

    async def test_both_gated_calls_are_asked_about_together(self) -> None:
        """The precondition, and the one part that works.

        Asserted on its own so the failures below cannot be misread as "the batch
        never formed". It also pins the intended behaviour, so a fix that stops
        batching (asking about one call and silently refusing the other) is a
        visible change rather than a silent one.
        """
        async with two_gate_world() as (world, calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            assert world.approvals.statuses() == {GATE_A_TOOL: "pending", GATE_B_TOOL: "pending"}, (
                f"both gated calls must be put to the user, got {world.approvals.statuses()}"
            )
            assert await world.cards_for(GATE_A_TOOL) == ["pending"]
            assert await world.cards_for(GATE_B_TOOL) == ["pending"]
            assert calls == [], "and neither may run before the user decides"

    async def test_deciding_one_of_them_actually_runs_it(self) -> None:
        """Approving one of two batched actions performs that one, straight away.

        The user answered; making them wait on an unrelated second approval before
        anything happens would be its own bug. It works only because BOTH approvals
        got re-dispatch context: LangGraph emits one ``__interrupt__`` event PER
        paused task, and the runner used to keep only the last one it saw — leaving
        the other record with no ``resume_item``, so deciding it raised
        ApprovalNotResumableError and that decision could never be applied.
        """
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
        """The turn goes ahead once every approval in it has an answer.

        The other half of the test above, and the one that stops "runs nothing yet"
        from passing by the turn being permanently wedged — which is what a bare
        ``Command(resume=...)`` used to cause, LangGraph refusing the dispatch
        outright while two interrupts were pending.
        """
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
        """The failed resume must not reach the user as an error result.

        ``_execute_executor`` catches the LangGraph exception and returns
        ``result_type == "error"``, which ``deliver_result`` then sends on as the
        turn's outcome. Separated from the assertion above because they are
        different failures: one is work not happening, this one is the user being
        told the assistant broke.
        """
        async with two_gate_world() as (world, _calls):
            await run_turn(world, "check the weather and draw me a flowchart")

            await world.decide("approve", tool=GATE_A_TOOL)

            errors = [text for text, kind in world.delivered if kind == "error"]
            assert errors == [], (
                "approving one of two batched approvals must not end the turn in an "
                f"executor error instead of performing the action. Delivered: {errors}"
            )

    async def test_the_user_is_never_shown_raw_framework_internals(self) -> None:
        """No LangGraph error text may reach the user verbatim.

        The text this used to leak named ``interrupt id``, tells the reader to "specify" one, and links to
        docs.langchain.com — an instruction aimed at whoever wrote the graph, not
        at somebody who just pressed Approve. Every other executor failure path is
        careful about this (``EXECUTOR_STEP_LIMIT_MESSAGE`` exists precisely so a
        recursion limit reaches the user as guidance rather than a traceback);
        this one is not.
        """
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
        """Answering one of the two must not cost the user the other.

        It stays ``pending`` — the user has not decided it — and that is only
        correct if it is still ANSWERABLE. Asserted by actually answering it and
        watching its action run, because "still pending" is exactly what a
        stranded card looks like too: while the resume was addressed positionally
        this decision raised, ended the run, and left a card nothing could ever
        action.
        """
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

    Exactly the shape ``list_decided_unresumed`` hunts for: decided, older than
    the grace period, still carrying its ``resume_item``, and with no
    ``resumed_at`` stamp. In production that record is written by a process that
    died between the decided-transition and the run spawn — and it is the sweep's
    whole reason for existing, so re-dispatching it is the intended behaviour,
    not an abuse of the harness.
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

    LangGraph returns the thread's final state for a resume against a thread with
    no pending interrupt — the node body never executes (verified directly:
    ``result: {'gated_done': True} | RUNS = []``). In GAIA that empty run leaves
    ``complete_message == ""``, the narration-only branch needs a truthy message
    so it is skipped, and ``final_message = complete_message or "Task completed"``
    (subagent_runner.py) hands back a success string for a run that did nothing.

    Reached here through the sweep's crashed-resume pass, which is a real
    production path; a busy-lock lapse or a lost checkpoint gets there too.

    RED on today's code.
    """

    async def test_a_second_resume_does_not_report_a_completed_task(self) -> None:
        """The user must not be told the work is done twice, once falsely.

        The first delivery is the genuine one and is asserted, so this cannot
        pass by the turn never having worked. The second is the defect: a
        re-dispatch that executed nothing, delivered as a completed task.
        """
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
    """A turn needing TWO decisions, with an ungated call running beside them."""
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
        """Every paused call must carry the context to restart its run.

        The defect this pins: LangGraph reports one ``__interrupt__`` event PER
        paused task, and the runner used to keep only one. The approval left out
        got no ``resume_item``, so deciding it raised ApprovalNotResumableError — the
        user presses Approve and nothing can ever happen. Asserted on the records
        directly, because through the UI it looks like a silent no-op.
        """
        async with compound_world() as (world, _calls):
            await run_turn(world, "check the weather and draw both flowcharts")

            for call_id in (FIRST_GATE_CALL_ID, SECOND_GATE_CALL_ID):
                record = world.approvals.for_call(call_id)
                assert record.resume_item, (
                    f"{call_id} parked without re-dispatch context, so its decision "
                    "could never be applied"
                )
