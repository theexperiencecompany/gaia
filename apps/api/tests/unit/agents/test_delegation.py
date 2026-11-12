"""The delegation runner: one lifecycle for every subagent the executor delegates to.

Redis is real (fakeredis) so the thread claim, the dispatch claim and the inbox are
the real mechanisms; the subagent graph run itself (execute_subagent_stream) and the
client edges (stream start, websocket, message persistence) are the doubled seams.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphInterrupt
import pytest

from app.agents.core.background import executor_queue
from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.subagents import delegation
from app.agents.core.subagents.delegation import (
    SUBAGENT_STREAM_ID_PREFIX,
    Delegation,
    SubagentDisplay,
    delegate,
    runs_in_background,
)
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext, SubagentOutcome
from app.agents.prompts import delegation_prompts
from app.agents.prompts.delegation_prompts import (
    BACKGROUND_DELEGATION_ACK,
    SUBAGENT_FAILED_RESULT,
    SUBAGENT_RESULT_ENTRY,
    THREAD_BUSY_REFUSAL,
)
from app.constants.agents import AgentTag
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable, RunningSubagent
from app.models.chat_models import MessageModel, ToolDataEntry
from app.utils import background_tasks
from app.utils.agent_utils import IntegrationMetadata
from shared.py.wide_events import log
from tests.helpers import WideEventRecorder, captured_wide_event

pytestmark = pytest.mark.unit

MODULE = "app.agents.core.subagents.delegation"
FOLDED = "app.agents.core.background.folded_stream"
FOLDED_CARDS = "app.services.folded_cards"


class _OwnStream:
    """Equal to any id of a background run's own stream: the one its frames were collected on."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, str) and other.startswith(SUBAGENT_STREAM_ID_PREFIX)

    def __hash__(self) -> int:
        return hash(SUBAGENT_STREAM_ID_PREFIX)


CONVERSATION = "conv-d"
THREAD = f"spawn_{CONVERSATION}_call-1"

LIVE: AgentConfigurable = {
    "user_id": "u1",
    "conversation_id": CONVERSATION,
    "stream_id": "parent-stream",
    "execution_mode": "interactive",
    "bot_message_id": "bot-msg-1",
}


def _delegation(parent: AgentConfigurable | None = None, **ctx_overrides: Any) -> Delegation:
    parent = dict(parent if parent is not None else LIVE)
    configurable = {**parent, "thread_id": THREAD, **ctx_overrides}
    return Delegation(
        ctx=SubagentExecutionContext(
            subagent_graph=MagicMock(),
            agent_name="spawned_subagent",
            config={"configurable": dict(configurable)},
            configurable=configurable,
            integration_id="spawn",
            initial_state={},
            user_id="u1",
            stream_id=parent.get("stream_id"),
        ),
        subagent_id="row-1",
        tool_call_id="call-1",
        task="summarise the report",
        display=SubagentDisplay(name="summarise the report", agent_type="spawned"),
        parent_configurable=parent,
    )


async def _drain() -> None:
    while pending := [
        t
        for t in background_tasks._background_tasks
        if t.get_name() in {delegation.BACKGROUND_SUBAGENT_TASK_NAME, "stream-publish"}
    ]:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
async def redis() -> AsyncIterator[Any]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(redis_cache, "redis", client):
        yield client
    await client.aclose()


@pytest.fixture
def client_edges() -> Iterator[SimpleNamespace]:
    """Record the stream, websocket and persistence edges a background run touches."""
    broadcasts: list[dict[str, Any]] = []

    async def _broadcast(_user_id: str, payload: dict[str, Any]) -> None:
        broadcasts.append(payload)

    with (
        patch.object(executor_queue, "StreamManager", AsyncMock()) as stream_manager,
        patch.object(executor_queue.websocket_manager, "broadcast_to_user", new=_broadcast),
        patch(f"{FOLDED_CARDS}.conversation_repository") as conversations,
        patch(f"{MODULE}.stream_manager") as streams,
        patch(f"{FOLDED}.stream_manager", new=streams),
        patch(f"{MODULE}.deliver_to_executor", new=AsyncMock()) as deliver,
    ):
        conversations.append_message_tool_data = AsyncMock(return_value=True)
        conversations.extend_subagent_group = AsyncMock(return_value=True)
        conversations.get_message = AsyncMock(
            return_value=MessageModel(type="bot", response="", tool_data=[])
        )
        streams.is_cancelled = AsyncMock(return_value=False)
        yield SimpleNamespace(
            broadcasts=broadcasts,
            conversations=conversations,
            deliver=deliver,
            streams=streams,
            stream_manager=stream_manager,
        )


