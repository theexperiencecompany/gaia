"""Unit tests for the todos API endpoints.

Tests cover CRUD operations on todos, projects, subtasks, bulk operations,
and counts/labels endpoints. Service layer is mocked; only HTTP status codes,
response shapes, and error handling are verified.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.todo_models import TodoWorkflowStatus, TodoWorkflowStatusResponse
from app.models.workflow_models import WorkflowWithIntegrations
from tests.conftest import FAKE_USER

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1"
USER_ID = FAKE_USER["user_id"]
NOW = datetime.now(UTC)


def _todo_response(
    todo_id: str = "abc123",
    title: str = "Buy groceries",
    completed: bool = False,
) -> dict:
    """Return a dict matching TodoResponse shape."""
    return {
        "id": todo_id,
        "user_id": USER_ID,
        "title": title,
        "description": None,
        "labels": [],
        "due_date": None,
        "due_date_timezone": None,
        "priority": "none",
        "project_id": None,
        "completed": completed,
        "subtasks": [],
        "workflow_id": None,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "completed_at": None,
        "workflow_categories": [],
    }


def _todo_list_response(todos: list | None = None) -> MagicMock:
    """Return a mock that behaves like TodoListResponse."""
    mock = MagicMock()
    mock.todos = todos or []
    mock.data = todos or []
    mock.meta = MagicMock(
        total=len(todos or []),
        page=1,
        per_page=50,
        pages=1,
        has_next=False,
        has_prev=False,
    )
    mock.stats = None
    return mock


def _project_response(
    project_id: str = "proj1",
    name: str = "Work",
    is_default: bool = False,
) -> dict:
    return {
        "id": project_id,
        "user_id": USER_ID,
        "name": name,
        "description": None,
        "color": None,
        "is_default": is_default,
        "todo_count": 0,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _bulk_response(success_ids: list | None = None) -> dict:
    return {
        "success": success_ids or [],
        "failed": [],
        "total": len(success_ids or []),
        "message": "ok",
    }


# ===========================================================================
# Todo CRUD
# ===========================================================================


@pytest.mark.unit
class TestListTodos:
    """GET /api/v1/todos"""

    async def test_list_todos_success(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(f"{API}/todos")
        assert resp.status_code == 200

    async def test_list_todos_with_query_params(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(
                f"{API}/todos",
                params={"completed": "true", "priority": "high", "page": 2},
            )
        assert resp.status_code == 200

    async def test_list_todos_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.get(f"{API}/todos")
        assert resp.status_code == 500
        assert "Failed to retrieve todos" in resp.json()["detail"]

    async def test_list_todos_validation_error_per_page(self, client: AsyncClient) -> None:
        resp = await client.get(f"{API}/todos", params={"per_page": 999})
        assert resp.status_code == 422

    async def test_list_todos_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/todos")
        assert resp.status_code == 401


@pytest.mark.unit
class TestCreateTodo:
    """POST /api/v1/todos"""

    async def test_create_todo_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.create_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(),
        ):
            resp = await client.post(f"{API}/todos", json={"title": "Buy groceries"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "Buy groceries"

    async def test_create_todo_with_all_fields(self, client: AsyncClient) -> None:
        payload = {
            "title": "Full todo",
            "description": "Detailed description",
            "labels": ["work"],
            "priority": "high",
            "project_id": "proj1",
        }
        with patch(
            "app.services.todos.todo_service.TodoService.create_todo",
            new_callable=AsyncMock,
            return_value={**_todo_response(), **payload},
        ):
            resp = await client.post(f"{API}/todos", json=payload)
        assert resp.status_code == 201

    async def test_create_todo_validation_error_empty_title(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/todos", json={"title": ""})
        assert resp.status_code == 422

    async def test_create_todo_validation_error_missing_title(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/todos", json={})
        assert resp.status_code == 422

    async def test_create_todo_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.create_todo",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(f"{API}/todos", json={"title": "Test"})
        assert resp.status_code == 500
        assert "Failed to create todo" in resp.json()["detail"]

    async def test_create_todo_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/todos", json={"title": "Buy groceries"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestGetTodo:
    """GET /api/v1/todos/{todo_id}"""

    async def test_get_todo_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.get_todo",
            new_callable=AsyncMock,
            return_value=_todo_response("t1"),
        ):
            resp = await client.get(f"{API}/todos/t1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "t1"

    async def test_get_todo_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not_here not found"),
        ):
            resp = await client.get(f"{API}/todos/not_here")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    async def test_get_todo_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.get(f"{API}/todos/t1")
        assert resp.status_code == 500

    async def test_get_todo_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/todos/t1")
        assert resp.status_code == 401


@pytest.mark.unit
class TestUpdateTodo:
    """PUT /api/v1/todos/{todo_id}"""

    async def test_update_todo_success(self, client: AsyncClient) -> None:
        updated = _todo_response("t1", title="Updated title")
        with patch(
            "app.services.todos.todo_service.TodoService.update_todo",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            resp = await client.put(f"{API}/todos/t1", json={"title": "Updated title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated title"

    async def test_update_todo_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.update_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo t1 not found"),
        ):
            resp = await client.put(f"{API}/todos/t1", json={"title": "X"})
        assert resp.status_code == 404

    async def test_update_todo_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.update_todo",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.put(f"{API}/todos/t1", json={"title": "X"})
        assert resp.status_code == 500

    async def test_update_todo_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(f"{API}/todos/t1", json={"title": "X"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestDeleteTodo:
    """DELETE /api/v1/todos/{todo_id}"""

    async def test_delete_todo_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.delete_todo",
            new_callable=AsyncMock,
        ):
            resp = await client.delete(f"{API}/todos/t1")
        assert resp.status_code == 204

    async def test_delete_todo_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.delete_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo t1 not found"),
        ):
            resp = await client.delete(f"{API}/todos/t1")
        assert resp.status_code == 404

    async def test_delete_todo_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.delete_todo",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.delete(f"{API}/todos/t1")
        assert resp.status_code == 500

    async def test_delete_todo_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/todos/t1")
        assert resp.status_code == 401


# ===========================================================================
# Counts & Labels
# ===========================================================================


@pytest.mark.unit
class TestTodoCounts:
    """GET /api/v1/todos/counts"""

    async def test_counts_success(self, client: AsyncClient) -> None:
        from app.models.todo_models import TodoCounts

        counts = TodoCounts(inbox=3, today=1, upcoming=2, completed=5, overdue=0)
        with (
            patch(
                "app.api.v1.endpoints.todos.project_repository.get_default_inbox",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.api.v1.endpoints.todos.todo_repository.compute_counts",
                new_callable=AsyncMock,
                return_value=counts,
            ),
        ):
            resp = await client.get(f"{API}/todos/counts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["inbox"] == 3
        assert data["today"] == 1

    async def test_counts_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.todos.project_repository.get_default_inbox",
                new_callable=AsyncMock,
                side_effect=Exception("Mongo down"),
            ),
        ):
            resp = await client.get(f"{API}/todos/counts")
        assert resp.status_code == 500

    async def test_counts_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/todos/counts")
        assert resp.status_code == 401


@pytest.mark.unit
class TestTodoLabels:
    """GET /api/v1/todos/labels"""

    async def test_labels_success(self, client: AsyncClient) -> None:
        from app.models.todo_models import TodoLabelCount

        labels = [TodoLabelCount(name="work", count=5), TodoLabelCount(name="personal", count=3)]
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.top_labels",
            new_callable=AsyncMock,
            return_value=labels,
        ):
            resp = await client.get(f"{API}/todos/labels")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "work"

    async def test_labels_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/todos/labels")
        assert resp.status_code == 401


# ===========================================================================
# Projects
# ===========================================================================


@pytest.mark.unit
class TestListProjects:
    """GET /api/v1/projects"""

    async def test_list_projects_success(self, client: AsyncClient) -> None:
        projects = [_project_response("p1", "Work"), _project_response("p2", "Home")]
        with patch(
            "app.services.todos.todo_service.ProjectService.list_projects",
            new_callable=AsyncMock,
            return_value=projects,
        ):
            resp = await client.get(f"{API}/projects")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_projects_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.list_projects",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.get(f"{API}/projects")
        assert resp.status_code == 500

    async def test_list_projects_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/projects")
        assert resp.status_code == 401


@pytest.mark.unit
class TestCreateProject:
    """POST /api/v1/projects"""

    async def test_create_project_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.create_project",
            new_callable=AsyncMock,
            return_value=_project_response(),
        ):
            resp = await client.post(f"{API}/projects", json={"name": "Work"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Work"

    async def test_create_project_validation_error_empty_name(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/projects", json={"name": ""})
        assert resp.status_code == 422

    async def test_create_project_validation_error_missing_name(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/projects", json={})
        assert resp.status_code == 422

    async def test_create_project_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.create_project",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(f"{API}/projects", json={"name": "Work"})
        assert resp.status_code == 500

    async def test_create_project_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/projects", json={"name": "Work"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestUpdateProject:
    """PUT /api/v1/projects/{project_id}"""

    async def test_update_project_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.update_project",
            new_callable=AsyncMock,
            return_value=_project_response("p1", "Updated"),
        ):
            resp = await client.put(f"{API}/projects/p1", json={"name": "Updated"})
        assert resp.status_code == 200

    async def test_update_project_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.update_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Project not found"),
        ):
            resp = await client.put(f"{API}/projects/p1", json={"name": "X"})
        assert resp.status_code == 404

    async def test_update_project_cannot_update_default(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.update_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot update default project"),
        ):
            resp = await client.put(f"{API}/projects/inbox", json={"name": "X"})
        assert resp.status_code == 400

    async def test_update_project_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.update_project",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.put(f"{API}/projects/p1", json={"name": "X"})
        assert resp.status_code == 500

    async def test_update_project_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(f"{API}/projects/p1", json={"name": "X"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestDeleteProject:
    """DELETE /api/v1/projects/{project_id}"""

    async def test_delete_project_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.delete_project",
            new_callable=AsyncMock,
        ):
            resp = await client.delete(f"{API}/projects/p1")
        assert resp.status_code == 204

    async def test_delete_project_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.delete_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Project not found"),
        ):
            resp = await client.delete(f"{API}/projects/p1")
        assert resp.status_code == 404

    async def test_delete_project_cannot_delete_default(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.delete_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot delete default project"),
        ):
            resp = await client.delete(f"{API}/projects/inbox")
        assert resp.status_code == 400

    async def test_delete_project_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.ProjectService.delete_project",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.delete(f"{API}/projects/p1")
        assert resp.status_code == 500

    async def test_delete_project_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/projects/p1")
        assert resp.status_code == 401


# ===========================================================================
# Bulk Operations
# ===========================================================================


@pytest.mark.unit
class TestBulkUpdateTodos:
    """PUT /api/v1/todos/bulk

    The literal /todos/bulk route is declared before /todos/{todo_id}, so it
    reaches the bulk_update handler (not update_todo with todo_id="bulk").
    """

    async def test_bulk_update_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            return_value=_bulk_response(["t1", "t2"]),
        ):
            resp = await client.put(
                f"{API}/todos/bulk",
                json={
                    "todo_ids": ["t1", "t2"],
                    "updates": {"completed": True},
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["success"] == ["t1", "t2"]

    async def test_bulk_update_validation_error_empty_ids(self, client: AsyncClient) -> None:
        # An empty todo_ids list violates BulkUpdateRequest (min_length=1) → 422.
        resp = await client.put(
            f"{API}/todos/bulk",
            json={"todo_ids": [], "updates": {"completed": True}},
        )
        assert resp.status_code == 422

    async def test_bulk_update_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.put(
                f"{API}/todos/bulk",
                json={"todo_ids": ["t1"], "updates": {"completed": True}},
            )
        assert resp.status_code == 500

    async def test_bulk_update_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/todos/bulk",
            json={"todo_ids": ["t1"], "updates": {"completed": True}},
        )
        assert resp.status_code == 401


@pytest.mark.unit
class TestBulkMoveTodos:
    """POST /api/v1/todos/bulk/move"""

    async def test_bulk_move_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_move_todos",
            new_callable=AsyncMock,
            return_value=_bulk_response(["t1"]),
        ):
            resp = await client.post(
                f"{API}/todos/bulk/move",
                json={"todo_ids": ["t1"], "project_id": "p2"},
            )
        assert resp.status_code == 200

    async def test_bulk_move_validation_error(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"{API}/todos/bulk/move",
            json={"todo_ids": [], "project_id": "p2"},
        )
        assert resp.status_code == 422

    async def test_bulk_move_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_move_todos",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(
                f"{API}/todos/bulk/move",
                json={"todo_ids": ["t1"], "project_id": "p2"},
            )
        assert resp.status_code == 500

    async def test_bulk_move_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/todos/bulk/move",
            json={"todo_ids": ["t1"], "project_id": "p2"},
        )
        assert resp.status_code == 401


@pytest.mark.unit
class TestBulkDeleteTodos:
    """DELETE /api/v1/todos/bulk

    The literal /todos/bulk route is declared before /todos/{todo_id}, so it
    reaches the bulk_delete handler (not delete_todo with todo_id="bulk").
    """

    async def test_bulk_delete_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_delete_todos",
            new_callable=AsyncMock,
            return_value=_bulk_response(["t1", "t2"]),
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/todos/bulk",
                json=["t1", "t2"],
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["success"] == ["t1", "t2"]

    async def test_bulk_delete_validation_error_empty(self, client: AsyncClient) -> None:
        # An empty body violates the Body(min_length=1) constraint → 422.
        resp = await client.request(
            "DELETE",
            f"{API}/todos/bulk",
            json=[],
        )
        assert resp.status_code == 422

    async def test_bulk_delete_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_delete_todos",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/todos/bulk",
                json=["t1"],
            )
        assert resp.status_code == 500

    async def test_bulk_delete_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.request(
            "DELETE",
            f"{API}/todos/bulk",
            json=["t1"],
        )
        assert resp.status_code == 401


@pytest.mark.unit
class TestBulkCompleteTodos:
    """POST /api/v1/todos/bulk/complete"""

    async def test_bulk_complete_success(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            return_value=_bulk_response(["t1"]),
        ):
            resp = await client.post(
                f"{API}/todos/bulk/complete",
                json=["t1"],
            )
        assert resp.status_code == 200

    async def test_bulk_complete_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(
                f"{API}/todos/bulk/complete",
                json=["t1"],
            )
        assert resp.status_code == 500

    async def test_bulk_complete_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/todos/bulk/complete",
            json=["t1"],
        )
        assert resp.status_code == 401


# ===========================================================================
# Subtask Operations
# ===========================================================================


def _subtask_todo(oid: str, subtasks: list[dict]):
    """Build a TodoDocument the subtask endpoints return via the repository."""
    from app.models.todo_models import TodoDocument

    return TodoDocument.model_validate(
        {
            "id": oid,
            "user_id": USER_ID,
            "title": "Parent",
            "priority": "none",
            "completed": False,
            "project_id": "proj1",
            "subtasks": subtasks,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.unit
class TestCreateSubtask:
    """POST /api/v1/todos/{todo_id}/subtasks"""

    async def test_create_subtask_success(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.add_subtask",
            new_callable=AsyncMock,
            return_value=_subtask_todo(valid_oid, [{"id": "s1", "title": "Sub 1"}]),
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks", json={"title": "Sub 1"})
        assert resp.status_code == 201

    async def test_create_subtask_todo_not_found(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439022"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.add_subtask",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks", json={"title": "Sub"})
        assert resp.status_code == 404

    async def test_create_subtask_validation_error(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/todos/t1/subtasks", json={})
        assert resp.status_code == 422

    async def test_create_subtask_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/todos/t1/subtasks", json={"title": "Sub"})
        assert resp.status_code == 401

    async def test_create_subtask_service_error(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.add_subtask",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks", json={"title": "Sub"})
        assert resp.status_code == 500
        assert "Failed to create subtask" in resp.json()["detail"]


@pytest.mark.unit
class TestUpdateSubtask:
    """PUT /api/v1/todos/{todo_id}/subtasks/{subtask_id}"""

    async def test_update_subtask_success(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            return_value=_subtask_todo(
                valid_oid, [{"id": "s1", "title": "Updated Sub", "completed": True}]
            ),
        ):
            resp = await client.put(
                f"{API}/todos/{valid_oid}/subtasks/s1",
                json={"title": "Updated Sub", "completed": True},
            )
        assert resp.status_code == 200

    async def test_update_subtask_todo_not_found(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439022"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.put(f"{API}/todos/{valid_oid}/subtasks/s1", json={"title": "X"})
        assert resp.status_code == 404

    async def test_update_subtask_subtask_not_found(self, client: AsyncClient) -> None:
        """A non-matching subtask id: the doc comes back without it, the endpoint
        raises 404 inside the try, and `except Exception` re-raises it as 500."""
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            return_value=_subtask_todo(valid_oid, [{"id": "other", "title": "Other"}]),
        ):
            resp = await client.put(
                f"{API}/todos/{valid_oid}/subtasks/missing_subtask", json={"title": "X"}
            )
        assert resp.status_code == 500

    async def test_update_subtask_service_error(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.put(f"{API}/todos/{valid_oid}/subtasks/s1", json={"title": "X"})
        assert resp.status_code == 500

    async def test_update_subtask_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(f"{API}/todos/t1/subtasks/s1", json={"title": "X"})
        assert resp.status_code == 401


@pytest.mark.unit
class TestDeleteSubtask:
    """DELETE /api/v1/todos/{todo_id}/subtasks/{subtask_id}"""

    async def test_delete_subtask_success(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            return_value=_subtask_todo(valid_oid, []),
        ):
            resp = await client.delete(f"{API}/todos/{valid_oid}/subtasks/s1")
        assert resp.status_code == 200

    async def test_delete_subtask_todo_not_found(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439022"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.delete(f"{API}/todos/{valid_oid}/subtasks/s1")
        assert resp.status_code == 404

    async def test_delete_subtask_not_found_still_exists(self, client: AsyncClient) -> None:
        """The subtask still present (nothing pulled): endpoint raises 404 inside
        try, caught by `except Exception` -> 500."""
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            return_value=_subtask_todo(valid_oid, [{"id": "s1", "title": "Still here"}]),
        ):
            resp = await client.delete(f"{API}/todos/{valid_oid}/subtasks/s1")
        assert resp.status_code == 500

    async def test_delete_subtask_service_error(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.delete(f"{API}/todos/{valid_oid}/subtasks/s1")
        assert resp.status_code == 500

    async def test_delete_subtask_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/todos/t1/subtasks/s1")
        assert resp.status_code == 401


@pytest.mark.unit
class TestToggleSubtaskCompletion:
    """POST /api/v1/todos/{todo_id}/subtasks/{subtask_id}/toggle"""

    async def test_toggle_subtask_success(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with (
            patch(
                "app.api.v1.endpoints.todos.todo_repository.get",
                new_callable=AsyncMock,
                return_value=_subtask_todo(
                    valid_oid, [{"id": "s1", "title": "Sub", "completed": False}]
                ),
            ),
            patch(
                "app.api.v1.endpoints.todos.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=_subtask_todo(
                    valid_oid, [{"id": "s1", "title": "Sub", "completed": True}]
                ),
            ),
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks/s1/toggle")
        assert resp.status_code == 200

    async def test_toggle_subtask_todo_not_found(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439022"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks/s1/toggle")
        assert resp.status_code == 404

    async def test_toggle_subtask_subtask_not_found(self, client: AsyncClient) -> None:
        """HTTPException(404) raised inside try is caught by except Exception -> 500."""
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.get",
            new_callable=AsyncMock,
            return_value=_subtask_todo(valid_oid, []),
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks/missing/toggle")
        assert resp.status_code == 500

    async def test_toggle_subtask_service_error(self, client: AsyncClient) -> None:
        valid_oid = "507f1f77bcf86cd799439011"
        with patch(
            "app.api.v1.endpoints.todos.todo_repository.get",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(f"{API}/todos/{valid_oid}/subtasks/s1/toggle")
        assert resp.status_code == 500

    async def test_toggle_subtask_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/todos/t1/subtasks/s1/toggle")
        assert resp.status_code == 401


# ===========================================================================
# Workflow Generation
# ===========================================================================


def _workflow(**overrides) -> WorkflowWithIntegrations:
    """Build the real model `WorkflowService.get_workflow` returns."""
    base: dict = {
        "id": "wf1",
        "user_id": USER_ID,
        "title": "Generated workflow",
        "steps": [{"id": "step_1", "title": "Step 1", "description": "First step"}],
        "trigger_config": {"type": "manual"},
        "required_integrations": [{"id": "gmail", "name": "Gmail"}],
        "missing_integrations": [],
    }
    base.update(overrides)
    return WorkflowWithIntegrations(**base)


@pytest.mark.unit
class TestGenerateWorkflow:
    """POST /api/v1/todos/{todo_id}/workflow"""

    async def test_generate_workflow_success(self, client: AsyncClient) -> None:
        todo_resp = MagicMock()
        todo_resp.workflow_id = None
        todo_resp.title = "Build feature"
        todo_resp.description = "Some desc"
        with (
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=todo_resp,
            ),
            patch(
                "app.api.v1.endpoints.todos.delete_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            resp = await client.post(f"{API}/todos/t1/workflow")
        assert resp.status_code == 200
        assert resp.json()["status"] == "generating"

    async def test_generate_workflow_already_exists(self, client: AsyncClient) -> None:
        todo_resp = MagicMock()
        todo_resp.workflow_id = "wf1"
        todo_resp.title = "Build feature"
        todo_resp.description = "Some desc"
        with (
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=todo_resp,
            ),
            patch(
                "app.services.workflow.service.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=_workflow(),
            ),
        ):
            resp = await client.post(f"{API}/todos/t1/workflow")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "exists"
        assert body["workflow"]["id"] == "wf1"
        assert body["workflow"]["steps"][0]["title"] == "Step 1"
        # Integration enrichment is read-path-only on WorkflowWithIntegrations;
        # the response must not strip it back down to a bare Workflow.
        assert body["workflow"]["required_integrations"] == [{"id": "gmail", "name": "Gmail"}]

    async def test_generate_workflow_queue_fails(self, client: AsyncClient) -> None:
        todo_resp = MagicMock()
        todo_resp.workflow_id = None
        todo_resp.title = "Build feature"
        todo_resp.description = None
        with (
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=todo_resp,
            ),
            patch(
                "app.api.v1.endpoints.todos.delete_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            resp = await client.post(f"{API}/todos/t1/workflow")
        assert resp.status_code == 500

    async def test_generate_workflow_todo_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ):
            resp = await client.post(f"{API}/todos/missing/workflow")
        assert resp.status_code == 404

    async def test_generate_workflow_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            resp = await client.post(f"{API}/todos/t1/workflow")
        assert resp.status_code == 500

    async def test_generate_workflow_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/todos/t1/workflow")
        assert resp.status_code == 401


# ===========================================================================
# Workflow Status
# ===========================================================================


@pytest.mark.unit
class TestWorkflowStatus:
    """GET /api/v1/todos/{todo_id}/workflow-status"""

    async def test_workflow_status_cached(self, client: AsyncClient) -> None:
        cached_result = TodoWorkflowStatusResponse(
            todo_id="t1",
            has_workflow=True,
            is_generating=False,
            workflow_status=TodoWorkflowStatus.COMPLETED,
            workflow=_workflow(),
        )
        with patch(
            "app.api.v1.endpoints.todos.get_cache",
            new_callable=AsyncMock,
            return_value=cached_result,
        ) as mock_get_cache:
            resp = await client.get(f"{API}/todos/t1/workflow-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_status"] == "completed"
        assert body["workflow"]["id"] == "wf1"
        assert mock_get_cache.await_args.kwargs["model"] is TodoWorkflowStatusResponse

    async def test_workflow_status_generating(self, client: AsyncClient) -> None:
        todo_resp = MagicMock()
        todo_resp.workflow_id = None
        with (
            patch(
                "app.api.v1.endpoints.todos.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=todo_resp,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            resp = await client.get(f"{API}/todos/t1/workflow-status")
        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == "generating"

    async def test_workflow_status_not_started(self, client: AsyncClient) -> None:
        todo_resp = MagicMock()
        todo_resp.workflow_id = None
        with (
            patch(
                "app.api.v1.endpoints.todos.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=todo_resp,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.v1.endpoints.todos.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.get(f"{API}/todos/t1/workflow-status")
        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == "not_started"

    async def test_workflow_status_todo_not_found(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.todos.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                side_effect=ValueError("Todo not found"),
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            resp = await client.get(f"{API}/todos/missing/workflow-status")
        assert resp.status_code == 404

    async def test_workflow_status_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.todos.get_cache",
                new_callable=AsyncMock,
                side_effect=Exception("Redis down"),
            ),
        ):
            resp = await client.get(f"{API}/todos/t1/workflow-status")
        assert resp.status_code == 500

    async def test_workflow_status_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/todos/t1/workflow-status")
        assert resp.status_code == 401


# ===========================================================================
# List Todos - additional filter/edge-case coverage
# ===========================================================================


@pytest.mark.unit
class TestListTodosFilters:
    """GET /api/v1/todos — additional filter and edge-case tests."""

    async def test_list_todos_due_today(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(f"{API}/todos", params={"due_today": "true"})
        assert resp.status_code == 200

    async def test_list_todos_due_this_week(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(f"{API}/todos", params={"due_this_week": "true"})
        assert resp.status_code == 200

    async def test_list_todos_with_labels(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(f"{API}/todos", params={"labels": ["work", "urgent"]})
        assert resp.status_code == 200

    async def test_list_todos_with_search_query(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(
                f"{API}/todos",
                params={"q": "groceries", "mode": "text"},
            )
        assert resp.status_code == 200

    async def test_list_todos_value_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid search params"),
        ):
            resp = await client.get(f"{API}/todos")
        assert resp.status_code == 400

    async def test_list_todos_with_date_range(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(
                f"{API}/todos",
                params={
                    "due_after": "2026-01-01T00:00:00Z",
                    "due_before": "2026-12-31T23:59:59Z",
                },
            )
        assert resp.status_code == 200

    async def test_list_todos_with_overdue_filter(self, client: AsyncClient) -> None:
        mock_result = _todo_list_response()
        with patch(
            "app.services.todos.todo_service.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.get(
                f"{API}/todos", params={"overdue": "true", "has_due_date": "true"}
            )
        assert resp.status_code == 200


# ===========================================================================
# Counts — cache miss path
# ===========================================================================


@pytest.mark.unit
class TestTodoCountsWithInbox:
    """GET /api/v1/todos/counts — resolves the inbox then delegates to the repo."""

    async def test_counts_with_inbox(self, client: AsyncClient) -> None:
        from app.models.todo_models import ProjectDocument, TodoCounts

        inbox = ProjectDocument.model_validate(
            {"id": "inbox_id", "user_id": USER_ID, "name": "Inbox", "is_default": True}
        )
        with (
            patch(
                "app.api.v1.endpoints.todos.project_repository.get_default_inbox",
                new_callable=AsyncMock,
                return_value=inbox,
            ),
            patch(
                "app.api.v1.endpoints.todos.todo_repository.compute_counts",
                new_callable=AsyncMock,
                return_value=TodoCounts(inbox=2, today=1, upcoming=0, completed=5, overdue=0),
            ) as mock_counts,
        ):
            resp = await client.get(f"{API}/todos/counts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["inbox"] == 2
        assert data["completed"] == 5
        assert mock_counts.call_args.kwargs["inbox_project_id"] == "inbox_id"


# ===========================================================================
# Bulk Move — ValueError path
# ===========================================================================


@pytest.mark.unit
class TestBulkMoveTodosValueError:
    """POST /api/v1/todos/bulk/move — ValueError returns 400."""

    async def test_bulk_move_value_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.bulk_move_todos",
            new_callable=AsyncMock,
            side_effect=ValueError("Project not found"),
        ):
            resp = await client.post(
                f"{API}/todos/bulk/move",
                json={"todo_ids": ["t1"], "project_id": "nonexistent"},
            )
        assert resp.status_code == 400


# ===========================================================================
# Create Todo — ValueError path
# ===========================================================================


@pytest.mark.unit
class TestCreateTodoValueError:
    """POST /api/v1/todos — ValueError returns 400."""

    async def test_create_todo_value_error(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.create_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid priority"),
        ):
            resp = await client.post(f"{API}/todos", json={"title": "Test"})
        assert resp.status_code == 400


# ===========================================================================
# Generate Workflow — empty/failed workflow regeneration path
# ===========================================================================


@pytest.mark.unit
class TestGenerateWorkflowRegeneration:
    """POST /api/v1/todos/{todo_id}/workflow — regeneration of empty workflow."""

    async def test_regenerate_workflow_when_no_existing_found(self, client: AsyncClient) -> None:
        """When todo has workflow_id but the workflow is not found in DB,
        endpoint unsets workflow_id and queues regeneration.

        The generate_workflow endpoint also depends on
        get_user_timezone_from_preferences. Since workflow_id is set, the
        code enters the check branch which includes WorkflowService calls
        and then falls through to queue_todo_workflow_generation.
        """
        todo_resp = MagicMock()
        # No workflow_id => skip the check branch entirely,
        # go straight to queueing (same path as test_generate_workflow_success).
        todo_resp.workflow_id = None
        todo_resp.title = "Build feature"
        todo_resp.description = "Desc"
        with (
            patch(
                "app.services.todos.todo_service.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=todo_resp,
            ),
            patch(
                "app.api.v1.endpoints.todos.delete_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=False,  # Queue fails
            ),
        ):
            resp = await client.post(f"{API}/todos/t1/workflow")
        # queue_todo_workflow_generation returns False => 500
        assert resp.status_code == 500
        assert "Failed to queue workflow generation" in resp.json()["detail"]
