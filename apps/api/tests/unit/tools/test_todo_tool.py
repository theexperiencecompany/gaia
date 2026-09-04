"""Unit tests for app.agents.tools.todo_tool."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.models.todo_models import Priority, TodoLabelCount, TodoStats

# ---------------------------------------------------------------------------
# Module-level patch: ensure tiered_limiter.check_and_increment returns a
# plain dict so the @with_rate_limiting decorator doesn't crash when
# iterating usage_info.items() on an AsyncMock.
# ---------------------------------------------------------------------------

_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.todo_tool"


class _UTCOnlyDateTime(datetime):
    """datetime stand-in whose ``now(None)`` (local time) reads a different DATE
    than ``now(UTC)``.

    The todo tools' day boundaries must follow the UTC calendar; this clock turns
    a non-UTC read into a wrong window the exact-boundary assertions can see,
    instead of relying on the run machine's timezone differing from UTC.
    """

    @classmethod
    def now(cls, tz: datetime | None = None) -> datetime:  # type: ignore[override]  # mirrors datetime.now's optional-tz signature deliberately
        if tz is None:
            return cls(2026, 6, 14, 20, 0)  # naive local read: previous day
        return cls(2026, 6, 15, 2, 0, tzinfo=UTC)


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _make_todo_response(**overrides: Any) -> MagicMock:
    """Create a mock TodoResponse with model_dump support."""
    defaults = {
        "id": "todo-1",
        "user_id": FAKE_USER_ID,
        "title": "Test Todo",
        "description": "A test todo",
        "labels": ["test"],
        "due_date": None,
        "due_date_timezone": None,
        "priority": Priority.NONE,
        "project_id": None,
        "completed": False,
        "completed_at": None,
        "subtasks": [],
        "workflow_id": None,
        "workflow_categories": [],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, val in defaults.items():
        setattr(mock, key, val)
    mock.model_dump.return_value = defaults
    return mock


def _make_project_response(**overrides: Any) -> MagicMock:
    """Create a mock ProjectResponse."""
    defaults = {
        "id": "proj-1",
        "user_id": FAKE_USER_ID,
        "name": "My Project",
        "description": "A project",
        "color": "#FF5733",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, val in defaults.items():
        setattr(mock, key, val)
    mock.model_dump.return_value = defaults
    return mock


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: create_todo
# ---------------------------------------------------------------------------


class TestCreateTodo:
    """Tests for the create_todo tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        todo = _make_todo_response(title="Buy groceries")
        mock_service.return_value = todo

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Buy groceries",
        )

        assert result["error"] is None
        assert result["todo"]["title"] == "Buy groceries"
        mock_service.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_id_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config_no_user(),
            title="Buy groceries",
        )

        assert result["error"] == "User authentication required"
        assert result["todo"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure_returns_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("DB connection failed")

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Buy groceries",
        )

        assert "Error creating todo" in result["error"]
        assert result["todo"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_with_all_optional_params(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        todo = _make_todo_response(
            title="Detailed task",
            priority=Priority.HIGH,
            labels=["work", "urgent"],
            project_id="proj-1",
        )
        mock_service.return_value = todo

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Detailed task",
            description="A detailed description",
            labels=["work", "urgent"],
            priority="high",
            project_id="proj-1",
        )

        assert result["error"] is None
        assert result["todo"]["priority"] == Priority.HIGH

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_workflow_included_in_response(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(title="Task with workflow")
        todo_dict = todo.model_dump()
        todo_dict["workflow"] = {"steps": ["step1"]}
        todo.model_dump.return_value = todo_dict
        mock_service.return_value = todo

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Task with workflow",
        )

        assert result["error"] is None
        # Writer should be called with workflow data
        writer.assert_called()


# ---------------------------------------------------------------------------
# Tests: list_todos
# ---------------------------------------------------------------------------


class TestListTodos:
    """Tests for the list_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        todos = [_make_todo_response(title=f"Todo {i}") for i in range(3)]
        mock_service.return_value = todos

        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config())

        assert result["error"] is None
        assert result["count"] == 3
        assert len(result["todos"]) == 3

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config_no_user())

        assert result["error"] == "User authentication required"
        assert result["todos"] == []

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_limit_capped_at_100(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import list_todos

        await list_todos.coroutine(config=_make_config(), limit=200)

        # Service should be called with limit=100 (capped)
        call_kwargs = mock_service.call_args
        assert call_kwargs.kwargs["limit"] == 100

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("timeout")

        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config())

        assert "Error listing todos" in result["error"]
        assert result["todos"] == []

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_results(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config())

        assert result["error"] is None
        assert result["count"] == 0
        assert result["todos"] == []


# ---------------------------------------------------------------------------
# Tests: update_todo
# ---------------------------------------------------------------------------


class TestUpdateTodo:
    """Tests for the update_todo tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        updated = _make_todo_response(title="Updated Title")
        mock_service.return_value = updated

        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Updated Title",
        )

        assert result["error"] is None
        assert result["todo"]["title"] == "Updated Title"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
        )

        assert result["error"] == "User authentication required"
        assert result["todo"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_mark_complete(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        updated = _make_todo_response(completed=True)
        mock_service.return_value = updated

        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            completed=True,
        )

        assert result["error"] is None
        assert result["todo"]["completed"] is True

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("Not found")

        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="New Title",
        )

        assert "Error updating todo" in result["error"]
        assert result["todo"] is None