@pytest.fixture
def recorder() -> Iterator[WideEventRecorder]:
    """Capture the wide events a background run emits on its own boundary."""
    events = WideEventRecorder()
    with patch("shared.py.wide_events._loguru", events):
        yield events


@pytest.fixture
def own_stream() -> Iterator[dict[str, list[dict[str, Any]]]]:
    """Record every frame a background run writes, keyed by the stream it writes to."""
    frames: dict[str, list[dict[str, Any]]] = {}

    def _writer(stream_id: str) -> Any:
        return frames.setdefault(stream_id, []).append

    with patch(f"{MODULE}.make_redis_stream_writer", side_effect=_writer):
        yield frames


def _running(subagent_id: str = "other", thread: str = THREAD) -> RunningSubagent:
    return RunningSubagent(
        subagent_id=subagent_id,
        subagent_thread_id=thread,
        integration_id="spawn",
        agent_name="spawned_subagent",
        task_summary="",
        started_at="",
    )


def _landings(deliver: AsyncMock) -> list[str]:
    return [c.args[2] for c in deliver.await_args_list]


def _landing(result: str) -> str:
    return SUBAGENT_RESULT_ENTRY.format(
        name="summarise the report", subagent_id="row-1", result=result
    )


class TestWhereARunRuns:
    def test_a_live_conversation_runs_in_the_background(self) -> None:
        assert runs_in_background(True, LIVE) is True

    def test_asking_to_wait_waits(self) -> None:
        assert runs_in_background(False, LIVE) is False

    def test_a_headless_run_waits_even_when_asked_for_the_background(self) -> None:
        # A workflow or scheduled todo delivers once: a later landing reaches nobody.
        assert runs_in_background(True, {**LIVE, "execution_mode": "background"}) is False

    def test_a_run_with_no_stream_or_conversation_waits(self) -> None:
        assert runs_in_background(True, {**LIVE, "stream_id": None}) is False
        assert runs_in_background(True, {**LIVE, "conversation_id": ""}) is False


@contextmanager
def _blocking(outcomes: list[Any]) -> Iterator[Any]:
    writer = MagicMock()
    execute = AsyncMock(side_effect=outcomes)
    with (
        patch(f"{MODULE}.current_stream_writer", return_value=writer),
        patch(f"{MODULE}.execute_subagent_stream", new=execute),
    ):
        yield SimpleNamespace(writer=writer, execute=execute)


def _events(writer: MagicMock) -> list[str]:
    return [next(iter(c.args[0])) for c in writer.call_args_list]


class TestABlockingRun:
    async def test_it_holds_its_thread_for_exactly_its_run(self, redis: Any) -> None:
        held_during: list[bool] = []

        async def _run(**_kwargs: Any) -> SubagentOutcome:
            held_during.append(await RunningSubagents(CONVERSATION).holds_thread(THREAD))
            return SubagentOutcome(text="done")

        with _blocking([]) as h:
            h.execute.side_effect = _run
            result = await delegate(_delegation(), background=False)

        assert result == "done"
        assert held_during == [True]
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)
        assert _events(h.writer) == ["subagent_start", "subagent_end"]

    async def test_a_failed_run_frees_its_thread_and_closes_its_row(self, redis: Any) -> None:
        with _blocking([RuntimeError("graph exploded")]) as h, pytest.raises(RuntimeError):
            await delegate(_delegation(), background=False)

        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)
        assert _events(h.writer) == ["subagent_start", "subagent_end"]

    async def test_graph_control_flow_bubbles_up_with_the_row_left_open(self, redis: Any) -> None:
        with _blocking([GraphInterrupt()]) as h, pytest.raises(GraphInterrupt):
            await delegate(_delegation(), background=False)

        assert _events(h.writer) == ["subagent_start"]
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)

    async def test_a_held_thread_refuses_in_whole_sentences(self, redis: Any) -> None:
        await RunningSubagents(CONVERSATION).claim(
            RunningSubagent(
                subagent_id="other",
                subagent_thread_id=THREAD,
                integration_id="spawn",
                agent_name="spawned_subagent",
                task_summary="",
                started_at="",
            )
        )
        with _blocking([]) as h:
            result = await delegate(_delegation(), background=False)

        h.execute.assert_not_awaited()
        assert result.startswith("summarise the report is already running on this integration")
        assert "message_subagent" in result and "cancel_subagent" in result

    async def test_a_workflow_run_returns_its_call_record(self, redis: Any) -> None:
        outcome = SubagentOutcome(
            text="sent",
            run_messages=(
                AIMessage(
                    content="",
                    tool_calls=[{"name": "GMAIL_SEND", "args": {"to": "a@b.c"}, "id": "t1"}],
                ),
                ToolMessage(content="ok", tool_call_id="t1"),
            ),
        )
        parent = {**LIVE, "workflow_id": "wf-1", "execution_mode": "background"}
        with _blocking([outcome]):
            result = await delegate(_delegation(parent), background=True)

        assert result.startswith("sent")
        assert 'GMAIL_SEND({"to":"a@b.c"})' in result


