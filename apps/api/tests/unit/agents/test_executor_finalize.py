"""Unit tests for the executor terminal routing matrix (_finalize_executor_run).

These are the regression tests for the "tool_data vanishes on stop" bug class:
every (cancelled? × kind × workflow) combination must route to exactly the
right terminal action. If a future change reintroduces an early-return on
cancellation, or flips ownership, these fail.

Boundaries mocked: Redis (StreamManager, redis_cache), queue pop, and the two
delivery entry points (each pinned by its own test file). Session state and
the routing logic under test are real.
"""

import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import executor_runner as er, session as sess
from app.agents.core.background.executor_queue import LockState, PreparedQueuedTask
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    create_session,
    get_session,
)

# The task text the finalize step now receives; forwarded to comms on a cancel.
TASK = "run the standup summary"


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _run(kind: RunKind, *, workflow_id: str | None = None, stream_id: str = "s1") -> ExecutorRun:
    return ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user={"user_id": "u1"},
        kind=kind,
        task_id="task-1",
        user_message_id=None,
        workflow_id=workflow_id,
    )


class _Boundaries:
    """All patched collaborators for one _finalize_executor_run call."""

    def __init__(self, stack) -> None:
        self.stream_manager = stack.enter_context(patch.object(er, "StreamManager"))
        self.stream_manager.is_cancelled = AsyncMock(return_value=False)
        self.stream_manager.publish_chunk = AsyncMock()
        self.stream_manager.complete_stream = AsyncMock()
        self.lock_state = stack.enter_context(
            patch.object(er, "get_lock_state", new_callable=AsyncMock, return_value=LockState.OURS)
        )
        self.release = stack.enter_context(
            patch.object(er, "release_lock_if_owned", new_callable=AsyncMock)
        )
        self.reclaim = stack.enter_context(
            patch.object(er, "reclaim_stranded_task", new_callable=AsyncMock, return_value=None)
        )
        self.pop = stack.enter_context(
            patch.object(er, "pop_next_queued_run", new_callable=AsyncMock, return_value=None)
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


@pytest.mark.unit
class TestCancelledRouting:
    async def test_cancelled_queued_run_persists_cards_and_skips_delivery(self, boundaries) -> None:
        boundaries.stream_manager.is_cancelled.return_value = True
        run = _run(RunKind.QUEUED)
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(run, TASK, "partial text", "final")

        # Comms' context must record the cancellation regardless of card ownership.
        boundaries.record_cancel.assert_awaited_once_with(run.conversation_id, run.task_id, TASK)
        boundaries.persist_cancelled.assert_awaited_once_with(run)
        boundaries.deliver.assert_not_awaited()
        # Queued stream is closed silently: no [DONE], no complete_stream.
        boundaries.stream_manager.publish_chunk.assert_not_awaited()
        boundaries.stream_manager.complete_stream.assert_not_awaited()
        # A cancel targets the RUNNING task only — the queue is still handed
        # off (cancel-all clears the queue itself before this runs), and with
        # nothing queued the lock is released.
        boundaries.pop.assert_awaited_once()
        boundaries.release.assert_awaited_once()
        # Queued sessions are torn down by finalize.
        assert get_session("s1") is None

    async def test_cancelled_live_run_defers_to_comms_ownership(self, boundaries) -> None:
        """Live cancel: the comms stream attaches the cards — the executor must
        NOT persist them too, or every stopped turn would show duplicates."""
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
        boundaries.persist_cancelled.assert_awaited_once_with(run)
        boundaries.deliver.assert_not_awaited()

    async def test_cancelled_run_skips_returned_note(self, boundaries) -> None:
        # The note drains the session for prompt context — pointless after a
        # cancel and it would race teardown.
        boundaries.stream_manager.is_cancelled.return_value = True
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "txt", "final")

        boundaries.note.assert_not_called()


@pytest.mark.unit
class TestCompletedRouting:
    async def test_completed_queued_run_delivers_and_closes_stream(self, boundaries) -> None:
        run = _run(RunKind.QUEUED)
        create_session("s1", RunKind.QUEUED)
        boundaries.note.return_value = "[RETURNED_TO_FRONTEND] cards"

        await er._finalize_executor_run(run, TASK, "result", "final")

        boundaries.deliver.assert_awaited_once_with(
            run, "result", "final", "[RETURNED_TO_FRONTEND] cards"
        )
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


