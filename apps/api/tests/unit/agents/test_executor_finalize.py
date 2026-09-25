"""Unit tests for the executor terminal routing matrix (_finalize_executor_run).

These are the regression tests for the "tool_data vanishes on stop" bug class:
every (cancelled? × kind × workflow) combination must route to exactly the
right terminal action. If a future change reintroduces an early-return on
cancellation, or flips ownership, these fail.

Boundaries mocked: Redis (StreamManager, redis_cache), the conversation's
inbox, and the two delivery entry points (each pinned by its own test file).
Session state and the routing logic under test are real.
"""

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from prometheus_client import REGISTRY
import pytest

from app.agents.core.background import (
    executor_channel as ec,
    executor_queue as eq,
    executor_runner as er,
    result_delivery as rd,
)
from app.agents.core.background.executor_capture import (
    await_executor_done,
    drain_executor_tool_data,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import (
    PreparedQueuedTask,
    build_lock_value,
    build_run_item,
)
from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    RunKind,
    create_session,
    get_session,
    mark_executor_spawned,
)
from app.agents.core.nodes import executor_status
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext, SubagentOutcome
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.executor import (
    EXECUTOR_APPROVAL_LOST_MESSAGE,
    EXECUTOR_CRASH_MESSAGE,
    EXECUTOR_PAUSED,
    EXECUTOR_STEP_LIMIT_MESSAGE,
)
from app.constants.hil import HIL_PAUSED_LOCK_TTL_SECONDS
from app.constants.log_tags import LogTag
from app.models.agent_models import InboxEntry
from app.models.chat_models import SourceCategory
from app.models.user_models import AuthenticatedUser
from app.services.hil import bridge
from shared.py.wide_events import log, log_context
from tests.helpers import WideEventRecorder, captured_wide_event

# The task text the finalize step now receives; forwarded to comms on a cancel.
TASK = "run the standup summary"
CARD_NOTE = wrap_agent_payload(AgentTag.RETURNED_TO_FRONTEND, "todo_data (1 todo)")


def _run(
    kind: RunKind,
    *,
    workflow_id: str | None = None,
    stream_id: str = "s1",
    source_category: SourceCategory = SourceCategory.UI,
) -> ExecutorRun:
    return ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user=AuthenticatedUser(user_id="u1"),
        kind=kind,
        task_id="task-1",
        user_message_id=None,
        workflow_id=workflow_id,
        source_category=source_category,
    )


class _Boundaries:
    """All patched collaborators for one _finalize_executor_run call."""

    def __init__(self, stack) -> None:
        self.stream_manager = stack.enter_context(patch.object(er, "StreamManager"))
        self.stream_manager.is_cancelled = AsyncMock(return_value=False)
        self.stream_manager.publish_chunk = AsyncMock()
        self.stream_manager.complete_stream = AsyncMock()
        # A queued run's stream is closed by close_detached_stream, in executor_queue.
        stack.enter_context(patch.object(eq, "StreamManager", self.stream_manager))
        self.release = stack.enter_context(
            patch.object(er, "release_lock_if_owned", new_callable=AsyncMock)
        )
        #: What the conversation's inbox still holds when finalize asks — work
        #: handed over too late for this run's last model call. Empty by default.
        self.pending: list[InboxEntry] = []
        self.inbox_cls = stack.enter_context(patch.object(er, "ExecutorInbox"))
        self.read_inbox = AsyncMock(side_effect=lambda: list(self.pending))
        self.inbox_cls.return_value.read = self.read_inbox
        self.inbox_cls.return_value.retire = AsyncMock()
        self.prepare = stack.enter_context(
            patch.object(er, "prepare_run_from_item", new_callable=AsyncMock, return_value=None)
        )
        self.deliver = stack.enter_context(
            patch.object(er, "deliver_result", new_callable=AsyncMock, return_value=(None, None))
        )
        self.persist_cancelled = stack.enter_context(
            patch.object(er, "persist_cancelled_run", new_callable=AsyncMock)
        )
        self.note = stack.enter_context(
            patch.object(er, "build_returned_to_frontend_note", return_value="")
        )
        self.record_cancel = stack.enter_context(
            patch.object(er, "record_executor_cancellation", new_callable=AsyncMock)
        )


@pytest.fixture
def boundaries():
    with ExitStack() as stack:
        yield _Boundaries(stack)