class TestABackgroundDispatch:
    async def test_it_returns_the_acknowledgement_and_runs_detached(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="the summary")),
        ):
            ack = await delegate(_delegation(), background=True)
            await _drain()

        assert "started in the background as subagent row-1" in ack
        landed = client_edges.deliver.await_args
        assert landed.args[2] == "summarise the report (subagent row-1): the summary"
        assert landed.kwargs["tag"] is AgentTag.SUBAGENT_RESULT
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)

    async def test_a_replay_of_the_dispatching_node_does_not_run_it_twice(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        execute = AsyncMock(return_value=SubagentOutcome(text="the summary"))
        with patch(f"{MODULE}.execute_subagent_stream", new=execute):
            first = await delegate(_delegation(), background=True)
            second = await delegate(_delegation(), background=True)
            await _drain()

        assert first == second
        assert execute.await_count == 1

    async def test_a_refused_dispatch_gives_its_claim_back(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        holder = RunningSubagent(
            subagent_id="other",
            subagent_thread_id=THREAD,
            integration_id="spawn",
            agent_name="spawned_subagent",
            task_summary="",
            started_at="",
        )
        await RunningSubagents(CONVERSATION).claim(holder)
        refused = await delegate(_delegation(), background=True)
        await RunningSubagents(CONVERSATION).deregister(holder)

        execute = AsyncMock(return_value=SubagentOutcome(text="ran"))
        with patch(f"{MODULE}.execute_subagent_stream", new=execute):
            retried = await delegate(_delegation(), background=True)
            await _drain()

        assert "already running" in refused
        assert "started in the background" in retried
        assert execute.await_count == 1


class TestABackgroundRunOwnsItsStream:
    async def test_it_announces_its_own_stream_folded_into_the_parents_message(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        seen: dict[str, Any] = {}

        async def _run(**kwargs: Any) -> SubagentOutcome:
            ctx = kwargs["ctx"]
            seen["stream_id"] = ctx.stream_id
            seen["configurable"] = dict(ctx.configurable)
            seen["parent_stream_id"] = ctx.parent_stream_id
            return SubagentOutcome(text="done")

        with patch(f"{MODULE}.execute_subagent_stream", new=_run):
            await delegate(_delegation(), background=True)
            await _drain()

        (announced,) = [
            b for b in client_edges.broadcasts if b["type"] == "executor.stream_started"
        ]
        assert announced["stream_id"] == seen["stream_id"] != "parent-stream"
        assert announced["task_id"] == "row-1"
        assert announced["bot_message_id"] == "bot-msg-1"
        # The client upserts only this run's cards: the turn's own run may still be writing.
        assert announced["kind"] == "subagent"
        # The gate reads it off the run's configurable: the card goes on this stream.
        assert seen["configurable"]["stream_id"] == seen["stream_id"]
        # A Stop on the dispatching turn still reaches it.
        assert seen["parent_stream_id"] == "parent-stream"

    async def test_its_frames_are_saved_into_the_parents_message(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="done")),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        saved = client_edges.conversations.append_message_tool_data.await_args
        assert saved.args[0] == CONVERSATION
        assert saved.kwargs["message_id"] == "bot-msg-1"
        assert saved.kwargs["entries"], "the run's subagent row must be saved"

    async def test_cards_that_cannot_be_saved_do_not_cost_the_run_its_result(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        client_edges.conversations.get_message.side_effect = RuntimeError("mongo down")
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="the summary")),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        (landed,) = [c.args[2] for c in client_edges.deliver.await_args_list]
        assert landed.endswith(": the summary")
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)


