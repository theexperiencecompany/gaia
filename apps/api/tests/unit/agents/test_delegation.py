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
import pytest

from app.agents.core.background import executor_queue, folded_stream
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
from app.constants.cache import RUNNING_SUBAGENT_THREAD_PREFIX
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable, RunningSubagent
from app.models.conversation_log_models import (
    Entry,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.tool_cards import FoldedCards
from app.utils import background_tasks
from app.utils.agent_utils import IntegrationMetadata
from shared.py.conversation_wire import ImageData, ToolDataEntry
from shared.py.wide_events import log
from tests.helpers import WideEventRecorder, captured_wide_event
from tests.unit.services.conversation.log_helpers import user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

MODULE = "app.agents.core.subagents.delegation"
FOLDED = "app.agents.core.background.folded_stream"


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


def _delegation(parent: AgentConfigurable | None = None) -> Delegation:
    parent = (LIVE if parent is None else parent).copy()
    configurable: AgentConfigurable = {**parent, "thread_id": THREAD}
    return Delegation(
        ctx=SubagentExecutionContext(
            subagent_graph=MagicMock(),
            agent_name="spawned_subagent",
            config={"agent_name": "spawned_subagent", "configurable": dict(configurable)},
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


async def _thread_held() -> bool:
    """Whether a live run's claim is on THREAD's checkpoint thread."""
    client = redis_cache.client
    assert client is not None
    return bool(await client.exists(f"{RUNNING_SUBAGENT_THREAD_PREFIX}{THREAD}"))


@pytest.fixture
async def redis() -> AsyncIterator[Any]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(redis_cache, "redis", client):
        yield client
    await client.aclose()


@pytest.fixture
async def client_edges() -> AsyncIterator[SimpleNamespace]:
    """Record the stream and log edges a background run touches."""
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    await runtime.log.append(CONVERSATION, "u1", user("u1"))
    with (
        patch.object(executor_queue, "StreamManager", AsyncMock()) as stream_manager,
        patch(f"{MODULE}.stream_manager") as streams,
        patch(f"{FOLDED}.stream_manager", new=streams),
        patch(f"{MODULE}.deliver_to_executor", new=AsyncMock()) as deliver,
    ):
        streams.is_cancelled = AsyncMock(return_value=False)
        yield SimpleNamespace(
            runtime=runtime, deliver=deliver, streams=streams, stream_manager=stream_manager
        )


async def _logged(edges: SimpleNamespace) -> list[Entry]:
    return [logged.entry for logged in await edges.runtime.log.read_after(CONVERSATION, "u1", 1)]


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
            held_during.append(await _thread_held())
            return SubagentOutcome(text="done")

        with _blocking([]) as h:
            h.execute.side_effect = _run
            result = await delegate(_delegation(), background=False)

        assert result == "done"
        assert held_during == [True]
        assert not await _thread_held()
        assert _events(h.writer) == ["subagent_start", "subagent_end"]

    async def test_a_workflow_parents_blocking_run_returns_its_call_record(
        self, redis: Any
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
        parent: AgentConfigurable = {**LIVE, "workflow_id": "wf-1"}
        with _blocking([outcome]):
            result = await delegate(_delegation(parent), background=False)

        assert result.startswith("sent\n\n")
        assert 'GMAIL_SEND({"to":"a@b.c"})' in result

    async def test_a_failed_run_frees_its_thread_and_closes_its_row(self, redis: Any) -> None:
        with _blocking([RuntimeError("graph exploded")]) as h, pytest.raises(RuntimeError):
            await delegate(_delegation(), background=False)

        assert not await _thread_held()
        assert _events(h.writer) == ["subagent_start", "subagent_end"]

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
        assert not await _thread_held()

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
    async def test_it_runs_on_its_own_stream_logged_as_detached_work(
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

        started, ended = await _logged(client_edges)
        assert isinstance(started, WorkStarted)
        assert (started.task_id, started.detached) == (seen["stream_id"], True)
        assert seen["stream_id"] != "parent-stream"
        assert isinstance(ended, WorkFinished)
        assert (ended.task_id, ended.outcome) == (seen["stream_id"], WorkOutcome.DONE)
        # The gate reads the run's stream off its configurable.
        assert seen["configurable"]["stream_id"] == seen["stream_id"]
        # A Stop on the dispatching turn still reaches it.
        assert seen["parent_stream_id"] == "parent-stream"

    async def test_its_cards_are_logged_on_its_own_finished_work(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        cards: list[ToolDataEntry] = [{"tool_name": "search", "data": {"q": "x"}}]

        async def _run(**kwargs: Any) -> SubagentOutcome:
            kwargs["stream_writer"]({"tool_data": cards[0]})
            return SubagentOutcome(text="done")

        with patch(f"{MODULE}.execute_subagent_stream", new=AsyncMock(side_effect=_run)):
            await delegate(_delegation(), background=True)
            await _drain()

        _, ended = await _logged(client_edges)
        assert isinstance(ended, WorkFinished)
        # Its own subagent group opens the record, the card it showed follows.
        assert [card["tool_name"] for card in ended.tool_data] == ["subagent_group", "search"]
        assert ended.tool_data[1] == cards[0]

    async def test_its_own_stream_is_opened_and_closed_as_the_users_work(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        carried = AsyncMock(wraps=folded_stream.record_work_carried)
        opened = AsyncMock(wraps=folded_stream.open_detached_stream)
        finished = AsyncMock(wraps=folded_stream.record_work_finished)
        with (
            patch(
                f"{MODULE}.execute_subagent_stream",
                new=AsyncMock(return_value=SubagentOutcome(text="done")),
            ),
            patch(f"{FOLDED}.record_work_carried", new=carried),
            patch(f"{FOLDED}.open_detached_stream", new=opened),
            patch(f"{FOLDED}.record_work_finished", new=finished),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        (own,) = carried.await_args.args[2:]
        carried.assert_awaited_once_with(CONVERSATION, "u1", own, detached=True)
        opened.assert_awaited_once_with(own, conversation_id=CONVERSATION, user_id="u1")
        assert finished.await_args.args[:3] == (CONVERSATION, "u1", own)

    async def test_a_run_with_no_user_opens_and_closes_its_work_under_one_owner(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        carried = AsyncMock(return_value=True)
        finished = AsyncMock()
        run = _delegation()
        run.ctx.user_id = None
        with (
            patch(
                f"{MODULE}.execute_subagent_stream",
                new=AsyncMock(return_value=SubagentOutcome(text="done")),
            ),
            patch(f"{FOLDED}.record_work_carried", new=carried),
            patch(f"{FOLDED}.open_detached_stream", new=AsyncMock()),
            patch(f"{FOLDED}.record_work_finished", new=finished),
        ):
            await delegate(run, background=True)
            await _drain()

        assert carried.await_args.args[1] == finished.await_args.args[1] == ""

    async def test_its_approval_cards_and_image_ride_on_its_finished_work(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        approval: ToolDataEntry = {"tool_name": "approval", "data": {"id": "a1"}}
        image = ImageData(url="https://img/1.png", prompt="a cat")
        streams: list[str] = []

        def approvals_of(stream_id: str) -> tuple[ToolDataEntry, ...]:
            streams.append(stream_id)
            return (approval,)

        with (
            patch(
                f"{MODULE}.execute_subagent_stream",
                new=AsyncMock(return_value=SubagentOutcome(text="done")),
            ),
            patch(f"{FOLDED}.session_approval_cards", new=approvals_of),
            patch(f"{FOLDED}.work_cards", new=AsyncMock(return_value=FoldedCards(image=image))),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        started, ended = await _logged(client_edges)
        assert isinstance(started, WorkStarted) and isinstance(ended, WorkFinished)
        assert streams == [started.task_id]
        assert (ended.tool_data, ended.image, ended.report, ended.nothing_for_user) == (
            (approval,),
            image,
            "",
            True,
        )

    async def test_a_run_its_stop_refused_never_opens_its_stream_or_starts(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        execute = AsyncMock(return_value=SubagentOutcome(text="done"))
        opened = AsyncMock()
        with (
            patch(f"{MODULE}.execute_subagent_stream", new=execute),
            patch(f"{FOLDED}.record_work_carried", new=AsyncMock(return_value=False)),
            patch(f"{FOLDED}.open_detached_stream", new=opened),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        execute.assert_not_awaited()
        opened.assert_not_awaited()
        # As stopped as one the user ended mid-run: nothing lands to restart the executor.
        client_edges.deliver.assert_not_awaited()

    async def test_cards_that_cannot_be_logged_do_not_cost_the_run_its_result(
        self, redis: Any, client_edges: SimpleNamespace, recorder: WideEventRecorder
    ) -> None:
        with (
            patch(
                f"{MODULE}.execute_subagent_stream",
                new=AsyncMock(return_value=SubagentOutcome(text="the summary")),
            ),
            patch(f"{FOLDED}.record_work_finished", side_effect=RuntimeError("mongo down")),
        ):
            await delegate(_delegation(), background=True)
            await _drain()

        (landed,) = [c.args[2] for c in client_edges.deliver.await_args_list]
        assert landed.endswith(": the summary")
        assert not await _thread_held()
        assert recorder.event("subagent_run")["errors"] == [
            {
                "msg": f"{LogTag.AGENT} Could not log a detached run's end",
                "conversation_id": CONVERSATION,
                "stream_id": _OwnStream(),
                "error_type": "RuntimeError",
                "error": "mongo down",
            }
        ]


FULL_DISPLAY = SubagentDisplay(
    name="summarise the report",
    agent_type="handoff",
    tool_category="linear",
    icon_url="https://icons.example/linear.png",
    integration="linear",
    parent_subagent_id="parent-row",
)


class TestABlockingRunDrivesItsGraph:
    async def test_the_run_drives_with_the_parents_writer_and_the_runs_identity(
        self, redis: Any
    ) -> None:
        metadata = IntegrationMetadata(name="Linear", integration_id="linear")
        run = replace(_delegation(), integration_metadata=metadata)
        with _blocking([SubagentOutcome(text="done")]) as h:
            await delegate(run, background=False)

        (segment,) = (c.kwargs for c in h.execute.await_args_list)
        assert segment["ctx"] is run.ctx
        assert segment["stream_writer"] is h.writer
        assert segment["integration_metadata"] is metadata
        assert segment["subagent_id"] == "row-1"

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
            "agent_type": "handoff",
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
        parent: AgentConfigurable = {**LIVE, "workflow_id": "wf-1"}
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
        started, _ = await _logged(client_edges)
        assert isinstance(started, WorkStarted)
        assert event["trace_id"] == "trace-1"
        assert event["agent_name"] == "spawned_subagent"
        assert event["conversation_id"] == CONVERSATION
        assert event["stream_id"] == started.task_id
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
        assert not await _thread_held()

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
        assert not await _thread_held()

    @pytest.mark.regression
    async def test_it_lands_nothing_so_the_stopped_executor_does_not_restart(
        self, redis: Any, client_edges: SimpleNamespace
    ) -> None:
        stopped = SubagentOutcome(text="got halfway", stopped=True)
        with patch(f"{MODULE}.execute_subagent_stream", new=AsyncMock(return_value=stopped)):
            await delegate(_delegation(), background=True)
            await _drain()

        client_edges.deliver.assert_not_awaited()
        assert not await _thread_held()

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
        assert stream_id.startswith(SUBAGENT_STREAM_ID_PREFIX)
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