class TestCancelledRouting:
    async def test_cancelled_queued_run_persists_cards_and_skips_delivery(self, boundaries) -> None:
        boundaries.stream_manager.is_cancelled.return_value = True
        run = _run(RunKind.QUEUED)
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(run, TASK, "partial text", "final")

        # Comms' context must record the cancellation regardless of card ownership.
        boundaries.record_cancel.assert_awaited_once_with(run.conversation_id, run.task_id, TASK)
        boundaries.persist_cancelled.assert_awaited_once_with(run, [])
        boundaries.deliver.assert_not_awaited()
        # Queued stream is closed silently: no [DONE], no complete_stream.
        boundaries.stream_manager.publish_chunk.assert_not_awaited()
        boundaries.stream_manager.complete_stream.assert_not_awaited()
        # A cancel targets the RUNNING task only — the lock is still released
        # and the inbox still rechecked (cancel-all clears the inbox itself
        # before this runs).
        boundaries.release.assert_awaited_once()
        boundaries.read_inbox.assert_awaited_once()
        # Queued sessions are torn down by finalize.
        assert get_session("s1") is None

    async def test_cancelled_live_run_defers_to_comms_ownership(self, boundaries) -> None:
        """Live cancel: the comms stream attaches the cards — the executor must NOT persist them too, or every stopped turn would show duplicates."""
        boundaries.stream_manager.is_cancelled.return_value = True
        run = _run(RunKind.LIVE)
        create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(run, TASK, "partial text", "final")

        # Cards defer to comms, but the cancellation is still recorded for context.
        boundaries.record_cancel.assert_awaited_once_with(run.conversation_id, run.task_id, TASK)
        boundaries.persist_cancelled.assert_not_awaited()
        boundaries.deliver.assert_not_awaited()
        # Live sessions are torn down by the chat stream, not by finalize.
        assert get_session("s1") is not None

    async def test_cancelled_workflow_run_persists_cards(self, boundaries) -> None:
        boundaries.stream_manager.is_cancelled.return_value = True
        run = _run(RunKind.LIVE, workflow_id="wf-1")
        create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(run, TASK, "", "final")

        boundaries.record_cancel.assert_awaited_once_with(run.conversation_id, run.task_id, TASK)
        boundaries.persist_cancelled.assert_awaited_once_with(run, [])
        boundaries.deliver.assert_not_awaited()

    async def test_cancelled_run_skips_returned_note(self, boundaries) -> None:
        # The note drains the session for prompt context — pointless after a
        # cancel and it would race teardown.
        boundaries.stream_manager.is_cancelled.return_value = True
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "txt", "final")

        boundaries.note.assert_not_called()


class TestCompletedRouting:
    async def test_completed_queued_run_delivers_and_closes_stream(self, boundaries) -> None:
        run = _run(RunKind.QUEUED)
        create_session("s1", RunKind.QUEUED)
        boundaries.note.return_value = CARD_NOTE

        await er._finalize_executor_run(run, TASK, "result", "final")

        boundaries.deliver.assert_awaited_once_with(run, "result", "final", CARD_NOTE, tool_data=[])
        # A completed run narrates and delivers — it never records a cancellation.
        boundaries.record_cancel.assert_not_awaited()
        boundaries.persist_cancelled.assert_not_awaited()
        boundaries.stream_manager.publish_chunk.assert_awaited_once_with("s1", "data: [DONE]\n\n")
        boundaries.stream_manager.complete_stream.assert_awaited_once_with("s1")
        assert get_session("s1") is None  # queued teardown

    async def test_completed_live_run_delivers_without_stream_close(self, boundaries) -> None:
        run = _run(RunKind.LIVE)
        create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(run, TASK, "result", "final")

        boundaries.deliver.assert_awaited_once()
        boundaries.record_cancel.assert_not_awaited()
        # The live SSE is owned by the chat stream — finalize must not close it.
        boundaries.stream_manager.publish_chunk.assert_not_awaited()
        assert get_session("s1") is not None

    async def test_empty_result_text_skips_delivery(self, boundaries) -> None:
        create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "", "final")

        boundaries.deliver.assert_not_awaited()
        boundaries.record_cancel.assert_not_awaited()
        boundaries.persist_cancelled.assert_not_awaited()


class TestDoneSignalAndOrdering:
    @pytest.mark.parametrize("cancelled", [True, False])
    async def test_done_event_is_always_signalled(self, boundaries, cancelled) -> None:
        """The chat stream blocks on this event — a missed signal hangs the SSE until the wait timeout, regardless of how the run ended."""
        boundaries.stream_manager.is_cancelled.return_value = cancelled
        session = create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "txt", "final")

        assert session.done_event.is_set()

    async def test_returned_note_is_snapshotted_before_done_signal(self, boundaries) -> None:
        """Once done_event fires, the chat stream drains + tears down the session in parallel — reading the note after would race teardown."""
        session = create_session("s1", RunKind.LIVE)
        done_state_at_note_time: list[bool] = []
        boundaries.note.side_effect = lambda _sid: (
            done_state_at_note_time.append(session.done_event.is_set()),
            "",
        )[1]

        await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "txt", "final")

        assert done_state_at_note_time == [False]


