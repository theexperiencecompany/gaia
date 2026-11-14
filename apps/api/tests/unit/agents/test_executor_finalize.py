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
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from prometheus_client import REGISTRY
import pytest

from app.agents.context.live_work import build_executor_status_block, executor_status_text
from app.agents.context.section_context import SectionContext
from app.agents.context.tiers import AgentTier
from app.agents.core.background import (
    executor_channel as ec,
    executor_progress,
    executor_queue as eq,
    executor_runner as er,
    running_registry,
)
from app.agents.core.background.confirmation_gate import spend_confirmation
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
)
from app.agents.core.outcome_review import NOT_REVIEWED, OutcomeReview
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext, SubagentOutcome
from app.constants.agents import AgentTag, OutcomeState
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.conversation import WORK_STOPPED_REPORT
from app.constants.executor import (
    EXECUTOR_CARRY_TASK,
    EXECUTOR_CRASH_MESSAGE,
    EXECUTOR_STEP_LIMIT_MESSAGE,
    INBOX_ENTRY_ID,
    INTERRUPTION_NOTICE,
)
from app.constants.general import FINISH_TASK_NAME
from app.constants.log_tags import LogTag
from app.core.stream_manager import StreamManager
from app.models.agent_models import InboxEntry
from app.models.chat_models import SourceCategory
from app.models.conversation_log_models import WorkOutcome
from app.models.executor_activity_models import ExecutorActivity
from app.models.user_models import AuthenticatedUser
from app.services.conversation.tool_cards import FoldedCards
from shared.py.conversation_wire import ToolDataEntry
from shared.py.wide_events import log, log_context
from tests.helpers import WideEventRecorder

# The task text the finalize step now receives; forwarded to comms on a cancel.
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
TASK = "run the standup summary"


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
        user=AuthenticatedUser(user_id=USER_ID),
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
        self.inbox_cls.return_value.keep_for = AsyncMock()
        self.prepare = stack.enter_context(
            patch.object(er, "prepare_run_from_item", new_callable=AsyncMock, return_value=None)
        )
        #: The run's end as finalize logs it: args[1] is its TerminalOutcome, None when it delivers nothing.
        self.logged = stack.enter_context(
            patch.object(er, "_log_work_finished", new_callable=AsyncMock)
        )


@pytest.fixture(autouse=True)
def _carried_work_is_logged() -> Iterator[None]:
    """Accept every carry run's WorkStarted on the conversation log."""
    with patch.object(er, "record_work_carried", AsyncMock(return_value=True)):
        yield


@pytest.fixture
def boundaries():
    with ExitStack() as stack:
        yield _Boundaries(stack)


class TestACompletedResultIsNeverDiscarded:
    """Regression for prod eefc68cc: Stop landed as the run finished, and the finished answer was thrown away."""

    async def test_a_run_not_said_to_be_stopped_is_a_finished_one(self, boundaries) -> None:
        """The default is the finished run: only the runner, which knows, says otherwise."""
        boundaries.stream_manager.is_cancelled.return_value = True
        create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(_run(RunKind.LIVE), "the answer", "final")

        assert boundaries.logged.await_args.args[1].result_text == "the answer"


def _tool_turn(name: str, args: Mapping[str, object], call_id: str) -> list[AnyMessage]:
    return [
        AIMessage(content="", tool_calls=[{"name": name, "args": dict(args), "id": call_id}]),
        ToolMessage(content="ok", tool_call_id=call_id, name=name, status="success"),
    ]


def _delegation(*work: list[AnyMessage], outcome: str) -> list[AnyMessage]:
    finish = _tool_turn(FINISH_TASK_NAME, {"result": "report", "outcome": outcome}, "finish")
    return [HumanMessage(content=TASK), *(m for turn in work for m in turn), *finish]


