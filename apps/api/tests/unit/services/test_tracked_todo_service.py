"""Unit tests for tracked_todo_service (GAIA working-memory todo lifecycle).

Covers the VFS label + canvas/log persistence + ChromaDB indexing pipeline,
completion/archival, and the context-summary renderers the agent sees.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import Priority, TodoDocument, TodoModel, TodoResponse
from app.services.tracked_todo_service import (
    CANVAS_TEMPLATE,
    TrackedTodoService,
    tracked_todo_service,
)

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
    return TodoDocument(**data)


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
    return TodoResponse(**data)


@pytest.fixture
def mock_repo():
    with patch(f"{_MOD}.todo_repository") as m:
        m.get = AsyncMock(return_value=None)
        m.update = AsyncMock(return_value=None)
        m.list_active_tracked = AsyncMock(return_value=[])
        yield m


@pytest.fixture
def mock_deps():
    with (
        patch(f"{_MOD}.TodoService.create_todo", new_callable=AsyncMock) as m_create,
        patch(f"{_MOD}.store_canvas_embedding", new_callable=AsyncMock) as m_store,
        patch(f"{_MOD}.mark_canvas_completed", new_callable=AsyncMock) as m_mark,
        patch(f"{_MOD}.update_canvas_embedding", new_callable=AsyncMock) as m_update_emb,
        patch(f"{_MOD}.schedule_gaia_tasks_sync", new_callable=MagicMock) as m_sync,
        patch(f"{_MOD}.RedisPoolManager.get_pool", new_callable=AsyncMock) as m_pool,
        patch(f"{_MOD}.read_canvas", new_callable=AsyncMock) as m_read,
        patch(f"{_MOD}.write_canvas", new_callable=AsyncMock) as m_write,
        patch(f"{_MOD}.append_log", new_callable=AsyncMock) as m_append_log,
        patch(f"{_MOD}.teardown_subscriptions", new_callable=AsyncMock) as m_teardown,
    ):
        yield SimpleNamespace(
            create=m_create,
            store=m_store,
            mark=m_mark,
            update_emb=m_update_emb,
            sync=m_sync,
            pool=m_pool,
            read=m_read,
            write=m_write,
            append_log=m_append_log,
            teardown=m_teardown,
        )


class TestCreateTrackedTodo:
    async def test_creates_with_template_canvas_and_indexes(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        result = await TrackedTodoService.create_tracked_todo(USER_ID, "Prepare Q3 report")

        assert result.id == TODO_ID
        assert result.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert GAIA_TRACKED_LABEL in todo_model.labels

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/{TODO_ID}"
        assert update.canvas_content == CANVAS_TEMPLATE.format(title="Prepare Q3 report")
        assert "[CREATED]" in update.log_content
        assert "Source: agent" in update.log_content

        mock_deps.store.assert_awaited_once()
        store_kwargs = mock_deps.store.call_args.kwargs
        assert store_kwargs["todo_id"] == TODO_ID
        assert store_kwargs["user_id"] == USER_ID
        assert store_kwargs["title"] == "Prepare Q3 report"
        assert GAIA_TRACKED_LABEL in store_kwargs["labels"]
        mock_deps.sync.assert_called_once_with(USER_ID)

    async def test_uses_provided_initial_canvas(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", initial_canvas="custom canvas"
        )

        assert mock_repo.update.await_args.kwargs["update"].canvas_content == "custom canvas"
        assert mock_deps.store.call_args.kwargs["canvas_content"] == "custom canvas"

    async def test_preserves_caller_labels(self, mock_repo, mock_deps):
        mock_deps.create.return_value = _todo_response()

        await TrackedTodoService.create_tracked_todo(
            USER_ID, "Prepare Q3 report", labels=["work", "finance"]
        )

        todo_model: TodoModel = mock_deps.create.call_args.args[0]
        assert set(todo_model.labels) == {"work", "finance", GAIA_TRACKED_LABEL}


class TestCompleteTrackedTodo:
    async def test_false_for_missing_todo(self, mock_repo, mock_deps):
        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is False
        mock_deps.append_log.assert_not_awaited()

    async def test_idempotent_for_already_completed(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(completed=True)

        assert await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done") is True
        mock_deps.append_log.assert_not_awaited()
        mock_repo.update.assert_not_awaited()

    async def test_appends_log_marks_completed_and_archives_path(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "Wrapped it up")

        assert ok is True
        log_entry = mock_deps.append_log.await_args.args[2]
        assert "[COMPLETED]" in log_entry
        assert "Wrapped it up" in log_entry

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.completed is True
        assert update.completed_at is not None
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"
        mock_deps.mark.assert_awaited_once_with(TODO_ID)
        mock_deps.sync.assert_called_once_with(USER_ID)

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
        """A doc with no stored label must get the derived /workspace-scoped one —
        never None, and never a label derived from the wrong id."""
        mock_repo.get.return_value = _todo_doc(vfs_path=None)

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"

    async def test_legacy_user_scoped_label_is_healed_on_completion(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """A doc still storing the host-side /users/<uid> label must not have it
        persisted back on completion — the derived archive label replaces it."""
        mock_repo.get.return_value = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")

        ok = await TrackedTodoService.complete_tracked_todo(TODO_ID, USER_ID, "done")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.vfs_path == f"/workspace/gaia-tasks/archive/{TODO_ID}"


class TestGetActiveTrackedSummary:
    async def test_empty_string_without_docs(self, mock_repo):
        assert await TrackedTodoService.get_active_tracked_summary(USER_ID) == ""

    @pytest.mark.regression
    async def test_stored_user_scoped_vfs_path_never_leaks_into_agent_context(
        self, mock_repo: MagicMock, mock_deps: SimpleNamespace
    ) -> None:
        """Old docs store vfs_path as /users/<uid>/todos/<id> — that host-side
        path must never reach the LLM, which only knows /workspace-scoped paths."""
        stale_doc = _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")
        mock_repo.list_active_tracked.return_value = [stale_doc]
        mock_deps.read.return_value = "## Key Details\nthread: abc123\n"

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert USER_ID not in summary
        assert "/users/" not in summary

    async def test_renders_summary_lines(self, mock_repo):
        mock_repo.list_active_tracked.return_value = [_todo_doc()]

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        lines = summary.split("\n")
        assert lines[0] == "ACTIVE TRACKED TODOS:"
        assert '"Prepare Q3 report" [work]' in lines[1]
        assert "ID: todo-1" in lines[1]
        assert "VFS" not in lines[1]
        assert USER_ID not in lines[1]
        assert lines[1].endswith("2d old, updated 0d ago") or "d old" in lines[1]

    async def test_active_todo_pinned_with_star(self, mock_repo):
        docs = [
            _todo_doc(id="todo-2", title="Second"),
            _todo_doc(id="todo-3", title="Third"),
        ]
        mock_repo.list_active_tracked.return_value = docs

        summary = await TrackedTodoService.get_active_tracked_summary(
            USER_ID, active_todo_id="todo-3"
        )

        lines = summary.split("\n")
        assert lines[1].startswith('  ⭐ ACTIVE "Third"')
        assert lines[2].startswith('  "Second"')

    async def test_due_and_overdue_suffixes(self, mock_repo):
        now = datetime.now(UTC)
        docs = [
            _todo_doc(id="todo-due", title="Due soon", due_date=now + timedelta(days=3, hours=1)),
            _todo_doc(id="todo-late", title="Late", due_date=now - timedelta(days=3, hours=23)),
        ]
        mock_repo.list_active_tracked.return_value = docs

        summary = await TrackedTodoService.get_active_tracked_summary(USER_ID)

        assert " due(3d)" in summary.split("\n")[1]
        assert " OVERDUE(4d)" in summary.split("\n")[2]


class TestAppendCanvasTimeline:
    async def test_false_when_canvas_read_fails(self, mock_repo, mock_deps):
        mock_deps.read.side_effect = RuntimeError("mongo down")

        assert await TrackedTodoService.append_canvas_timeline(TODO_ID, USER_ID, "step") is False
        mock_deps.write.assert_not_awaited()

    async def test_false_when_canvas_empty(self, mock_repo, mock_deps):
        mock_deps.read.return_value = None

        assert await TrackedTodoService.append_canvas_timeline(TODO_ID, USER_ID, "step") is False

    async def test_inserts_at_top_of_existing_timeline_section(self, mock_repo, mock_deps):
        canvas = "# T\n\n## Timeline\n- old step\n"
        mock_deps.read.return_value = canvas
        mock_deps.write.return_value = True

        ok = await TrackedTodoService.append_canvas_timeline(TODO_ID, USER_ID, "new step")

        assert ok is True
        written = mock_deps.write.await_args.args[2]
        assert written == "# T\n\n## Timeline\n- new step\n- old step\n"

    async def test_appends_section_when_timeline_missing(self, mock_repo, mock_deps):
        canvas = "# T\n\n## Key Details\nnothing"
        mock_deps.read.return_value = canvas
        mock_deps.write.return_value = True

        ok = await TrackedTodoService.append_canvas_timeline(TODO_ID, USER_ID, "first step")

        assert ok is True
        written = mock_deps.write.await_args.args[2]
        assert written == "# T\n\n## Key Details\nnothing\n\n## Timeline\n- first step\n"

    async def test_adds_dash_prefix_to_plain_entry(self, mock_repo, mock_deps):
        mock_deps.read.return_value = "# T\n\n## Timeline\n"
        mock_deps.write.return_value = True

        await TrackedTodoService.append_canvas_timeline(TODO_ID, USER_ID, "bare entry")

        assert mock_deps.write.await_args.args[2].count("- bare entry") == 1

    async def test_false_when_write_fails(self, mock_repo, mock_deps):
        mock_deps.read.return_value = "# T\n\n## Timeline\n"
        mock_deps.write.side_effect = RuntimeError("write failed")

        assert await TrackedTodoService.append_canvas_timeline(TODO_ID, USER_ID, "step") is False


class TestSystemLog:
    async def test_appends_formatted_entry(self, mock_repo, mock_deps):
        await TrackedTodoService.system_log(TODO_ID, USER_ID, "rescheduled", "Retry at 9am")

        entry = mock_deps.append_log.await_args.args[2]
        assert "[rescheduled]" in entry
        assert "Retry at 9am" in entry


class TestReindexCanvas:
    async def test_false_for_missing_todo(self, mock_repo, mock_deps):
        assert await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID) is False
        mock_deps.update_emb.assert_not_awaited()

    async def test_false_without_canvas_content(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc(canvas_content=None)

        assert await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID) is False

    async def test_reindexes_with_document_content(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()
        mock_deps.update_emb.return_value = True

        ok = await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID)

        assert ok is True
        kwargs = mock_deps.update_emb.call_args.kwargs
        assert kwargs["todo_id"] == TODO_ID
        assert kwargs["user_id"] == USER_ID
        assert kwargs["title"] == "Prepare Q3 report"
        assert kwargs["labels"] == [GAIA_TRACKED_LABEL, "work"]
        assert "thread: abc123" in kwargs["canvas_content"]

    async def test_propagates_embedding_failure(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()
        mock_deps.update_emb.return_value = False

        assert await TrackedTodoService.reindex_canvas(TODO_ID, USER_ID) is False


class TestScheduleExecution:
    async def test_enqueues_deferred_job(self, mock_repo, mock_deps):
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
        assert args == ("execute_tracked_todo", TODO_ID)
        assert kwargs["_defer_until"] == when

    async def test_false_when_enqueue_fails(self, mock_repo, mock_deps):
        mock_deps.pool.side_effect = RuntimeError("redis down")

        assert await TrackedTodoService.schedule_execution(TODO_ID, datetime.now(UTC)) is False

    async def test_reschedule_reuses_schedule(self, mock_repo, mock_deps):
        pool = AsyncMock()
        mock_deps.pool.return_value = pool
        when = datetime.now(UTC) + timedelta(hours=2)

        assert await TrackedTodoService.reschedule_execution(TODO_ID, when) is True
        pool.enqueue_job.assert_awaited_once()


class TestArchiveTrackedTodo:
    async def test_logs_reason_and_completes(self, mock_repo, mock_deps):
        mock_repo.get.return_value = _todo_doc()

        ok = await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired")

        assert ok is True
        archived_entry = mock_deps.append_log.await_args_list[0].args[2]
        assert "[auto_archived]" in archived_entry
        assert "expired" in archived_entry

    async def test_false_when_completion_fails(self, mock_repo, mock_deps):
        mock_repo.get.return_value = None

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False

    async def test_false_when_unexpected_error(self, mock_repo, mock_deps):
        mock_deps.append_log.side_effect = RuntimeError("boom")

        assert await TrackedTodoService.archive_tracked_todo(TODO_ID, USER_ID, "expired") is False


class TestSingleton:
    def test_module_singleton_is_an_instance(self):
        assert isinstance(tracked_todo_service, TrackedTodoService)

    def test_priority_default_is_none(self):
        assert Priority.NONE.value == "none"
