"""Endpoint tests for /api/v1/todos.

Covers the MAX_PAGE_NUMBER page bound on the todo list endpoint, the
happy path with the service faked, and analytics captures on mutations.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.constants.general import MAX_PAGE_NUMBER
from app.models.todo_models import (
    BulkOperationResponse,
    BulkUpdateRequest,
    PaginationMeta,
    SubTask,
    TodoDocument,
    TodoListResponse,
    TodoResponse,
    TodoUpdateRequest,
)
from app.services.analytics_service import AnalyticsEvents

TODOS_ENDPOINT = "app.api.v1.endpoints.todos"
ANALYTICS_PATCH = "app.api.v1.endpoints.todos.capture_context_event"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


def _todo_response() -> TodoResponse:
    return TodoResponse(
        id="todo-1",
        user_id="507f1f77bcf86cd799439011",
        title="Test todo",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _empty_list_response() -> TodoListResponse:
    return TodoListResponse(
        data=[],
        meta=PaginationMeta(total=0, page=1, per_page=50, pages=0, has_next=False, has_prev=False),
    )


class TestListTodos:
    """GET /api/v1/todos"""

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/todos?page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_list_returns_todos(self, client: AsyncClient) -> None:
        with patch(
            f"{TODOS_ENDPOINT}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get("/api/v1/todos?page=1&per_page=50")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["page"] == 1
        assert list_todos.await_args.args[0] == "507f1f77bcf86cd799439011"


class TestTodoAnalytics:
    """Analytics captures on todo endpoints without a service-layer capture.

    Single-todo mutations are captured inside TodoService (covered by
    test_todo_service.py); these assert the endpoint-only bulk and subtask
    captures.
    """

    async def test_bulk_complete_captures_todo_completed(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{TODOS_ENDPOINT}.TodoService.bulk_update_todos",
                new_callable=AsyncMock,
                return_value=BulkOperationResponse(total=2, message="ok"),
            ) as mock_bulk,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post(
                "/api/v1/todos/bulk/complete",
                json=["todo-1", "todo-2"],
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.TODO_TOGGLED, {"bulk_count": 2})
        mock_bulk.assert_awaited_once_with(
            BulkUpdateRequest(
                todo_ids=["todo-1", "todo-2"],
                updates=TodoUpdateRequest(completed=True),
            ),
            "507f1f77bcf86cd799439011",
        )

    async def test_toggle_subtask_captures_todo_completed(self, client: AsyncClient) -> None:
        doc = TodoDocument(
            id="todo-1",
            user_id="507f1f77bcf86cd799439011",
            title="Test todo",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, tzinfo=UTC),
            subtasks=[SubTask(id="sub-1", title="Buy milk", completed=False)],
        )
        updated_doc = doc.model_copy(deep=True)
        updated_doc.subtasks[0].completed = True
        with (
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.TODO_TOGGLED,
            {"is_subtask": True, "completed": True},
        )