# ---------------------------------------------------------------------------
# Tests: delete_todo
# ---------------------------------------------------------------------------


class TestDeleteTodo:
    """Tests for the delete_todo tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_get_todo.return_value = _make_todo_response(title="To Delete")

        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
        )

        assert result["success"] is True
        assert result["error"] is None
        mock_delete.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
        )

        assert result["error"] == "User authentication required"
        assert result["success"] is False

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_todo_not_found_raises_error(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.side_effect = Exception("Todo not found")

        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config(),
            todo_id="nonexistent",
        )

        assert "Error deleting todo" in result["error"]
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Tests: search_todos
# ---------------------------------------------------------------------------


class TestSearchTodos:
    """Tests for the search_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_todo_response(title="Match")]

        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(
            config=_make_config(),
            query="test",
        )

        assert result["error"] is None
        assert result["count"] == 1

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(
            config=_make_config_no_user(),
            query="test",
        )

        assert result["error"] == "User authentication required"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_no_results(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(
            config=_make_config(),
            query="nonexistent",
        )

        assert result["error"] is None
        assert result["count"] == 0
        assert result["todos"] == []


# ---------------------------------------------------------------------------
# Tests: semantic_search_todos
# ---------------------------------------------------------------------------


class TestSemanticSearchTodos:
    """Tests for the semantic_search_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.semantic_search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_todo_response()]

        from app.agents.tools.todo_tool import semantic_search_todos

        result = await semantic_search_todos.coroutine(
            config=_make_config(),
            query="tasks related to shopping",
        )

        assert result["error"] is None
        assert result["search_type"] == "semantic"
        assert result["count"] == 1

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.semantic_search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_limit_capped_at_50(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import semantic_search_todos

        await semantic_search_todos.coroutine(
            config=_make_config(),
            query="anything",
            limit=100,
        )

        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["limit"] == 50


# ---------------------------------------------------------------------------
# Tests: get_todo_statistics
# ---------------------------------------------------------------------------


class TestGetTodoStatistics:
    """Tests for the get_todo_statistics tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todo_stats_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = TodoStats(total=10, completed=5, pending=5)

        from app.agents.tools.todo_tool import get_todo_statistics

        result = await get_todo_statistics.coroutine(config=_make_config())

        assert result["error"] is None
        assert result["stats"]["total"] == 10

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_todo_statistics

        result = await get_todo_statistics.coroutine(config=_make_config_no_user())

        assert result["error"] == "User authentication required"
        assert result["stats"] is None


# ---------------------------------------------------------------------------
# Tests: get_today_todos
# ---------------------------------------------------------------------------


class TestGetTodayTodos:
    """Tests for the get_today_todos tool."""

    @patch(f"{MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_todo_response()]

        from app.agents.tools.todo_tool import get_today_todos

        result = await get_today_todos.coroutine(config=_make_config())

        assert result["error"] is None
        assert result["count"] == 1
        # The query window is the full day "now" falls on, as naive datetimes
        # (datetime.combine keeps time.min/max's null tzinfo) on the UTC clock's
        # calendar date — pinned exactly against a fake clock so a local-time or
        # None bound cannot slip through.
        (user_arg, start, end), _ = mock_service.await_args
        assert user_arg == FAKE_USER_ID
        assert start == datetime(2026, 6, 15, 0, 0)
        assert end == datetime(2026, 6, 15, 23, 59, 59, 999999)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("DB error")

        from app.agents.tools.todo_tool import get_today_todos

        result = await get_today_todos.coroutine(config=_make_config())

        assert "Error getting today's todos" in result["error"]
        assert result["todos"] == []


# ---------------------------------------------------------------------------
# Tests: get_upcoming_todos
# ---------------------------------------------------------------------------


class TestGetUpcomingTodos:
    """Tests for the get_upcoming_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path_default_days(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_todo_response(), _make_todo_response()]

        from app.agents.tools.todo_tool import get_upcoming_todos

        result = await get_upcoming_todos.coroutine(config=_make_config())

        assert result["error"] is None
        assert result["count"] == 2

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_custom_days(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import get_upcoming_todos

        result = await get_upcoming_todos.coroutine(
            config=_make_config(),
            days=14,
        )

        assert result["error"] is None
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# Tests: create_project
# ---------------------------------------------------------------------------


class TestCreateProject:
    """Tests for the create_project tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        project = _make_project_response(name="New Project")
        mock_service.return_value = project

        from app.agents.tools.todo_tool import create_project

        result = await create_project.coroutine(
            config=_make_config(),
            name="New Project",
        )

        assert result["error"] is None
        assert result["project"]["name"] == "New Project"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import create_project

        result = await create_project.coroutine(
            config=_make_config_no_user(),
            name="Project",
        )

        assert result["error"] == "User authentication required"
        assert result["project"] is None


# ---------------------------------------------------------------------------
# Tests: list_projects
# ---------------------------------------------------------------------------


class TestListProjects:
    """Tests for the list_projects tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_project_response()]

        from app.agents.tools.todo_tool import list_projects

        result = await list_projects.coroutine(config=_make_config())

        assert result["error"] is None
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# Tests: delete_project
# ---------------------------------------------------------------------------


class TestDeleteProject:
    """Tests for the delete_project tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_get_all: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        project = _make_project_response(id="proj-1", name="To Delete")
        mock_get_all.return_value = [project]

        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
        )

        assert result["success"] is True
        assert result["error"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_project_not_found_uses_unknown(
        self,
        mock_get_user: MagicMock,
        mock_get_all: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """When the project is not in the list, the name defaults to 'Unknown Project'."""
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_get_all.return_value = []

        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config(),
            project_id="nonexistent",
        )

        assert result["success"] is True
        # Verify writer was called with "Unknown Project"
        call_args = writer.call_args_list
        assert any("Unknown Project" in str(c) for c in call_args)


# ---------------------------------------------------------------------------
# Tests: get_todos_by_label
# ---------------------------------------------------------------------------


class TestGetTodosByLabel:
    """Tests for the get_todos_by_label tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_label_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_todo_response(labels=["work"])]

        from app.agents.tools.todo_tool import get_todos_by_label

        result = await get_todos_by_label.coroutine(
            config=_make_config(),
            label="work",
        )

        assert result["error"] is None
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# Tests: get_all_labels
# ---------------------------------------------------------------------------


class TestGetAllLabels:
    """Tests for the get_all_labels tool."""

    @patch(f"{MODULE}.get_all_labels_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        mock_service.return_value = [
            TodoLabelCount(name="work", count=3),
            TodoLabelCount(name="personal", count=2),
            TodoLabelCount(name="urgent", count=1),
        ]

        from app.agents.tools.todo_tool import get_all_labels

        result = await get_all_labels.coroutine(config=_make_config())

        assert result["error"] is None
        assert len(result["labels"]) == 3

    @patch(f"{MODULE}.get_all_labels_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_all_labels

        result = await get_all_labels.coroutine(config=_make_config_no_user())

        assert result["error"] == "User authentication required"
        assert result["labels"] == []


# ---------------------------------------------------------------------------
# Tests: bulk_complete_todos
# ---------------------------------------------------------------------------


class TestBulkCompleteTodos:
    """Tests for the bulk_complete_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_complete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        todos = [_make_todo_response(completed=True) for _ in range(3)]
        mock_service.return_value = todos

        from app.agents.tools.todo_tool import bulk_complete_todos

        result = await bulk_complete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1", "t2", "t3"],
        )

        assert result["error"] is None
        assert result["count"] == 3


# ---------------------------------------------------------------------------
# Tests: bulk_move_todos
# ---------------------------------------------------------------------------


class TestBulkMoveTodos:
    """Tests for the bulk_move_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_move_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = [_make_todo_response(project_id="proj-2")]

        from app.agents.tools.todo_tool import bulk_move_todos

        result = await bulk_move_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
            project_id="proj-2",
        )

        assert result["error"] is None
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# Tests: bulk_delete_todos
# ---------------------------------------------------------------------------


class TestBulkDeleteTodos:
    """Tests for the bulk_delete_todos tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_delete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.todo_tool import bulk_delete_todos

        result = await bulk_delete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1", "t2"],
        )

        assert result["success"] is True
        assert result["error"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_delete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("Bulk delete failed")

        from app.agents.tools.todo_tool import bulk_delete_todos

        result = await bulk_delete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
        )

        assert "Error bulk deleting todos" in result["error"]
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Tests: add_subtask
# ---------------------------------------------------------------------------


