"""Unit tests for app.agents.tools.todo_tool."""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.todo_models import Priority

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


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> Dict[str, Any]:
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
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
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
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
        stats_data = {"total": 10, "completed": 5, "pending": 5}
        mock_service.return_value = stats_data

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


@pytest.mark.unit
class TestGetTodayTodos:
    """Tests for the get_today_todos tool."""

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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestGetAllLabels:
    """Tests for the get_all_labels tool."""

    @patch(f"{MODULE}.get_all_labels_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        mock_service.return_value = ["work", "personal", "urgent"]

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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestGetTodosSummary:
    """Tests for the get_todos_summary tool."""

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
        now = datetime.now(timezone.utc)
        todo = _make_todo_response(
            due_date=now,
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
