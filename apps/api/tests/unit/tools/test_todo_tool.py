"""Unit tests for app.agents.tools.todo_tool.

Every tool is asserted on its contract, not its shape: exact return dicts,
exact arguments to the mocked service seams, exact stream-writer payloads,
exact error strings, and exact ``model_dump`` call arguments. A mutant that
changes any of those must fail a test.
"""

from datetime import UTC, datetime, time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
import uuid

import pytest

from app.constants.log_tags import LogTag
from app.models.todo_models import (
    Priority,
    ProjectCreate,
    SubTask,
    TodoLabelCount,
    TodoModel,
    TodoStats,
    TodoUpdateRequest,
    UpdateProjectRequest,
)

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

# ---------------------------------------------------------------------------
# Module-level patch for the wide-event logger: every tool stamps log.set /
# log.info on entry and log.error on the failure path. The calls carry the
# tool's context (feature key, tool name, action, entity ids), so they are
# asserted per-test; the autouse fixture resets the call history first.
# ---------------------------------------------------------------------------

_log_patch = patch(f"{MODULE}.log", new_callable=MagicMock)
_log_mock = _log_patch.start()


@pytest.fixture(autouse=True)
def _reset_log_mock() -> None:
    _log_mock.reset_mock()


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


def _todo_model_dump(model: TodoModel) -> dict[str, Any]:
    """Serialize a TodoModel without the non-deterministic timestamps."""
    return model.model_dump(exclude={"created_at", "updated_at"})


def _assert_tool_result(result: dict[str, Any], expected: dict[str, Any]) -> None:
    """Assert the tool's own payload exactly.

    ``@with_rate_limiting`` (currently only on ``create_todo``) stamps the
    result dict with a ``_rate_limit_info`` key (feature/plan/usage); that is
    decorator machinery, not the tool's contract, so it is asserted
    separately when present.
    """
    rate_limit_info = result.pop("_rate_limit_info", None)
    if rate_limit_info is not None:
        assert rate_limit_info["feature"] == "todo_operations"
        assert rate_limit_info["usage"] == {}
    assert result == expected


def _assert_log_entry(tool_name: str, action: str) -> None:
    """Assert the tool's wide-event context stamp."""
    _log_mock.set.assert_called_once_with(tool={"name": tool_name, "action": action})


def _assert_log_info(message: str, **kwargs: Any) -> None:
    """Assert the tool's entry log line, context kwargs included."""
    _log_mock.info.assert_called_once_with(message, **kwargs)


def _assert_log_error(message: str, error: str, **kwargs: Any) -> None:
    """Assert the tool's failure log line (raised exception, context kwargs)."""
    _log_mock.error.assert_called_once_with(
        message, error_type="Exception", error=error, **kwargs
    )