class TestBackgroundRunCardsSurviveTheCommsDrain:
    """A scheduled workflow's tool cards must reach the bot message it saves.

    The comms silent path and the executor's delivery read the run's cards off
    the SAME session. call_agent_silent waits on done_event, drains, and
    tears the session down in its finally — so a delivery that reads the
    session AFTER signalling done finds nothing left. The symptom: a workflow
    run whose execution record listed every tool call saved a bot message with
    an empty tool_data, and the chat showed no "Used N tools" thread.
    """

    @staticmethod
    def _delivery_seams(stack: ExitStack) -> AsyncMock:
        """Patch delivery's I/O only; the real card-attaching logic runs."""
        stack.enter_context(patch.object(er, "StreamManager")).is_cancelled = AsyncMock(
            return_value=False
        )
        stack.enter_context(patch.object(er, "release_lock_if_owned", new_callable=AsyncMock))
        stack.enter_context(patch.object(er, "ExecutorInbox")).return_value.read = AsyncMock(
            return_value=[]
        )
        stack.enter_context(
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock, return_value="done")
        )
        stack.enter_context(
            patch.object(rd, "_safe_inline_follow_ups", new_callable=AsyncMock, return_value=[])
        )
        stack.enter_context(
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None)
        )
        stack.enter_context(patch.object(rd, "deliver_result_to_platforms", new_callable=AsyncMock))
        stack.enter_context(
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock)
        )
        return stack.enter_context(patch.object(rd, "update_messages", new_callable=AsyncMock))

    async def test_a_workflow_run_saves_the_cards_it_produced(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        mark_executor_spawned("s1")
        session.tool_events.append(
            {"tool_data": {"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}}
        )
        run = _run(RunKind.LIVE, workflow_id="wf-1", source_category=SourceCategory.BG)

        async def comms_silent_path() -> None:
            """Run what call_agent_silent does around a workflow's graph run."""
            await await_executor_done("s1")
            drain_executor_tool_data("s1")
            teardown_executor_capture("s1")

        with ExitStack() as stack:
            save = self._delivery_seams(stack)
            # The comms consumer is already waiting when the run finalizes, exactly
            # as it is in a workflow fire.
            await asyncio.gather(
                comms_silent_path(),
                er._finalize_executor_run(run, TASK, "the digest", "final"),
            )

        saved = save.await_args.args[0].messages[0]
        assert [entry["tool_name"] for entry in (saved.tool_data or [])] == ["tool_calls_data"]


class TestCancelStillCarriesHandedOverWork:
    """Adversarial test for the lock/hand-off lifecycle, written red-first."""

    async def test_stop_does_not_strand_work_handed_over_mid_run(self, boundaries) -> None:
        """BUG B: the user hands the running executor a second thing, then presses Stop."""
        boundaries.stream_manager.is_cancelled.return_value = True
        create_session("s1", RunKind.QUEUED)
        boundaries.pending = [InboxEntry(id="e1", text="the handed-over ask")]
        boundaries.prepare.return_value = PreparedQueuedTask(
            run=_run(RunKind.QUEUED, stream_id="queued_next"),
            task="the handed-over ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "partial", "final")
            await asyncio.sleep(0)

        boundaries.inbox_cls.assert_called_with("conv-1")
        # A run is started to drain the inbox, seeded (not stuffed) with the ask;
        # the handed-over entry is never retired before a run is durably going to
        # take it, so a crash here cannot strand it.
        assert boundaries.prepare.await_args.args[1]["task"] == er.EXECUTOR_CARRY_TASK
        boundaries.inbox_cls.return_value.retire.assert_not_awaited()
        spawn.assert_awaited_once()

    async def test_a_run_that_failed_setup_does_not_restart_itself_for_its_pending_work(
        self, boundaries
    ) -> None:
        """No context means no model call: the carried work would fail setup the same way, forever."""
        create_session("s1", RunKind.QUEUED)
        boundaries.pending = [InboxEntry(id="e1", text="the handed-over ask")]
        boundaries.prepare.return_value = PreparedQueuedTask(
            run=_run(RunKind.QUEUED, stream_id="queued_next"),
            task="the handed-over ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(
                _run(RunKind.QUEUED), TASK, "Executor agent not available", "error"
            )
            await asyncio.sleep(0)

        spawn.assert_not_awaited()
        boundaries.inbox_cls.return_value.retire.assert_not_awaited()


class TestRecordPause:
    """_record_pause must fail the run, never the process, when the write fails.

    A batch pause with no resumable context is worse than an error: it holds the
    busy lock for its full TTL waiting on a resume that can never come. The
    caller (run_executor_background) treats a False return as "fail this
    run" — so a write failure here must surface as False, not an exception.
    """

    async def test_a_failed_write_fails_the_run_instead_of_raising(self) -> None:
        run = _run(RunKind.LIVE)

        with patch.object(
            er, "set_resume_item", new_callable=AsyncMock, side_effect=RuntimeError("redis down")
        ):
            recorded = await er._record_pause(
                run, TASK, {"user_id": "u1"}, ("appr-1", "appr-2")
            )  # must not raise

        assert recorded is False

    async def test_a_successful_write_reports_true(self) -> None:
        run = _run(RunKind.LIVE)

        with patch.object(er, "set_resume_item", new_callable=AsyncMock) as set_item:
            recorded = await er._record_pause(run, TASK, {"user_id": "u1"}, ("appr-1", "appr-2"))

        assert recorded is True
        assert set_item.await_count == 2  # every approval id in the batch gets stamped


class TestFinalizeDeliveryFailureDoesNotStrandTheHandoff:
    """A delivery/close failure inside finalize must not skip the lock release and inbox hand-off below it — otherwise handed-over work strands and the busy lock leaks until its TTL (see the comment on the guarding except in _finalize_executor_run)."""

    async def test_delivery_blowing_up_still_carries_the_handed_over_work(self, boundaries) -> None:
        run = _run(RunKind.QUEUED)
        create_session("s1", RunKind.QUEUED)
        boundaries.deliver.side_effect = RuntimeError("delivery blew up")
        boundaries.pending = [InboxEntry(id="e1", text="the handed-over ask")]
        boundaries.prepare.return_value = PreparedQueuedTask(
            run=_run(RunKind.QUEUED, stream_id="queued_next"),
            task="the handed-over ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(run, TASK, "result", "final")  # must not raise
            await asyncio.sleep(0)

        boundaries.release.assert_awaited_once()  # and the lock still goes
        boundaries.read_inbox.assert_awaited_once()
        spawn.assert_awaited_once()  # the handed-over work still gets a run

    async def test_a_swallowed_delivery_failure_is_named_in_the_wide_event(
        self, boundaries
    ) -> None:
        """Swallowing the exception is deliberate — losing it is not."""
        create_session("s1", RunKind.QUEUED)
        boundaries.deliver.side_effect = RuntimeError("telegram rejected the message")

        async with log_context("executor_finalize_test"):
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")
            event = dict(log.get())

        assert any(
            "telegram rejected the message" in str(entry.get("error", ""))
            for entry in event["errors"]
        ), event["errors"]

    async def test_a_swallowed_lock_release_failure_is_named_in_the_wide_event(
        self, boundaries
    ) -> None:
        """The other swallowing except in finalize."""
        create_session("s1", RunKind.QUEUED)
        boundaries.release.side_effect = RuntimeError("redis went away")

        async with log_context("executor_finalize_test"):
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")
            event = dict(log.get())

        assert any(
            "lock release" in str(entry.get("msg", ""))
            and "redis went away" in str(entry.get("error", ""))
            for entry in event["errors"]
        ), event["errors"]


class TestLockThenInboxHandoff:
    async def test_the_lock_is_released_then_the_inbox_is_rechecked(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")

        boundaries.release.assert_awaited_once()
        boundaries.inbox_cls.assert_called_with("conv-1")
        boundaries.read_inbox.assert_awaited_once()

    async def test_carried_work_is_spawned_as_a_fresh_run(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)
        boundaries.pending = [InboxEntry(id="e1", text="do the thing")]
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.prepare.return_value = PreparedQueuedTask(
            run=next_run,
            task="do the thing",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")
            await asyncio.sleep(0)  # let the spawned task start

        spawn.assert_awaited_once_with(
            run=next_run,
            task="do the thing",
            configurable={"stream_id": "queued_next"},
        )

    async def test_an_empty_inbox_starts_no_second_run(self, boundaries) -> None:
        """Nothing was handed over, so nothing is carried — otherwise every run would spawn a successor with an empty task, forever."""
        create_session("s1", RunKind.QUEUED)

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")
            await asyncio.sleep(0)

        boundaries.prepare.assert_not_awaited()
        spawn.assert_not_awaited()


class TestThePausedRunKeepsItsLock:
    """A run parked on a HIL approval is NOT over: its thread is checkpointed with pending work, so no other run may take it.

    Releasing the lock — or letting its TTL lapse while the user takes hours to answer — lets the
    next run take that thread and discard the interrupt.
    """

    async def test_a_pause_re_arms_the_lock_instead_of_releasing_it(self, boundaries) -> None:
        session = create_session("s1", RunKind.QUEUED)

        with patch.object(
            er, "extend_lock_if_owned", new_callable=AsyncMock, return_value=True
        ) as extend:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "", EXECUTOR_PAUSED)

        extend.assert_awaited_once_with("conv-1", "s1", "task-1", HIL_PAUSED_LOCK_TTL_SECONDS)
        boundaries.release.assert_not_awaited()
        # Nothing to deliver, and nothing may be carried into a second run — this
        # thread still holds the work the approval is gating.
        boundaries.deliver.assert_not_awaited()
        boundaries.read_inbox.assert_not_awaited()
        # The turn's SSE must still close, or the user watches a spinner instead
        # of the approval card.
        assert session.done_event.is_set()


class _FakeRedisClient:
    """Just enough of the raw Redis surface for the busy-lock lifecycle."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class _FakeRedisCache:
    def __init__(self) -> None:
        self.client = _FakeRedisClient()

    async def delete(self, key: str) -> None:
        await self.client.delete(key)


@contextmanager
def _real_lock_lifecycle(cache: _FakeRedisCache):
    """Drive finalize with the REAL lock functions over an in-memory Redis, so what the status hook reads afterwards is what the lock actually says."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(eq, "redis_cache", cache))
        stack.enter_context(patch.object(executor_status, "redis_cache", cache))
        stack.enter_context(patch.object(er, "StreamManager")).is_cancelled = AsyncMock(
            return_value=False
        )
        stack.enter_context(
            patch.object(er, "deliver_result", new_callable=AsyncMock)
        ).return_value = (None, None)
        stack.enter_context(patch.object(er, "build_returned_to_frontend_note", return_value=""))
        stack.enter_context(patch.object(er, "ExecutorInbox")).return_value.read = AsyncMock(
            return_value=[]
        )
        yield


async def _status_frames(thread_id: str) -> list[str]:
    state = await executor_status.executor_status_hook(
        {"messages": []}, {"configurable": {"thread_id": thread_id}}, store=None
    )
    return [str(m.content) for m in state["messages"]]


class TestTheBusyLockDoesNotOutliveTheResult:
    """The lock is what tells comms a task is in flight.

    Released only at the very end of finalize, it was still held while the user read the result —
    comms' next turn was handed "a background task is STILL RUNNING" about work it had already
    delivered — and anything that raised on the way there left it held for the full 30-minute TTL.
    """

    async def test_the_status_frame_is_gone_once_the_result_is_delivered(self) -> None:
        cache = _FakeRedisCache()
        cache.client.store[f"{EXECUTOR_BUSY_PREFIX}conv-1"] = build_lock_value("s1", "task-1")
        create_session("s1", RunKind.LIVE)

        with _real_lock_lifecycle(cache):
            assert await _status_frames("conv-1"), "the lock must read as running before finalize"
            await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "8 todos created", "final")
            assert await _status_frames("conv-1") == []

    async def test_the_lock_is_released_even_when_the_handoff_blows_up(self) -> None:
        cache = _FakeRedisCache()
        lock_key = f"{EXECUTOR_BUSY_PREFIX}conv-1"
        cache.client.store[lock_key] = build_lock_value("s1", "task-1")
        create_session("s1", RunKind.QUEUED)

        with _real_lock_lifecycle(cache):
            with patch.object(
                er,
                "_carry_pending_into_new_run",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "done", "final")

        assert lock_key not in cache.client.store

    async def test_a_stale_finalize_never_frees_a_newer_runs_lock(self) -> None:
        """Cancel_executor frees the lock and a NEW run acquires it; the OLD cancelled run's finalize firing later must leave that lock alone, or two executors end up running on one conversation."""
        cache = _FakeRedisCache()
        lock_key = f"{EXECUTOR_BUSY_PREFIX}conv-1"
        cache.client.store[lock_key] = build_lock_value("newer-stream", "task-9")
        create_session("s1", RunKind.QUEUED)

        with _real_lock_lifecycle(cache):
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "done", "final")

        assert cache.client.store[lock_key] == build_lock_value("newer-stream", "task-9")


class _FakeInboxRedisClient:
    """Just enough of the raw Redis list surface to run a real ExecutorInbox."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key: str, *values: str) -> int:
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    async def lrem(self, key: str, count: int, value: str) -> int:
        items = self.lists.get(key, [])
        limit = len(items) if count == 0 else count
        removed, kept = 0, []
        for item in items:
            if item == value and removed < limit:
                removed += 1
                continue
            kept.append(item)
        self.lists[key] = kept
        return removed

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.lists.pop(key, None)


class _FakeInboxCache:
    def __init__(self) -> None:
        self.client = _FakeInboxRedisClient()


class TestFinalizeCarriesOnlyWorkTheThreadNeverTook:
    """What a run actually delivered is read off its THREAD, not off a marker.

    An entry stays on the inbox until a LATER drain pass sees it committed, so a
    hand-off injected on a run's FINAL model call still looks pending at
    finalize. Carrying everything pending started a second run answering a
    request the finishing run had already answered; trusting a "delivered"
    marker written BEFORE the model call dropped work whenever that call failed.
    The checkpoint is the only thing that can tell those two apart.
    """

    @staticmethod
    def _committed(entry_id: str) -> HumanMessage:
        return HumanMessage(content="x", additional_kwargs={ec.INBOX_ENTRY_ID: entry_id})

    async def test_committed_work_is_not_re_run_but_late_work_is(self) -> None:
        cache = _FakeInboxCache()

        with ExitStack() as stack:
            stack.enter_context(patch.object(ec, "redis_cache", cache))
            inbox = ec.ExecutorInbox("conv-1")
            await inbox.append("e1", "also check my calendar")  # committed on the last call
            await inbox.append("e2", "and book the flight")  # landed after it
            stack.enter_context(
                patch.object(er, "thread_messages", AsyncMock(return_value=[self._committed("e1")]))
            )
            prepare = stack.enter_context(
                patch.object(er, "prepare_run_from_item", new_callable=AsyncMock, return_value=None)
            )

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), object())
            still_pending = [entry.id for entry in await inbox.read()]

        prepare.assert_awaited_once()
        # The run is seeded to drain the inbox, not stuffed with the late work.
        assert prepare.await_args.args[1]["task"] == er.EXECUTOR_CARRY_TASK
        # e1 was committed to the thread, so it is retired. e2 was not — it stays
        # for the new run's own drain to inject, commit, and retire crash-safely.
        assert still_pending == ["e2"]

    async def test_work_staged_into_a_model_call_that_failed_is_still_carried(self) -> None:
        """BUG: the run marked an entry delivered BEFORE the model call, so a call that then failed left it neither answered nor carried — it sat in Redis until its TTL."""
        cache = _FakeInboxCache()

        with ExitStack() as stack:
            stack.enter_context(patch.object(ec, "redis_cache", cache))
            inbox = ec.ExecutorInbox("conv-1")
            await inbox.append("e1", "also check my calendar")
            stack.enter_context(patch.object(er, "thread_messages", AsyncMock(return_value=[])))
            prepare = stack.enter_context(
                patch.object(er, "prepare_run_from_item", new_callable=AsyncMock, return_value=None)
            )

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), object())
            still_pending = [entry.id for entry in await inbox.read()]

        # Seeded to drain; the un-committed entry stays for that drain, never
        # retired before a run exists to take it.
        assert prepare.await_args.args[1]["task"] == er.EXECUTOR_CARRY_TASK
        assert still_pending == ["e1"]

    async def test_a_bare_stop_starts_no_run(self) -> None:
        """BUG: cancel_executor appends its interruption notice, and the cancelled run's own finalize read it back as pending work — so pressing Stop spawned a fresh run whose task WAS "the task you were working on was INTERRUPTED"."""
        cache = _FakeInboxCache()

        with ExitStack() as stack:
            stack.enter_context(patch.object(ec, "redis_cache", cache))
            inbox = ec.ExecutorInbox("conv-1")
            await inbox.announce_interruption(None)
            prepare = stack.enter_context(
                patch.object(er, "prepare_run_from_item", new_callable=AsyncMock, return_value=None)
            )

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), None)
            still_pending = [entry.text for entry in await inbox.read()]

        prepare.assert_not_awaited()
        assert still_pending == [ec.INTERRUPTION_NOTICE]

    async def test_a_redirect_starts_a_run_and_leaves_the_entries_for_its_drain(self) -> None:
        cache = _FakeInboxCache()

        with ExitStack() as stack:
            stack.enter_context(patch.object(ec, "redis_cache", cache))
            inbox = ec.ExecutorInbox("conv-1")
            await inbox.announce_interruption("book the flight instead")
            prepare = stack.enter_context(
                patch.object(
                    er, "prepare_run_from_item", new_callable=AsyncMock, return_value=AsyncMock()
                )
            )
            spawn = stack.enter_context(patch.object(er, "_spawn_detached_run"))

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), None)
            still_pending = [entry.text for entry in await inbox.read()]

        spawn.assert_called_once()
        assert prepare.await_args.args[1]["task"] == er.EXECUTOR_CARRY_TASK
        # Both entries stay in the inbox, each keeping its own tag, for the new
        # run's drain to inject and retire — never stuffed into the seed task.
        assert still_pending == [ec.INTERRUPTION_NOTICE, "book the flight instead"]


