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
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import (
    executor_queue as eq,
    executor_runner as er,
    result_delivery as rd,
    session as sess,
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
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.models.chat_models import SourceCategory
from shared.py.wide_events import log, log_context

# The task text the finalize step now receives; forwarded to comms on a cancel.
TASK = "run the standup summary"
CARD_NOTE = wrap_agent_payload(AgentTag.RETURNED_TO_FRONTEND, "todo_data (1 todo)")


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


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
        user={"user_id": "u1"},
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
        self.release = stack.enter_context(
            patch.object(er, "release_lock_if_owned", new_callable=AsyncMock)
        )
        self.reclaim = stack.enter_context(
            patch.object(er, "reclaim_stranded_task", new_callable=AsyncMock, return_value=None)
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
        # and the queue still rechecked (cancel-all clears the queue itself
        # before this runs).
        boundaries.release.assert_awaited_once()
        boundaries.reclaim.assert_awaited_once()
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


class TestBackgroundRunCardsSurviveTheCommsDrain:
    """A scheduled workflow's tool cards must reach the bot message it saves.

    The comms silent path and the executor's delivery read the run's cards off
    the SAME session. ``call_agent_silent`` waits on ``done_event``, drains, and
    tears the session down in its ``finally`` — so a delivery that reads the
    session AFTER signalling done finds nothing left. The symptom: a workflow
    run whose execution record listed every tool call saved a bot message with
    an empty ``tool_data``, and the chat showed no "Used N tools" thread.
    """

    @staticmethod
    def _delivery_seams(stack: ExitStack) -> AsyncMock:
        """Patch delivery's I/O only; the real card-attaching logic runs."""
        stack.enter_context(patch.object(er, "StreamManager")).is_cancelled = AsyncMock(
            return_value=False
        )
        stack.enter_context(patch.object(er, "release_lock_if_owned", new_callable=AsyncMock))
        stack.enter_context(
            patch.object(er, "reclaim_stranded_task", new_callable=AsyncMock, return_value=None)
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
            """What ``call_agent_silent`` does around a workflow's graph run."""
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
        boundaries.reclaim.return_value = PreparedQueuedTask(
            run=next_run,
            task="the queued ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "partial", "final")
            await asyncio.sleep(0)

        boundaries.reclaim.assert_awaited_once_with("conv-1")
        spawn.assert_awaited_once()

    async def test_a_stranded_queue_is_claimed_and_spawned(self, boundaries) -> None:
        """BUG A: a task enqueued while the finished run still held the lock (or
        left behind a cancel-freed lock) must be claimed and spawned, not left to
        expire silently with the queue TTL."""
        create_session("s1", RunKind.QUEUED)
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.reclaim.return_value = PreparedQueuedTask(
            run=next_run,
            task="stranded ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")
            await asyncio.sleep(0)

        boundaries.reclaim.assert_awaited_once_with("conv-1")
        spawn.assert_awaited_once()


class TestRecordPause:
    """``_record_pause`` must fail the run, never the process, when the write fails.

    A batch pause with no resumable context is worse than an error: it holds the
    busy lock for its full TTL waiting on a resume that can never come. The
    caller (``run_executor_background``) treats a False return as "fail this
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


class TestFinalizeDeliveryFailureDoesNotStrandQueue:
    """A delivery/close failure inside finalize must not skip the queue handoff
    below it — otherwise queued work strands and the busy lock leaks until its
    TTL (see the comment on the guarding except in _finalize_executor_run)."""

    async def test_delivery_blowing_up_still_hands_off_the_queue(self, boundaries) -> None:
        run = _run(RunKind.QUEUED)
        create_session("s1", RunKind.QUEUED)
        boundaries.deliver.side_effect = RuntimeError("delivery blew up")
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.reclaim.return_value = PreparedQueuedTask(
            run=next_run,
            task="the queued ask",
            configurable={"stream_id": "queued_next"},
        )

        with patch.object(er, "run_executor_background", new_callable=AsyncMock) as spawn:
            await er._finalize_executor_run(run, TASK, "result", "final")  # must not raise
            await asyncio.sleep(0)

        boundaries.release.assert_awaited_once()  # and the lock still goes
        boundaries.reclaim.assert_awaited_once_with("conv-1")
        spawn.assert_awaited_once()  # the queued task still gets spawned

    async def test_a_swallowed_delivery_failure_is_named_in_the_wide_event(
        self, boundaries
    ) -> None:
        """Swallowing the exception is deliberate — losing it is not.

        ``log.error`` is what puts the failure in the wide event's ``errors[]``;
        without the cause in it, a user whose result never arrived leaves an
        event that says the run finished cleanly.
        """
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
        """The other swallowing except in finalize. Its message is the only thing
        separating a failed lock release from a failed delivery in the event."""
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


class TestQueueLockHandoff:
    async def test_the_lock_is_released_then_the_queue_is_rechecked(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "result", "final")

        boundaries.release.assert_awaited_once()
        boundaries.reclaim.assert_awaited_once_with("conv-1")

    async def test_a_claimed_next_task_is_spawned(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)
        next_run = _run(RunKind.QUEUED, stream_id="queued_next")
        boundaries.reclaim.return_value = PreparedQueuedTask(
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

    async def llen(self, key: str) -> int:
        return 0

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class _FakeRedisCache:
    def __init__(self) -> None:
        self.client = _FakeRedisClient()

    async def delete(self, key: str) -> None:
        await self.client.delete(key)


@contextmanager
def _real_lock_lifecycle(cache: _FakeRedisCache):
    """Drive finalize with the REAL lock functions over an in-memory Redis, so
    what the status hook reads afterwards is what the lock actually says."""
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
        stack.enter_context(
            patch.object(er, "_queue_collection_if_uncollected", new_callable=AsyncMock)
        )
        yield


async def _status_frames(thread_id: str) -> list[str]:
    state = await executor_status.executor_status_hook(
        {"messages": []}, {"configurable": {"thread_id": thread_id}}, store=None
    )
    return [str(m.content) for m in state["messages"]]


class TestTheBusyLockDoesNotOutliveTheResult:
    """The lock is what tells comms a task is in flight. Released only at the very
    end of finalize, it was still held while the user read the result — comms'
    next turn was handed "a background task is STILL RUNNING" about work it had
    already delivered — and anything that raised on the way there left it held
    for the full 30-minute TTL."""

    async def test_the_status_frame_is_gone_once_the_result_is_delivered(self) -> None:
        cache = _FakeRedisCache()
        cache.client.store[f"{EXECUTOR_BUSY_PREFIX}conv-1"] = build_lock_value("s1", "task-1")
        create_session("s1", RunKind.LIVE)

        with _real_lock_lifecycle(cache):
            assert await _status_frames("conv-1"), "the lock must read as running before finalize"
            await er._finalize_executor_run(_run(RunKind.LIVE), TASK, "8 todos created", "final")
            assert await _status_frames("conv-1") == []

    async def test_the_lock_is_released_even_when_the_queue_handoff_blows_up(self) -> None:
        cache = _FakeRedisCache()
        lock_key = f"{EXECUTOR_BUSY_PREFIX}conv-1"
        cache.client.store[lock_key] = build_lock_value("s1", "task-1")
        create_session("s1", RunKind.QUEUED)

        with _real_lock_lifecycle(cache):
            with patch.object(
                er,
                "reclaim_stranded_task",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(RuntimeError):
                    await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "done", "final")

        assert lock_key not in cache.client.store

    async def test_a_stale_finalize_never_frees_a_newer_runs_lock(self) -> None:
        """cancel_executor frees the lock and a NEW run acquires it; the OLD
        cancelled run's finalize firing later must leave that lock alone, or two
        executors end up running on one conversation."""
        cache = _FakeRedisCache()
        lock_key = f"{EXECUTOR_BUSY_PREFIX}conv-1"
        cache.client.store[lock_key] = build_lock_value("newer-stream", "task-9")
        create_session("s1", RunKind.QUEUED)

        with _real_lock_lifecycle(cache):
            await er._finalize_executor_run(_run(RunKind.QUEUED), TASK, "done", "final")

        assert cache.client.store[lock_key] == build_lock_value("newer-stream", "task-9")


class TestTheCardNoteOnlyGoesWhereCardsRender:
    """``returned_to_frontend`` tells comms "these items are already on screen,
    don't re-type them". On a bot conversation there is no screen — the reply is
    plain text over the platform API — so the note suppresses the only copy of
    the data the user would ever see."""

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
        """Its delivery is text-only too, and the narrator was already dropping
        the note for it — building it was wasted work with one more way to leak."""
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
    """The one serialized run-context shape, written by the queue and by the HIL
    resume store and read back by ``prepare_run_from_item``. A renamed or dropped
    key here is invisible on write and only shows when a resumed run silently
    loses what a queued run kept."""

    def test_every_field_survives_the_round_trip_shape(self) -> None:
        item = build_run_item(
            task="triage my inbox",
            task_id="task-1",
            configurable={"user_id": "user-1", "thread_id": "conv-1"},
            conversation_id="conv-1",
            user_message_id="user-msg-1",
            bot_message_id="bot-msg-1",
        )

        assert item["task"] == "triage my inbox"
        assert item["task_id"] == "task-1"
        assert item["conversation_id"] == "conv-1"
        assert item["user_message_id"] == "user-msg-1"
        assert item["bot_message_id"] == "bot-msg-1"

    def test_a_plain_enqueue_carries_no_bot_message_id(self) -> None:
        """Only a HIL pause sets it; a queued run must still carry the key, as
        ``prepare_run_from_item`` reads it unconditionally."""
        item = build_run_item(
            task="t",
            task_id=None,
            configurable={"user_id": "user-1"},
            conversation_id="conv-1",
            user_message_id=None,
        )

        assert item["bot_message_id"] is None
