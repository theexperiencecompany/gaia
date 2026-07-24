"""Integration tests for the todos endpoints — route resolution.

Regression coverage for the ordering bug where the literal ``/todos/bulk`` paths
were declared AFTER the parameterized ``/todos/{todo_id}`` routes. FastAPI matches
in declaration order, so ``PUT/DELETE /todos/bulk`` was captured by the
``{todo_id}`` handler (todo_id="bulk") and 500'd instead of running the bulk op.
These tests pin the dispatch: the bulk paths must reach the bulk handlers, and the
single-item paths must still reach their handlers.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.todo_models import (
    BulkOperationResponse,
    TodoDocument,
    TodoResponse,
)

USER_ID = "integration-test-user-1"


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Bypass the tiered rate limiter's Redis/payment calls for these tests.

    The todo endpoints are wrapped in ``@tiered_rate_limit``; patching the
    limiter's increment and the subscription lookup avoids any real Redis/DB.
    """
    with (
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
        ),
    ):
        yield


def _todo_response(todo_id: str) -> TodoResponse:
    doc = TodoDocument.model_validate(
        {
            "id": todo_id,
            "user_id": USER_ID,
            "title": "Single",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    return TodoResponse.from_document(doc)


@pytest.mark.integration
class TestTodosBulkRouteResolution:
    """The literal /todos/bulk routes must win over /todos/{todo_id}."""

    async def test_put_bulk_reaches_bulk_handler(self, test_client) -> None:
        """PUT /todos/bulk runs the bulk update, not update_todo(todo_id="bulk")."""
        todo_ids = ["id-a", "id-b", "id-c"]

        async def fake_bulk_update(request, user_id):
            return BulkOperationResponse(
                success=request.todo_ids,
                failed=[],
                total=len(request.todo_ids),
                message=f"Updated {len(request.todo_ids)} todos",
            )

        with (
            patch(
                "app.api.v1.endpoints.todos.TodoService.bulk_update_todos",
                new=AsyncMock(side_effect=fake_bulk_update),
            ),
            patch(
                "app.api.v1.endpoints.todos.TodoService.update_todo",
                new=AsyncMock(),
            ) as mock_single_update,
        ):
            response = await test_client.put(
                "/api/v1/todos/bulk",
                json={"todo_ids": todo_ids, "updates": {"completed": True}},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert body["success"] == todo_ids
        assert "Updated 3" in body["message"]
        # The parameterized single-update handler must never have been reached.
        mock_single_update.assert_not_called()

    async def test_delete_bulk_reaches_bulk_handler(self, test_client) -> None:
        """DELETE /todos/bulk runs the bulk delete, not delete_todo(todo_id="bulk")."""
        todo_ids = ["id-x", "id-y"]

        async def fake_bulk_delete(ids, user_id):
            return BulkOperationResponse(
                success=ids, failed=[], total=len(ids), message=f"Deleted {len(ids)} todos"
            )

        with (
            patch(
                "app.api.v1.endpoints.todos.TodoService.bulk_delete_todos",
                new=AsyncMock(side_effect=fake_bulk_delete),
            ),
            patch(
                "app.api.v1.endpoints.todos.TodoService.delete_todo",
                new=AsyncMock(),
            ) as mock_single_delete,
        ):
            response = await test_client.request("DELETE", "/api/v1/todos/bulk", json=todo_ids)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert body["success"] == todo_ids
        assert "Deleted 2" in body["message"]
        mock_single_delete.assert_not_called()


@pytest.mark.integration
class TestTodosSingleItemRoutesStillWork:
    """The parameterized routes must still dispatch for real todo ids."""

    async def test_put_single_todo_still_updates(self, test_client) -> None:
        real_id = "507f1f77bcf86cd799439099"
        mock_update = AsyncMock(
            side_effect=lambda todo_id, updates, user_id: _todo_response(todo_id)
        )

        with (
            patch("app.api.v1.endpoints.todos.TodoService.update_todo", new=mock_update),
            patch(
                "app.api.v1.endpoints.todos.TodoService.bulk_update_todos",
                new=AsyncMock(),
            ) as mock_bulk_update,
        ):
            response = await test_client.put(f"/api/v1/todos/{real_id}", json={"completed": True})

        assert response.status_code == 200, response.text
        assert response.json()["id"] == real_id
        assert mock_update.await_args.args[0] == real_id
        mock_bulk_update.assert_not_called()

    async def test_delete_single_todo_still_deletes(self, test_client) -> None:
        real_id = "507f1f77bcf86cd799439100"
        mock_delete = AsyncMock()

        with (
            patch("app.api.v1.endpoints.todos.TodoService.delete_todo", new=mock_delete),
            patch(
                "app.api.v1.endpoints.todos.TodoService.bulk_delete_todos",
                new=AsyncMock(),
            ) as mock_bulk_delete,
        ):
            response = await test_client.delete(f"/api/v1/todos/{real_id}")

        assert response.status_code == 204, response.text
        assert mock_delete.await_args.args[0] == real_id
        mock_bulk_delete.assert_not_called()