class TestTheCardNoteOnlyGoesWhereCardsRender:
    """returned_to_frontend tells comms "these items are already on screen, don't re-type them".

    On a bot conversation there is no screen — the reply is plain text over the platform API — so
    the note suppresses the only copy of the data the user would ever see.
    """

    async def test_a_telegram_run_gets_no_card_suppression_note(self, boundaries) -> None:
        run = _run(RunKind.QUEUED, source_category=SourceCategory.BOT)

        await er._finalize_executor_run(run, TASK, "result", "final")

        boundaries.note.assert_not_called()
        assert boundaries.deliver.await_args.args[3] == ""

    async def test_a_web_run_still_gets_the_note(self, boundaries) -> None:
        boundaries.note.return_value = CARD_NOTE
        run = _run(RunKind.QUEUED, source_category=SourceCategory.UI)

        await er._finalize_executor_run(run, TASK, "result", "final")

        boundaries.note.assert_called_once_with("s1")
        assert boundaries.deliver.await_args.args[3] == CARD_NOTE

    async def test_a_scheduled_workflow_run_gets_no_note(self, boundaries) -> None:
        """Its delivery is text-only too, and the narrator was already dropping the note for it — building it was wasted work with one more way to leak."""
        run = _run(RunKind.QUEUED, workflow_id="wf-1", source_category=SourceCategory.BG)

        await er._finalize_executor_run(run, TASK, "result", "final")

        boundaries.note.assert_not_called()