# Fixed clock for the date-range tools: 2026-08-10 12:00 UTC.
_FIXED_TODAY = datetime(2026, 8, 10)
_FIXED_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class _FixedDatetime:
    """Stand-in for the module's ``datetime`` so date arithmetic is exact."""

    @classmethod
    def today(cls) -> datetime:
        return _FIXED_TODAY

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return datetime(2026, 8, 10, 12, 0, tzinfo=tz)

    @classmethod
    def combine(cls, date: datetime, time_: time) -> datetime:
        return datetime.combine(date, time_)


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(title="Buy groceries")
        mock_service.return_value = todo
        todo_dict = todo.model_dump.return_value

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Buy groceries",
        )

        _assert_tool_result(result, {"todo": todo_dict, "error": None})
        todo.model_dump.assert_called_once_with(mode="json")
        assert mock_service.await_args.args[1] == FAKE_USER_ID
        assert _todo_model_dump(mock_service.await_args.args[0]) == _todo_model_dump(
            TodoModel(title="Buy groceries")
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [todo_dict],
                    "action": "create",
                    "message": "Created task: Buy groceries",
                }
            }
        )
        _assert_log_entry("create_todo", "create")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Creating todo", title="Buy groceries")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_all_optional_params_are_forwarded(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        due_date = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        mock_service.return_value = _make_todo_response(title="Detailed task")

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Detailed task",
            description="A detailed description",
            labels=["work", "urgent"],
            due_date=due_date,
            due_date_timezone="America/New_York",
            priority="high",
            project_id="proj-1",
        )

        assert result["error"] is None
        assert mock_service.await_args.args[1] == FAKE_USER_ID
        assert _todo_model_dump(mock_service.await_args.args[0]) == _todo_model_dump(
            TodoModel(
                title="Detailed task",
                description="A detailed description",
                labels=["work", "urgent"],
                due_date=due_date,
                due_date_timezone="America/New_York",
                priority=Priority.HIGH,
                project_id="proj-1",
            )
        )
        _assert_tool_result(result, {"todo": mock_service.return_value.model_dump(), "error": None})
        writer.assert_called_once()
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Created task: Detailed task"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_priority_and_missing_labels_default(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(config=_make_config(), title="Task", priority="")

        assert _todo_model_dump(mock_service.await_args.args[0]) == _todo_model_dump(
            TodoModel(title="Task", priority=Priority.NONE, labels=[])
        )
        _assert_tool_result(result, {"todo": mock_service.return_value.model_dump(), "error": None})

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
        todo_dict = todo.model_dump.return_value
        todo_dict["workflow"] = {"steps": ["step1"]}
        todo.model_dump.return_value = todo_dict
        mock_service.return_value = todo

        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config(),
            title="Task with workflow",
        )

        _assert_tool_result(result, {"todo": todo_dict, "error": None})
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["todos"] == [todo_dict]
        assert streamed["workflow"] == {"steps": ["step1"]}
        assert streamed["message"] == "Created task: Task with workflow with workflow plan"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_id_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import create_todo

        result = await create_todo.coroutine(
            config=_make_config_no_user(),
            title="Buy groceries",
        )

        assert result == {"error": "User authentication required", "todo": None}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

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

        _assert_tool_result(result, {"error": "Error creating todo: DB connection failed", "todo": None})
        _assert_log_error(
            f"{LogTag.TOOL} Error creating todo", "DB connection failed", title="Buy groceries"
        )
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todos = [_make_todo_response(id=f"todo-{i}", title=f"Todo {i}") for i in range(3)]
        mock_service.return_value = todos
        todos_data = [t.model_dump() for t in todos]

        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config())

        _assert_tool_result(result, {"todos": todos_data, "count": 3, "error": None})
        mock_service.assert_awaited_once_with(
            FAKE_USER_ID,
            project_id=None,
            completed=None,
            priority=None,
            has_due_date=None,
            overdue=None,
            skip=0,
            limit=50,
        )
        for t in todos:
            t.model_dump.assert_called_with(mode="json")
        writer.assert_called_once_with(
            {"todo_data": {"todos": todos_data, "action": "list", "message": "Found 3 tasks"}}
        )
        _assert_log_entry("list_todos", "list")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Listing todos with filters")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_singular_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response()]

        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config())

        assert result["count"] == 1
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 1 task"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_filters_are_forwarded_with_priority_converted(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import list_todos

        await list_todos.coroutine(
            config=_make_config(),
            project_id="proj-1",
            completed=True,
            priority="high",
            has_due_date=True,
            overdue=True,
            skip=5,
            limit=25,
        )

        mock_service.assert_awaited_once_with(
            FAKE_USER_ID,
            project_id="proj-1",
            completed=True,
            priority=Priority.HIGH,
            has_due_date=True,
            overdue=True,
            skip=5,
            limit=25,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_priority_filter_defaults_to_none(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = []

        from app.agents.tools.todo_tool import list_todos

        await list_todos.coroutine(config=_make_config(), priority="")

        assert mock_service.await_args.kwargs["priority"] is None

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

        assert mock_service.await_args.kwargs["limit"] == 100

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import list_todos

        result = await list_todos.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

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

        _assert_tool_result(result, {"error": "Error listing todos: timeout", "todos": []})
        _assert_log_error(f"{LogTag.TOOL} Error listing todos", "timeout")
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        updated = _make_todo_response(title="Updated Title")
        mock_service.return_value = updated
        updated_dict = updated.model_dump.return_value

        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Updated Title",
        )

        _assert_tool_result(result, {"todo": updated_dict, "error": None})
        updated.model_dump.assert_called_once_with(mode="json")
        mock_service.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(title="Updated Title"), FAKE_USER_ID
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [updated_dict],
                    "action": "update",
                    "message": "Updated task: Updated Title",
                }
            }
        )
        _assert_log_entry("update_todo", "update")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Updating todo", todo_id="todo-1")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_all_fields_forwarded(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = _make_todo_response(completed=True)
        due_date = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)

        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="New Title",
            description="New description",
            labels=["a", "b"],
            due_date=due_date,
            due_date_timezone="Europe/Berlin",
            priority="high",
            project_id="proj-2",
            completed=True,
        )

        assert result["todo"]["completed"] is True
        mock_service.assert_awaited_once_with(
            "todo-1",
            TodoUpdateRequest(
                title="New Title",
                description="New description",
                labels=["a", "b"],
                due_date=due_date,
                due_date_timezone="Europe/Berlin",
                priority=Priority.HIGH,
                project_id="proj-2",
                completed=True,
            ),
            FAKE_USER_ID,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_priority_none_when_not_provided(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import update_todo

        await update_todo.coroutine(config=_make_config(), todo_id="todo-1", completed=False)

        mock_service.assert_awaited_once_with(
            "todo-1",
            TodoUpdateRequest(completed=False, priority=None),
            FAKE_USER_ID,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import update_todo

        result = await update_todo.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
        )

        assert result == {"error": "User authentication required", "todo": None}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

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

        _assert_tool_result(result, {"error": "Error updating todo: Not found", "todo": None})
        _assert_log_error(f"{LogTag.TOOL} Error updating todo", "Not found", todo_id="todo-1")
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_get_todo.return_value = _make_todo_response(title="To Delete")

        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
        )

        _assert_tool_result(result, {"success": True, "error": None})
        mock_get_todo.assert_awaited_once_with("todo-1", FAKE_USER_ID)
        mock_delete.assert_awaited_once_with("todo-1", FAKE_USER_ID)
        writer.assert_called_once_with(
            {"todo_data": {"action": "delete", "message": "Deleted task: To Delete"}}
        )
        _assert_log_entry("delete_todo", "delete")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Deleting todo", todo_id="todo-1")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
        )

        assert result == {"error": "User authentication required", "success": False}
        mock_get_todo.assert_not_awaited()
        mock_delete.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_todo_not_found_raises_error(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.side_effect = Exception("Todo not found")

        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config(),
            todo_id="nonexistent",
        )

        _assert_tool_result(result, {"error": "Error deleting todo: Todo not found", "success": False})
        _assert_log_error(f"{LogTag.TOOL} Error deleting todo", "Todo not found", todo_id="nonexistent")
        mock_delete.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_delete_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.return_value = _make_todo_response()
        mock_delete.side_effect = Exception("DB gone")

        from app.agents.tools.todo_tool import delete_todo

        result = await delete_todo.coroutine(
            config=_make_config(),
            todo_id="todo-1",
        )

        _assert_tool_result(result, {"error": "Error deleting todo: DB gone", "success": False})
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(id="match-1", title="Match")
        mock_service.return_value = [todo]
        todo_dict = todo.model_dump.return_value

        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(
            config=_make_config(),
            query="groceries",
        )

        _assert_tool_result(result, {"todos": [todo_dict], "count": 1, "error": None})
        mock_service.assert_awaited_once_with("groceries", FAKE_USER_ID)
        todo.model_dump.assert_called_once_with(mode="json")
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [todo_dict],
                    "action": "search",
                    "message": "Found 1 task matching 'groceries'",
                }
            }
        )
        _assert_log_entry("search_todos", "search")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Searching todos", query="groceries")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_plural_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response(), _make_todo_response()]

        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(config=_make_config(), query="x")

        assert result["count"] == 2
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 2 tasks matching 'x'"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(
            config=_make_config_no_user(),
            query="test",
        )

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_no_results(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = []

        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(
            config=_make_config(),
            query="nonexistent",
        )

        _assert_tool_result(result, {"todos": [], "count": 0, "error": None})
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 0 tasks matching 'nonexistent'"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("search backend down")

        from app.agents.tools.todo_tool import search_todos

        result = await search_todos.coroutine(config=_make_config(), query="test")

        _assert_tool_result(result, {"error": "Error searching todos: search backend down", "todos": []})
        _assert_log_error(f"{LogTag.TOOL} Error searching todos", "search backend down")
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(id="sem-1")
        mock_service.return_value = [todo]
        todo_dict = todo.model_dump.return_value

        from app.agents.tools.todo_tool import semantic_search_todos

        result = await semantic_search_todos.coroutine(
            config=_make_config(),
            query="shopping list",
        )

        _assert_tool_result(result, {
            "todos": [todo_dict],
            "count": 1,
            "search_type": "semantic",
            "error": None,
        })
        mock_service.assert_awaited_once_with(
            query="shopping list",
            user_id=FAKE_USER_ID,
            limit=20,
            project_id=None,
            completed=None,
            priority=None,
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [todo_dict],
                    "action": "search",
                    "message": "Found 1 task using AI search for 'shopping list'",
                }
            }
        )
        _assert_log_entry("semantic_search_todos", "search")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Semantic search", query="shopping list")
        todo.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.semantic_search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_plural_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response(), _make_todo_response()]

        from app.agents.tools.todo_tool import semantic_search_todos

        result = await semantic_search_todos.coroutine(config=_make_config(), query="x")

        assert result["count"] == 2
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 2 tasks using AI search for 'x'"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.semantic_search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_filters_forwarded_with_priority_converted(
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
            query="x",
            limit=30,
            project_id="proj-1",
            completed=False,
            priority="low",
        )

        mock_service.assert_awaited_once_with(
            query="x",
            user_id=FAKE_USER_ID,
            limit=30,
            project_id="proj-1",
            completed=False,
            priority=Priority.LOW,
        )

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

        assert mock_service.await_args.kwargs["limit"] == 50

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.semantic_search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import semantic_search_todos

        result = await semantic_search_todos.coroutine(
            config=_make_config_no_user(),
            query="x",
        )

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.semantic_search_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("embeddings unavailable")

        from app.agents.tools.todo_tool import semantic_search_todos

        result = await semantic_search_todos.coroutine(config=_make_config(), query="x")

        _assert_tool_result(result, {
            "error": "Error in semantic search: embeddings unavailable",
            "todos": [],
        })
        _assert_log_error(f"{LogTag.TOOL} Error in semantic search", "embeddings unavailable")
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        stats_model = TodoStats(total=10, completed=5, pending=5)
        mock_service.return_value = stats_model
        stats = stats_model.model_dump(mode="json")

        from app.agents.tools.todo_tool import get_todo_statistics

        result = await get_todo_statistics.coroutine(config=_make_config())

        _assert_tool_result(result, {"stats": stats, "error": None})
        mock_service.assert_awaited_once_with(FAKE_USER_ID)
        writer.assert_called_once_with(
            {"todo_data": {"stats": stats, "action": "stats", "message": "Here's your task overview"}}
        )
        _assert_log_entry("get_todo_statistics", "stats")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Getting todo statistics")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todo_stats_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_todo_statistics

        result = await get_todo_statistics.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "stats": None}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todo_stats_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("stats unavailable")

        from app.agents.tools.todo_tool import get_todo_statistics

        result = await get_todo_statistics.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "Error getting todo statistics: stats unavailable", "stats": None})
        _assert_log_error(f"{LogTag.TOOL} Error getting todo statistics", "stats unavailable")
        mock_writer_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: get_today_todos
