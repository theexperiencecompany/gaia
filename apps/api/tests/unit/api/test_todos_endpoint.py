"""Endpoint tests for /api/v1/todos.

Covers the MAX_PAGE_NUMBER page bound on the todo list endpoint and the
happy path with the service faked.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.constants.general import MAX_PAGE_NUMBER
from app.models.todo_models import PaginationMeta, TodoListResponse

TODOS_ENDPOINT = "app.api.v1.endpoints.todos"


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