class TestExecutorRunSource:
    def test_the_source_category_comes_from_the_configurable(self) -> None:
        run = ExecutorRun.from_configurable(
            {"user_id": "u1", "source_category": "bot"},
            identity=RunIdentity(
                stream_id="s1",
                conversation_id="conv-1",
                kind=RunKind.QUEUED,
                task_id="task-1",
                user_message_id=None,
            ),
        )

        assert run.source_category is SourceCategory.BOT
        assert run.renders_native_cards is False

    def test_a_configurable_with_no_source_is_background_work(self) -> None:
        run = ExecutorRun.from_configurable(
            {"user_id": "u1"},
            identity=RunIdentity(
                stream_id="s1",
                conversation_id="conv-1",
                kind=RunKind.QUEUED,
                task_id="task-1",
                user_message_id=None,
            ),
        )

        assert run.source_category is SourceCategory.BG


class TestBuildRunItem:
    """The one serialized run-context shape, written by the queue and by the HIL resume store and read back by prepare_run_from_item.

    A renamed or dropped key here is invisible on write and only shows when a resumed run silently
    loses what a queued run kept.
    """

    def test_every_field_survives_the_round_trip_shape(self) -> None:
        item = build_run_item(
            task="triage my inbox",
            configurable={"user_id": "user-1", "thread_id": "conv-1"},
            identity=RunIdentity(
                stream_id="",
                conversation_id="conv-1",
                kind=RunKind.QUEUED,
                task_id="task-1",
                user_message_id="user-msg-1",
                bot_message_id="bot-msg-1",
            ),
        )

        assert item["task"] == "triage my inbox"
        assert item["task_id"] == "task-1"
        assert item["conversation_id"] == "conv-1"
        assert item["user_message_id"] == "user-msg-1"
        assert item["bot_message_id"] == "bot-msg-1"

    def test_a_plain_enqueue_carries_no_bot_message_id(self) -> None:
        """Only a HIL pause sets it; a queued run must still carry the key, as prepare_run_from_item reads it unconditionally."""
        item = build_run_item(
            task="t",
            configurable={"user_id": "user-1"},
            identity=RunIdentity(
                stream_id="",
                conversation_id="conv-1",
                kind=RunKind.QUEUED,
                task_id=None,
                user_message_id=None,
            ),
        )

        assert item["bot_message_id"] is None


