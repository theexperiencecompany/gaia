"""Todo pending-approval enrichment (TodoService.get_todo/list_todos).

The tasks UI shows a jump-to-chat icon on todos parked on a live approval.
The ref carries approval + conversation ids only — the card itself renders
from the conversation, so no summary or args travel here.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.hil_models import LedgerState
from app.models.todo_models import TodoDocument

MODULE = "app.services.todos.todo_service"


def _todo(**overrides: Any) -> TodoDocument:
    fields: dict[str, Any] = {
        "id": "todo-1",
        "user_id": "user-1",
        "title": "Check the deploy",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return TodoDocument(**fields)


def _row(owner_id: str = "todo-1", **overrides: Any) -> MagicMock:
    row = MagicMock()
    row.approval_id = "ap_1"
    row.conversation_id = "conv-9"
    row.owner_id = owner_id
    row.state = LedgerState.PENDING
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _page(items: list[TodoDocument]) -> MagicMock:
    page = MagicMock()
    page.items = items
    page.total = len(items)
    return page


class TestGetTodoPending:
    async def test_live_row_attaches_the_jump_link(self) -> None:
        from app.services.todos.todo_service import TodoService

        with (
            patch(f"{MODULE}.todo_repository.get", new=AsyncMock(return_value=_todo())),
            patch(
                f"{MODULE}.approval_ledger_repository.list_live_by_owners",
                new=AsyncMock(return_value=[_row()]),
            ) as live,
        ):
            response = await TodoService.get_todo("todo-1", "user-1")

        live.assert_awaited_once_with("todo", ["todo-1"])
        assert response.pending_approval is not None
        assert response.pending_approval.approval_id == "ap_1"
        assert response.pending_approval.conversation_id == "conv-9"

    async def test_no_live_row_means_no_link(self) -> None:
        from app.services.todos.todo_service import TodoService

        with (
            patch(f"{MODULE}.todo_repository.get", new=AsyncMock(return_value=_todo())),
            patch(
                f"{MODULE}.approval_ledger_repository.list_live_by_owners",
                new=AsyncMock(return_value=[]),
            ),
        ):
            response = await TodoService.get_todo("todo-1", "user-1")

        assert response.pending_approval is None


class TestListTodosPending:
    async def test_one_query_covers_the_page(self) -> None:
        from app.models.todo_models import SearchMode, TodoSearchParams
        from app.services.todos.todo_service import TodoService

        todos = [_todo(id="todo-1"), _todo(id="todo-2")]
        with (
            patch(
                f"{MODULE}.todo_repository.list_page",
                new=AsyncMock(return_value=_page(todos)),
            ),
            patch(
                f"{MODULE}.approval_ledger_repository.list_live_by_owners",
                new=AsyncMock(return_value=[_row(owner_id="todo-2")]),
            ) as live,
        ):
            response = await TodoService.list_todos(
                "user-1", TodoSearchParams(q=None, mode=SearchMode.TEXT, project_id="p1")
            )

        live.assert_awaited_once_with("todo", ["todo-1", "todo-2"])
        by_id = {item.id: item for item in response.data}
        assert by_id["todo-1"].pending_approval is None
        assert by_id["todo-2"].pending_approval is not None
        assert by_id["todo-2"].pending_approval.approval_id == "ap_1"