# ---------------------------------------------------------------------------


class TestGetTodayTodos:
    """Tests for the get_today_todos tool."""

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(id="today-1")
        mock_service.return_value = [todo]
        todo_dict = todo.model_dump.return_value

        from app.agents.tools.todo_tool import get_today_todos

        result = await get_today_todos.coroutine(config=_make_config())

        _assert_tool_result(result, {"todos": [todo_dict], "count": 1, "error": None})
        mock_service.assert_awaited_once_with(
            FAKE_USER_ID, datetime(2026, 8, 10, 0, 0), datetime(2026, 8, 10, 23, 59, 59, 999999)
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [todo_dict],
                    "action": "list",
                    "message": "Found 1 task due today",
                }
            }
        )
        _assert_log_entry("get_today_todos", "get")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Getting today's todos")
        todo.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_plural_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response(), _make_todo_response()]

        from app.agents.tools.todo_tool import get_today_todos

        result = await get_today_todos.coroutine(config=_make_config())

        assert result["count"] == 2
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 2 tasks due today"

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_today_todos

        result = await get_today_todos.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.datetime", _FixedDatetime)
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

        _assert_tool_result(result, {"error": "Error getting today's todos: DB error", "todos": []})
        _assert_log_error(f"{LogTag.TOOL} Error getting today's todos", "DB error")
        mock_writer_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: get_upcoming_todos
# ---------------------------------------------------------------------------