class TestHeldCardsFlushedAtFinalize:
    async def test_finalize_flushes_held_cards_before_done_signal(self, boundaries) -> None:
        """Held PENDING cards must go live at run end — otherwise the open client never renders them until a full refresh re-fetches messages."""
        from app.services.hil import bridge

        boundaries.stream_manager.is_cancelled.return_value = False
        session = create_session("s1", RunKind.LIVE)

        with patch.object(
            bridge, "flush_held_approval_cards", new=AsyncMock(return_value=1)
        ) as flush:
            await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "txt", "final")

        flush.assert_awaited_once_with("s1")
        assert session.done_event.is_set()

    async def test_flush_failure_never_breaks_finalize(self, boundaries) -> None:
        from app.services.hil import bridge

        boundaries.stream_manager.is_cancelled.return_value = False
        session = create_session("s1", RunKind.LIVE)

        with patch.object(
            bridge,
            "flush_held_approval_cards",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            async with captured_wide_event() as event:
                await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "txt", "final")

        assert session.done_event.is_set()
        (error,) = [e for e in event["errors"] if "flush" in e["msg"]]
        assert error["msg"] == f"{LogTag.AGENT} Held card flush failed"
        assert (error["stream_id"], error["error_type"]) == ("s1", "RuntimeError")