FULL_DISPLAY = SubagentDisplay(
    name="summarise the report",
    agent_type="mcp",
    tool_category="linear",
    icon_url="https://icons.example/linear.png",
    integration="linear",
    parent_subagent_id="parent-row",
)


class TestABlockingRunDrivesItsGraph:
    async def test_it_runs_with_the_parents_writer_and_the_runs_identity(self, redis: Any) -> None:
        metadata = IntegrationMetadata(name="Linear", integration_id="linear")
        run = replace(_delegation(), integration_metadata=metadata)
        with _blocking([SubagentOutcome(text="done")]) as h:
            await delegate(run, background=False)

        assert h.execute.await_args.kwargs == {
            "ctx": run.ctx,
            "stream_writer": h.writer,
            "integration_metadata": metadata,
            "subagent_id": "row-1",
        }

    async def test_it_is_steerable_for_exactly_its_run(self, redis: Any) -> None:
        seen: list[RunningSubagent | None] = []

        async def _run(**_kwargs: Any) -> SubagentOutcome:
            seen.append(await RunningSubagents(CONVERSATION).get("row-1"))
            return SubagentOutcome(text="done")

        with _blocking([]) as h:
            h.execute.side_effect = _run
            await delegate(_delegation(), background=False)

        assert seen[0] is not None and seen[0].subagent_thread_id == THREAD
        assert await RunningSubagents(CONVERSATION).get("row-1") is None

    async def test_its_row_presents_the_subagent_and_how_long_it_ran(self, redis: Any) -> None:
        clock = SimpleNamespace(monotonic=MagicMock(side_effect=[10.0, 12.5]))
        run = replace(_delegation(), display=FULL_DISPLAY)
        with _blocking([SubagentOutcome(text="done")]) as h, patch(f"{MODULE}.time", clock):
            await delegate(run, background=False)

        start = h.writer.call_args_list[0].args[0]["subagent_start"]
        end = h.writer.call_args_list[1].args[0]["subagent_end"]
        assert {k: v for k, v in start.items() if k != "started_at"} == {
            "subagent": "linear",
            "subagent_id": "row-1",
            "subagent_name": "summarise the report",
            "agent_type": "mcp",
            "icon_url": "https://icons.example/linear.png",
            "tool_category": "linear",
            "parent_subagent_id": "parent-row",
        }
        assert end["subagent_id"] == "row-1"
        assert end["duration_ms"] == 2500


