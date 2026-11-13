"""Fixtures shared by the API endpoint unit tests."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
async def _bypass_integration_check():
    """Patch check_integration_status so require_integration("gmail") passes."""
    with patch(
        "app.api.v1.dependencies.google_scope_dependencies.check_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def todo_response_reads():
    """Answer a todo response's side reads with nothing; yields the open sub-todo count read."""
    with (
        patch(
            "app.services.todos.todo_service.todo_repository.count_open_sub_todos",
            new_callable=AsyncMock,
            return_value={},
        ) as count_open_sub_todos,
        patch(
            "app.services.todos.todo_service.approval_ledger_repository.list_live_by_owners",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        yield count_open_sub_todos
