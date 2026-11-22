"""Unit tests for tracked_todo_service (GAIA working-memory todo lifecycle).

Covers the VFS label + canvas/log persistence + ChromaDB indexing pipeline,
completion/archival, and the context-summary renderers the agent sees.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import time_machine

from app.constants.todos import (
    CANVAS_SECTIONS,
    GAIA_TRACKED_LABEL,
    SUB_TODO_PARENT_WAKE_DELAY,
    TodoActivityEvent,
    WaitingOn,
)
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    Priority,
    TodoDocument,
    TodoResponse,
    TodoUpdate,
)
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.canvas_markdown import normalize_canvas
from app.services.tasks.notes import CANVAS_TEMPLATE, starting_canvas
from app.services.tracked_todo_service import (
    TrackedTodoService,
    tracked_todo_service,
)
from app.utils.occurrence import occurrence_stamp
from tests.helpers import captured_wide_event

_MOD = "app.services.tracked_todo_service"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "labels": [GAIA_TRACKED_LABEL, "work"],
        "vfs_path": f"/workspace/gaia-tasks/{TODO_ID}",
        "canvas_content": "# Prepare Q3 report\n\n## Key Details\nthread: abc123\n\n## Timeline\n- step one\n",
        "log_content": "# System Log\n",
        "completed": False,
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(hours=1),
        "due_date": None,
    }
    data.update(overrides)
    return TodoDocument.model_validate(data)


def _todo_response(**overrides: object) -> TodoResponse:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TodoResponse.model_validate(data)


@pytest.fixture
def mock_repo():
    with patch(f"{_MOD}.todo_repository") as m:
        m.get = AsyncMock(return_value=None)
        m.update = AsyncMock(return_value=None)
        m.list_active_tracked = AsyncMock(return_value=[])
        m.find_latest_by_external_ref = AsyncMock(return_value=None)
        m.find_sub_todos = AsyncMock(return_value=[])
        m.count_open_sub_todos = AsyncMock(return_value={})
        m.is_valid_id = MagicMock(side_effect=lambda todo_id: len(todo_id) == 24)
        yield m


@pytest.fixture
def mock_deps():
    with (
        patch(f"{_MOD}.set_canvas_completed", new_callable=AsyncMock) as m_mark,
        patch(f"{_MOD}.RedisPoolManager.get_pool", new_callable=AsyncMock) as m_pool,
        # create=True: append_activity is imported into the service only on
        # this branch. The regression lane runs these tests against base,
        # where the name is absent, and an erroring fixture is not proof.
        patch(f"{_MOD}.append_activity", new_callable=AsyncMock, create=True) as m_append_activity,
        patch(f"{_MOD}.append_log", new_callable=AsyncMock) as m_append_log,
        patch(f"{_MOD}.teardown_subscriptions", new_callable=AsyncMock) as m_teardown,
        patch(f"{_MOD}.record_activity", new_callable=AsyncMock) as m_record,
    ):
        yield SimpleNamespace(
            mark=m_mark,
            pool=m_pool,
            append_activity=m_append_activity,
            append_log=m_append_log,
            teardown=m_teardown,
            record=m_record,
        )


_THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="thread-1")
_REGISTER = "app.services.todos.external_ref_watch.register_subscription"


async def _registered(
    *, trigger_name: str, conditions: list[SubscriptionCondition], **_: object
) -> tuple[TriggerSubscription, None, bool]:
    """Stand in for register_subscription: the stored watch, with no repairs to report."""
    return (
        TriggerSubscription(
            trigger_name=trigger_name,
            conditions=conditions,
            action=SubscriptionAction.EXECUTE,
            resolution=SubscriptionResolution.ACCOUNT,
        ),
        None,
        True,
    )


@pytest.fixture
def watch():
    with (
        patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as m_register,
        patch(
            "app.services.todos.external_ref_watch.unregister_subscription", new_callable=AsyncMock
        ) as m_unregister,
        patch(f"{_MOD}.TodoService.delete_todo", new_callable=AsyncMock) as m_delete,
    ):
        yield SimpleNamespace(register=m_register, unregister=m_unregister, delete=m_delete)


_NEXT_CHECK = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
_REOPENED_ID = "66f838cc8829054e5f10e40b"


def _closed_thread_todo(**overrides: object) -> TodoDocument:
    fields: dict[str, object] = {
        "id": _REOPENED_ID,
        "completed": True,
        "completed_at": datetime(2026, 11, 1, tzinfo=UTC),
        "external_ref": _THREAD,
        "canvas_content": starting_canvas("Reply to Sam", ["Draft, never send."]),
    }
    fields.update(overrides)
    return _todo_doc(**fields)


@asynccontextmanager
async def _reopening(*_args: object, **_kwargs: object) -> AsyncIterator[None]:
    yield


_PARENT_ID = "66f838cc8829054e5f10e401"
_CHILD_ID = "66f838cc8829054e5f10e402"


def _parent(**overrides: object) -> TodoDocument:
    return _todo_doc(id=_PARENT_ID, title="Inbox desk", **overrides)


def _child(**overrides: object) -> TodoDocument:
    fields: dict[str, object] = {"id": _CHILD_ID, "title": "Reply to Sam"}
    fields.update(overrides)
    return _todo_doc(parent_todo_id=_PARENT_ID, **fields)


class TestCompletingAParentCompletesItsSubTodos:
    """A sub-todo does not outlive its parent: completion goes through the one completion path."""

    async def test_each_open_sub_todo_is_completed_and_stops_watching(self, mock_repo, mock_deps):
        docs = {_PARENT_ID: _parent(), _CHILD_ID: _child()}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs.get(todo_id)
        mock_repo.find_sub_todos.side_effect = lambda user_id, parent_ids: (
            [docs[_CHILD_ID]] if parent_ids == [_PARENT_ID] else []
        )

        async def _write(todo_id: str, *, user_id: str, update: object) -> None:
            docs[todo_id] = docs[todo_id].model_copy(update={"completed": True})

        mock_repo.update.side_effect = _write

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        completed = [c.args[0] for c in mock_repo.update.await_args_list]
        assert completed == [_CHILD_ID, _PARENT_ID]
        assert [c.args[0] for c in mock_deps.teardown.await_args_list] == [_CHILD_ID, _PARENT_ID]
        child_entry = mock_deps.record.await_args_list[0].args
        assert child_entry == (
            _CHILD_ID,
            USER_ID,
            TodoActivityEvent.COMPLETED,
            'Parent "Inbox desk" completed: Desk retired',
        )
        assert mock_repo.find_sub_todos.await_args_list[0] == call(USER_ID, [_PARENT_ID])

    async def test_a_sub_todo_already_completed_is_left_alone(self, mock_repo, mock_deps):
        docs = {_PARENT_ID: _parent(), _CHILD_ID: _child(completed=True)}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs.get(todo_id)
        mock_repo.find_sub_todos.return_value = [docs[_CHILD_ID]]

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        assert [c.args[0] for c in mock_repo.update.await_args_list] == [_PARENT_ID]

    async def test_a_sub_todo_created_while_the_parent_closes_is_completed_too(
        self, mock_repo, mock_deps
    ):
        docs = {_PARENT_ID: _parent(), _CHILD_ID: _child()}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs.get(todo_id)
        mock_repo.find_sub_todos.side_effect = [[], [docs[_CHILD_ID]], [], []]

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        assert [c.args[0] for c in mock_repo.update.await_args_list] == [_PARENT_ID, _CHILD_ID]
        assert mock_deps.record.await_args_list[1] == call(
            _CHILD_ID,
            USER_ID,
            TodoActivityEvent.COMPLETED,
            'Parent "Inbox desk" completed: Desk retired',
        )


class TestACompletedSubTodoReportsToItsParent:
    async def test_the_parents_timeline_gets_the_sub_todos_outcome(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _child()

        await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed Friday")

        assert mock_deps.record.await_args_list == [
            call(_CHILD_ID, USER_ID, TodoActivityEvent.COMPLETED, "Sam confirmed Friday"),
            call(
                _PARENT_ID,
                USER_ID,
                TodoActivityEvent.SUB_TODO_COMPLETED,
                f'"Reply to Sam" ({_CHILD_ID}): Sam confirmed Friday',
            ),
        ]

    async def test_a_top_level_todo_reports_nowhere(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _parent()

        await TrackedTodoService.complete_tracked_todo(_PARENT_ID, USER_ID, "Desk retired")

        assert mock_deps.record.await_args_list == [
            call(_PARENT_ID, USER_ID, TodoActivityEvent.COMPLETED, "Desk retired")
        ]


class TestACompletedSubTodoWakesAParentThatWaitsOnIt:
    @pytest.fixture
    def parents(self, mock_repo):
        """Serve the child by id and the parent as the test sets it up."""
        docs = {_CHILD_ID: _child(), _PARENT_ID: _parent()}
        mock_repo.get.side_effect = lambda todo_id, user_id: docs[todo_id]
        return docs

    @pytest.fixture
    def armed(self):
        with patch.object(TrackedTodoService, "schedule_execution", AsyncMock()) as armed:
            yield armed

    async def test_the_parent_runs_soon_after_instead_of_at_its_backup_check(
        self, mock_repo, mock_deps, parents, armed
    ):
        """Seen in real use: a parent waiting on its sub-todos only heard of a finished one at its next run."""
        frozen = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
        parents[_PARENT_ID] = _parent(
            waiting_on=WaitingOn.SUB_TODOS, scheduled_at=frozen + timedelta(days=5)
        )

        with time_machine.travel(frozen, tick=False):
            await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed")

        wake_at = frozen + SUB_TODO_PARENT_WAKE_DELAY
        assert call(_PARENT_ID, user_id=USER_ID) in mock_repo.get.await_args_list
        assert mock_repo.update.await_args_list[-1] == call(
            _PARENT_ID, user_id=USER_ID, update=TodoUpdate(scheduled_at=wake_at)
        )
        armed.assert_awaited_once_with(_PARENT_ID, wake_at)

    async def test_a_parent_waiting_on_something_else_is_left_alone(
        self, mock_repo, mock_deps, parents, armed
    ):
        parents[_PARENT_ID] = _parent(
            waiting_on=WaitingOn.TIME, scheduled_at=datetime.now(UTC) + timedelta(days=5)
        )

        await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed")

        armed.assert_not_awaited()
        assert _PARENT_ID not in [c.args[0] for c in mock_repo.update.await_args_list]

    async def test_a_parent_already_due_sooner_is_not_pushed_later(
        self, mock_repo, mock_deps, parents, armed
    ):
        parents[_PARENT_ID] = _parent(
            waiting_on=WaitingOn.SUB_TODOS, scheduled_at=datetime.now(UTC) + timedelta(seconds=5)
        )

        await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed")

        armed.assert_not_awaited()

    async def test_a_parent_due_exactly_at_the_wake_time_is_left_as_it_is(
        self, mock_repo, mock_deps, parents, armed
    ):
        frozen = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
        parents[_PARENT_ID] = _parent(
            waiting_on=WaitingOn.SUB_TODOS, scheduled_at=frozen + SUB_TODO_PARENT_WAKE_DELAY
        )

        with time_machine.travel(frozen, tick=False):
            await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed")

        armed.assert_not_awaited()
        assert _PARENT_ID not in [c.args[0] for c in mock_repo.update.await_args_list]

    async def test_a_parent_that_is_already_closed_is_left_alone(
        self, mock_repo, mock_deps, parents, armed
    ):
        parents[_PARENT_ID] = _parent(waiting_on=WaitingOn.SUB_TODOS, completed=True)

        await TrackedTodoService.complete_tracked_todo(_CHILD_ID, USER_ID, "Sam confirmed")

        armed.assert_not_awaited()


def test_the_template_opens_on_standing_rules_and_is_already_in_shape() -> None:
    canvas = CANVAS_TEMPLATE.format(title="Inbox desk")

    assert normalize_canvas(canvas) == (canvas, None)
    assert re.findall(r"^## (.+)$", canvas, re.MULTILINE) == list(CANVAS_SECTIONS)


class TestStartingCanvas:
    def test_without_rules_it_is_the_template(self) -> None:
        assert starting_canvas("Inbox desk") == CANVAS_TEMPLATE.format(title="Inbox desk")

    def test_rules_open_the_standing_rules_section_under_its_comment_in_order(self) -> None:
        template = CANVAS_TEMPLATE.format(title="Inbox desk")

        canvas = starting_canvas("Inbox desk", ["Brief me by 9", "Never send a draft"])

        assert canvas == template.replace(
            "-->\n\n## Done when",
            "-->\n- Brief me by 9\n- Never send a draft\n\n## Done when",
            1,
        )
        assert normalize_canvas(canvas) == (canvas, None)

    def test_a_title_that_reads_like_the_heading_leaves_the_rules_in_their_section(self) -> None:
        template = CANVAS_TEMPLATE.format(title="## Standing rules")

        canvas = starting_canvas("## Standing rules", ["Brief me by 9"])

        assert canvas == template.replace(
            "-->\n\n## Done when", "-->\n- Brief me by 9\n\n## Done when", 1
        )


class TestCompleteTrackedTodo:
    async def test_false_for_missing_todo(self, mock_repo, mock_deps):
        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is False
        mock_deps.record.assert_not_awaited()

    async def test_idempotent_for_already_completed(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(completed=True)

        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is True
        mock_deps.record.assert_not_awaited()
        mock_repo.update.assert_not_awaited()

    async def test_appends_log_marks_completed_and_keeps_its_folder_label(
        self, mock_repo, mock_deps
    ):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "Wrapped it up")

        assert ok is True
        assert mock_repo.get.await_args_list[0] == call(TODO_ID, user_id=USER_ID)
        mock_deps.record.assert_awaited_once_with(
            TODO_ID, USER_ID, TodoActivityEvent.COMPLETED, "Wrapped it up"
        )

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.completed is True
        assert update.completed_at is not None
        assert update.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"
        mock_deps.mark.assert_awaited_once_with(TODO_ID, completed=True)

    async def test_completion_stops_the_todo_watching(self, mock_repo, mock_deps):
        # Teardown lives inside completion rather than at its callers (tool, sweep,
        # worker) so no completion path can forget it and strand a live trigger.
        mock_repo.get.return_value = _todo_doc()

        await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        mock_deps.teardown.assert_awaited_once_with(TODO_ID, USER_ID, reason="completed")

    async def test_an_already_completed_todo_does_not_tear_down_again(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(completed=True)

        await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        mock_deps.teardown.assert_not_awaited()

    async def test_missing_vfs_path_falls_back_to_derived_workspace_label(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """A doc with no stored label must get the derived /workspace-scoped one — never None, never derived from the wrong id."""
        mock_repo.get.return_value = _todo_doc(vfs_path=None)

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"

    async def test_legacy_user_scoped_label_is_healed_on_completion(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """A doc still storing the host-side /users/<uid> label must not have it persisted back on completion."""
        mock_repo.get.return_value = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"


class TestSystemLog:
    async def test_appends_formatted_entry(self, mock_repo, mock_deps):
        await TrackedTodoService.system_log(TODO_ID, USER_ID, "rescheduled", "Retry at 9am")

        entry = mock_deps.append_log.await_args.args[2]
        assert "[rescheduled]" in entry
        assert "Retry at 9am" in entry


class TestScheduleExecution:
    async def test_the_job_is_armed_for_its_occurrence(self, mock_repo, mock_deps):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        when = datetime.now(UTC) + timedelta(hours=1)

        ok = await TrackedTodoService.schedule_execution(TODO_ID, when)

        assert ok is True
        # enqueue_worker_job may stamp the caller's _gaia_trace_id kwarg when
        # an ambient wide-event trace is active (the full suite leaks one
        # into this worker) — pin the job contract, not the trace.
        pool.enqueue_job.assert_awaited_once()
        args, kwargs = pool.enqueue_job.await_args
        stamp = occurrence_stamp(when)
        assert args == ("execute_tracked_todo", TODO_ID)
        assert kwargs["scheduled_for"] == stamp
        # One job id per occurrence: a repeat enqueue for it dedupes in ARQ.
        assert kwargs["_job_id"] == f"execute_tracked_todo:{TODO_ID}:{stamp}"
        assert kwargs["_defer_until"] == when

    async def test_a_delayed_fire_keeps_the_occurrence_it_is_for(self, mock_repo, mock_deps):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        due = datetime.now(UTC) - timedelta(minutes=5)
        later = datetime.now(UTC) + timedelta(seconds=30)

        await TrackedTodoService.schedule_execution(TODO_ID, due, defer_until=later)

        kwargs = pool.enqueue_job.await_args.kwargs
        assert kwargs["scheduled_for"] == occurrence_stamp(due)
        assert kwargs["_defer_until"] == later

    async def test_a_naive_time_is_stamped_as_the_utc_instant_mongo_stores(
        self, mock_repo, mock_deps
    ):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        naive = datetime(2026, 9, 27, 10, 0, 0)

        await TrackedTodoService.schedule_execution(TODO_ID, naive)

        aware = naive.replace(tzinfo=UTC)
        kwargs = pool.enqueue_job.await_args.kwargs
        assert kwargs["scheduled_for"] == occurrence_stamp(aware)
        # A naive defer time would be read as the worker's local time, not UTC.
        assert kwargs["_defer_until"] == aware

    async def test_false_when_the_occurrence_is_already_queued(self, mock_repo, mock_deps):
        pool = AsyncMock()
        pool.enqueue_job.return_value = None
        mock_deps.pool.return_value = pool

        assert await TrackedTodoService.schedule_execution(TODO_ID, datetime.now(UTC)) is False

    async def test_a_queue_failure_propagates(self, mock_repo, mock_deps):
        """Every caller persisted scheduled_at first; hiding the failure hid a todo that never runs."""
        mock_deps.pool.side_effect = RuntimeError("redis down")

        with pytest.raises(RuntimeError, match="redis down"):
            await TrackedTodoService.schedule_execution(TODO_ID, datetime.now(UTC))


class TestArchiveTrackedTodo:
    async def test_completes_with_the_reason_on_the_timeline(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired")

        assert ok is True
        mock_deps.record.assert_awaited_once_with(
            TODO_ID, USER_ID, TodoActivityEvent.COMPLETED, "Auto-archived: expired"
        )

    async def test_false_when_completion_fails(self, mock_repo, mock_deps):
        mock_repo.get.return_value = None

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False

    async def test_false_when_unexpected_error(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()
        mock_repo.update.side_effect = RuntimeError("boom")

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False


class TestSingleton:
    def test_module_singleton_is_an_instance(self):
        assert isinstance(tracked_todo_service, TrackedTodoService)

    def test_priority_default_is_none(self):
        assert Priority.NONE.value == "none"


_CLEAN_CANVAS = (
    "# T\n\n## Standing rules\n\n## Done when\n\n## Evidence\n\n## Key Details\nk\n\n"
    "## Current State\n\n## Context\n\n## Learnings\n"
)


class TestMigrateLegacyCanvas:
    LEGACY = (
        "# T\n\n## Key Details\nk\n\n## Activity Log\n- did x\n\n"
        "## Timeline\n- 2026-01-02T00:00:00+00:00 second\n- 2026-01-01T00:00:00+00:00 first\n\n"
        "## Learnings\n"
    )

    async def test_legacy_canvas_is_split_into_both_fields(self):
        doc = _todo_doc(canvas_content=self.LEGACY, activity_content=None)
        with patch(
            f"{_MOD}.repair_notes", new_callable=AsyncMock, return_value=_todo_doc()
        ) as write:
            assert await TrackedTodoService.normalize_stored_canvas(doc) is True

        notes = write.await_args.args[2]
        assert write.await_args.args[:2] == (doc.id, doc.user_id)
        assert write.await_args.kwargs["expected_updated_at"] == doc.updated_at
        assert "## Activity Log" not in notes.canvas_content
        assert "## Timeline" not in notes.canvas_content
        assert notes.activity_content.index("first") < notes.activity_content.index("second")
        assert "did x" in notes.activity_content

    async def test_moved_legacy_entries_come_before_existing_activity(self):
        doc = _todo_doc(canvas_content=self.LEGACY, activity_content="- already here")
        with patch(
            f"{_MOD}.repair_notes", new_callable=AsyncMock, return_value=_todo_doc()
        ) as write:
            await TrackedTodoService.normalize_stored_canvas(doc)

        activity = write.await_args.args[2].activity_content
        assert activity == (
            "- 2026-01-01T00:00:00+00:00 first\n\n- 2026-01-02T00:00:00+00:00 second\n\n"
            "- did x\n\n- already here"
        )

    async def test_clean_canvas_is_not_touched(self):
        doc = _todo_doc(canvas_content=_CLEAN_CANVAS)
        with patch(f"{_MOD}.repair_notes", new_callable=AsyncMock) as write:
            assert await TrackedTodoService.normalize_stored_canvas(doc) is False

        write.assert_not_awaited()

    async def test_empty_canvas_is_not_touched(self):
        doc = _todo_doc(canvas_content=None)
        with patch(f"{_MOD}.repair_notes", new_callable=AsyncMock) as write:
            assert await TrackedTodoService.normalize_stored_canvas(doc) is False

        write.assert_not_awaited()

    async def test_revision_race_retries_once_against_fresh_content(self, mock_repo):
        stale = _todo_doc(canvas_content=self.LEGACY, activity_content=None)
        fresh = _todo_doc(
            canvas_content=self.LEGACY,
            activity_content="- fresh here",
            updated_at=datetime.now(UTC),
        )
        mock_repo.get.return_value = fresh
        with patch(
            f"{_MOD}.repair_notes",
            new_callable=AsyncMock,
            side_effect=[None, _todo_doc()],
        ) as write:
            assert await TrackedTodoService.normalize_stored_canvas(stale) is True

        mock_repo.get.assert_awaited_once_with(stale.id, user_id=stale.user_id)
        assert write.await_count == 2
        assert write.await_args_list[0].args[:2] == (stale.id, stale.user_id)
        assert write.await_args_list[1].args[:2] == (fresh.id, fresh.user_id)
        assert write.await_args_list[0].kwargs["expected_updated_at"] == stale.updated_at
        assert write.await_args_list[1].kwargs["expected_updated_at"] == fresh.updated_at
        assert write.await_args_list[1].args[2].canvas_content == _CLEAN_CANVAS
        assert write.await_args_list[1].args[2].activity_content == (
            "- 2026-01-01T00:00:00+00:00 first\n\n- 2026-01-02T00:00:00+00:00 second\n\n"
            "- did x\n\n- fresh here"
        )

    async def test_fresh_doc_already_clean_skips_retry(self, mock_repo):
        """When the re-read doc has no legacy sections, the migration gives up instead of reporting a write it never made."""
        fresh = _todo_doc(
            canvas_content=_CLEAN_CANVAS,
            updated_at=datetime.now(UTC),
        )
        mock_repo.get.return_value = fresh
        with patch(f"{_MOD}.repair_notes", new_callable=AsyncMock, return_value=None) as write:
            assert (
                await TrackedTodoService.normalize_stored_canvas(
                    _todo_doc(canvas_content=self.LEGACY)
                )
                is False
            )

        write.assert_awaited_once()

    async def test_vanished_todo_is_not_retried(self, mock_repo):
        mock_repo.get.return_value = None
        with patch(f"{_MOD}.repair_notes", new_callable=AsyncMock, return_value=None) as write:
            assert (
                await TrackedTodoService.normalize_stored_canvas(
                    _todo_doc(canvas_content=self.LEGACY)
                )
                is False
            )

        write.assert_awaited_once()


class TestResumePausedFor:
    @pytest.fixture(autouse=True)
    def _held_events(self, fake_redis):
        """Back the held-event replay with real list semantics; nothing is held unless a test holds it."""
        return fake_redis

    async def test_one_todo_that_cannot_resume_does_not_strand_the_rest(self, mock_repo):
        stuck = _todo_doc(pause_reason="subscription_lapsed")
        fine = _todo_doc(id="todo-2", pause_reason="subscription_lapsed")
        mock_repo.find_paused_for_reason = AsyncMock(return_value=[stuck, fine])
        mock_repo.update = AsyncMock(side_effect=[ConnectionError("mongo blip"), None])

        with (
            patch(f"{_MOD}.log") as log,
            pytest.raises(ExceptionGroup, match=r"^1 paused tracked todo\(s\) could not resume"),
        ):
            await tracked_todo_service.resume_paused_for(
                USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
            )

        assert [c.args[0] for c in mock_repo.update.call_args_list] == [TODO_ID, "todo-2"]
        log.warning.assert_called_once_with(
            "tracked_todo.resume_failed",
            todo_id=TODO_ID,
            user_id=USER_ID,
            error="mongo blip",
            error_type="ConnectionError",
        )
        log.set.assert_called_once_with(
            tracked_todos_resumed=1, tracked_todos_resume_reason="subscription_lapsed"
        )

    async def test_activation_clears_the_pause_and_fires_a_missed_run_now(self, mock_repo):
        missed = datetime.now(UTC) - timedelta(hours=3)
        paused = _todo_doc(pause_reason="subscription_lapsed", scheduled_at=missed)
        unscheduled = _todo_doc(id="todo-2", pause_reason="subscription_lapsed")
        mock_repo.find_paused_for_reason = AsyncMock(return_value=[paused, unscheduled])
        schedule = AsyncMock(return_value=True)
        before = datetime.now(UTC)
        with patch.object(TrackedTodoService, "schedule_execution", schedule):
            async with captured_wide_event() as wide:
                resumed = await tracked_todo_service.resume_paused_for(
                    USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
                )

        assert resumed == 2
        assert (wide["tracked_todos_resumed"], wide["tracked_todos_resume_reason"]) == (
            2,
            "subscription_lapsed",
        )
        assert [(c.args, c.kwargs["user_id"]) for c in mock_repo.update.call_args_list] == [
            ((TODO_ID,), USER_ID),
            (("todo-2",), USER_ID),
        ]
        mock_repo.find_paused_for_reason.assert_awaited_once_with(
            USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
        )
        cleared = [
            c.kwargs["update"].model_dump(exclude_unset=True)
            for c in mock_repo.update.call_args_list
        ]
        assert cleared == [{"pause_reason": None}, {"pause_reason": None}]
        ((args, kwargs),) = [(c.args, c.kwargs) for c in schedule.await_args_list]
        assert args == (TODO_ID, missed)
        assert kwargs["defer_until"] >= before

    async def test_activation_replays_the_trigger_events_held_while_paused(self, mock_repo):
        paused = _todo_doc(pause_reason="subscription_lapsed")
        mock_repo.find_paused_for_reason = AsyncMock(return_value=[paused])
        with patch(
            f"{_MOD}.release_trigger_events_held_while_paused", AsyncMock(return_value=2)
        ) as release:
            resumed = await tracked_todo_service.resume_paused_for(
                USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
            )

        assert resumed == 1
        release.assert_awaited_once_with(TODO_ID)

    async def test_held_events_that_cannot_replay_keep_the_todo_paused_for_the_retry(
        self, mock_repo
    ):
        paused = _todo_doc(pause_reason="subscription_lapsed")
        mock_repo.find_paused_for_reason = AsyncMock(return_value=[paused])
        with (
            patch(
                f"{_MOD}.release_trigger_events_held_while_paused",
                AsyncMock(side_effect=ConnectionError("arq down")),
            ),
            pytest.raises(ExceptionGroup, match=r"^1 paused tracked todo\(s\) could not resume"),
        ):
            await tracked_todo_service.resume_paused_for(
                USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
            )

        writes = [
            c.kwargs["update"].model_dump(exclude_unset=True)
            for c in mock_repo.update.call_args_list
        ]
        assert writes == [
            {"pause_reason": None},
            {"pause_reason": DeactivationReason.SUBSCRIPTION_LAPSED},
        ]
        assert [(c.args, c.kwargs["user_id"]) for c in mock_repo.update.call_args_list] == [
            ((TODO_ID,), USER_ID),
            ((TODO_ID,), USER_ID),
        ]

    async def test_a_run_that_cannot_be_enqueued_stays_paused_for_the_retry(self, mock_repo):
        paused = _todo_doc(
            pause_reason="subscription_lapsed", scheduled_at=datetime.now(UTC) - timedelta(hours=1)
        )
        mock_repo.find_paused_for_reason = AsyncMock(return_value=[paused])
        with (
            patch.object(
                TrackedTodoService,
                "schedule_execution",
                AsyncMock(side_effect=ConnectionError("redis down")),
            ),
            pytest.raises(ExceptionGroup, match=r"^1 paused tracked todo\(s\) could not resume"),
        ):
            await tracked_todo_service.resume_paused_for(
                USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
            )

        writes = [
            c.kwargs["update"].model_dump(exclude_unset=True)
            for c in mock_repo.update.call_args_list
        ]
        assert writes == [
            {"pause_reason": None},
            {"pause_reason": DeactivationReason.SUBSCRIPTION_LAPSED},
        ]
        assert [(c.args, c.kwargs["user_id"]) for c in mock_repo.update.call_args_list] == [
            ((TODO_ID,), USER_ID),
            ((TODO_ID,), USER_ID),
        ]