class TestGetUpcomingTodos:
    """Tests for the get_upcoming_todos tool."""

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path_default_days(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todos = [_make_todo_response(id="up-1"), _make_todo_response(id="up-2")]
        mock_service.return_value = todos
        todos_data = [t.model_dump() for t in todos]

        from app.agents.tools.todo_tool import get_upcoming_todos

        result = await get_upcoming_todos.coroutine(config=_make_config())

        _assert_tool_result(result, {"todos": todos_data, "count": 2, "error": None})
        mock_service.assert_awaited_once_with(
            FAKE_USER_ID, _FIXED_NOW, datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        )
        for t in todos:
            t.model_dump.assert_called_with(mode="json")
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": todos_data,
                    "action": "list",
                    "message": "Found 2 upcoming tasks in the next 7 days",
                }
            }
        )
        _assert_log_entry("get_upcoming_todos", "get")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Getting upcoming todos", days=7)

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_custom_days(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response()]

        from app.agents.tools.todo_tool import get_upcoming_todos

        result = await get_upcoming_todos.coroutine(config=_make_config(), days=14)

        assert result["count"] == 1
        mock_service.assert_awaited_once_with(
            FAKE_USER_ID, _FIXED_NOW, datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
        )
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 1 upcoming task in the next 14 days"

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_upcoming_todos

        result = await get_upcoming_todos.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.datetime", _FixedDatetime)
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

        from app.agents.tools.todo_tool import get_upcoming_todos

        result = await get_upcoming_todos.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "Error getting upcoming todos: DB error", "todos": []})
        _assert_log_error(f"{LogTag.TOOL} Error getting upcoming todos", "DB error", days=7)
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        project = _make_project_response(name="New Project")
        mock_service.return_value = project
        project_dict = project.model_dump.return_value

        from app.agents.tools.todo_tool import create_project

        result = await create_project.coroutine(
            config=_make_config(),
            name="New Project",
        )

        _assert_tool_result(result, {"project": project_dict, "error": None})
        project.model_dump.assert_called_once_with(mode="json")
        mock_service.assert_awaited_once_with(
            ProjectCreate(name="New Project", description=None, color=None), FAKE_USER_ID
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "projects": [project_dict],
                    "action": "create",
                    "message": "Created project: New Project",
                }
            }
        )
        _assert_log_entry("create_project", "create")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Creating project", project_name="New Project")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_all_fields_forwarded(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = _make_project_response()

        from app.agents.tools.todo_tool import create_project

        await create_project.coroutine(
            config=_make_config(),
            name="Work",
            description="Everything work",
            color="#FF5733",
        )

        mock_service.assert_awaited_once_with(
            ProjectCreate(name="Work", description="Everything work", color="#FF5733"),
            FAKE_USER_ID,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import create_project

        result = await create_project.coroutine(
            config=_make_config_no_user(),
            name="Project",
        )

        assert result == {"error": "User authentication required", "project": None}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.create_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("name taken")

        from app.agents.tools.todo_tool import create_project

        result = await create_project.coroutine(
            config=_make_config(),
            name="Project",
        )

        _assert_tool_result(result, {"error": "Error creating project: name taken", "project": None})
        _assert_log_error(f"{LogTag.TOOL} Error creating project", "name taken")
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        project = _make_project_response(name="My Project")
        mock_service.return_value = [project]
        project_dict = project.model_dump.return_value

        from app.agents.tools.todo_tool import list_projects

        result = await list_projects.coroutine(config=_make_config())

        _assert_tool_result(result, {"projects": [project_dict], "count": 1, "error": None})
        mock_service.assert_awaited_once_with(FAKE_USER_ID)
        project.model_dump.assert_called_once_with(mode="json")
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "projects": [project_dict],
                    "action": "list",
                    "message": "You have 1 project",
                }
            }
        )
        _assert_log_entry("list_projects", "list")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Listing all projects")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_plural_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_project_response(), _make_project_response()]

        from app.agents.tools.todo_tool import list_projects

        result = await list_projects.coroutine(config=_make_config())

        assert result["count"] == 2
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "You have 2 projects"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import list_projects

        result = await list_projects.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "projects": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("list failed")

        from app.agents.tools.todo_tool import list_projects

        result = await list_projects.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "Error listing projects: list failed", "projects": []})
        _assert_log_error(f"{LogTag.TOOL} Error listing projects", "list failed")
        mock_writer_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: update_project
# ---------------------------------------------------------------------------