class TestWhatTheExecutorIsTold:
    async def test_a_dispatch_acknowledges_with_the_subagents_name_and_id(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="the summary")),
        ):
            ack = await delegate(_delegation(), background=True)
            await _drain()

        assert ack == BACKGROUND_DELEGATION_ACK.format(
            name="summarise the report", subagent_id="row-1"
        )

    async def test_a_dispatch_onto_a_held_thread_refuses_by_name(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        await RunningSubagents(CONVERSATION).claim(_running())

        refused = await delegate(_delegation(), background=True)

        assert refused == THREAD_BUSY_REFUSAL.format(name="summarise the report")

    async def test_a_background_run_is_steerable_while_it_runs_and_not_after(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        seen: list[RunningSubagent | None] = []

        async def _run(**_kwargs: Any) -> SubagentOutcome:
            seen.append(await RunningSubagents(CONVERSATION).get("row-1"))
            return SubagentOutcome(text="done")

        with patch(f"{MODULE}.execute_subagent_stream", new=_run):
            await delegate(_delegation(), background=True)
            await _drain()

        assert seen[0] is not None
        assert await RunningSubagents(CONVERSATION).get("row-1") is None

    async def test_a_workflow_parents_background_run_lands_its_call_record(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        outcome = SubagentOutcome(
            text="sent",
            run_messages=(
                AIMessage(
                    content="",
                    tool_calls=[{"name": "GMAIL_SEND", "args": {"to": "a@b.c"}, "id": "t1"}],
                ),
                ToolMessage(content="ok", tool_call_id="t1"),
            ),
        )
        parent = {**LIVE, "workflow_id": "wf-1"}
        with patch(f"{MODULE}.execute_subagent_stream", new=AsyncMock(return_value=outcome)):
            await delegate(_delegation(parent), background=True)
            await _drain()

        (landed,) = _landings(client_edges.deliver)
        assert landed.startswith(_landing("sent"))
        assert 'GMAIL_SEND({"to":"a@b.c"})' in landed


class TestABackgroundRunsBoundary:
    async def test_its_wide_event_names_the_run_and_carries_the_dispatchers_trace(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="done")),
        ):
            async with captured_wide_event():
                log.set(trace_id="trace-1")
                await delegate(_delegation(), background=True)
                await _drain()

        event = recorder.event("subagent_run")
        (announced,) = [
            b for b in client_edges.broadcasts if b["type"] == "executor.stream_started"
        ]
        assert event["trace_id"] == "trace-1"
        assert event["agent_name"] == "spawned_subagent"
        assert event["conversation_id"] == CONVERSATION
        assert event["stream_id"] == announced["stream_id"]
        assert event["subagent_id"] == "row-1"
        assert event["integration_id"] == "spawn"

    async def test_a_failed_run_lands_its_error_and_closes_its_row(
        self,
        redis: Any,
        client_edges: SimpleNamespace,
        recorder: WideEventRecorder,
        own_stream: dict[str, list[dict[str, Any]]],
    ) -> None:
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(side_effect=RuntimeError("graph exploded")),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        failure = SUBAGENT_FAILED_RESULT.format(name="summarise the report", error="graph exploded")
        assert _landings(client_edges.deliver) == [_landing(failure)]
        (frames,) = own_stream.values()
        assert [next(iter(f)) for f in frames] == ["subagent_start", "subagent_end"]
        (error,) = recorder.event("subagent_run")["errors"]
        assert error == {
            "msg": f"{LogTag.AGENT} Background subagent failed",
            "agent_name": "spawned_subagent",
            "error_type": "RuntimeError",
            "error": "graph exploded",
        }
        assert await RunningSubagents(CONVERSATION).get("row-1") is None
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)

    async def test_a_landing_that_cannot_be_delivered_is_recorded(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        client_edges.deliver.side_effect = RuntimeError("redis down")
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="done")),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        (error,) = recorder.event("subagent_run")["errors"]
        assert error == {
            "msg": f"{LogTag.AGENT} Could not deliver a background subagent's landing",
            "conversation_id": CONVERSATION,
            "subagent_id": "row-1",
            "error_type": "RuntimeError",
            "error": "redis down",
        }