@pytest.mark.usefixtures("fake_redis")
class TestTheRunsDeclaredOutcomeIsCheckedAtFinalize:
    """The outcome the executor declares is checked against its own thread before delivery reads it."""

    async def _finalize(
        self, boundaries: _Boundaries, thread: list[AnyMessage]
    ) -> tuple[OutcomeReview, dict[str, Any]]:
        ctx = _executor_ctx()
        create_session("s1", RunKind.QUEUED)
        read = AsyncMock(side_effect=lambda c: thread if c is ctx else [])
        with patch.object(er, "thread_messages", read):
            async with log_context("executor_finalize_test"):
                await er._finalize_executor_run(_run(RunKind.QUEUED), "result", "final", ctx)
                event = dict(log.get())
        return boundaries.logged.await_args.args[1].review, event

    async def test_a_verified_ask_is_voiced_as_an_ask_and_awaits_the_users_answer(
        self, boundaries: _Boundaries
    ) -> None:
        review, event = await self._finalize(boundaries, _delegation(outcome="ask"))

        assert review == OutcomeReview(OutcomeState.ASK, None)
        assert event["executor"] == {"outcome": "ask", "outcome_verified": True}
        assert await spend_confirmation("conv-1") is True

    async def test_an_unbacked_done_is_voiced_as_not_verified_and_named_in_the_wide_event(
        self, boundaries: _Boundaries
    ) -> None:
        problem = "done was declared but no work call succeeded"

        review, event = await self._finalize(boundaries, _delegation(outcome="done"))

        assert review == OutcomeReview(OutcomeState.DONE, problem)
        assert event["executor"] == {"outcome": "done", "outcome_verified": False}
        assert [(w["msg"], w["problem"]) for w in event["warnings"]] == [
            (f"{LogTag.AGENT} Executor outcome not verified", problem)
        ]
        assert await spend_confirmation("conv-1") is False

    async def test_a_verified_done_is_not_taken_for_a_question_to_the_user(
        self, boundaries: _Boundaries
    ) -> None:
        thread = _delegation(_tool_turn("create_todo", {"title": "visa"}, "c1"), outcome="done")

        review, event = await self._finalize(boundaries, thread)

        assert review == OutcomeReview(OutcomeState.DONE, None)
        assert "warnings" not in event
        assert await spend_confirmation("conv-1") is False

    async def test_a_review_that_cannot_read_the_thread_still_delivers_the_result(
        self, boundaries: _Boundaries
    ) -> None:
        create_session("s1", RunKind.QUEUED)
        unreadable = AsyncMock(side_effect=ConnectionError("checkpointer down"))
        with patch.object(er, "thread_messages", unreadable):
            async with log_context("executor_finalize_test"):
                await er._finalize_executor_run(
                    _run(RunKind.QUEUED), "result", "final", _executor_ctx()
                )
                event = dict(log.get())

        assert boundaries.logged.await_args.args[1].result_text == "result"
        assert boundaries.logged.await_args.args[1].review is NOT_REVIEWED
        assert [(e["msg"], e["error_type"]) for e in event["errors"]] == [
            (f"{LogTag.AGENT} Executor outcome review failed", "ConnectionError")
        ]

    async def test_a_run_that_says_it_found_nothing_for_the_user_is_delivered_as_such(
        self, boundaries: _Boundaries
    ) -> None:
        finish = {"result": "report", "outcome": "ask", "nothing_for_user": True}
        thread = [HumanMessage(content=TASK), *_tool_turn(FINISH_TASK_NAME, finish, "finish")]

        review, _ = await self._finalize(boundaries, thread)

        assert review == OutcomeReview(OutcomeState.ASK, None, nothing_for_user=True)

    async def test_a_run_with_no_thread_to_read_is_delivered_unreviewed(
        self, boundaries: _Boundaries
    ) -> None:
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), "result", "final")

        assert boundaries.logged.await_args.args[1].review is NOT_REVIEWED


