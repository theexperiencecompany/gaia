"""
Tests for todo endpoints (/api/v1/todos/*).

Covers:
- GET /todos/counts — dashboard counts
- GET /todos — list with filters
- POST /todos — create
- GET /todos/{id} — get single
- PUT /todos/{id} — update
- DELETE /todos/{id} — delete
- GET /projects — list projects
- POST /projects — create project
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from tests.conftest import FAKE_USER

TODO_SERVICE = "app.api.v1.endpoints.todos.TodoService"
PROJECT_SERVICE = "app.api.v1.endpoints.todos.ProjectService"

# Minimal valid TodoResponse-compatible dict
_NOW = datetime.now(timezone.utc)
FAKE_TODO = {
    "id": "todo_123",
    "title": "Buy groceries",
    "description": None,
    "labels": [],
    "due_date": None,
    "due_date_timezone": None,
    "priority": "none",
    "project_id": None,
    "completed": False,
    "subtasks": [],
    "workflow_id": None,
    "user_id": FAKE_USER["user_id"],
    "created_at": _NOW,
    "updated_at": _NOW,
    "completed_at": None,
    "workflow_categories": [],
}


def _todo_response(**overrides):
    """Build a TodoResponse-compatible object from FAKE_TODO with overrides."""
    from app.models.todo_models import TodoResponse

    data = {**FAKE_TODO, **overrides}
    return TodoResponse(**data)


def _todo_list_response(todos=None):
    """Build a TodoListResponse-compatible object."""
    from app.models.todo_models import PaginationMeta, TodoListResponse

    items = todos or []
    return TodoListResponse(
        data=items,
        meta=PaginationMeta(
            page=1,
            per_page=50,
            total=len(items),
            pages=1,
            has_next=False,
            has_prev=False,
        ),
    )


class TestTodoCounts:
    """GET /api/v1/todos/counts"""

    async def test_counts_returns_expected_shape(self, client: AsyncClient):
        mock_aggregate = AsyncMock()
        mock_aggregate.to_list = AsyncMock(
            return_value=[
                {
                    "inbox": [{"count": 2}],
                    "today": [{"count": 1}],
                    "upcoming": [],
                    "overdue": [],
                    "completed": [{"count": 3}],
                }
            ]
        )
        mock_inbox = {"_id": "proj_inbox", "is_default": True}

        with (
            patch("app.api.v1.endpoints.todos.projects_collection") as mock_proj_col,
            patch("app.api.v1.endpoints.todos.todos_collection") as mock_todo_col,
        ):
            mock_proj_col.find_one = AsyncMock(return_value=mock_inbox)
            mock_todo_col.aggregate = MagicMock(return_value=mock_aggregate)

            resp = await client.get("/api/v1/todos/counts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["inbox"] == 2
        assert body["today"] == 1
        assert body["completed"] == 3

    async def test_counts_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get("/api/v1/todos/counts")
        assert resp.status_code == 401


class TestListTodos:
    """GET /api/v1/todos"""

    async def test_list_default(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.list_todos",
            new_callable=AsyncMock,
            return_value=_todo_list_response(),
        ):
            resp = await client.get("/api/v1/todos")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "meta" in body

    async def test_list_with_filters(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.list_todos",
            new_callable=AsyncMock,
            return_value=_todo_list_response(),
        ):
            resp = await client.get(
                "/api/v1/todos?completed=false&priority=high&page=1&per_page=10"
            )

        assert resp.status_code == 200


class TestCreateTodo:
    """POST /api/v1/todos"""

    async def test_create_success(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.create_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(),
        ):
            resp = await client.post(
                "/api/v1/todos",
                json={"title": "Buy groceries"},
            )

        assert resp.status_code == 201
        assert resp.json()["title"] == "Buy groceries"

    async def test_create_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/v1/todos",
            json={"title": "Nope"},
        )
        assert resp.status_code == 401

    async def test_create_missing_title(self, client: AsyncClient):
        resp = await client.post("/api/v1/todos", json={})
        assert resp.status_code == 422


class TestGetTodo:
    """GET /api/v1/todos/{id}"""

    async def test_get_existing(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.get_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(),
        ):
            resp = await client.get("/api/v1/todos/todo_123")

        assert resp.status_code == 200
        assert resp.json()["id"] == "todo_123"

    async def test_get_not_found(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.get_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ):
            resp = await client.get("/api/v1/todos/nonexistent")

        assert resp.status_code == 404


class TestUpdateTodo:
    """PUT /api/v1/todos/{id}"""

    async def test_update_success(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.update_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(completed=True),
        ):
            resp = await client.put(
                "/api/v1/todos/todo_123",
                json={"completed": True},
            )

        assert resp.status_code == 200


class TestDeleteTodo:
    """DELETE /api/v1/todos/{id}"""

    async def test_delete_success(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.delete_todo",
            new_callable=AsyncMock,
        ):
            resp = await client.delete("/api/v1/todos/todo_123")

        assert resp.status_code == 204

    async def test_delete_not_found(self, client: AsyncClient):
        with patch(
            f"{TODO_SERVICE}.delete_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ):
            resp = await client.delete("/api/v1/todos/nonexistent")

        assert resp.status_code == 404


class TestListProjects:
    """GET /api/v1/projects"""

    async def test_list_projects(self, client: AsyncClient):
        from app.models.todo_models import ProjectResponse

        mock_project = ProjectResponse(
            id="proj_1",
            name="Inbox",
            is_default=True,
            todo_count=5,
            user_id=FAKE_USER["user_id"],
            created_at=_NOW,
            updated_at=_NOW,
        )
        with patch(
            f"{PROJECT_SERVICE}.list_projects",
            new_callable=AsyncMock,
            return_value=[mock_project],
        ):
            resp = await client.get("/api/v1/projects")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert body[0]["name"] == "Inbox"


class TestCreateProject:
    """POST /api/v1/projects"""

    async def test_create_project(self, client: AsyncClient):
        from app.models.todo_models import ProjectResponse

        mock_project = ProjectResponse(
            id="proj_new",
            name="Work",
            is_default=False,
            todo_count=0,
            user_id=FAKE_USER["user_id"],
            created_at=_NOW,
            updated_at=_NOW,
        )
        with patch(
            f"{PROJECT_SERVICE}.create_project",
            new_callable=AsyncMock,
            return_value=mock_project,
        ):
            resp = await client.post(
                "/api/v1/projects",
                json={"name": "Work"},
            )

        assert resp.status_code == 201
