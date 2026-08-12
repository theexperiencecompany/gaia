"""Canonical service test — copy into ``tests/unit/services/``, rename, adapt.

Mirrors ``tests/unit/services/test_todo_service.py``: the repository singleton
is patched at the module where the service imports it, and the test asserts the
service's orchestration — never the repo's behavior (that lives in
``tests/contracts/``). Arranged (fixture + mocks) → acted (one await) →
asserted (result + the mock's call contract). Every test covers a failure path.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.todo_models import TodoDocument, TodoResponse
from app.services.todos.todo_service import TodoService

FAKE_USER_ID = "507f1f77bcf86cd799439011"
NOW = datetime.now(UTC)


@pytest.fixture
def mock_todo_repo():
    with patch("app.services.todos.todo_service.todo_repository") as repo:
        repo.get = AsyncMock(return_value=None)
        yield repo


def _todo_doc(todo_id: str) -> TodoDocument:
    return TodoDocument.model_validate(
        {
            "id": todo_id,
            "user_id": FAKE_USER_ID,
            "title": "Buy milk",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.unit
class TestGetTodo:
    async def test_returns_response_when_found(self, mock_todo_repo):
        # Arrange
        mock_todo_repo.get = AsyncMock(return_value=_todo_doc("todo-1"))
        # Act
        result = await TodoService.get_todo("todo-1", FAKE_USER_ID)
        # Assert
        assert isinstance(result, TodoResponse)
        assert result.id == "todo-1"
        mock_todo_repo.get.assert_awaited_once_with("todo-1", user_id=FAKE_USER_ID)

    async def test_raises_when_not_found(self, mock_todo_repo):
        with pytest.raises(ValueError, match="not found"):
            await TodoService.get_todo("missing", FAKE_USER_ID)
        mock_todo_repo.get.assert_awaited_once_with("missing", user_id=FAKE_USER_ID)
