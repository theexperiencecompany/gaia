"""Signal-matching context rendering, extracted from tracked_todo_service.

Same coverage as before the extraction: the entry format the agent sees, the
key-details cap, graceful degradation when a canvas cannot be read, and the
regression that a stored host-side vfs_path never reaches the LLM.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument
from app.services.todos.signal_context import (
    _SIGNAL_CONTEXT_TODO_LIMIT,
    get_signal_matching_context,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_MOD = "app.services.todos.signal_context"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "labels": [GAIA_TRACKED_LABEL, "work"],
        "vfs_path": f"/workspace/gaia-tasks/{TODO_ID}",
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(hours=1),
    }
    data.update(overrides)
    return TodoDocument(**data)


@pytest.fixture
def deps():
    with (
        patch(f"{_MOD}.todo_repository") as repo,
        patch(f"{_MOD}.read_canvas", new_callable=AsyncMock) as read,
    ):
        repo.list_active_tracked = AsyncMock(return_value=[])
        read.return_value = ""
        yield SimpleNamespace(repo=repo, read=read)


class TestGetSignalMatchingContext:
    async def test_empty_string_without_docs(self, deps) -> None:
        assert await get_signal_matching_context(USER_ID) == ""

    async def test_renders_entries_with_indented_key_details(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [_todo_doc()]
        deps.read.return_value = (
            "# Prepare Q3 report\n\n## Key Details\nthread: abc123\nemail: x@y.com\n"
        )

        context = await get_signal_matching_context(USER_ID)

        lines = context.split("\n")
        assert lines[0] == "ACTIVE TRACKED TODOS (check if incoming signal relates to any):"
        assert lines[1] == '- "Prepare Q3 report" [work] (ID: todo-1)'
        assert USER_ID not in context
        assert "    thread: abc123" in lines[2]
        assert "    email: x@y.com" in lines[3]
        # The repo is queried for this user's active tracked todos, capped at the limit.
        deps.repo.list_active_tracked.assert_awaited_once_with(
            USER_ID, limit=_SIGNAL_CONTEXT_TODO_LIMIT
        )
        # The canvas is read with the todo's id and the user's id, in that order.
        deps.read.assert_awaited_once_with(TODO_ID, USER_ID)

    async def test_empty_canvas_adds_no_key_details(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [_todo_doc()]
        deps.read.return_value = ""

        context = await get_signal_matching_context(USER_ID)

        assert context == (
            "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n"
            '- "Prepare Q3 report" [work] (ID: todo-1)'
        )

    async def test_canvas_without_key_details_section_adds_nothing(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [_todo_doc()]
        deps.read.return_value = "# Prepare Q3 report\n\nSome body with no key details section.\n"

        context = await get_signal_matching_context(USER_ID)

        assert context == (
            "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n"
            '- "Prepare Q3 report" [work] (ID: todo-1)'
        )

    async def test_multiple_labels_joined_with_comma_space(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [
            _todo_doc(labels=[GAIA_TRACKED_LABEL, "work", "urgent"])
        ]

        context = await get_signal_matching_context(USER_ID)

        assert context.split("\n")[1] == '- "Prepare Q3 report" [work, urgent] (ID: todo-1)'

    async def test_no_extra_labels_renders_without_bracket(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [_todo_doc(labels=[GAIA_TRACKED_LABEL])]

        context = await get_signal_matching_context(USER_ID)

        assert context.split("\n")[1] == '- "Prepare Q3 report" (ID: todo-1)'

    async def test_multiple_docs_joined_by_newline(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [
            _todo_doc(id="todo-1", title="First"),
            _todo_doc(id="todo-2", title="Second"),
        ]

        context = await get_signal_matching_context(USER_ID)

        assert context == (
            "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n"
            '- "First" [work] (ID: todo-1)\n'
            '- "Second" [work] (ID: todo-2)'
        )

    async def test_caps_key_details_at_five_lines(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [_todo_doc()]
        deps.read.return_value = "## Key Details\n" + "\n".join(f"line {i}" for i in range(8))

        context = await get_signal_matching_context(USER_ID)

        indented = [line for line in context.split("\n") if line.startswith("    ")]
        assert len(indented) == 5

    async def test_degrades_gracefully_when_canvas_unreadable(self, deps) -> None:
        deps.repo.list_active_tracked.return_value = [_todo_doc()]
        deps.read.side_effect = RuntimeError("read failed")

        async with captured_wide_event() as event:
            context = await get_signal_matching_context(USER_ID)

        # A read failure degrades to no key details — the entry, and nothing after it.
        assert context == (
            "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n"
            '- "Prepare Q3 report" [work] (ID: todo-1)'
        )
        # ...and it is surfaced on the wide event with the todo id and error text.
        (warning,) = event["warnings"]
        assert warning["msg"] == "tracked_todo.canvas_read_failed"
        assert warning["todo_id"] == TODO_ID
        assert warning["error"] == "read failed"

    async def test_stored_user_scoped_vfs_path_never_leaks_into_agent_context(self, deps) -> None:
        """Old docs store vfs_path as /users/<uid>/todos/<id> — that host-side
        path must never reach the LLM, which only knows /workspace-scoped paths."""
        deps.repo.list_active_tracked.return_value = [
            _todo_doc(vfs_path=f"/users/{USER_ID}/todos/{TODO_ID}")
        ]
        deps.read.return_value = "## Key Details\nthread: abc123\n"

        context = await get_signal_matching_context(USER_ID)

        assert USER_ID not in context
        assert "/users/" not in context
