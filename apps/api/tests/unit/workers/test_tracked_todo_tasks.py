"""Unit tests for app.workers.tasks.tracked_todo_tasks.

The ARQ side of tracked todos: the lock-guarded entrypoint, the retry/backoff
ladder, the recurrence re-enqueue, the agent execution path (canvas timeline
markers), and the orphan safety net.

The bug these tests pin down: ``scheduled_at`` was only ever moved forward for a
*recurring* todo. After a one-shot run — and during the exponential-backoff
window of a failed run — it kept pointing at a time in the past, which is
exactly what ``find_due_tracked_all_users`` selects on, so
``safety_net_check_orphaned_todos`` re-enqueued those todos every 30 minutes
forever (one-shot) / every 30 minutes instead of after 1h then 4h (retry).
``scheduled_at`` now always names the next planned execution, or nothing.

Recurrence/timezone resolution itself is covered by test_tracked_todo_recurrence.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.constants.todos import FAILED_LABEL
from app.models.agent_models import SilentRunResult
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.workers.tasks.tracked_todo_tasks import (
    MAX_RETRY_ATTEMPTS,
    RETRY_BACKOFF,
    _build_execution_prompt,
    _collect_reference_context,
    _compute_next_run,
    _execute_todo_with_retry,
    _execute_via_agent,
    _extract_learnings,
    _mark_todo_failed,
    _run_execution,
    execute_tracked_todo,
    safety_net_check_orphaned_todos,
)

MODULE = "app.workers.tasks.tracked_todo_tasks"
KOLKATA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")


def _doc(**overrides) -> TodoDocument:
    fields: dict = {
        "id": "todo-1",
        "user_id": "user-1",
        "title": "Check the deploy",
        "labels": ["gaia-tracked"],
    }
    fields.update(overrides)
    return TodoDocument(**fields)


def _pool() -> MagicMock:
    """An ArqRedis stand-in: set/delete/exists/enqueue_job are all awaitables."""
    pool = MagicMock()
    pool.set = AsyncMock(return_value=True)
    pool.delete = AsyncMock(return_value=1)
    pool.exists = AsyncMock(return_value=0)
    pool.enqueue_job = AsyncMock(return_value=MagicMock())
    return pool


def _updates(repo: MagicMock) -> list[dict]:
    """The ``$set`` payloads (explicitly-set fields only) of every repo.update."""
    return [c.kwargs["update"].model_dump(exclude_unset=True) for c in repo.update.call_args_list]


# ---------------------------------------------------------------------------
# execute_tracked_todo — the Redis lock
# ---------------------------------------------------------------------------


class TestExecuteTrackedTodoLock:
    async def test_acquires_lock_with_nx_and_ttl_then_releases_it(self):
        pool = _pool()
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{MODULE}._execute_todo_with_retry", AsyncMock(return_value="success:todo-1")),
        ):
            result = await execute_tracked_todo({}, "todo-1")

        assert result == "success:todo-1"
        pool.set.assert_awaited_once_with("gaia_todo_exec:todo-1", "1", nx=True, ex=1800)
        pool.delete.assert_awaited_once_with("gaia_todo_exec:todo-1")

    async def test_lock_already_held_skips_and_does_not_release_the_other_holders_lock(self):
        """Deleting a lock this run never acquired would break mutual exclusion."""
        pool = _pool()
        pool.set = AsyncMock(return_value=None)
        inner = AsyncMock(return_value="success:todo-1")
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{MODULE}._execute_todo_with_retry", inner),
        ):
            result = await execute_tracked_todo({}, "todo-1")

        assert result == "skipped:todo-1 (lock held)"
        inner.assert_not_awaited()
        pool.delete.assert_not_awaited()

    async def test_lock_is_released_when_execution_raises(self):
        pool = _pool()
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(
                f"{MODULE}._execute_todo_with_retry",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            pytest.raises(RuntimeError, match="mongo down"),
        ):
            await execute_tracked_todo({}, "todo-1")

        pool.delete.assert_awaited_once_with("gaia_todo_exec:todo-1")


# ---------------------------------------------------------------------------
# _execute_todo_with_retry — early exits
# ---------------------------------------------------------------------------


class TestExecuteTodoWithRetryEarlyExits:
    @pytest.fixture(autouse=True)
    def _route_enqueue(self, route_enqueue_via_pool):
        return

    async def _run(self, doc, *, pool=None):
        pool = pool or _pool()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=doc)
        repo.update = AsyncMock()
        run_execution = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}._run_execution", run_execution),
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"timezone": "UTC"})),
        ):
            result = await _execute_todo_with_retry("todo-1", pool)
        return result, repo, run_execution

    async def test_missing_document(self):
        result, _repo, run_execution = await self._run(None)
        assert result == "not_found:todo-1"
        run_execution.assert_not_awaited()

    async def test_already_completed(self):
        result, _repo, run_execution = await self._run(_doc(completed=True))
        assert result == "completed:todo-1"
        run_execution.assert_not_awaited()

    async def test_expired_todo_is_skipped(self):
        past = datetime.now(UTC) - timedelta(seconds=1)
        result, _repo, run_execution = await self._run(_doc(expires_at=past))
        assert result == "expired:todo-1"
        run_execution.assert_not_awaited()

    async def test_expiry_in_the_future_still_executes(self):
        future = datetime.now(UTC) + timedelta(days=1)
        result, _repo, run_execution = await self._run(_doc(expires_at=future))
        assert result == "success:todo-1"
        run_execution.assert_awaited_once()

    async def test_todo_already_marked_failed_is_skipped(self):
        result, _repo, run_execution = await self._run(_doc(labels=["gaia-tracked", FAILED_LABEL]))
        assert result == "skipped:todo-1 (marked failed)"
        run_execution.assert_not_awaited()

    async def test_missing_user_id_is_an_error_not_an_execution(self):
        result, repo, run_execution = await self._run(_doc(user_id=""))
        assert result == "error:todo-1 (missing user_id)"
        run_execution.assert_not_awaited()
        repo.update.assert_not_awaited()


# ---------------------------------------------------------------------------
# _execute_todo_with_retry — success path
# ---------------------------------------------------------------------------


class TestExecuteTodoWithRetrySuccess:
    @pytest.fixture(autouse=True)
    def _route_enqueue(self, route_enqueue_via_pool):
        return

    async def _run(self, doc, *, tz="UTC"):
        pool = _pool()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=doc)
        repo.update = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}._run_execution", AsyncMock()),
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(return_value={"timezone": tz}),
            ),
        ):
            result = await _execute_todo_with_retry("todo-1", pool)
        return result, repo, pool

    async def test_one_shot_success_resets_retries_and_clears_scheduled_at(self):
        """A past scheduled_at left behind after a one-shot run is what
        find_due_tracked_all_users matches on — the safety net would re-enqueue
        the same completed-work run every 30 minutes, forever."""
        stale = datetime.now(UTC) - timedelta(minutes=5)
        result, repo, pool = await self._run(_doc(scheduled_at=stale, recurrence=None))

        assert result == "success:todo-1"
        assert _updates(repo) == [{"gaia_retry_count": 0, "scheduled_at": None}]
        pool.enqueue_job.assert_not_awaited()

    async def test_recurring_success_moves_scheduled_at_forward_and_re_enqueues(self):
        anchor = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
        result, repo, pool = await self._run(_doc(scheduled_at=anchor, recurrence="daily"))

        assert result == "success:todo-1"
        (payload,) = _updates(repo)
        assert payload["gaia_retry_count"] == 0
        next_run = payload["scheduled_at"]
        assert next_run > datetime.now(UTC)
        # Anchored daily keeps the original wall-clock time-of-day.
        assert (next_run - anchor) % timedelta(days=1) == timedelta(0)
        pool.enqueue_job.assert_awaited_once_with(
            "execute_tracked_todo", "todo-1", _defer_until=next_run
        )

    async def test_recurrence_is_evaluated_in_the_users_timezone(self):
        """A cron recurrence means 9am *local*: 03:30 UTC for Asia/Kolkata."""
        _result, repo, _pool_ = await self._run(_doc(recurrence="0 9 * * *"), tz="Asia/Kolkata")
        next_run = _updates(repo)[0]["scheduled_at"]
        assert next_run.astimezone(KOLKATA).hour == 9
        assert next_run.astimezone(UTC).hour == 3
        assert next_run.astimezone(UTC).minute == 30

    async def test_unparseable_recurrence_clears_scheduled_at_and_does_not_enqueue(self):
        """No computable next run means no schedule — leaving the stale past
        value would hand the todo straight back to the safety net."""
        stale = datetime.now(UTC) - timedelta(hours=1)
        result, repo, pool = await self._run(
            _doc(scheduled_at=stale, recurrence="not-a-recurrence")
        )

        assert result == "success:todo-1"
        assert _updates(repo) == [{"gaia_retry_count": 0, "scheduled_at": None}]
        pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# _execute_todo_with_retry — failure / retry ladder
# ---------------------------------------------------------------------------


class TestExecuteTodoWithRetryFailure:
    async def _run(self, doc):
        pool = _pool()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=doc)
        repo.update = AsyncMock()
        repo.add_labels = AsyncMock()
        mark_failed = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}._run_execution", AsyncMock(side_effect=RuntimeError("boom"))),
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"timezone": "UTC"})),
            patch(f"{MODULE}._mark_todo_failed", mark_failed),
        ):
            result = await _execute_todo_with_retry("todo-1", pool)
        return result, repo, pool, mark_failed

    @pytest.mark.parametrize(
        ("retry_count", "expected_backoff"),
        [(0, RETRY_BACKOFF[0]), (1, RETRY_BACKOFF[1])],
    )
    async def test_retry_defers_by_the_backoff_ladder(self, retry_count, expected_backoff):
        before = datetime.now(UTC)
        result, repo, pool, mark_failed = await self._run(_doc(gaia_retry_count=retry_count))
        after = datetime.now(UTC)

        assert result == f"retry:todo-1 (attempt {retry_count + 1})"
        mark_failed.assert_not_awaited()

        next_attempt = pool.enqueue_job.await_args.kwargs["_defer_until"]
        assert before + expected_backoff <= next_attempt <= after + expected_backoff
        assert pool.enqueue_job.await_args.args == ("execute_tracked_todo", "todo-1")

    async def test_retry_parks_scheduled_at_on_the_backoff_target(self):
        """Leaving scheduled_at in the past lets the 30-minute safety net fire
        the retry early, collapsing the 1h/4h backoff to 30 minutes."""
        _result, repo, pool, _mf = await self._run(_doc(gaia_retry_count=0))

        (payload,) = _updates(repo)
        assert payload["gaia_retry_count"] == 1
        assert payload["scheduled_at"] == pool.enqueue_job.await_args.kwargs["_defer_until"]
        assert payload["scheduled_at"] > datetime.now(UTC)

    async def test_final_attempt_marks_failed_and_stops_retrying(self):
        doc = _doc(gaia_retry_count=MAX_RETRY_ATTEMPTS - 1)
        result, repo, pool, mark_failed = await self._run(doc)

        assert result == "failed:todo-1 (max retries reached)"
        pool.enqueue_job.assert_not_awaited()
        mark_failed.assert_awaited_once_with("todo-1", "user-1", doc)
        # The count must be persisted at the cap: the safety net's
        # gaia_retry_count < MAX filter is what keeps it from coming back.
        assert _updates(repo) == [{"gaia_retry_count": MAX_RETRY_ATTEMPTS}]

    async def test_a_retry_count_already_past_the_cap_does_not_get_another_attempt(self):
        result, _repo, pool, mark_failed = await self._run(
            _doc(gaia_retry_count=MAX_RETRY_ATTEMPTS + 5)
        )
        assert result == "failed:todo-1 (max retries reached)"
        pool.enqueue_job.assert_not_awaited()
        mark_failed.assert_awaited_once()


# ---------------------------------------------------------------------------
# _run_execution — workflow vs agent dispatch
# ---------------------------------------------------------------------------


class TestRunExecution:
    async def test_workflow_todo_queues_the_workflow_and_skips_the_agent(self):
        queue = AsyncMock(return_value=True)
        via_agent = AsyncMock()
        with (
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_workflow_execution",
                queue,
            ),
            patch(f"{MODULE}._execute_via_agent", via_agent),
        ):
            await _run_execution(_doc(workflow_id="wf-9"), "user-1", user_data={})

        via_agent.assert_not_awaited()
        queue.assert_awaited_once_with(
            "wf-9", "user-1", {"trigger_type": "scheduled_todo", "todo_id": "todo-1"}
        )

    async def test_failed_workflow_queue_raises_so_the_retry_ladder_engages(self):
        with (
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_workflow_execution",
                AsyncMock(return_value=False),
            ),
            pytest.raises(RuntimeError, match="Failed to queue workflow wf-9 for todo todo-1"),
        ):
            await _run_execution(_doc(workflow_id="wf-9"), "user-1", user_data={})

    async def test_todo_without_a_workflow_runs_the_agent(self):
        via_agent = AsyncMock(return_value="done")
        with patch(f"{MODULE}._execute_via_agent", via_agent):
            await _run_execution(_doc(), "user-1", user_data={"user_id": "user-1"})

        via_agent.assert_awaited_once()
        assert via_agent.await_args.kwargs["user_data"] == {"user_id": "user-1"}


# ---------------------------------------------------------------------------
# _extract_learnings
# ---------------------------------------------------------------------------


class TestExtractLearnings:
    def test_returns_none_when_the_section_is_absent(self):
        assert _extract_learnings("## Current State\nfine") is None

    def test_returns_none_for_an_empty_canvas(self):
        assert _extract_learnings("") is None

    def test_reads_to_the_end_when_learnings_is_the_last_section(self):
        canvas = "## Context\nc\n\n## Learnings\n- retry the API twice"
        assert _extract_learnings(canvas) == "## Learnings\n- retry the API twice"

    def test_stops_at_the_next_section_heading(self):
        canvas = "## Learnings\n- a lesson\n\n## Timeline\n- ran at noon"
        result = _extract_learnings(canvas)
        assert result is not None
        assert "- a lesson" in result
        assert "Timeline" not in result

    def test_handles_learnings_as_the_very_first_line(self):
        canvas = "## Learnings\n- first-line lesson\n\n## Context\nc"
        result = _extract_learnings(canvas)
        assert result == "## Learnings\n- first-line lesson\n"


# ---------------------------------------------------------------------------
# _collect_reference_context
# ---------------------------------------------------------------------------


class TestCollectReferenceContext:
    async def _run(self, ref_ids, *, docs, canvases):
        repo = MagicMock()
        repo.get_by_id = AsyncMock(side_effect=lambda rid: docs.get(rid))
        read = AsyncMock(side_effect=lambda rid, _uid: canvases[rid])
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.read_canvas", read),
        ):
            return await _collect_reference_context(ref_ids, "user-1"), repo, read

    async def test_no_references_short_circuits_without_touching_mongo(self):
        repo = MagicMock()
        repo.get_by_id = AsyncMock()
        with patch(f"{MODULE}.todo_repository", repo):
            assert await _collect_reference_context([], "user-1") == ""
        repo.get_by_id.assert_not_awaited()

    async def test_includes_the_referenced_todo_title_and_its_learnings(self):
        docs = {"r1": _doc(id="r1", title="Last quarter's rollout")}
        canvases = {"r1": "## Learnings\n- ship on Tuesdays\n"}
        result, _repo, _read = await self._run(["r1"], docs=docs, canvases=canvases)

        assert result.startswith("\n\nPast experience (from similar completed todos):\n")
        assert 'From past todo "Last quarter\'s rollout":' in result
        assert "- ship on Tuesdays" in result

    async def test_caps_reference_reads_at_five(self):
        ids = [f"r{i}" for i in range(9)]
        docs = {i: _doc(id=i, title=i) for i in ids}
        canvases = {i: f"## Learnings\n- lesson {i}" for i in ids}
        result, repo, _read = await self._run(ids, docs=docs, canvases=canvases)

        assert repo.get_by_id.await_count == 5
        assert "- lesson r4" in result
        assert "- lesson r5" not in result

    async def test_a_deleted_reference_is_skipped_and_the_rest_still_load(self):
        docs = {"gone": None, "r2": _doc(id="r2", title="Kept")}
        canvases = {"gone": "## Learnings\n- never read", "r2": "## Learnings\n- kept lesson"}
        result, _repo, read = await self._run(["gone", "r2"], docs=docs, canvases=canvases)

        assert "- never read" not in result
        assert "- kept lesson" in result
        # A missing doc must short-circuit before the canvas read.
        assert read.await_count == 1

    async def test_a_canvas_read_failure_does_not_abort_the_remaining_references(self):
        docs = {"bad": _doc(id="bad", title="Bad"), "good": _doc(id="good", title="Good")}
        repo = MagicMock()
        repo.get_by_id = AsyncMock(side_effect=lambda rid: docs[rid])

        async def _read(ref_id: str, _user_id: str) -> str:
            if ref_id == "bad":
                raise RuntimeError("canvas unavailable")
            return "## Learnings\n- good lesson"

        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.read_canvas", AsyncMock(side_effect=_read)),
        ):
            result = await _collect_reference_context(["bad", "good"], "user-1")

        assert "- good lesson" in result
        assert "Bad" not in result

    async def test_references_without_learnings_produce_no_context_block(self):
        docs = {"r1": _doc(id="r1", title="No lessons")}
        canvases = {"r1": "## Current State\nnothing learned"}
        result, _repo, _read = await self._run(["r1"], docs=docs, canvases=canvases)
        assert result == ""

    async def test_a_null_canvas_is_tolerated(self):
        docs = {"r1": _doc(id="r1", title="Empty canvas")}
        canvases = {"r1": None}
        result, _repo, _read = await self._run(["r1"], docs=docs, canvases=canvases)
        assert result == ""


# ---------------------------------------------------------------------------
# _build_execution_prompt
# ---------------------------------------------------------------------------


class TestBuildExecutionPrompt:
    def test_title_only(self):
        assert (
            _build_execution_prompt(
                title="Ship it", description="", canvas_content=None, reference_context=""
            )
            == "Execute the following scheduled task: Ship it"
        )

    def test_all_sections_appear_in_order(self):
        prompt = _build_execution_prompt(
            title="Ship it",
            description="the release",
            canvas_content="## Current State\nblocked",
            reference_context="past stuff",
        )
        assert prompt.split("\n\n") == [
            "Execute the following scheduled task: Ship it",
            "Details: the release",
            "Canvas context:\n## Current State\nblocked",
            "past stuff",
        ]

    def test_empty_canvas_string_is_omitted_not_rendered_as_an_empty_header(self):
        prompt = _build_execution_prompt(
            title="Ship it", description="", canvas_content="", reference_context=""
        )
        assert "Canvas context" not in prompt


# ---------------------------------------------------------------------------
# _execute_via_agent
# ---------------------------------------------------------------------------


class TestExecuteViaAgent:
    def _patches(
        self,
        *,
        agent,
        canvas="## Current State\nall good",
        canvas_side_effect=None,
    ):
        self.timeline = AsyncMock(return_value=True)
        read = (
            AsyncMock(side_effect=canvas_side_effect)
            if canvas_side_effect
            else AsyncMock(return_value=canvas)
        )
        return (
            patch(f"{MODULE}.call_agent_silent", agent),
            patch(f"{MODULE}.read_canvas", read),
            patch(f"{MODULE}.tracked_todo_service.append_canvas_timeline", self.timeline),
            patch(f"{MODULE}._collect_reference_context", AsyncMock(return_value="")),
        )

    def _entries(self) -> list[str]:
        return [c.kwargs["entry"] for c in self.timeline.call_args_list]

    async def test_writes_start_and_success_markers_around_the_agent_call(self):
        agent = AsyncMock(
            return_value=SilentRunResult(message="Deploy verified.\nAll green.", tool_data={})
        )
        p1, p2, p3, p4 = self._patches(agent=agent)
        with p1, p2, p3, p4:
            result = await _execute_via_agent(_doc(), "user-1", user_data={"user_id": "user-1"})

        assert result == "Deploy verified.\nAll green."
        start, end = self._entries()
        assert start.startswith("▶ ")
        assert "scheduled run started (conversation_id=" in start
        assert end.startswith("✓ ")
        assert "summary='Deploy verified. All green.'" in end

    async def test_a_queued_dispatch_is_not_a_finished_run(self):
        """The executor was busy, so the request was queued and answered with an
        acknowledgement. Reading that acknowledgement as the result wrote a
        success marker for work that had not happened (same shape as the
        workflow fire bug fixed in #1129)."""
        agent = AsyncMock(
            return_value=SilentRunResult(
                message="That task is queued behind the one already running.",
                tool_data={},
                queued_task_id="task-9",
            )
        )
        p1, p2, p3, p4 = self._patches(agent=agent)
        with p1, p2, p3, p4:
            result = await _execute_via_agent(_doc(), "user-1", user_data={"user_id": "user-1"})

        assert result == ""
        start, end = self._entries()
        assert start.startswith("▶ ")
        assert not end.startswith("✓ ")
        assert "queued" in end and "task-9" in end

    async def test_the_queued_marker_names_the_todo_the_user_and_the_queued_task(self):
        """Every field of the queued branch, on the values the branch is for. The
        marker is the only place the user sees that the run did not happen, and the
        warning is the only place an operator does, so a field silently dropped or
        blanked from either is the whole finding."""
        recorded: list[dict[str, str]] = []

        # append_canvas_timeline's real signature, so an argument the branch stops
        # passing is a TypeError here rather than a quietly thinner call.
        async def timeline(todo_id: str, user_id: str, entry: str) -> bool:
            recorded.append({"todo_id": todo_id, "user_id": user_id, "entry": entry})
            return True

        agent = AsyncMock(
            return_value=SilentRunResult(
                message="That task is queued.", tool_data={}, queued_task_id="task-9"
            )
        )
        with (
            patch(f"{MODULE}.call_agent_silent", agent),
            patch(f"{MODULE}.read_canvas", AsyncMock(return_value="")),
            patch(f"{MODULE}.tracked_todo_service.append_canvas_timeline", timeline),
            patch(f"{MODULE}._collect_reference_context", AsyncMock(return_value="")),
            patch(f"{MODULE}.log") as log_mock,
        ):
            result = await _execute_via_agent(
                _doc(id="todo-7"), "user-9", user_data={"user_id": "user-9"}
            )

        assert result == ""
        queued = recorded[1]
        assert queued["todo_id"] == "todo-7"
        assert queued["user_id"] == "user-9"
        stamp = queued["entry"].split(" ", 2)[1]
        assert queued["entry"] == (
            f"⏸ {stamp} — scheduled run queued behind an in-flight run (task task-9); not run"
        )
        # Stamped in UTC: a naive or local timestamp reads as a different moment
        # to anyone reading the canvas from another timezone.
        assert datetime.fromisoformat(stamp).utcoffset() == timedelta(0)
        assert log_mock.warning.call_args.args == ("tracked_todo.agent_dispatch_queued",)
        assert log_mock.warning.call_args.kwargs == {
            "todo_id": "todo-7",
            "queued_task_id": "task-9",
        }

    async def test_the_start_marker_is_written_before_the_agent_runs(self):
        """A run that dies inside the agent must still leave evidence."""
        order: list[str] = []
        timeline = AsyncMock(side_effect=lambda **kw: order.append("timeline"))
        agent = AsyncMock(
            side_effect=lambda **kw: (
                order.append("agent"),
                SilentRunResult(message="ok", tool_data={}),
            )[1]
        )
        with (
            patch(f"{MODULE}.call_agent_silent", agent),
            patch(f"{MODULE}.read_canvas", AsyncMock(return_value="")),
            patch(f"{MODULE}.tracked_todo_service.append_canvas_timeline", timeline),
        ):
            await _execute_via_agent(_doc(), "user-1", user_data={})

        assert order == ["timeline", "agent", "timeline"]

    async def test_prompt_and_trigger_context_carry_the_todo_identity(self):
        agent = AsyncMock(return_value=SilentRunResult(message="ok", tool_data={}))
        p1, p2, p3, p4 = self._patches(agent=agent, canvas="## Current State\nblocked")
        with p1, p2, p3, p4:
            await _execute_via_agent(
                _doc(description="verify staging"), "user-1", user_data={"user_id": "user-1"}
            )

        kwargs = agent.await_args.kwargs
        assert kwargs["options"].trigger_context == {
            "trigger_type": "scheduled_todo",
            "todo_id": "todo-1",
            "todo_title": "Check the deploy",
            "active_todo_id": "todo-1",
            "execution_mode": "background",
        }
        assert kwargs["user"] == {"user_id": "user-1"}
        prompt = kwargs["request"].message
        assert "Execute the following scheduled task: Check the deploy" in prompt
        assert "Details: verify staging" in prompt
        assert "Canvas context:\n## Current State\nblocked" in prompt

    async def test_each_run_gets_a_fresh_conversation_id(self):
        agent = AsyncMock(return_value=SilentRunResult(message="ok", tool_data={}))
        p1, p2, p3, p4 = self._patches(agent=agent)
        with p1, p2, p3, p4:
            await _execute_via_agent(_doc(), "user-1", user_data={})
            await _execute_via_agent(_doc(), "user-1", user_data={})

        first, second = (c.kwargs["conversation_id"] for c in agent.call_args_list)
        assert first != second

    async def test_a_canvas_read_failure_does_not_abort_the_run(self):
        agent = AsyncMock(return_value=SilentRunResult(message="ok", tool_data={}))
        p1, p2, p3, p4 = self._patches(agent=agent, canvas_side_effect=RuntimeError("mongo down"))
        with p1, p2, p3, p4:
            result = await _execute_via_agent(_doc(), "user-1", user_data={})

        assert result == "ok"
        assert "Canvas context" not in agent.await_args.kwargs["request"].message

    async def test_an_agent_exception_writes_a_failure_marker_and_propagates(self):
        agent = AsyncMock(side_effect=TimeoutError("llm timeout"))
        p1, p2, p3, p4 = self._patches(agent=agent)
        with p1, p2, p3, p4, pytest.raises(TimeoutError):
            await _execute_via_agent(_doc(), "user-1", user_data={})

        _start, end = self._entries()
        assert "scheduled run failed (TimeoutError)" in end

    async def test_an_empty_agent_response_is_not_an_error(self):
        agent = AsyncMock(return_value=SilentRunResult(message="", tool_data={}))
        p1, p2, p3, p4 = self._patches(agent=agent)
        with p1, p2, p3, p4:
            result = await _execute_via_agent(_doc(), "user-1", user_data={})

        assert result == ""
        assert "summary=''" in self._entries()[1]

    async def test_a_long_response_is_truncated_for_the_return_value_and_the_marker(self):
        agent = AsyncMock(return_value=SilentRunResult(message="x" * 500, tool_data={}))
        p1, p2, p3, p4 = self._patches(agent=agent)
        with p1, p2, p3, p4:
            result = await _execute_via_agent(_doc(), "user-1", user_data={})

        assert result == "x" * 200
        assert f"summary={'x' * 120!r}" in self._entries()[1]


# ---------------------------------------------------------------------------
# _mark_todo_failed
# ---------------------------------------------------------------------------


class TestMarkTodoFailed:
    async def test_labels_the_todo_and_notifies_the_user(self):
        repo = MagicMock()
        repo.add_labels = AsyncMock()
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.notification_service.create_notification", notify),
        ):
            await _mark_todo_failed("todo-1", "user-1", _doc(title="Nightly backup"))

        repo.add_labels.assert_awaited_once_with("todo-1", user_id="user-1", labels=[FAILED_LABEL])
        request = notify.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB
        assert request.type == NotificationType.ERROR
        assert request.content.title == "Scheduled Task Failed: Nightly backup"
        assert f"after {MAX_RETRY_ATTEMPTS} attempts" in request.content.body
        assert request.metadata == {"todo_id": "todo-1", "retry_count": MAX_RETRY_ATTEMPTS}

    async def test_a_notification_failure_never_loses_the_failed_label(self):
        repo = MagicMock()
        repo.add_labels = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(
                f"{MODULE}.notification_service.create_notification",
                AsyncMock(side_effect=RuntimeError("notification bus down")),
            ),
        ):
            await _mark_todo_failed("todo-1", "user-1", _doc())

        repo.add_labels.assert_awaited_once()