class TestDoneSignalAndOrdering:
    @pytest.mark.parametrize("cancelled", [True, False])
    async def test_done_event_is_always_signalled(self, boundaries, cancelled) -> None:
        """The chat stream blocks on this event — a missed signal hangs the SSE until the wait timeout, regardless of how the run ended."""
        boundaries.stream_manager.is_cancelled.return_value = cancelled
        session = create_session("s1", RunKind.LIVE)

        await er._finalize_executor_run(_run(RunKind.LIVE), "txt", "final")

        assert session.done_event.is_set()

    async def test_the_approval_cards_are_snapshotted_before_done_signal(self, boundaries) -> None:
        """Once done_event fires, a waiting todo run tears the session down — reading the cards after would race it."""
        session = create_session("s1", RunKind.LIVE)
        done_state_at_drain_time: list[bool] = []

        def _drain(_sid: str) -> tuple[ToolDataEntry, ...]:
            done_state_at_drain_time.append(session.done_event.is_set())
            return ()

        with patch.object(er, "session_approval_cards", side_effect=_drain):
            await er._finalize_executor_run(_run(RunKind.LIVE), "txt", "final")

        assert done_state_at_drain_time == [False]


async def test_a_live_run_carries_only_its_sessions_approval_cards_to_work_finished(
    boundaries,
) -> None:
    session = create_session("s1", RunKind.LIVE)
    session.tool_events.extend(
        [
            {"tool_data": {"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}},
            {"tool_data": {"tool_name": "approval_request", "data": {"approval_id": "a1"}}},
        ]
    )
    await er._finalize_executor_run(_run(RunKind.LIVE), "the digest", "final")
    outcome = boundaries.logged.await_args.args[1]
    assert [card["tool_name"] for card in outcome.approval_cards] == ["approval_request"]


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
            await er._finalize_executor_run(_run(RunKind.QUEUED), "partial", "final", stopped=True)
            await asyncio.sleep(0)

        boundaries.inbox_cls.assert_called_with("conv-1")
        # A run is started to drain the inbox, seeded (not stuffed) with the ask;
        # the handed-over entry is never retired before a run is durably going to
        # take it, so a crash here cannot strand it.
        assert boundaries.prepare.await_args.args[1]["task"] == EXECUTOR_CARRY_TASK
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
                _run(RunKind.QUEUED), "Executor agent not available", "error"
            )
            await asyncio.sleep(0)

        spawn.assert_not_awaited()
        boundaries.inbox_cls.return_value.retire.assert_not_awaited()


class TestLockThenInboxHandoff:
    async def test_the_lock_is_released_then_the_inbox_is_rechecked(self, boundaries) -> None:
        create_session("s1", RunKind.QUEUED)

        await er._finalize_executor_run(_run(RunKind.QUEUED), "result", "final")

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
            await er._finalize_executor_run(_run(RunKind.QUEUED), "result", "final")
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
            await er._finalize_executor_run(_run(RunKind.QUEUED), "result", "final")
            await asyncio.sleep(0)

        boundaries.prepare.assert_not_awaited()
        spawn.assert_not_awaited()


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

    async def exists(self, key: str) -> int:
        return int(key in self.store)

    async def ttl(self, key: str) -> int:
        return -1 if key in self.store else -2

    async def hgetall(self, key: str) -> dict[str, str]:
        return {}


class _FakeRedisCache:
    def __init__(self) -> None:
        self.client = _FakeRedisClient()

    async def delete(self, key: str) -> None:
        await self.client.delete(key)


@contextmanager
def _real_lock_lifecycle(cache: _FakeRedisCache):
    """Drive finalize with the REAL lock functions over an in-memory Redis, so what the turn-start status reads afterwards is what the lock actually says."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(eq, "redis_cache", cache))
        stack.enter_context(patch.object(running_registry, "redis_cache", cache))
        stack.enter_context(patch.object(executor_progress, "redis_cache", cache))
        stack.enter_context(patch.object(er, "StreamManager")).is_cancelled = AsyncMock(
            return_value=False
        )
        stack.enter_context(patch.object(er, "_log_work_finished", new_callable=AsyncMock))
        stack.enter_context(patch.object(er, "ExecutorInbox")).return_value.read = AsyncMock(
            return_value=[]
        )
        yield


async def _status(conversation_id: str) -> str:
    return await build_executor_status_block(
        SectionContext(tier=AgentTier.COMMS, conversation_id=conversation_id)
    )


class TestTheBusyLockDoesNotOutliveTheResult:
    """The lock is what tells comms a task is in flight.

    Released only at the very end of finalize, it was still held while the user read the result —
    comms' next turn was handed "a background task is STILL RUNNING" about work it had already
    delivered — and anything that raised on the way there left it held for the full 30-minute TTL.
    """

    async def test_the_status_reads_idle_once_the_result_is_delivered(self) -> None:
        cache = _FakeRedisCache()
        cache.client.store[f"{EXECUTOR_BUSY_PREFIX}conv-1"] = build_lock_value("s1", "task-1")
        create_session("s1", RunKind.LIVE)

        with _real_lock_lifecycle(cache):
            assert await _status("conv-1") == executor_status_text(
                ExecutorActivity.RUNNING, "task-1", running=True
            ), "the lock must read as running before finalize"
            await er._finalize_executor_run(_run(RunKind.LIVE), "8 todos created", "final")
            assert await _status("conv-1") == executor_status_text(
                ExecutorActivity.IDLE, "", running=False
            )

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
                    await er._finalize_executor_run(_run(RunKind.QUEUED), "done", "final")

        assert lock_key not in cache.client.store

    async def test_a_stale_finalize_never_frees_a_newer_runs_lock(self) -> None:
        """Cancel_executor frees the lock and a NEW run acquires it; the OLD cancelled run's finalize firing later must leave that lock alone, or two executors end up running on one conversation."""
        cache = _FakeRedisCache()
        lock_key = f"{EXECUTOR_BUSY_PREFIX}conv-1"
        cache.client.store[lock_key] = build_lock_value("newer-stream", "task-9")
        create_session("s1", RunKind.QUEUED)

        with _real_lock_lifecycle(cache):
            await er._finalize_executor_run(_run(RunKind.QUEUED), "done", "final")

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
        return HumanMessage(content="x", additional_kwargs={INBOX_ENTRY_ID: entry_id})

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

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), _executor_ctx())
            still_pending = [entry.id for entry in await inbox.read()]

        prepare.assert_awaited_once()
        # The run is seeded to drain the inbox, not stuffed with the late work.
        assert prepare.await_args.args[1]["task"] == EXECUTOR_CARRY_TASK
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

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), _executor_ctx())
            still_pending = [entry.id for entry in await inbox.read()]

        # Seeded to drain; the un-committed entry stays for that drain, never
        # retired before a run exists to take it.
        assert prepare.await_args.args[1]["task"] == EXECUTOR_CARRY_TASK
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
        assert still_pending == [INTERRUPTION_NOTICE]

    async def test_a_stopped_browser_jobs_notice_starts_no_run(self) -> None:
        """The stop already answered the user: a run woken for its notice would answer them again."""
        cache = _FakeInboxCache()

        with ExitStack() as stack:
            stack.enter_context(patch.object(ec, "redis_cache", cache))
            inbox = ec.ExecutorInbox("conv-1")
            await inbox.append("n1", "job-1 was stopped", AgentTag.BROWSER_STOPPED)
            prepare = stack.enter_context(
                patch.object(er, "prepare_run_from_item", new_callable=AsyncMock, return_value=None)
            )

            await er._carry_pending_into_new_run(_run(RunKind.QUEUED), None)
            still_pending = [entry.id for entry in await inbox.read()]

        prepare.assert_not_awaited()
        assert still_pending == ["n1"]

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
        assert prepare.await_args.args[1]["task"] == EXECUTOR_CARRY_TASK
        # Both entries stay in the inbox, each keeping its own tag, for the new
        # run's drain to inject and retire — never stuffed into the seed task.
        assert still_pending == [INTERRUPTION_NOTICE, "book the flight instead"]


