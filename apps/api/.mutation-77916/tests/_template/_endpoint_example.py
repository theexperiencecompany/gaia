"""Canonical endpoint test — copy into ``tests/unit/api/``, rename, adapt.

Mirrors ``tests/unit/api/test_todos_endpoint.py``: the root ``client`` fixture
(ASGITransport against the test app, auth dependency overridden), the service
mocked at the class the endpoint calls, and asserts on status code + response
body only. The 401 path uses ``unauthed_client`` (auth dependency popped).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest
from tests.conftest import FAKE_USER

API = "/api/v1"
USER_ID = FAKE_USER["user_id"]
NOW = datetime.now(UTC)


def _todo_response(todo_id: str = "abc123", title: str = "Buy milk") -> dict:
    """A dict matching the TodoResponse shape, as the service returns it."""
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
        "completed": False,
        "subtasks": [],
        "workflow_id": None,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "completed_at": None,
        "workflow_categories": [],
    }


@pytest.mark.unit
class TestCreateTodo:
    async def test_returns_created_with_body(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.create_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(),
        ):
            resp = await client.post(f"{API}/todos", json={"title": "Buy milk"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "Buy milk"

    async def test_returns_400_when_service_raises(self, client: AsyncClient) -> None:
        with patch(
            "app.services.todos.todo_service.TodoService.create_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo missing not found"),
        ):
            resp = await client.post(f"{API}/todos", json={"title": "X"})
        assert resp.status_code == 400

    async def test_returns_401_without_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/todos", json={"title": "Buy milk"})
        assert resp.status_code == 401