class TestUpdateProject:
    """Tests for the update_project tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        project = _make_project_response(name="New Name")
        mock_service.return_value = project
        project_dict = project.model_dump.return_value

        from app.agents.tools.todo_tool import update_project

        result = await update_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
            name="New Name",
        )

        _assert_tool_result(result, {"project": project_dict, "error": None})
        project.model_dump.assert_called_once_with(mode="json")
        mock_service.assert_awaited_once_with(
            "proj-1",
            UpdateProjectRequest(name="New Name", description=None, color=None),
            FAKE_USER_ID,
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "projects": [project_dict],
                    "action": "update",
                    "message": "Updated project: New Name",
                }
            }
        )
        _assert_log_entry("update_project", "update")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Updating project", project_id="proj-1")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_all_fields_forwarded(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_service.return_value = _make_project_response()

        from app.agents.tools.todo_tool import update_project

        await update_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
            name="Renamed",
            description="Renamed project",
            color="#112233",
        )

        mock_service.assert_awaited_once_with(
            "proj-1",
            UpdateProjectRequest(name="Renamed", description="Renamed project", color="#112233"),
            FAKE_USER_ID,
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import update_project

        result = await update_project.coroutine(
            config=_make_config_no_user(),
            project_id="proj-1",
        )

        assert result == {"error": "User authentication required", "project": None}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("update failed")

        from app.agents.tools.todo_tool import update_project

        result = await update_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
        )

        _assert_tool_result(result, {"error": "Error updating project: update failed", "project": None})
        _assert_log_error(f"{LogTag.TOOL} Error updating project", "update failed", project_id="proj-1")
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        project = _make_project_response(id="proj-1", name="To Delete")
        mock_get_all.return_value = [project]

        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
        )

        _assert_tool_result(result, {"success": True, "error": None})
        mock_get_all.assert_awaited_once_with(FAKE_USER_ID)
        mock_delete.assert_awaited_once_with("proj-1", FAKE_USER_ID)
        writer.assert_called_once_with(
            {"todo_data": {"action": "delete", "message": "Deleted project: To Delete"}}
        )
        _assert_log_entry("delete_project", "delete")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Deleting project", project_id="proj-1")

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
        mock_get_all.return_value = [_make_project_response(id="other-proj", name="Other")]

        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config(),
            project_id="nonexistent",
        )

        _assert_tool_result(result, {"success": True, "error": None})
        mock_delete.assert_awaited_once_with("nonexistent", FAKE_USER_ID)
        writer.assert_called_once_with(
            {"todo_data": {"action": "delete", "message": "Deleted project: Unknown Project"}}
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_get_all: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config_no_user(),
            project_id="proj-1",
        )

        assert result == {"error": "User authentication required", "success": False}
        mock_get_all.assert_not_awaited()
        mock_delete.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_list_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_all: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_all.side_effect = Exception("list failed")

        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
        )

        _assert_tool_result(result, {"error": "Error deleting project: list failed", "success": False})
        _assert_log_error(f"{LogTag.TOOL} Error deleting project", "list failed", project_id="proj-1")
        mock_delete.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_project_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_delete_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_all: AsyncMock,
        mock_delete: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_all.return_value = [_make_project_response(id="proj-1")]
        mock_delete.side_effect = Exception("delete failed")

        from app.agents.tools.todo_tool import delete_project

        result = await delete_project.coroutine(
            config=_make_config(),
            project_id="proj-1",
        )

        _assert_tool_result(result, {"error": "Error deleting project: delete failed", "success": False})
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(id="label-1", labels=["work"])
        mock_service.return_value = [todo]
        todo_dict = todo.model_dump.return_value

        from app.agents.tools.todo_tool import get_todos_by_label

        result = await get_todos_by_label.coroutine(
            config=_make_config(),
            label="work",
        )

        _assert_tool_result(result, {"todos": [todo_dict], "count": 1, "error": None})
        mock_service.assert_awaited_once_with(FAKE_USER_ID, "work")
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [todo_dict],
                    "action": "list",
                    "message": "Found 1 task with label 'work'",
                }
            }
        )
        _assert_log_entry("get_todos_by_label", "get")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Getting todos by label", label="work")
        todo.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_label_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_plural_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response(), _make_todo_response()]

        from app.agents.tools.todo_tool import get_todos_by_label

        result = await get_todos_by_label.coroutine(
            config=_make_config(),
            label="work",
        )

        assert result["count"] == 2
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Found 2 tasks with label 'work'"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_label_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_todos_by_label

        result = await get_todos_by_label.coroutine(
            config=_make_config_no_user(),
            label="work",
        )

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_todos_by_label_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("label query failed")

        from app.agents.tools.todo_tool import get_todos_by_label

        result = await get_todos_by_label.coroutine(
            config=_make_config(),
            label="work",
        )

        _assert_tool_result(result, {
            "error": "Error getting todos by label: label query failed",
            "todos": [],
        })
        _assert_log_error(f"{LogTag.TOOL} Error getting todos by label", "label query failed", label="work")
        mock_writer_factory.assert_not_called()


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

        _assert_tool_result(
            result,
            {
                "labels": [
                    {"name": "work", "count": 3},
                    {"name": "personal", "count": 2},
                    {"name": "urgent", "count": 1},
                ],
                "error": None,
            },
        )
        _assert_log_entry("get_all_labels", "get")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Getting all labels")
        mock_service.assert_awaited_once_with(FAKE_USER_ID)

    @patch(f"{MODULE}.get_all_labels_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_no_labels(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        mock_service.return_value = []

        from app.agents.tools.todo_tool import get_all_labels

        result = await get_all_labels.coroutine(config=_make_config())

        _assert_tool_result(result, {"labels": [], "error": None})

    @patch(f"{MODULE}.get_all_labels_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_all_labels

        result = await get_all_labels.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "labels": []}
        mock_service.assert_not_awaited()

    @patch(f"{MODULE}.get_all_labels_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        mock_service.side_effect = Exception("labels unavailable")

        from app.agents.tools.todo_tool import get_all_labels

        result = await get_all_labels.coroutine(config=_make_config())

        _assert_tool_result(result, {"error": "Error getting labels: labels unavailable", "labels": []})
        _assert_log_error(f"{LogTag.TOOL} Error getting labels", "labels unavailable")


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todos = [_make_todo_response(id=f"t{i}", completed=True) for i in range(3)]
        mock_service.return_value = todos
        todos_data = [t.model_dump() for t in todos]

        from app.agents.tools.todo_tool import bulk_complete_todos

        result = await bulk_complete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1", "t2", "t3"],
        )

        _assert_tool_result(result, {"todos": todos_data, "count": 3, "error": None})
        mock_service.assert_awaited_once_with(["t1", "t2", "t3"], FAKE_USER_ID)
        for t in todos:
            t.model_dump.assert_called_with(mode="json")
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": todos_data,
                    "action": "update",
                    "message": "Completed 3 tasks",
                }
            }
        )
        _assert_log_entry("bulk_complete_todos", "bulk_complete")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Bulk completing todos", todo_count=3)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_complete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_singular_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response()]

        from app.agents.tools.todo_tool import bulk_complete_todos

        result = await bulk_complete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
        )

        assert result["count"] == 1
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Completed 1 task"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_complete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import bulk_complete_todos

        result = await bulk_complete_todos.coroutine(
            config=_make_config_no_user(),
            todo_ids=["t1"],
        )

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_complete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("bulk failed")

        from app.agents.tools.todo_tool import bulk_complete_todos

        result = await bulk_complete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
        )

        _assert_tool_result(result, {"error": "Error bulk completing todos: bulk failed", "todos": []})
        _assert_log_error(f"{LogTag.TOOL} Error bulk completing todos", "bulk failed", todo_count=1)
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todo = _make_todo_response(id="moved-1", project_id="proj-2")
        mock_service.return_value = [todo]
        todo_dict = todo.model_dump.return_value

        from app.agents.tools.todo_tool import bulk_move_todos

        result = await bulk_move_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
            project_id="proj-2",
        )

        _assert_tool_result(result, {"todos": [todo_dict], "count": 1, "error": None})
        mock_service.assert_awaited_once_with(["t1"], "proj-2", FAKE_USER_ID)
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [todo_dict],
                    "action": "update",
                    "message": "Moved 1 task to project",
                }
            }
        )
        _assert_log_entry("bulk_move_todos", "bulk_move")
        _assert_log_info(
            f"{LogTag.TOOL} Todo Tool: Bulk moving todos", todo_count=1, project_id="proj-2"
        )
        todo.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_move_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_plural_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_service.return_value = [_make_todo_response(), _make_todo_response()]

        from app.agents.tools.todo_tool import bulk_move_todos

        result = await bulk_move_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1", "t2"],
            project_id="proj-2",
        )

        assert result["count"] == 2
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Moved 2 tasks to project"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_move_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import bulk_move_todos

        result = await bulk_move_todos.coroutine(
            config=_make_config_no_user(),
            todo_ids=["t1"],
            project_id="proj-2",
        )

        assert result == {"error": "User authentication required", "todos": []}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_move_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_failure(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_service.side_effect = Exception("move failed")

        from app.agents.tools.todo_tool import bulk_move_todos

        result = await bulk_move_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
            project_id="proj-2",
        )

        _assert_tool_result(result, {"error": "Error bulk moving todos: move failed", "todos": []})
        _assert_log_error(
            f"{LogTag.TOOL} Error bulk moving todos", "move failed", todo_count=1, project_id="proj-2"
        )
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        from app.agents.tools.todo_tool import bulk_delete_todos

        result = await bulk_delete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1", "t2"],
        )

        _assert_tool_result(result, {"success": True, "error": None})
        mock_service.assert_awaited_once_with(["t1", "t2"], FAKE_USER_ID)
        writer.assert_called_once_with(
            {"todo_data": {"action": "delete", "message": "Deleted 2 tasks"}}
        )
        _assert_log_entry("bulk_delete_todos", "bulk_delete")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Bulk deleting todos", todo_count=2)

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_delete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_singular_message(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        from app.agents.tools.todo_tool import bulk_delete_todos

        result = await bulk_delete_todos.coroutine(
            config=_make_config(),
            todo_ids=["t1"],
        )

        _assert_tool_result(result, {"success": True, "error": None})
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Deleted 1 task"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.bulk_delete_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_service: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import bulk_delete_todos

        result = await bulk_delete_todos.coroutine(
            config=_make_config_no_user(),
            todo_ids=["t1"],
        )

        assert result == {"error": "User authentication required", "success": False}
        mock_service.assert_not_awaited()
        mock_writer_factory.assert_not_called()

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

        _assert_tool_result(result, {"error": "Error bulk deleting todos: Bulk delete failed", "success": False})
        _assert_log_error(f"{LogTag.TOOL} Error bulk deleting todos", "Bulk delete failed", todo_count=1)
        mock_writer_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: add_subtask
# ---------------------------------------------------------------------------


class TestAddSubtask:
    """Tests for the add_subtask tool."""

    @patch(f"{MODULE}.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
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
        _mock_uuid: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        subtask = SubTask(id="sub-1", title="Buy milk", completed=False)
        parent = _make_todo_response(subtasks=[subtask])
        mock_get_todo.return_value = parent
        updated = _make_todo_response(title="Updated Parent")
        mock_update.return_value = updated
        updated_dict = updated.model_dump.return_value

        from app.agents.tools.todo_tool import add_subtask

        result = await add_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Buy milk",
        )

        _assert_tool_result(result, {"todo": updated_dict, "error": None})
        mock_get_todo.assert_awaited_once_with("todo-1", FAKE_USER_ID)
        assert mock_update.await_args.args[0] == "todo-1"
        assert mock_update.await_args.args[2] == FAKE_USER_ID
        update_request: TodoUpdateRequest = mock_update.await_args.args[1]
        assert update_request.subtasks[:1] == [subtask]
        assert len(update_request.subtasks) == 2
        added = update_request.subtasks[1]
        assert added.model_dump(exclude={"created_at"}) == {
            "id": "12345678-1234-5678-1234-567812345678",
            "title": "Buy milk",
            "completed": False,
        }
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [updated_dict],
                    "action": "update",
                    "message": "Added subtask 'Buy milk' to Updated Parent",
                }
            }
        )
        _assert_log_entry("add_subtask", "create")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Adding subtask", todo_id="todo-1")
        updated.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_existing_subtasks_preserved(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
        _mock_uuid: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        first = SubTask(id="sub-1", title="First", completed=False)
        second = SubTask(id="sub-2", title="Second", completed=True)
        mock_get_todo.return_value = _make_todo_response(subtasks=[first, second])
        mock_update.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import add_subtask

        await add_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Third",
        )

        update_request: TodoUpdateRequest = mock_update.await_args.args[1]
        assert update_request.subtasks[:2] == [first, second]
        assert update_request.subtasks[2].title == "Third"

    @patch(f"{MODULE}.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
        _mock_uuid: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import add_subtask

        result = await add_subtask.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
            title="Sub",
        )

        assert result == {"error": "User authentication required", "todo": None}
        mock_get_todo.assert_not_awaited()
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_get_todo_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.side_effect = Exception("todo gone")

        from app.agents.tools.todo_tool import add_subtask

        result = await add_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Sub",
        )

        _assert_tool_result(result, {"error": "Error adding subtask: todo gone", "todo": None})
        _assert_log_error(f"{LogTag.TOOL} Error adding subtask", "todo gone", todo_id="todo-1")
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_update_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
        _mock_uuid: MagicMock,
    ) -> None:
        mock_get_todo.return_value = _make_todo_response(subtasks=[])
        mock_update.side_effect = Exception("update failed")

        from app.agents.tools.todo_tool import add_subtask

        result = await add_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            title="Sub",
        )

        _assert_tool_result(result, {"error": "Error adding subtask: update failed", "todo": None})
        mock_writer_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: update_subtask
# ---------------------------------------------------------------------------


def _make_subtask(subtask_id: str, title: str, completed: bool) -> SubTask:
    return SubTask(id=subtask_id, title=title, completed=completed)


class TestUpdateSubtask:
    """Tests for the update_subtask tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_title_and_completed_updated(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        subtask = _make_subtask("sub-1", "Original", False)
        mock_get_todo.return_value = _make_todo_response(subtasks=[subtask])
        updated = _make_todo_response(title="Updated Parent")
        mock_update.return_value = updated
        updated_dict = updated.model_dump.return_value

        from app.agents.tools.todo_tool import update_subtask

        result = await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
            title="New title",
            completed=True,
        )

        _assert_tool_result(result, {"todo": updated_dict, "error": None})
        assert subtask.title == "New title"
        assert subtask.completed is True
        mock_get_todo.assert_awaited_once_with("todo-1", FAKE_USER_ID)
        mock_update.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(subtasks=[subtask]), FAKE_USER_ID
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [updated_dict],
                    "action": "update",
                    "message": "Updated subtask in Updated Parent",
                }
            }
        )
        _assert_log_entry("update_subtask", "update")
        _assert_log_info(
            f"{LogTag.TOOL} Todo Tool: Updating subtask", subtask_id="sub-1", todo_id="todo-1"
        )
        updated.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_title_only_leaves_completed_untouched(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        subtask = _make_subtask("sub-1", "Original", False)
        mock_get_todo.return_value = _make_todo_response(subtasks=[subtask])
        mock_update.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import update_subtask

        await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
            title="Renamed",
        )

        assert subtask.title == "Renamed"
        assert subtask.completed is False
        mock_update.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(subtasks=[subtask]), FAKE_USER_ID
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_completed_false_sets_flag(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        subtask = _make_subtask("sub-1", "Original", True)
        mock_get_todo.return_value = _make_todo_response(subtasks=[subtask])
        mock_update.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import update_subtask

        await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
            completed=False,
        )

        assert subtask.title == "Original"
        assert subtask.completed is False
        mock_update.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(subtasks=[subtask]), FAKE_USER_ID
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_only_target_subtask_mutated(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        target = _make_subtask("sub-1", "Original", False)
        other = _make_subtask("sub-2", "Keep me", True)
        mock_get_todo.return_value = _make_todo_response(subtasks=[target, other])
        mock_update.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import update_subtask

        await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
            title="Changed",
            completed=True,
        )

        assert target.title == "Changed"
        assert target.completed is True
        assert other.title == "Keep me"
        assert other.completed is True
        mock_update.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(subtasks=[target, other]), FAKE_USER_ID
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_subtask_not_found(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.return_value = _make_todo_response(subtasks=[])

        from app.agents.tools.todo_tool import update_subtask

        result = await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="nonexistent",
        )

        _assert_tool_result(result, {"error": "Subtask nonexistent not found", "todo": None})
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import update_subtask

        result = await update_subtask.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        assert result == {"error": "User authentication required", "todo": None}
        mock_get_todo.assert_not_awaited()
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_get_todo_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.side_effect = Exception("todo gone")

        from app.agents.tools.todo_tool import update_subtask

        result = await update_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        _assert_tool_result(result, {"error": "Error updating subtask: todo gone", "todo": None})
        _assert_log_error(
            f"{LogTag.TOOL} Error updating subtask",
            "todo gone",
            todo_id="todo-1",
            subtask_id="sub-1",
        )
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()


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
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        subtask = _make_subtask("sub-1", "Doomed", False)
        mock_get_todo.return_value = _make_todo_response(subtasks=[subtask])
        updated = _make_todo_response(title="Updated Parent")
        mock_update.return_value = updated
        updated_dict = updated.model_dump.return_value

        from app.agents.tools.todo_tool import delete_subtask

        result = await delete_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        _assert_tool_result(result, {"todo": updated_dict, "error": None})
        mock_get_todo.assert_awaited_once_with("todo-1", FAKE_USER_ID)
        mock_update.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(subtasks=[]), FAKE_USER_ID
        )
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "todos": [updated_dict],
                    "action": "update",
                    "message": "Removed subtask from Updated Parent",
                }
            }
        )
        _assert_log_entry("delete_subtask", "delete")
        _assert_log_info(
            f"{LogTag.TOOL} Todo Tool: Deleting subtask", subtask_id="sub-1", todo_id="todo-1"
        )
        updated.model_dump.assert_called_once_with(mode="json")

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_only_target_subtask_removed(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        doomed = _make_subtask("sub-1", "Doomed", False)
        survivor = _make_subtask("sub-2", "Keep me", True)
        mock_get_todo.return_value = _make_todo_response(subtasks=[doomed, survivor])
        mock_update.return_value = _make_todo_response()

        from app.agents.tools.todo_tool import delete_subtask

        await delete_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        mock_update.assert_awaited_once_with(
            "todo-1", TodoUpdateRequest(subtasks=[survivor]), FAKE_USER_ID
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_subtask_not_found(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.return_value = _make_todo_response(subtasks=[])

        from app.agents.tools.todo_tool import delete_subtask

        result = await delete_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="nonexistent",
        )

        _assert_tool_result(result, {"error": "Subtask nonexistent not found", "todo": None})
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import delete_subtask

        result = await delete_subtask.coroutine(
            config=_make_config_no_user(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        assert result == {"error": "User authentication required", "todo": None}
        mock_get_todo.assert_not_awaited()
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todo_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_get_todo_failure(
        self,
        mock_get_user: MagicMock,
        mock_get_todo: AsyncMock,
        mock_update: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_get_todo.side_effect = Exception("todo gone")

        from app.agents.tools.todo_tool import delete_subtask

        result = await delete_subtask.coroutine(
            config=_make_config(),
            todo_id="todo-1",
            subtask_id="sub-1",
        )

        _assert_tool_result(result, {"error": "Error deleting subtask: todo gone", "todo": None})
        _assert_log_error(
            f"{LogTag.TOOL} Error deleting subtask",
            "todo gone",
            todo_id="todo-1",
            subtask_id="sub-1",
        )
        mock_update.assert_not_awaited()
        mock_writer_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: get_todos_summary
# ---------------------------------------------------------------------------


def _summary_todos() -> dict[str, MagicMock]:
    """The todo set for the exact-summary test (clock: 2026-08-10 12:00 UTC)."""
    return {
        "overdue": _make_todo_response(
            id="ov",
            due_date=datetime(2026, 8, 10, 11, 0, tzinfo=UTC),
            completed=False,
            project_id="alpha",
        ),
        "high": _make_todo_response(
            id="hi", priority=Priority.HIGH, completed=False, project_id="alpha"
        ),
        "done_recent": _make_todo_response(
            id="dr",
            due_date=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
            priority=Priority.HIGH,
            completed=True,
            completed_at=datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
            project_id="alpha",
        ),
        "done_old": _make_todo_response(
            id="do", completed=True, completed_at=datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
        ),
        "future_late": _make_todo_response(
            id="fa", due_date=datetime(2026, 8, 15, 0, 0, tzinfo=UTC), completed=False
        ),
        "future_soon": _make_todo_response(
            id="fb", due_date=datetime(2026, 8, 14, 0, 0, tzinfo=UTC), completed=False
        ),
        "boundary_now": _make_todo_response(
            id="bo", due_date=datetime(2026, 8, 10, 12, 0, tzinfo=UTC), completed=False
        ),
        "boundary_yesterday": _make_todo_response(
            id="db",
            completed=True,
            completed_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        ),
    }


class TestGetTodosSummary:
    """Tests for the get_todos_summary tool."""

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_full_summary_exact(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        todos = _summary_todos()
        all_todos = list(todos.values())
        today_todos = [_make_todo_response(id=f"today-{i}") for i in range(5)]
        mock_date_range.side_effect = [today_todos, [todos["future_late"]]]
        mock_all_todos.return_value = all_todos
        alpha = _make_project_response(id="alpha", name="Alpha")
        beta = _make_project_response(id="beta", name="Beta")
        mock_all_projects.return_value = [alpha, beta]

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        assert result["error"] is None
        summary = result["summary"]
        assert summary == {
            "today": {
                "count": 5,
                "todos": [t.model_dump(mode="json") for t in today_todos],
                "has_more": False,
            },
            "overdue": {
                "count": 1,
                "todos": [todos["overdue"].model_dump(mode="json")],
                "has_more": False,
            },
            "upcoming_week": {
                "count": 1,
                "todos": [todos["future_late"].model_dump(mode="json")],
                "has_more": False,
            },
            "high_priority": {
                "count": 1,
                "todos": [todos["high"].model_dump(mode="json")],
                "has_more": False,
            },
            "recently_completed": {
                "count": 1,
                "todos": [todos["done_recent"].model_dump(mode="json")],
            },
            "next_deadline": todos["future_soon"].model_dump(mode="json"),
            "stats": {
                "total": 8,
                "completed": 3,
                "pending": 5,
                "completed_today": 1,
                "overdue": 1,
                "completion_rate": 37.5,
            },
            "by_project": {
                "Alpha": {"total": 3, "completed": 1, "pending": 2},
                "Beta": {"total": 0, "completed": 0, "pending": 0},
            },
        }
        mock_date_range.assert_has_awaits(
            [
                call(
                    FAKE_USER_ID,
                    datetime(2026, 8, 10, 0, 0),
                    datetime(2026, 8, 10, 23, 59, 59, 999999),
                ),
                call(FAKE_USER_ID, _FIXED_NOW, datetime(2026, 8, 17, 12, 0, tzinfo=UTC)),
            ]
        )
        mock_all_todos.assert_awaited_once_with(FAKE_USER_ID, limit=100)
        mock_all_projects.assert_awaited_once_with(FAKE_USER_ID)
        _assert_tool_result(result, {"summary": summary, "error": None})
        _assert_log_entry("get_todos_summary", "summary")
        _assert_log_info(f"{LogTag.TOOL} Todo Tool: Getting comprehensive todos summary")
        for dumped in [
            *today_todos,
            todos["future_late"],
            todos["overdue"],
            todos["high"],
            todos["done_recent"],
            todos["future_soon"],
        ]:
            dumped.model_dump.assert_called_with(mode="json")
        writer.assert_called_once_with(
            {
                "todo_data": {
                    "summary": summary,
                    "action": "summary",
                    "message": "Here's your productivity snapshot: 5 tasks today, 1 overdue, 37.5% completion rate",
                }
            }
        )

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_bucket_capping_at_limit(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        today_todos = [_make_todo_response(id=f"today-{i}") for i in range(6)]
        mock_date_range.side_effect = [today_todos, []]
        mock_all_todos.return_value = []
        mock_all_projects.return_value = []

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        summary = result["summary"]
        assert summary["today"] == {
            "count": 6,
            "todos": [t.model_dump(mode="json") for t in today_todos[:5]],
            "has_more": True,
        }
        assert summary["stats"] == {
            "total": 0,
            "completed": 0,
            "pending": 0,
            "completed_today": 0,
            "overdue": 0,
            "completion_rate": 0.0,
        }
        assert summary["next_deadline"] is None
        _assert_tool_result(result, {"summary": summary, "error": None})

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_has_more_false_at_exactly_limit(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        mock_writer_factory.return_value = _writer_mock()
        mock_date_range.side_effect = [
            [_make_todo_response(id=f"today-{i}") for i in range(5)],
            [],
        ]
        mock_all_todos.return_value = []
        mock_all_projects.return_value = []

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        assert result["summary"]["today"]["has_more"] is False
        _assert_tool_result(result, {"summary": result["summary"], "error": None})

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_next_deadline_earliest_and_recently_completed_capped(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        done = [
            _make_todo_response(
                id=f"rc-{i}",
                completed=True,
                completed_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            )
            for i in range(4)
        ]
        future_soon = _make_todo_response(
            id="fsoon", due_date=datetime(2026, 8, 14, 0, 0, tzinfo=UTC), completed=False
        )
        future_late = _make_todo_response(
            id="flate", due_date=datetime(2026, 8, 15, 0, 0, tzinfo=UTC), completed=False
        )
        mock_date_range.side_effect = [[], []]
        mock_all_todos.return_value = [*done, future_soon, future_late]
        mock_all_projects.return_value = []

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        summary = result["summary"]
        assert summary["recently_completed"] == {
            "count": 4,
            "todos": [d.model_dump(mode="json") for d in done[:3]],
        }
        assert summary["next_deadline"] == future_soon.model_dump(mode="json")
        assert summary["stats"] == {
            "total": 6,
            "completed": 4,
            "pending": 2,
            "completed_today": 4,
            "overdue": 0,
            "completion_rate": 66.7,
        }
        streamed = writer.call_args.args[0]["todo_data"]
        assert streamed["message"] == "Here's your productivity snapshot: 0 tasks today, 0 overdue, 66.7% completion rate"
        _assert_tool_result(result, {"summary": result["summary"], "error": None})

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_data(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_date_range.side_effect = [[], []]
        mock_all_todos.return_value = []
        mock_all_projects.return_value = []

        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config())

        summary = result["summary"]
        assert summary == {
            "today": {"count": 0, "todos": [], "has_more": False},
            "overdue": {"count": 0, "todos": [], "has_more": False},
            "upcoming_week": {"count": 0, "todos": [], "has_more": False},
            "high_priority": {"count": 0, "todos": [], "has_more": False},
            "recently_completed": {"count": 0, "todos": []},
            "next_deadline": None,
            "stats": {
                "total": 0,
                "completed": 0,
                "pending": 0,
                "completed_today": 0,
                "overdue": 0,
                "completion_rate": 0.0,
            },
            "by_project": {},
        }
        streamed = writer.call_args.args[0]["todo_data"]
        assert (
            streamed["message"]
            == "Here's your productivity snapshot: 0 tasks today, 0 overdue, 0% completion rate"
        )
        _assert_tool_result(result, {"summary": result["summary"], "error": None})

    @patch(f"{MODULE}.datetime", _FixedDatetime)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_all_projects_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_all_todos_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_todos_by_date_range", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_returns_auth_error(
        self,
        mock_get_user: MagicMock,
        mock_date_range: AsyncMock,
        mock_all_todos: AsyncMock,
        mock_all_projects: AsyncMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        from app.agents.tools.todo_tool import get_todos_summary

        result = await get_todos_summary.coroutine(config=_make_config_no_user())

        assert result == {"error": "User authentication required", "summary": None}
        mock_date_range.assert_not_awaited()
        mock_all_todos.assert_not_awaited()
        mock_all_projects.assert_not_awaited()
        mock_writer_factory.assert_not_called()

    @patch(f"{MODULE}.datetime", _FixedDatetime)
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

        _assert_tool_result(result, {"error": "Error getting todos summary: DB down", "summary": None})
        _assert_log_error(f"{LogTag.TOOL} Error getting todos summary", "DB down")
        mock_writer_factory.assert_not_called()
