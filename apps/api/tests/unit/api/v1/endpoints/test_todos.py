"""
Exhaustive unit tests for app.api.v1.endpoints.todos

Covers all 22 route handlers, success paths, validation, service
errors and edge cases. Uses AsyncClient with mocked DB/services so
no external infra is required.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from httpx import AsyncClient
import pytest

from app.constants.general import MAX_PAGE_NUMBER
from app.models.todo_models import (
    BulkOperationResponse,
    PaginationMeta,
    ProjectResponse,
    SubTask,
    TodoCounts,
    TodoDocument,
    TodoLabelCount,
    TodoListResponse,
    TodoResponse,
    TodoWorkflowGenerationStatus,
    TodoWorkflowStatus,
    TodoWorkflowStatusResponse,
)

pytestmark = pytest.mark.unit

from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowStep, WorkflowWithIntegrations

TODOS_MOD = "app.api.v1.endpoints.todos"
ANALYTICS_PATCH = f"{TODOS_MOD}.capture_context_event"
FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture(autouse=True)
def _noop_analytics():
    with patch(ANALYTICS_PATCH):
        yield


def _todo_resp(todo_id: str = "todo-1", workflow_id: str | None = None, vfs_path: str | None = None) -> TodoResponse:
    return TodoResponse(
        id=todo_id,
        user_id=FAKE_USER_ID,
        title="Test todo",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        workflow_id=workflow_id,
        vfs_path=vfs_path,
    )


def _todo_doc(todo_id: str = "todo-1", vfs_path: str | None = None, subtasks: list[SubTask] | None = None) -> TodoDocument:
    return TodoDocument(
        id=todo_id,
        user_id=FAKE_USER_ID,
        title="Test todo",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        vfs_path=vfs_path,
        subtasks=subtasks or [],
    )


def _project_resp(project_id: str = "proj-1", is_default: bool = False) -> ProjectResponse:
    return ProjectResponse(
        id=project_id,
        user_id=FAKE_USER_ID,
        name="My Project",
        is_default=is_default,
        todo_count=0,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _empty_list_response() -> TodoListResponse:
    return TodoListResponse(
        data=[],
        meta=PaginationMeta(total=0, page=1, per_page=50, pages=0, has_next=False, has_prev=False),
    )


def _make_workflow(workflow_id: str = "wf-1", steps: list | None = None) -> MagicMock:
    wf = MagicMock()
    wf.id = workflow_id
    wf.steps = steps if steps is not None else [MagicMock(category="cat1")]
    return wf


# ============================================================================
# GET /todos/counts
# ============================================================================


class TestGetTodoCounts:
    async def test_success(self, client: AsyncClient) -> None:
        counts = TodoCounts(inbox=1, today=2, upcoming=3, completed=4, overdue=0)
        mock_inbox = MagicMock()
        mock_inbox.id = "inbox-1"
        with (
            patch(f"{TODOS_MOD}.project_repository.get_default_inbox", new_callable=AsyncMock, return_value=mock_inbox) as mock_get_inbox,
            patch(f"{TODOS_MOD}.todo_repository.compute_counts", new_callable=AsyncMock, return_value=counts) as mock_counts,
        ):
            resp = await client.get("/api/v1/todos/counts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["inbox"] == 1
        assert body["today"] == 2
        assert resp.headers["Cache-Control"] == "private, max-age=10"
        mock_get_inbox.assert_awaited_once_with(FAKE_USER_ID)
        mock_counts.assert_awaited_once_with(user_id=FAKE_USER_ID, inbox_project_id="inbox-1")

    async def test_no_inbox_uses_fallback_id(self, client: AsyncClient) -> None:
        counts = TodoCounts(inbox=0, today=0, upcoming=0, completed=0)
        with (
            patch(f"{TODOS_MOD}.project_repository.get_default_inbox", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.todo_repository.compute_counts", new_callable=AsyncMock, return_value=counts) as mock_counts,
        ):
            resp = await client.get("/api/v1/todos/counts")

        assert resp.status_code == 200
        assert mock_counts.await_args.kwargs["inbox_project_id"] == "no_inbox_found"

    async def test_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.project_repository.get_default_inbox", new_callable=AsyncMock, side_effect=RuntimeError("db fail")):
            resp = await client.get("/api/v1/todos/counts")

        assert resp.status_code == 500
        assert "Failed to retrieve counts" in resp.json()["detail"]


# ============================================================================
# GET /todos/labels
# ============================================================================


class TestGetTodoLabels:
    async def test_success_default_limit(self, client: AsyncClient) -> None:
        labels = [TodoLabelCount(name="work", count=5), TodoLabelCount(name="home", count=3)]
        with patch(f"{TODOS_MOD}.todo_repository.top_labels", new_callable=AsyncMock, return_value=labels) as mock_top:
            resp = await client.get("/api/v1/todos/labels")

        assert resp.status_code == 200
        assert len(resp.json()) == 2
        mock_top.assert_awaited_once_with(user_id=FAKE_USER_ID, limit=10)

    async def test_custom_limit(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.top_labels", new_callable=AsyncMock, return_value=[]) as mock_top:
            resp = await client.get("/api/v1/todos/labels?limit=5")

        assert resp.status_code == 200
        mock_top.assert_awaited_once_with(user_id=FAKE_USER_ID, limit=5)

    async def test_empty_labels(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.top_labels", new_callable=AsyncMock, return_value=[]):
            resp = await client.get("/api/v1/todos/labels")

        assert resp.status_code == 200
        assert resp.json() == []


# ============================================================================
# GET /todos
# ============================================================================


class TestListTodos:
    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/todos?page={MAX_PAGE_NUMBER + 1}")
        assert resp.status_code == 422

    async def test_list_returns_todos(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?page=1&per_page=10")

        assert resp.status_code == 200
        assert resp.json()["data"] == []
        assert mock_list.await_args.args[0] == FAKE_USER_ID

    async def test_due_today_sets_date_range(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?due_today=true")

        assert resp.status_code == 200
        params = mock_list.await_args.args[1]
        assert params.due_date_start is not None
        assert params.due_date_end is not None
        assert params.due_date_start.tzinfo is not None

    async def test_due_this_week_sets_date_range(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?due_this_week=true")

        assert resp.status_code == 200
        params = mock_list.await_args.args[1]
        assert params.due_date_start is not None
        assert params.due_date_end is not None

    async def test_filters_q_project_completed_priority_labels(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?q=hello&project_id=proj-1&completed=false&priority=high&labels=work&labels=home")

        assert resp.status_code == 200
        params = mock_list.await_args.args[1]
        assert params.q == "hello"
        assert params.project_id == "proj-1"
        assert params.completed is False
        assert params.priority.value == "high"
        assert params.labels == ["work", "home"]

    async def test_value_error_returns_400(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, side_effect=ValueError("bad filter")):
            resp = await client.get("/api/v1/todos")

        assert resp.status_code == 400
        assert "bad filter" in resp.json()["detail"]

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            resp = await client.get("/api/v1/todos")

        assert resp.status_code == 500
        assert "Failed to retrieve todos" in resp.json()["detail"]

    async def test_search_mode_default_hybrid(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?q=test")

        assert resp.status_code == 200
        params = mock_list.await_args.args[1]
        assert params.mode.value == "hybrid"

    async def test_overdue_and_has_due_date_filters(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?overdue=true&has_due_date=true")

        assert resp.status_code == 200
        params = mock_list.await_args.args[1]
        assert params.overdue is True
        assert params.has_due_date is True

    async def test_pagination_per_page_bounds(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/todos?per_page=101")
        assert resp.status_code == 422
        resp2 = await client.get("/api/v1/todos?per_page=0")
        assert resp2.status_code == 422

    async def test_include_stats(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.list_todos", new_callable=AsyncMock, return_value=_empty_list_response()) as mock_list:
            resp = await client.get("/api/v1/todos?include_stats=true")

        assert resp.status_code == 200
        params = mock_list.await_args.args[1]
        assert params.include_stats is True


# ============================================================================
# POST /todos
# ============================================================================


class TestCreateTodo:
    async def test_success(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp()
        with patch(f"{TODOS_MOD}.TodoService.create_todo", new_callable=AsyncMock, return_value=todo_resp):
            resp = await client.post("/api/v1/todos", json={"title": "New todo"})

        assert resp.status_code == 201
        assert resp.json()["id"] == "todo-1"
        assert resp.json()["title"] == "Test todo"

    async def test_value_error_returns_400(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.create_todo", new_callable=AsyncMock, side_effect=ValueError("Project not found")):
            resp = await client.post("/api/v1/todos", json={"title": "New todo"})

        assert resp.status_code == 400
        assert "Project not found" in resp.json()["detail"]

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.create_todo", new_callable=AsyncMock, side_effect=RuntimeError("db down")):
            resp = await client.post("/api/v1/todos", json={"title": "New todo"})

        assert resp.status_code == 500
        assert "Failed to create todo" in resp.json()["detail"]

    async def test_validation_missing_title_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/todos", json={})
        assert resp.status_code == 422


# ============================================================================
# PUT /todos/bulk
# ============================================================================


class TestBulkUpdateTodos:
    async def test_success(self, client: AsyncClient) -> None:
        bulk_resp = BulkOperationResponse(success=["id1"], failed=[], total=1, message="Updated 1 todos")
        with patch(f"{TODOS_MOD}.TodoService.bulk_update_todos", new_callable=AsyncMock, return_value=bulk_resp) as mock_bulk:
            resp = await client.put("/api/v1/todos/bulk", json={"todo_ids": ["id1"], "updates": {"completed": True}})

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        mock_bulk.assert_awaited_once()

    async def test_bulk_update_calls_analytics(self, client: AsyncClient) -> None:
        bulk_resp = BulkOperationResponse(success=["id1", "id2"], failed=[], total=2, message="ok")
        with (
            patch(f"{TODOS_MOD}.TodoService.bulk_update_todos", new_callable=AsyncMock, return_value=bulk_resp),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.put("/api/v1/todos/bulk", json={"todo_ids": ["id1", "id2"], "updates": {"completed": True}})

        assert resp.status_code == 200
        mock_capture.assert_called_once()
        # first arg is event name string
        assert mock_capture.call_args[0][0] == "todos:updated" or "TODO" in str(mock_capture.call_args)

    async def test_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.bulk_update_todos", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.put("/api/v1/todos/bulk", json={"todo_ids": ["id1"], "updates": {"completed": True}})

        assert resp.status_code == 500
        assert "Bulk update failed" in resp.json()["detail"]


# ============================================================================
# POST /todos/bulk/move
# ============================================================================


class TestBulkMoveTodos:
    async def test_success(self, client: AsyncClient) -> None:
        bulk_resp = BulkOperationResponse(success=["id1"], failed=[], total=1, message="Moved 1 todos")
        with patch(f"{TODOS_MOD}.TodoService.bulk_move_todos", new_callable=AsyncMock, return_value=bulk_resp):
            resp = await client.post("/api/v1/todos/bulk/move", json={"todo_ids": ["id1"], "project_id": "proj-1"})

        assert resp.status_code == 200
        assert resp.json()["message"] == "Moved 1 todos"

    async def test_value_error_returns_400(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.bulk_move_todos", new_callable=AsyncMock, side_effect=ValueError("Project not found")):
            resp = await client.post("/api/v1/todos/bulk/move", json={"todo_ids": ["id1"], "project_id": "bad"})

        assert resp.status_code == 400
        assert "Project not found" in resp.json()["detail"]

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.bulk_move_todos", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.post("/api/v1/todos/bulk/move", json={"todo_ids": ["id1"], "project_id": "proj-1"})

        assert resp.status_code == 500

    async def test_missing_project_id_validation(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/todos/bulk/move", json={"todo_ids": ["id1"]})
        assert resp.status_code == 422


# ============================================================================
# DELETE /todos/bulk
# ============================================================================


class TestBulkDeleteTodos:
    async def test_success(self, client: AsyncClient) -> None:
        bulk_resp = BulkOperationResponse(success=["id1", "id2"], failed=[], total=2, message="Deleted 2 todos")
        with patch(f"{TODOS_MOD}.TodoService.bulk_delete_todos", new_callable=AsyncMock, return_value=bulk_resp):
            resp = await client.request("DELETE", "/api/v1/todos/bulk", json=["id1", "id2"])

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_validation_empty_list_returns_422(self, client: AsyncClient) -> None:
        resp = await client.request("DELETE", "/api/v1/todos/bulk", json=[])
        assert resp.status_code == 422

    async def test_too_many_ids_returns_422(self, client: AsyncClient) -> None:
        many = [f"id-{i}" for i in range(101)]
        resp = await client.request("DELETE", "/api/v1/todos/bulk", json=many)
        assert resp.status_code == 422

    async def test_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.bulk_delete_todos", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.request("DELETE", "/api/v1/todos/bulk", json=["id1"])

        assert resp.status_code == 500


# ============================================================================
# POST /todos/bulk/complete
# ============================================================================


class TestBulkCompleteTodos:
    async def test_success(self, client: AsyncClient) -> None:
        bulk_resp = BulkOperationResponse(success=["id1"], failed=[], total=1, message="ok")
        with patch(f"{TODOS_MOD}.TodoService.bulk_update_todos", new_callable=AsyncMock, return_value=bulk_resp) as mock_bulk:
            resp = await client.post("/api/v1/todos/bulk/complete", json=["id1", "id2"])

        assert resp.status_code == 200
        # should have called bulk_update with completed=True
        call_args = mock_bulk.await_args
        assert call_args[0][0].updates.completed is True
        assert call_args[0][0].todo_ids == ["id1", "id2"]

    async def test_bulk_complete_captures_analytics(self, client: AsyncClient) -> None:
        bulk_resp = BulkOperationResponse(success=["id1"], failed=[], total=1, message="ok")
        with (
            patch(f"{TODOS_MOD}.TodoService.bulk_update_todos", new_callable=AsyncMock, return_value=bulk_resp),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post("/api/v1/todos/bulk/complete", json=["id1"])

        assert resp.status_code == 200
        mock_capture.assert_called_once()

    async def test_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.bulk_update_todos", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.post("/api/v1/todos/bulk/complete", json=["id1"])

        assert resp.status_code == 500
        assert "Bulk complete failed" in resp.json()["detail"]

    async def test_empty_list_validation(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/todos/bulk/complete", json=[])
        assert resp.status_code == 422


# ============================================================================
# GET /todos/{todo_id}
# ============================================================================


class TestGetTodo:
    async def test_success(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp()
        with patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp):
            resp = await client.get("/api/v1/todos/todo-1")

        assert resp.status_code == 200
        assert resp.json()["id"] == "todo-1"

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, side_effect=ValueError("Todo not found")):
            resp = await client.get("/api/v1/todos/missing")

        assert resp.status_code == 404
        assert "Todo not found" in resp.json()["detail"]

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, side_effect=RuntimeError("db fail")):
            resp = await client.get("/api/v1/todos/todo-1")

        assert resp.status_code == 500


# ============================================================================
# GET /todos/{todo_id}/canvas
# ============================================================================


class TestGetTodoCanvas:
    async def test_success_returns_content(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.read_canvas", new_callable=AsyncMock, return_value="# Canvas\nhello"):
            resp = await client.get("/api/v1/todos/todo-1/canvas")

        assert resp.status_code == 200
        assert resp.json()["content"] == "# Canvas\nhello"

    async def test_empty_canvas_returns_empty_string(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.read_canvas", new_callable=AsyncMock, return_value=""):
            resp = await client.get("/api/v1/todos/todo-1/canvas")

        assert resp.status_code == 200
        assert resp.json()["content"] == ""

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.read_canvas", new_callable=AsyncMock, return_value=None):
            resp = await client.get("/api/v1/todos/missing/canvas")

        assert resp.status_code == 404
        assert "Todo not found" in resp.json()["detail"]


# ============================================================================
# PUT /todos/{todo_id}
# ============================================================================


class TestUpdateTodo:
    async def test_success(self, client: AsyncClient) -> None:
        updated = _todo_resp()
        updated.title = "Updated"
        with patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, return_value=updated):
            resp = await client.put("/api/v1/todos/todo-1", json={"title": "Updated"})

        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    async def test_reschedules_when_scheduled_at_and_vfs(self, client: AsyncClient) -> None:
        updated = _todo_resp(vfs_path="/users/u/todos/todo-1")
        with (
            patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, return_value=updated),
            patch(f"{TODOS_MOD}.tracked_todo_service.reschedule_execution", new_callable=AsyncMock, return_value=True) as mock_resched,
        ):
            resp = await client.put(
                "/api/v1/todos/todo-1",
                json={"scheduled_at": "2025-06-01T10:00:00Z"},
            )

        assert resp.status_code == 200
        mock_resched.assert_awaited_once_with("todo-1", datetime(2025, 6, 1, 10, 0, tzinfo=UTC))

    async def test_reschedule_failure_is_swallowed(self, client: AsyncClient) -> None:
        updated = _todo_resp(vfs_path="/users/u/todos/todo-1")
        with (
            patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, return_value=updated),
            patch(f"{TODOS_MOD}.tracked_todo_service.reschedule_execution", new_callable=AsyncMock, side_effect=RuntimeError("redis down")),
        ):
            resp = await client.put("/api/v1/todos/todo-1", json={"scheduled_at": "2025-06-01T10:00:00Z"})

        assert resp.status_code == 200  # still success

    async def test_no_reschedule_when_no_vfs(self, client: AsyncClient) -> None:
        updated = _todo_resp(vfs_path=None)
        with (
            patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, return_value=updated),
            patch(f"{TODOS_MOD}.tracked_todo_service.reschedule_execution", new_callable=AsyncMock) as mock_resched,
        ):
            resp = await client.put("/api/v1/todos/todo-1", json={"scheduled_at": "2025-06-01T10:00:00Z"})

        assert resp.status_code == 200
        mock_resched.assert_not_called()

    async def test_no_reschedule_when_scheduled_at_none(self, client: AsyncClient) -> None:
        updated = _todo_resp(vfs_path="/users/u/todos/t1")
        with (
            patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, return_value=updated),
            patch(f"{TODOS_MOD}.tracked_todo_service.reschedule_execution", new_callable=AsyncMock) as mock_resched,
        ):
            resp = await client.put("/api/v1/todos/todo-1", json={"title": "no schedule"})

        assert resp.status_code == 200
        mock_resched.assert_not_called()

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, side_effect=ValueError("Todo not found")):
            resp = await client.put("/api/v1/todos/missing", json={"title": "x"})

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.put("/api/v1/todos/todo-1", json={"title": "x"})

        assert resp.status_code == 500

    async def test_completion_toggled(self, client: AsyncClient) -> None:
        updated = _todo_resp()
        updated.completed = True
        with patch(f"{TODOS_MOD}.TodoService.update_todo", new_callable=AsyncMock, return_value=updated):
            resp = await client.put("/api/v1/todos/todo-1", json={"completed": True})

        assert resp.status_code == 200


# ============================================================================
# DELETE /todos/{todo_id}
# ============================================================================


class TestDeleteTodo:
    async def test_success_returns_204(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.delete_todo", new_callable=AsyncMock, return_value=None):
            resp = await client.delete("/api/v1/todos/todo-1")

        assert resp.status_code == 204
        assert resp.content == b""

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.delete_todo", new_callable=AsyncMock, side_effect=ValueError("Todo not found")):
            resp = await client.delete("/api/v1/todos/missing")

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.delete_todo", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.delete("/api/v1/todos/todo-1")

        assert resp.status_code == 500


# ============================================================================
# POST /todos/{todo_id}/workflow
# ============================================================================


class TestGenerateWorkflow:
    async def test_generating_when_no_workflow(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id=None)
        todo_resp.description = "desc"
        with (
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch(f"{TODOS_MOD}.delete_cache", new_callable=AsyncMock),
            patch("app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation", new_callable=AsyncMock, return_value=True),
        ):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == TodoWorkflowGenerationStatus.GENERATING.value
        assert body["todo_id"] == "todo-1"

    async def test_exists_when_workflow_has_steps(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id="wf-1")
        # The EXISTS/COMPLETED response serializes the workflow through
        # WorkflowWithIntegrations — a real model (with a real step) is required,
        # a MagicMock fails response validation (404).
        wf = WorkflowWithIntegrations(
            id="wf-1",
            user_id=FAKE_USER_ID,
            title="Test workflow",
            description="desc",
            prompt="prompt",
            icon=None,
            steps=[WorkflowStep(title="Step 1", description="do the thing")],
            trigger_config=TriggerConfig(type=TriggerType.MANUAL),
        )
        with (
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.service.WorkflowService.get_workflow", new_callable=AsyncMock, return_value=wf),
            patch(f"{TODOS_MOD}.delete_cache", new_callable=AsyncMock),
        ):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == TodoWorkflowGenerationStatus.EXISTS.value

    async def test_regenerates_when_workflow_empty(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id="wf-1")
        wf_empty = _make_workflow(steps=[])
        with (
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.service.WorkflowService.get_workflow", new_callable=AsyncMock, return_value=wf_empty),
            patch("app.services.workflow.service.WorkflowService.delete_workflow", new_callable=AsyncMock, return_value=True),
            patch(f"{TODOS_MOD}.todo_repository.clear_workflow_id", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.delete_cache", new_callable=AsyncMock),
            patch("app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation", new_callable=AsyncMock, return_value=True),
        ):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == TodoWorkflowGenerationStatus.GENERATING.value

    async def test_regenerates_when_workflow_is_none(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id="wf-1")
        with (
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.service.WorkflowService.get_workflow", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.todo_repository.clear_workflow_id", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.delete_cache", new_callable=AsyncMock),
            patch("app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation", new_callable=AsyncMock, return_value=True),
        ):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == TodoWorkflowGenerationStatus.GENERATING.value

    async def test_queue_failure_returns_500(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id=None)
        with (
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch(f"{TODOS_MOD}.delete_cache", new_callable=AsyncMock),
            patch("app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation", new_callable=AsyncMock, return_value=False),
        ):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 500
        assert "Failed to queue workflow generation" in resp.json()["detail"]

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, side_effect=ValueError("Todo not found")):
            resp = await client.post("/api/v1/todos/missing/workflow")

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 500


# ============================================================================
# GET /todos/{todo_id}/workflow-status
# ============================================================================


class TestGetWorkflowStatus:
    async def test_cached_returns_immediately(self, client: AsyncClient) -> None:
        cached = TodoWorkflowStatusResponse(
            todo_id="todo-1",
            has_workflow=True,
            is_generating=False,
            workflow_status=TodoWorkflowStatus.COMPLETED,
            workflow=None,
        )
        with patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=cached):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == TodoWorkflowStatus.COMPLETED.value
        assert resp.headers["Cache-Control"] == "private, max-age=15"

    async def test_is_generating_true(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id=None)
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=True),
            patch(f"{TODOS_MOD}.set_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_generating"] is True
        assert body["workflow_status"] == TodoWorkflowStatus.GENERATING.value

    async def test_has_workflow_with_steps_completed(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id="wf-1")
        wf = WorkflowWithIntegrations(
            id="wf-1",
            user_id=FAKE_USER_ID,
            title="Test workflow",
            description="desc",
            prompt="prompt",
            icon=None,
            steps=[WorkflowStep(title="Step 1", description="do the thing")],
            trigger_config=TriggerConfig(type=TriggerType.MANUAL),
        )
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=False),
            patch("app.services.workflow.service.WorkflowService.get_workflow", new_callable=AsyncMock, return_value=wf),
            patch(f"{TODOS_MOD}.set_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == TodoWorkflowStatus.COMPLETED.value
        assert resp.json()["has_workflow"] is True

    async def test_has_workflow_empty_but_generating(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id="wf-1")
        wf_empty = _make_workflow(steps=[])
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            # First call returns False (initial gather), second call inside branch returns True
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, side_effect=[False, True]),
            patch("app.services.workflow.service.WorkflowService.get_workflow", new_callable=AsyncMock, return_value=wf_empty),
            patch(f"{TODOS_MOD}.set_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        # After second check, is_generating should be True, status GENERATING
        assert resp.json()["workflow_status"] == TodoWorkflowStatus.GENERATING.value
        assert resp.json()["is_generating"] is True

    async def test_has_workflow_empty_not_generating_failed(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id="wf-1")
        wf_empty = _make_workflow(steps=[])
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=False),
            patch("app.services.workflow.service.WorkflowService.get_workflow", new_callable=AsyncMock, return_value=wf_empty),
            patch(f"{TODOS_MOD}.set_cache", new_callable=AsyncMock),
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == TodoWorkflowStatus.FAILED.value
        assert resp.json()["has_workflow"] is False

    async def test_not_started_when_no_workflow_and_not_generating(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id=None)
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=False),
            patch(f"{TODOS_MOD}.set_cache", new_callable=AsyncMock) as mock_set,
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == TodoWorkflowStatus.NOT_STARTED.value
        mock_set.assert_awaited_once()  # caches non-generating result

    async def test_generating_does_not_cache(self, client: AsyncClient) -> None:
        todo_resp = _todo_resp(workflow_id=None)
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, return_value=todo_resp),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=True),
            patch(f"{TODOS_MOD}.set_cache", new_callable=AsyncMock) as mock_set,
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 200
        mock_set.assert_not_called()

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, side_effect=ValueError("Todo not found")),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=False),
        ):
            resp = await client.get("/api/v1/todos/missing/workflow-status")

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(f"{TODOS_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{TODOS_MOD}.TodoService.get_todo", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating", new_callable=AsyncMock, return_value=False),
        ):
            resp = await client.get("/api/v1/todos/todo-1/workflow-status")

        assert resp.status_code == 500


# ============================================================================
# Projects
# ============================================================================


class TestListProjects:
    async def test_success(self, client: AsyncClient) -> None:
        projects = [_project_resp("p1"), _project_resp("p2")]
        with patch(f"{TODOS_MOD}.ProjectService.list_projects", new_callable=AsyncMock, return_value=projects):
            resp = await client.get("/api/v1/projects")

        assert resp.status_code == 200
        assert len(resp.json()) == 2
        assert resp.json()[0]["id"] == "p1"

    async def test_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.list_projects", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.get("/api/v1/projects")

        assert resp.status_code == 500


class TestCreateProject:
    async def test_success(self, client: AsyncClient) -> None:
        proj = _project_resp()
        with patch(f"{TODOS_MOD}.ProjectService.create_project", new_callable=AsyncMock, return_value=proj):
            resp = await client.post("/api/v1/projects", json={"name": "My Project"})

        assert resp.status_code == 201
        assert resp.json()["name"] == "My Project"

    async def test_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.create_project", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.post("/api/v1/projects", json={"name": "x"})

        assert resp.status_code == 500

    async def test_validation_missing_name_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/projects", json={})
        assert resp.status_code == 422

    async def test_with_color_and_description(self, client: AsyncClient) -> None:
        proj = _project_resp()
        proj.color = "#FF0000"
        proj.description = "desc"
        with patch(f"{TODOS_MOD}.ProjectService.create_project", new_callable=AsyncMock, return_value=proj):
            resp = await client.post("/api/v1/projects", json={"name": "x", "color": "#FF0000", "description": "desc"})

        assert resp.status_code == 201


class TestUpdateProject:
    async def test_success(self, client: AsyncClient) -> None:
        updated = _project_resp()
        updated.name = "Updated"
        with patch(f"{TODOS_MOD}.ProjectService.update_project", new_callable=AsyncMock, return_value=updated):
            resp = await client.put("/api/v1/projects/proj-1", json={"name": "Updated"})

        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    async def test_cannot_update_default_returns_400(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.update_project", new_callable=AsyncMock, side_effect=ValueError("Cannot update default Inbox project")):
            resp = await client.put("/api/v1/projects/proj-1", json={"name": "x"})

        assert resp.status_code == 400
        assert "Cannot update" in resp.json()["detail"]

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.update_project", new_callable=AsyncMock, side_effect=ValueError("Project not found")):
            resp = await client.put("/api/v1/projects/missing", json={"name": "x"})

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.update_project", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.put("/api/v1/projects/proj-1", json={"name": "x"})

        assert resp.status_code == 500


class TestDeleteProject:
    async def test_success_returns_204(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.delete_project", new_callable=AsyncMock, return_value=None):
            resp = await client.delete("/api/v1/projects/proj-1")

        assert resp.status_code == 204

    async def test_cannot_delete_default_returns_400(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.delete_project", new_callable=AsyncMock, side_effect=ValueError("Cannot delete default Inbox project")):
            resp = await client.delete("/api/v1/projects/proj-1")

        assert resp.status_code == 400
        assert "Cannot delete" in resp.json()["detail"]

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.delete_project", new_callable=AsyncMock, side_effect=ValueError("Project not found")):
            resp = await client.delete("/api/v1/projects/missing")

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.ProjectService.delete_project", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.delete("/api/v1/projects/proj-1")

        assert resp.status_code == 500


# ============================================================================
# Subtasks
# ============================================================================


class TestCreateSubtask:
    async def test_success(self, client: AsyncClient) -> None:
        # repository returns updated document
        doc = _todo_doc(subtasks=[SubTask(id="sub-1", title="Buy milk", completed=False)])
        with patch(f"{TODOS_MOD}.todo_repository.add_subtask", new_callable=AsyncMock, return_value=doc):
            resp = await client.post("/api/v1/todos/todo-1/subtasks", json={"title": "Buy milk"})

        assert resp.status_code == 201
        assert resp.json()["id"] == "todo-1"
        assert len(resp.json()["subtasks"]) == 1
        assert resp.json()["subtasks"][0]["title"] == "Buy milk"

    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.add_subtask", new_callable=AsyncMock, return_value=None):
            resp = await client.post("/api/v1/todos/todo-1/subtasks", json={"title": "x"})

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.add_subtask", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.post("/api/v1/todos/todo-1/subtasks", json={"title": "x"})

        assert resp.status_code == 500

    async def test_validation_missing_title_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/todos/todo-1/subtasks", json={})
        assert resp.status_code == 422


class TestUpdateSubtask:
    async def test_success_update_title(self, client: AsyncClient) -> None:
        doc = _todo_doc(subtasks=[SubTask(id="sub-1", title="New title", completed=False)])
        with patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=doc):
            resp = await client.put("/api/v1/todos/todo-1/subtasks/sub-1", json={"title": "New title"})

        assert resp.status_code == 200
        assert resp.json()["subtasks"][0]["title"] == "New title"

    async def test_success_update_completed(self, client: AsyncClient) -> None:
        doc = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=True)])
        with patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=doc):
            resp = await client.put("/api/v1/todos/todo-1/subtasks/sub-1", json={"completed": True})

        assert resp.status_code == 200
        assert resp.json()["subtasks"][0]["completed"] is True

    async def test_todo_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=None):
            resp = await client.put("/api/v1/todos/missing/subtasks/sub-1", json={"title": "x"})

        assert resp.status_code == 404

    async def test_subtask_not_found_returns_404(self, client: AsyncClient) -> None:
        # repository returns document but without matching subtask -> endpoint checks and returns 404
        doc = _todo_doc(subtasks=[SubTask(id="other", title="x", completed=False)])
        with patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=doc):
            resp = await client.put("/api/v1/todos/todo-1/subtasks/sub-1", json={"title": "x"})

        assert resp.status_code == 404
        assert "Subtask not found" in resp.json()["detail"]

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.put("/api/v1/todos/todo-1/subtasks/sub-1", json={"title": "x"})

        assert resp.status_code == 500


class TestDeleteSubtask:
    async def test_success(self, client: AsyncClient) -> None:
        # after deletion, doc.subtasks should NOT contain the deleted id
        doc = _todo_doc(subtasks=[SubTask(id="sub-2", title="keep", completed=False)])
        with patch(f"{TODOS_MOD}.todo_repository.remove_subtask", new_callable=AsyncMock, return_value=doc):
            resp = await client.delete("/api/v1/todos/todo-1/subtasks/sub-1")

        assert resp.status_code == 200
        assert all(s["id"] != "sub-1" for s in resp.json()["subtasks"])

    async def test_todo_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.remove_subtask", new_callable=AsyncMock, return_value=None):
            resp = await client.delete("/api/v1/todos/missing/subtasks/sub-1")

        assert resp.status_code == 404

    async def test_subtask_not_found_returns_404(self, client: AsyncClient) -> None:
        # If subtask still present after remove, it means nothing was removed -> 404
        doc = _todo_doc(subtasks=[SubTask(id="sub-1", title="still there", completed=False)])
        with patch(f"{TODOS_MOD}.todo_repository.remove_subtask", new_callable=AsyncMock, return_value=doc):
            resp = await client.delete("/api/v1/todos/todo-1/subtasks/sub-1")

        assert resp.status_code == 404
        assert "Subtask not found" in resp.json()["detail"]

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.remove_subtask", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.delete("/api/v1/todos/todo-1/subtasks/sub-1")

        assert resp.status_code == 500


class TestToggleSubtaskCompletion:
    async def test_toggle_from_false_to_true(self, client: AsyncClient) -> None:
        doc_before = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=False)])
        doc_after = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=True)])
        with (
            patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, return_value=doc_before),
            patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=doc_after),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 200
        assert resp.json()["subtasks"][0]["completed"] is True
        mock_capture.assert_called_once()
        # check captured props
        assert mock_capture.call_args[0][1]["is_subtask"] is True
        assert mock_capture.call_args[0][1]["completed"] is True

    async def test_toggle_from_true_to_false(self, client: AsyncClient) -> None:
        doc_before = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=True)])
        doc_after = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=False)])
        with (
            patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, return_value=doc_before),
            patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=doc_after),
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 200
        assert resp.json()["subtasks"][0]["completed"] is False

    async def test_todo_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, return_value=None):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 404

    async def test_subtask_not_found_returns_404(self, client: AsyncClient) -> None:
        doc = _todo_doc(subtasks=[SubTask(id="other", title="x", completed=False)])
        with patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, return_value=doc):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 404
        assert "Subtask not found" in resp.json()["detail"]

    async def test_set_subtask_fields_returns_none_returns_404(self, client: AsyncClient) -> None:
        doc_before = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=False)])
        with (
            patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, return_value=doc_before),
            patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 404

    async def test_generic_exception_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 500

    async def test_set_fields_exception_returns_500(self, client: AsyncClient) -> None:
        doc_before = _todo_doc(subtasks=[SubTask(id="sub-1", title="x", completed=False)])
        with (
            patch(f"{TODOS_MOD}.todo_repository.get", new_callable=AsyncMock, return_value=doc_before),
            patch(f"{TODOS_MOD}.todo_repository.set_subtask_fields", new_callable=AsyncMock, side_effect=RuntimeError("fail")),
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 500