class TestAddSubtask:
    """Tests for the add_subtask tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        parent = _make_todo_response(subtasks=[])
        mock_get_todo.return_value = parent
        updated = _make_todo_response(
            subtasks=[{"id": "sub-1", "title": "Buy milk", "completed": False}]
        )
        mock_update.return_value = updated

        from app.agents.tools.todo_tool import add_subtask

        result = await add_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Buy milk",
        )

        assert result["error"] is None
        mock_update.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import add_subtask

        result = await add_subtask.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
            title="Sub",
        )

        assert result["error"] == "User authentication required"
        assert result["todo"] is None


# ---------------------------------------------------------------------------
# Tests: update_subtask
# ---------------------------------------------------------------------------


class TestUpdateSubtask:
    """Tests for the update_subtask tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        subtask = MagicMock()
        subtask.id = "sub-1"
        subtask.title = "Original"
        subtask.completed = False
        parent = _make_todo_response(subtasks=[subtask])
        mock_get_todo.return_value = parent
        mock_update.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import update_subtask

        result = await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
            completed=True,
        )

        assert result["error"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_subtask_not_found(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        parent = _make_todo_response(subtasks=[])
        mock_get_todo.return_value = parent

        from app.agents.tools.todo_tool import update_subtask

        result = await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="nonexistent",
        )

        assert "not found" in result["error"]
        assert result["todo"] is None


# ---------------------------------------------------------------------------
# Tests: delete_subtask
# ---------------------------------------------------------------------------


class TestDeleteSubtask:
    """Tests for the delete_subtask tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        subtask = MagicMock()
        subtask.id = "sub-1"
        parent = _make_todo_response(subtasks=[subtask])
        mock_get_todo.return_value = parent
        mock_update.return_value = _make_todo_response(subtasks=[])

        from app.agents.tools.todo_tool import delete_subtask

        result = await delete_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        assert result["error"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_subtask_not_found(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        parent = _make_todo_response(subtasks=[])
        mock_get_todo.return_value = parent

        from app.agents.tools.todo_tool import delete_subtask

        result = await delete_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="nonexistent",
        )

        assert "not found" in result["error"]
        assert result["todo"] is None


# ---------------------------------------------------------------------------
# Tests: get_todos_summary
# ---------------------------------------------------------------------------


class TestGetTodosSummary:
    """Tests for the get_todos_summary tool."""

    @patch(f"{MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        todo = _make_todo_response(
            due_date=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
            completed=False,
            priority=Priority.HIGH,
            completed_at=None,
        )
        mock_date_range.return_value = [todo]
        mock_all_todos.return_value = [todo]
        mock_all_projects.return_value = []

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        assert result["error"] is None
        assert "summary" in result
        summary = result["summary"]
        assert "today" in summary
        assert "stats" in summary
        assert "by_project" in summary
        # Same day-window contract as get_today_todos, pinned against the same
        # fake clock: the first gather call fetches today's bounds.
        (user_arg, start, end), _ = mock_date_range.await_args_list[0]
        assert user_arg == FAKE_USER_ID
        assert start == datetime(2026, 6, 15, 0, 0)
        assert end == datetime(2026, 6, 15, 23, 59, 59, 999999)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config_no_user())

        assert result["error"] == "User authentication required"
        assert result["summary"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_date_range.side_effect = Exception("DB down")

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        assert "Error getting todos summary" in result["error"]
        assert result["summary"] is None


# ---------------------------------------------------------------------------
# The priority argument is a closed set; the tool schema must say so.
# ---------------------------------------------------------------------------
# Prod, Sep 3 2026: `[TOOL] Error creating todo: 'normal' is not a valid
# Priority`. The parameter was typed `str`, so the model only ever saw the
# allowed values as prose in a description and guessed a synonym. With the
# enum in the schema the API refuses the call before the tool body runs.

PRIORITY_TOOL_NAMES = ["create_todo", "list_todos", "update_todo", "semantic_search_todos"]


class TestPriorityIsAnEnumInTheToolSchema:
    @pytest.mark.regression
    @pytest.mark.parametrize("tool_name", PRIORITY_TOOL_NAMES)
    def test_schema_enumerates_the_allowed_values(self, tool_name):
        from app.agents.tools import todo_tool

        schema = getattr(todo_tool, tool_name).tool_call_schema.model_json_schema()
        enum = schema.get("$defs", {}).get("Priority", {}).get("enum")
        assert enum == [p.value for p in Priority], schema["properties"]["priority"]

    @pytest.mark.regression
    async def test_unknown_priority_never_reaches_the_service(self):
        from app.agents.tools.todo_tool import create_todo

        with (
            patch(f"{MODULE}.get_stream_writer"),
            patch(f"{MODULE}.create_todo_service", new=AsyncMock()) as svc,
            patch(f"{MODULE}.get_user_id_from_config", return_value="u1"),
        ):
            with pytest.raises(ValidationError):
                await create_todo.ainvoke(
                    {"title": "x", "priority": "normal"}, config=_make_config()
                )
        svc.assert_not_awaited()