@pytest.mark.unit
class TestDoneSignalAndOrdering:
    @pytest.mark.parametrize("cancelled", [True, False])
    async def test_done_event_is_always_signalled(self, boundaries, cancelled) -> None:
        """The chat stream blocks on this event — a missed signal hangs the SSE
        until the wait timeout, regardless of how the run ended."""
        boundaries.stream_manager.is_cancelled.return_value = cancelled
        session = create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "txt", "final")

        assert session.done_event.is_set()

    async def test_returned_note_is_snapshotted_before_done_signal(self, boundaries) -> None:
        """Once done_event fires, the chat stream drains + tears down the session
        in parallel — reading the note after would race teardown."""
        session = create_session("s1", RunKind.LIVE)
        done_state_at_note_time: list[bool] = []
        boundaries.note.side_effect = lambda _sid: (
            done_state_at_note_time.append(session.done_event.is_set()),
            "",
        )[1]

        await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "txt", "final")

        assert done_state_at_note_time == [False]


@pytest.mark.unit
class TestQueueLockBugs:
    """Adversarial tests for the lock/queue lifecycle.

    Written red-first: each pins a real defect in the handoff protocol.
    """

    async def test_stop_does_not_strand_queued_tasks(self, boundaries) -> None:
        """BUG B: user queues a second task while one runs, then presses Stop.
        The cancelled run's finalize must still hand the queue off — otherwise
        the acknowledged ('queued, I'll handle it right after') task silently
        never runs and expires in Redis."""
        boundaries.stream_manager.is_cancelled.return_value = True
        create_session("s1", RunKind.QUEUED)
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.pop.return_value = PreparedQueuedTask(
            run=next_run,
            task="the queued ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "partial", "final")
            await asyncio.sleep(0)

        boundaries.pop.assert_awaited_once_with("conv-1")
        spawn.assert_awaited_once()

    async def test_stale_finalize_never_releases_a_lock_it_does_not_own(self, boundaries) -> None:
        """BUG C: cancel_executor frees the lock and a NEW run acquires it; when
        the OLD cancelled run's finalize fires later it must not delete the new
        holder's lock (that would allow concurrent executors)."""
        boundaries.stream_manager.is_cancelled.return_value = True
        create_session("s1", RunKind.QUEUED)
        # The busy lock now belongs to someone else entirely.
        boundaries.lock_state.return_value = LockState.FOREIGN

        await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "partial", "final")

        boundaries.release.assert_not_awaited()
        boundaries.pop.assert_not_awaited()  # not ours to hand off
        boundaries.reclaim.assert_not_awaited()  # the owner's finalize drains it

    async def test_free_lock_with_stranded_queue_is_reclaimed(self, boundaries) -> None:
        """BUG A: a task enqueued in the pop→release race window (or left
        behind a cancel-freed lock) must be reclaimed and spawned, not left to
        expire silently with the queue TTL."""
        create_session("s1", RunKind.QUEUED)
        boundaries.lock_state.return_value = LockState.FREE
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.reclaim.return_value = PreparedQueuedTask(
            run=next_run,
            task="stranded ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")
            await asyncio.sleep(0)

        boundaries.pop.assert_not_awaited()  # not owner — never overwrite the lock
        boundaries.reclaim.assert_awaited_once_with("conv-1")
        spawn.assert_awaited_once()


@pytest.mark.unit
class TestQueueLockHandoff:
    async def test_no_next_task_releases_the_busy_lock_then_rechecks(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")

        boundaries.pop.assert_awaited_once_with("conv-1")
        boundaries.release.assert_awaited_once()
        # The post-release recheck that closes the enqueue↔release race.
        boundaries.reclaim.assert_awaited_once_with("conv-1")

    async def test_prepared_next_task_is_spawned_and_lock_kept(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.pop.return_value = PreparedQueuedTask(
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
        # Lock handed off to the next run — must NOT be released or reclaimed.
        boundaries.release.assert_not_awaited()
        boundaries.reclaim.assert_not_awaited()