def _count(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0


def _sum(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_sum", labels) or 0.0


def _counter(name: str, labels: dict[str, str]) -> float:
    """Read a Counter's own sample, which is its base name and not <name>_count."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestTerminalRunMetrics:
    """The terminal labels and the e2e boundary.

    A run's end status drives alerts and SLOs, so the exact literal on the
    collector is the contract.
    """

    async def test_error_run_records_error_status_and_a_zero_e2e_sample(self, boundaries) -> None:
        """Labelled lowercase error, and a stamp equal to the finalize instant is a real 0.0 sample."""
        boundaries.stream_manager.is_cancelled.return_value = False
        run = replace(_run(RunKind.QUEUED), t_dispatch_perf=1234.5, queued=True)
        create_session("s1", RunKind.QUEUED)
        e2e_before = _count("executor_e2e_seconds", {"status": "error", "queued": "true"})
        error_before = _counter("executor_run_total", {"status": "error", "queued": "true"})
        success_before = _counter("executor_run_total", {"status": "success", "queued": "true"})

        with patch.object(er.time, "perf_counter", return_value=1234.5):
            await er._finalize_executor_run(run, TASK, "the model call failed", "error")

        assert (
            _count("executor_e2e_seconds", {"status": "error", "queued": "true"}) == e2e_before + 1
        )
        assert (
            _counter("executor_run_total", {"status": "error", "queued": "true"})
            == error_before + 1
        )
        assert (
            _counter("executor_run_total", {"status": "success", "queued": "true"})
            == success_before
        )

    async def test_cancelled_run_records_cancelled_status(self, boundaries) -> None:
        boundaries.stream_manager.is_cancelled.return_value = True
        run = replace(_run(RunKind.QUEUED), t_dispatch_perf=1234.5, queued=True)
        create_session("s1", RunKind.QUEUED)
        before = _counter("executor_run_total", {"status": "cancelled", "queued": "true"})
        success_before = _counter("executor_run_total", {"status": "success", "queued": "true"})

        with patch.object(er.time, "perf_counter", return_value=1234.5):
            await er._finalize_executor_run(run, TASK, "partial text", "final")

        assert (
            _counter("executor_run_total", {"status": "cancelled", "queued": "true"}) == before + 1
        )
        assert (
            _counter("executor_run_total", {"status": "success", "queued": "true"})
            == success_before
        )


class TestFinalizePausedRun:
    """A HIL pause holds the lock and signals the stream.

    It must not deliver or drain the queue, and observe_executor_run_total gets
    the pause's own label.
    """

    async def _pause(self, *, queued: bool):
        run = replace(_run(RunKind.QUEUED), queued=queued)
        with (
            patch.object(er, "extend_lock_if_owned", AsyncMock(return_value=True)) as extend,
            patch.object(er, "signal_executor_done") as signal,
            patch.object(er, "_close_queued_stream", AsyncMock()) as close,
            patch.object(er, "observe_executor_run_total") as total,
            patch.object(er, "log") as mock_log,
        ):
            await er._finalize_paused_run(run)
        return run, extend, signal, close, total, mock_log

    async def test_it_extends_the_lock_signals_done_and_counts_paused(self) -> None:
        run, extend, signal, close, total, mock_log = await self._pause(queued=True)

        extend.assert_awaited_once_with("conv-1", "s1", "task-1", HIL_PAUSED_LOCK_TTL_SECONDS)
        signal.assert_called_once_with("s1")
        close.assert_awaited_once_with(run, was_cancelled=False)
        total.assert_called_once_with(status="paused", queued=True)
        # A successful extend is not a warning: the orphan warning is for the
        # losing branch only.
        mock_log.warning.assert_not_called()

    async def test_a_non_queued_pause_is_counted_as_not_queued(self) -> None:
        _run_arg, _extend, _signal, _close, total, _log = await self._pause(queued=False)

        total.assert_called_once_with(status="paused", queued=False)


class TestRecordPauseIdentityRewrite:
    async def test_the_resume_context_drops_the_stamp_and_the_queue_origin(self) -> None:
        """The stamp goes (no queue wait for decision time) and the queue origin is cleared."""
        run = replace(_run(RunKind.QUEUED), t_dispatch_perf=1234.5, queued=True)

        with patch.object(er, "set_resume_item", new_callable=AsyncMock) as set_item:
            recorded = await er._record_pause(run, TASK, {"user_id": "u1"}, ("appr-1",))

        assert recorded is True
        item = set_item.await_args.args[1]
        # The serialized resume item carries no queue-timing at all, so a rebuilt
        # run defaults to no dispatch stamp and no queue origin — the resume
        # measures user decision time as neither queue wait nor a lock wait.
        assert "t_dispatch_perf" not in item
        assert "queued" not in item


def _executor_ctx() -> SubagentExecutionContext:
    return SubagentExecutionContext(
        subagent_graph=MagicMock(),
        agent_name="executor_agent",
        config={"configurable": {}},
        configurable={},
        integration_id="executor",
        initial_state={},
    )


class TestARunHandsFinalizeWhatItProduced:
    """run_executor_background through the real execute step and finalize, down to its seams.

    The graph run, prep, delivery and the thread read are doubled; the busy lock, the
    inbox and the carry are real (fakeredis), so what a run leaves behind for the next
    one is what the real lifecycle leaves.
    """

    @contextmanager
    def _lifecycle(
        self,
        *,
        execute: Any = None,
        prepare: Any = None,
        committed: tuple[str, ...] = (),
        record_pause: bool = True,
    ) -> Iterator[SimpleNamespace]:
        ctx = _executor_ctx()
        prepare = prepare or AsyncMock(return_value=(ctx, None))
        execute = execute or AsyncMock(return_value=SubagentOutcome(text="all done"))
        thread = [
            HumanMessage(content="x", additional_kwargs={ec.INBOX_ENTRY_ID: entry_id})
            for entry_id in committed
        ]

        async def _thread_of(read_ctx: SubagentExecutionContext) -> list[HumanMessage]:
            return thread if read_ctx is ctx else []

        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch.object(er, "prepare_executor_execution", prepare))
            enter(patch.object(er, "execute_subagent_stream", execute))
            enter(patch.object(er, "make_redis_stream_writer", MagicMock()))
            enter(patch.object(er, "thread_messages", _thread_of))
            enter(patch.object(er, "_record_pause", AsyncMock(return_value=record_pause)))
            deliver = enter(patch.object(er, "_deliver_terminal_outcome", AsyncMock()))
            enter(patch.object(er, "release_lock_if_owned", AsyncMock()))
            enter(patch.object(er.StreamManager, "is_cancelled", AsyncMock(return_value=False)))
            enter(patch.object(er, "capture_event", MagicMock()))
            enter(patch.object(bridge, "flush_held_approval_cards", AsyncMock()))
            enter(patch.object(eq, "StreamManager", AsyncMock()))
            enter(patch.object(eq, "websocket_manager", AsyncMock()))
            spawn = enter(patch.object(er, "_spawn_detached_run"))
            yield SimpleNamespace(deliver=deliver, spawn=spawn)

    @staticmethod
    async def _drive(inbox_ids: tuple[str, ...] = ()) -> None:
        inbox = ec.ExecutorInbox("conv-1")
        for entry_id in inbox_ids:
            await inbox.append(entry_id, f"handed over {entry_id}")
        await er.run_executor_background(
            run=_run(RunKind.LIVE), task=TASK, configurable={"user_id": "u1"}
        )

    @staticmethod
    def _delivered(deliver: AsyncMock) -> tuple[str, str]:
        run, task, outcome = deliver.await_args.args
        assert (run.stream_id, task) == ("s1", TASK)
        return outcome.result_text, outcome.result_type

    async def test_a_finished_run_delivers_its_answer_and_retires_what_it_absorbed(
        self, fake_redis: Any
    ) -> None:
        with self._lifecycle(committed=("e1",)) as h:
            await self._drive(inbox_ids=("e1",))

        assert self._delivered(h.deliver) == ("all done", "final")
        h.spawn.assert_not_called()
        assert await ec.ExecutorInbox("conv-1").read() == []

    async def test_a_run_whose_setup_raised_leaves_pending_work_for_the_next_run(
        self, fake_redis: Any
    ) -> None:
        recorder = WideEventRecorder()
        with (
            self._lifecycle(prepare=AsyncMock(side_effect=RuntimeError("no model"))) as h,
            patch("shared.py.wide_events._loguru", recorder),
        ):
            await self._drive(inbox_ids=("e1",))

        assert self._delivered(h.deliver) == (EXECUTOR_CRASH_MESSAGE, "error")
        h.spawn.assert_not_called()
        assert [e.id for e in await ec.ExecutorInbox("conv-1").read()] == ["e1"]
        warnings = recorder.event("executor_run")["warnings"]
        (warning,) = [w for w in warnings if "setup failed" in w["msg"]]
        assert warning["msg"] == (
            f"{LogTag.AGENT} Executor setup failed; pending work left for the next run"
        )
        assert (warning["conversation_id"], warning["task_id"]) == ("conv-1", "task-1")

    @pytest.mark.parametrize(
        ("execute", "delivered"),
        [
            (
                AsyncMock(side_effect=RuntimeError("graph exploded")),
                (EXECUTOR_CRASH_MESSAGE, "error"),
            ),
            (
                AsyncMock(side_effect=GraphRecursionError("too deep")),
                (EXECUTOR_STEP_LIMIT_MESSAGE, "error"),
            ),
            (
                AsyncMock(return_value=SubagentOutcome(text="", interrupt={"summary": "x"})),
                ("Approval request was malformed", "error"),
            ),
        ],
        ids=["crash", "recursion-limit", "unresumable-pause"],
    )
    async def test_a_run_that_failed_after_setup_carries_the_work_handed_to_it(
        self, fake_redis: Any, execute: AsyncMock, delivered: tuple[str, str]
    ) -> None:
        with self._lifecycle(execute=execute) as h:
            await self._drive(inbox_ids=("e1",))

        assert self._delivered(h.deliver) == delivered
        h.spawn.assert_called_once()
        assert h.spawn.call_args.args[0].task == er.EXECUTOR_CARRY_TASK

    async def test_a_pause_that_could_not_be_recorded_fails_and_carries_the_handed_work(
        self, fake_redis: Any
    ) -> None:
        paused = AsyncMock(return_value=SubagentOutcome(text="", interrupt={"approval_id": "a1"}))
        with self._lifecycle(execute=paused, record_pause=False) as h:
            await self._drive(inbox_ids=("e1",))

        assert self._delivered(h.deliver) == (EXECUTOR_APPROVAL_LOST_MESSAGE, "error")
        h.spawn.assert_called_once()