# ---------------------------------------------------------------------------
# _compute_next_run — cases not covered by test_tracked_todo_recurrence.py
# ---------------------------------------------------------------------------


class TestComputeNextRunExtra:
    def test_every_4h_is_a_four_hour_delta_from_now(self):
        before = datetime.now(UTC)
        next_run = _compute_next_run("every_4h")
        after = datetime.now(UTC)
        assert next_run is not None
        assert before + timedelta(hours=4) <= next_run <= after + timedelta(hours=4)

    @pytest.mark.parametrize(
        ("recurrence", "step"), [("daily", timedelta(days=1)), ("weekly", timedelta(weeks=1))]
    )
    def test_without_an_anchor_it_falls_back_to_a_plain_delta(self, recurrence, step):
        before = datetime.now(UTC)
        next_run = _compute_next_run(recurrence, "Asia/Kolkata", anchor=None)
        after = datetime.now(UTC)
        assert next_run is not None
        assert before + step <= next_run <= after + step

    def test_anchored_weekly_keeps_the_weekday_and_the_local_time_of_day(self):
        anchor = (datetime.now(KOLKATA) - timedelta(weeks=5)).replace(
            hour=7, minute=45, second=0, microsecond=0
        )
        next_run = _compute_next_run("weekly", "Asia/Kolkata", anchor=anchor)

        assert next_run is not None
        assert next_run > datetime.now(UTC)
        local = next_run.astimezone(KOLKATA)
        assert (local.hour, local.minute) == (7, 45)
        assert local.weekday() == anchor.weekday()
        assert (local.date() - anchor.date()).days % 7 == 0

    def test_an_anchor_already_in_the_future_is_kept_as_is(self):
        anchor = datetime.now(UTC) + timedelta(hours=6)
        assert _compute_next_run("daily", "UTC", anchor=anchor) == anchor

    def test_an_anchor_exactly_at_now_advances_by_a_full_step(self):
        """The boundary: `<=` must advance, otherwise the next run is now and
        the job re-fires immediately in a tight loop."""
        now = datetime.now(UTC)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = now
            next_run = _compute_next_run("daily", "UTC", anchor=now)

        assert next_run == now + timedelta(days=1)

    def test_daily_across_a_dst_transition_holds_the_local_wall_clock(self):
        """US DST starts 2025-03-09. An anchor at 08:00 EST must still be 08:00
        EDT afterwards — i.e. 13:00 UTC becomes 12:00 UTC, not a fixed +24h."""
        anchor = datetime(2025, 3, 8, 8, 0, tzinfo=NEW_YORK)
        frozen_now = datetime(2025, 3, 8, 20, 0, tzinfo=UTC)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            next_run = _compute_next_run("daily", "America/New_York", anchor=anchor)

        assert next_run is not None
        assert next_run.astimezone(NEW_YORK).hour == 8
        assert next_run == datetime(2025, 3, 9, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# safety_net_check_orphaned_todos
# ---------------------------------------------------------------------------


class TestSafetyNet:
    async def _run(self, candidates, *, locked: set[str] | None = None):
        locked = locked or set()
        pool = _pool()
        pool.exists = AsyncMock(side_effect=lambda key: 1 if key in locked else 0)
        repo = MagicMock()
        repo.find_due_tracked_all_users = AsyncMock(return_value=candidates)
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        ):
            result = await safety_net_check_orphaned_todos({})
        return result, repo, pool

    async def test_queries_only_due_todos_still_under_the_retry_budget(self):
        before = datetime.now(UTC)
        _result, repo, _pool_ = await self._run([])
        after = datetime.now(UTC)

        kwargs = repo.find_due_tracked_all_users.await_args.kwargs
        assert before <= kwargs["now"] <= after
        assert kwargs["max_retries"] == MAX_RETRY_ATTEMPTS
        assert kwargs["limit"] == 100

    async def test_no_candidates_reports_zero(self):
        result, _repo, pool = await self._run([])
        assert result == "re_enqueued:0 skipped:0"
        pool.enqueue_job.assert_not_awaited()

    async def test_re_enqueues_an_orphan_with_bounded_jitter(self):
        before = datetime.now(UTC)
        result, _repo, pool = await self._run([_doc(id="orphan")])
        after = datetime.now(UTC)

        assert result == "re_enqueued:1 skipped:0"
        run_at = pool.enqueue_job.await_args.kwargs["_defer_until"]
        assert pool.enqueue_job.await_args.args == ("execute_tracked_todo", "orphan")
        assert before <= run_at <= after + timedelta(seconds=60)

    async def test_a_todo_already_executing_is_skipped_not_double_enqueued(self):
        result, _repo, pool = await self._run(
            [_doc(id="running")], locked={"gaia_todo_exec:running"}
        )
        assert result == "re_enqueued:0 skipped:1"
        pool.enqueue_job.assert_not_awaited()

    async def test_locked_and_orphaned_todos_are_counted_separately(self):
        candidates = [_doc(id="a"), _doc(id="b"), _doc(id="c")]
        result, _repo, pool = await self._run(candidates, locked={"gaia_todo_exec:b"})

        assert result == "re_enqueued:2 skipped:1"
        enqueued = {c.args[1] for c in pool.enqueue_job.call_args_list}
        assert enqueued == {"a", "c"}

    async def test_jitter_spreads_the_load_rather_than_stacking_every_todo_on_now(self):
        candidates = [_doc(id=f"t{i}") for i in range(40)]
        _result, _repo, pool = await self._run(candidates)

        run_ats = {c.kwargs["_defer_until"] for c in pool.enqueue_job.call_args_list}
        assert len(run_ats) > 1