class TestExecutorRunSource:
    def test_a_configurable_with_no_source_is_background_work(self) -> None:
        run = ExecutorRun.from_configurable(
            {"user_id": USER_ID},
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

        with patch.object(time, "perf_counter", return_value=1234.5):
            await er._finalize_executor_run(run, "the model call failed", "error")

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

        with patch.object(time, "perf_counter", return_value=1234.5):
            await er._finalize_executor_run(run, "partial text", "final", stopped=True)

        assert (
            _counter("executor_run_total", {"status": "cancelled", "queued": "true"}) == before + 1
        )
        assert (
            _counter("executor_run_total", {"status": "success", "queued": "true"})
            == success_before
        )


# A park re-arms the inbox in Redis: a per-test one, never the ambient client.
def _executor_ctx() -> SubagentExecutionContext:
    return SubagentExecutionContext(
        subagent_graph=MagicMock(),
        agent_name="executor_agent",
        config={"configurable": {}, "agent_name": "executor_agent"},
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
    ) -> Iterator[SimpleNamespace]:
        ctx = _executor_ctx()
        prepare = prepare or AsyncMock(return_value=(ctx, None))
        execute = execute or AsyncMock(return_value=SubagentOutcome(text="all done"))
        thread = [
            HumanMessage(content="x", additional_kwargs={INBOX_ENTRY_ID: entry_id})
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
            deliver = enter(patch.object(er, "_log_work_finished", AsyncMock()))
            enter(patch.object(er, "release_lock_if_owned", AsyncMock()))
            enter(patch.object(StreamManager, "is_cancelled", AsyncMock(return_value=False)))
            enter(patch("app.services.analytics_service.capture", MagicMock()))
            enter(patch.object(eq, "StreamManager", AsyncMock()))
            spawn = enter(patch.object(er, "_spawn_detached_run"))
            yield SimpleNamespace(deliver=deliver, spawn=spawn)

    @staticmethod
    async def _drive(inbox_ids: tuple[str, ...] = ()) -> None:
        inbox = ec.ExecutorInbox("conv-1")
        for entry_id in inbox_ids:
            await inbox.append(entry_id, f"handed over {entry_id}")
        await er.run_executor_background(
            run=_run(RunKind.LIVE), task=TASK, configurable={"user_id": USER_ID}
        )

    @staticmethod
    def _delivered(deliver: AsyncMock) -> tuple[str, str]:
        run, outcome = deliver.await_args.args
        assert run.stream_id == "s1"
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
        ],
        ids=["crash", "recursion-limit"],
    )
    async def test_a_run_that_failed_after_setup_carries_the_work_handed_to_it(
        self, fake_redis: Any, execute: AsyncMock, delivered: tuple[str, str]
    ) -> None:
        with self._lifecycle(execute=execute) as h:
            await self._drive(inbox_ids=("e1",))

        assert self._delivered(h.deliver) == delivered
        h.spawn.assert_called_once()
        assert h.spawn.call_args.args[0].task == EXECUTOR_CARRY_TASK


async def test_a_stopped_run_reports_that_the_user_stopped_it() -> None:
    """Regression (live test): a user Stop reported "The executor_agent run ended without reporting a result"."""
    stopped = er.TerminalOutcome(
        result_text="The executor_agent run ended without reporting a result, so nothing confirms any of it happened.",
        result_type="final",
        was_cancelled=True,
    )
    with (
        patch.object(er, "record_work_finished", new_callable=AsyncMock) as record,
        patch.object(er, "work_cards", new=AsyncMock(return_value=FoldedCards())),
    ):
        await er._log_work_finished(_run(RunKind.LIVE), stopped, stopped=True)
    report = record.await_args.args[4]
    assert record.await_args.args[3] is WorkOutcome.CANCELLED
    assert report.text == WORK_STOPPED_REPORT