class TestABackgroundRunTheUserStopped:
    @pytest.mark.regression
    async def test_a_dispatch_after_its_turn_was_stopped_never_starts(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        client_edges.streams.is_cancelled = AsyncMock(
            side_effect=lambda sid: sid == LIVE["stream_id"]
        )
        execute = AsyncMock(return_value=SubagentOutcome(text="done"))
        with patch(f"{MODULE}.execute_subagent_stream", new=execute):
            result = await delegate(_delegation(), background=True)
            await _drain()

        assert result == delegation_prompts.STOPPED_BEFORE_START.format(name="summarise the report")
        execute.assert_not_awaited()
        assert await RunningSubagents(CONVERSATION).live() == []
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)

    @pytest.mark.regression
    async def test_it_lands_nothing_so_the_stopped_executor_does_not_restart(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        stopped = SubagentOutcome(text="got halfway", stopped=True)
        with patch(f"{MODULE}.execute_subagent_stream", new=AsyncMock(return_value=stopped)):
            await delegate(_delegation(), background=True)
            await _drain()

        client_edges.deliver.assert_not_awaited()
        assert not await RunningSubagents(CONVERSATION).holds_thread(THREAD)

    @pytest.mark.regression
    async def test_its_record_names_its_own_stream_and_the_stream_that_dispatched_it(
        self,
        redis: Any,
        client_edges: SimpleNamespace,
        own_stream: dict[str, list[dict[str, Any]]],
    ) -> None:
        seen: list[RunningSubagent] = []

        async def _run(**_kwargs: Any) -> SubagentOutcome:
            seen.extend(await RunningSubagents(CONVERSATION).live())
            return SubagentOutcome(text="done")

        with patch(f"{MODULE}.execute_subagent_stream", new=_run):
            await delegate(_delegation(), background=True)
            await _drain()

        ((own_stream_id, _),) = own_stream.items()
        (record,) = seen
        assert record.stream_id == own_stream_id
        assert record.dispatched_by == LIVE["stream_id"]

    async def test_a_blocking_run_is_recorded_on_the_stream_it_shares(self, redis: Any) -> None:
        seen: list[RunningSubagent] = []

        async def _run(**_kwargs: Any) -> SubagentOutcome:
            seen.extend(await RunningSubagents(CONVERSATION).live())
            return SubagentOutcome(text="done")

        with (
            patch(f"{MODULE}.execute_subagent_stream", new=_run),
            patch(f"{MODULE}.current_stream_writer", return_value=MagicMock()),
        ):
            await delegate(_delegation(), background=False)

        (record,) = seen
        assert record.stream_id == record.dispatched_by == LIVE["stream_id"]


class TestABackgroundRunsStreamLifecycle:
    async def test_a_finished_run_opens_and_closes_its_row_on_its_own_stream(
        self,
        redis: Any,
        client_edges: SimpleNamespace,
        own_stream: dict[str, list[dict[str, Any]]],
    ) -> None:
        metadata = IntegrationMetadata(name="Linear")
        run = replace(_delegation(), display=FULL_DISPLAY, integration_metadata=metadata)
        execute = AsyncMock(return_value=SubagentOutcome(text="done"))
        with patch(f"{MODULE}.execute_subagent_stream", new=execute):
            await delegate(run, background=True)
            await _drain()

        ((stream_id, frames),) = own_stream.items()
        (announced,) = [
            b for b in client_edges.broadcasts if b["type"] == "executor.stream_started"
        ]
        assert stream_id == announced["stream_id"]
        assert stream_id.startswith(SUBAGENT_STREAM_ID_PREFIX)
        assert announced["conversation_id"] == CONVERSATION
        assert [next(iter(f)) for f in frames] == ["subagent_start", "subagent_end"]
        assert frames[0]["subagent_start"]["subagent"] == "linear"
        assert frames[0]["subagent_start"]["icon_url"] == "https://icons.example/linear.png"
        kwargs = execute.await_args.kwargs
        assert kwargs["integration_metadata"] is metadata
        assert kwargs["subagent_id"] == "row-1"
        client_edges.stream_manager.complete_stream.assert_awaited_once_with(stream_id)

    async def test_a_stopped_run_closes_its_stream_silently(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        client_edges.streams.is_cancelled = AsyncMock(
            side_effect=lambda sid: str(sid).startswith(SUBAGENT_STREAM_ID_PREFIX)
        )
        with patch(
            f"{MODULE}.execute_subagent_stream",
            new=AsyncMock(return_value=SubagentOutcome(text="done")),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        client_edges.stream_manager.publish_chunk.assert_not_awaited()
        client_edges.stream_manager.complete_stream.assert_not_awaited()

    async def test_the_runs_config_carries_its_stream_even_when_it_had_none(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        run = _delegation()
        run.ctx.config.pop("configurable")
        seen: dict[str, Any] = {}

        async def _run(**kwargs: Any) -> SubagentOutcome:
            seen.update(kwargs["ctx"].config["configurable"])
            seen["own"] = kwargs["ctx"].stream_id
            return SubagentOutcome(text="done")

        with patch(f"{MODULE}.execute_subagent_stream", new=_run):
            await delegate(run, background=True)
            await _drain()

        assert seen["stream_id"] == seen["own"]

    async def test_a_run_with_no_user_announces_nothing_and_saves_under_no_user(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        base = _delegation()
        run = replace(base, ctx=replace(base.ctx, user_id=None))
        entries: list[ToolDataEntry] = [{"tool_name": "search", "data": {"q": "x"}}]
        with (
            patch(
                f"{MODULE}.execute_subagent_stream",
                new=AsyncMock(return_value=SubagentOutcome(text="done")),
            ),
            patch(f"{FOLDED}.drain_executor_tool_data", return_value=entries),
        ):
            await delegate(run, background=True)
            await _drain()

        conversations = client_edges.conversations
        assert client_edges.broadcasts == []
        assert conversations.get_message.await_args.kwargs["user_id"] == ""
        assert conversations.append_message_tool_data.await_args.kwargs["user_id"] == ""


GROUP = {"tool_name": "subagent_group", "data": {"subagent_id": "row-1", "tool_calls": []}}
HELD_CARD = {"tool_name": "approval_request", "data": {"approval_id": "appr-1"}}
NEW_CARD = {"tool_name": "approval_request", "data": {"approval_id": "appr-2"}}
SEARCH = {"tool_name": "search", "data": {"q": "x"}}


class TestSavingABackgroundRunsFrames:
    @staticmethod
    async def _run(entries: list[Any], parent: AgentConfigurable | None = None) -> None:
        with (
            patch(
                f"{MODULE}.execute_subagent_stream",
                new=AsyncMock(return_value=SubagentOutcome(text="done")),
            ),
            patch(f"{FOLDED}.drain_executor_tool_data", return_value=entries),
        ):
            await delegate(_delegation(parent), background=True)
            await _drain()

    async def test_the_frames_are_appended_to_the_users_own_message(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        await self._run([GROUP, SEARCH])

        conversations = client_edges.conversations
        conversations.get_message.assert_awaited_once_with(CONVERSATION, "bot-msg-1", user_id="u1")
        conversations.append_message_tool_data.assert_awaited_once_with(
            CONVERSATION, user_id="u1", message_id="bot-msg-1", entries=[GROUP, SEARCH]
        )
        assert "errors" not in recorder.event("subagent_run")

    async def test_a_resumed_segment_extends_its_row_and_saves_only_new_cards(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        client_edges.conversations.get_message.return_value = MessageModel(
            type="bot", response="", tool_data=[GROUP, HELD_CARD]
        )

        await self._run([GROUP, HELD_CARD, NEW_CARD, SEARCH])

        extended = client_edges.conversations.extend_subagent_group.await_args
        assert extended.args == (CONVERSATION,)
        assert extended.kwargs["user_id"] == "u1"
        assert extended.kwargs["message_id"] == "bot-msg-1"
        assert extended.kwargs["group"].subagent_id == "row-1"
        client_edges.conversations.append_message_tool_data.assert_awaited_once_with(
            CONVERSATION, user_id="u1", message_id="bot-msg-1", entries=[NEW_CARD, SEARCH]
        )

    async def test_a_run_with_no_message_to_fold_into_saves_nothing_and_says_so(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        parent = {k: v for k, v in LIVE.items() if k != "bot_message_id"}

        await self._run([GROUP, SEARCH], parent)

        client_edges.conversations.get_message.assert_not_awaited()
        client_edges.conversations.append_message_tool_data.assert_not_awaited()
        assert recorder.event("subagent_run")["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} Detached stream has no message to save its cards into",
                "conversation_id": CONVERSATION,
                "stream_id": _OwnStream(),
                "entries": 2,
            }
        ]

    async def test_frames_for_a_message_not_saved_yet_wait_for_its_save(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        """A fast run can end before its turn saved the message: its cards wait on the conversation."""
        conversations = client_edges.conversations
        conversations.get_message.return_value = None
        conversations.park_folded_cards = AsyncMock(return_value=True)

        await self._run([GROUP, SEARCH])

        conversations.append_message_tool_data.assert_not_awaited()
        conversations.park_folded_cards.assert_awaited_once_with(
            CONVERSATION, user_id="u1", message_id="bot-msg-1", entries=[GROUP, SEARCH]
        )
        assert "errors" not in recorder.event("subagent_run")

    async def test_an_append_that_matched_nothing_is_recorded(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        client_edges.conversations.append_message_tool_data.return_value = False

        await self._run([GROUP, SEARCH, NEW_CARD])

        assert recorder.event("subagent_run")["errors"] == [
            {
                "msg": f"{LogTag.AGENT} Detached stream cards matched no message; not saved",
                "conversation_id": CONVERSATION,
                "message_id": "bot-msg-1",
                "entries": 3,
            }
        ]

    async def test_a_save_that_raises_is_recorded_and_the_result_still_lands(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        client_edges.conversations.get_message.side_effect = RuntimeError("mongo down")

        await self._run([GROUP])

        assert _landings(client_edges.deliver) == [_landing("done")]
        assert recorder.event("subagent_run")["errors"] == [
            {
                "msg": f"{LogTag.AGENT} Could not save a detached stream's cards",
                "conversation_id": CONVERSATION,
                "stream_id": _OwnStream(),
                "error_type": "RuntimeError",
                "error": "mongo down",
            }
        ]
