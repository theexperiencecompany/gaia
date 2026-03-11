"""Integration tests for real production tool execution.

These tests import and invoke REAL tool functions from app.agents.tools.*
and mock only at the I/O boundary (DB/HTTP calls, LangGraph stream writer).

If any of the tested production tool functions are deleted or renamed,
the import at the top of this file will cause an immediate ImportError,
and the tests will fail — which is the intended behaviour.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# CRITICAL: these imports must reference real production tool functions.
# Deleting create_todo / list_todos / search_todos from todo_tool.py, or
# deleting get_weather from weather_tool.py, will break this file.
# ---------------------------------------------------------------------------
from app.agents.tools.todo_tool import create_todo, list_todos, search_todos
from app.agents.tools.weather_tool import get_weather
from app.models.todo_models import Priority, TodoResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runnable_config(user_id: str | None = None) -> dict[str, Any]:
    """Build a RunnableConfig-compatible dict accepted by the production tools.

    get_user_id_from_config() reads from config["metadata"]["user_id"].
    with_rate_limiting() also reads that same path.
    """
    uid = user_id or str(uuid4())
    return {
        "metadata": {"user_id": uid},
        "configurable": {"thread_id": str(uuid4())},
    }


def _make_todo_response(**overrides: Any) -> TodoResponse:
    """Build a minimal TodoResponse with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults: dict[str, Any] = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "title": "Test task",
        "description": None,
        "labels": [],
        "due_date": None,
        "due_date_timezone": None,
        "priority": Priority.NONE,
        "project_id": None,
        "completed": False,
        "subtasks": [],
        "workflow_id": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "workflow_categories": [],
    }
    defaults.update(overrides)
    return TodoResponse(**defaults)


def _fake_subscription() -> SimpleNamespace:
    """Return a subscription object that satisfies the rate-limiter's plan lookup."""
    from app.models.payment_models import PlanType

    sub = SimpleNamespace()
    sub.plan_type = PlanType.FREE
    return sub


# ---------------------------------------------------------------------------
# Shared patches applied to every test in this module
# ---------------------------------------------------------------------------

# 1. Prevent get_stream_writer from requiring a real LangGraph streaming context.
# 2. Prevent _get_cached_subscription from touching Redis or the payment service.
TOOL_PATCHES = [
    patch(
        "langgraph.config.get_stream_writer",
        return_value=MagicMock(),
    ),
    patch(
        "app.decorators.rate_limiting._get_cached_subscription",
        new_callable=AsyncMock,
        return_value=_fake_subscription(),
    ),
]


def _apply_patches(patches):
    """Context-manager helper: enter all patches and return started mocks."""
    started = [p.start() for p in patches]
    return started


def _stop_patches(patches):
    for p in patches:
        try:
            p.stop()
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Tests: create_todo
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateTodoTool:
    """Tests for the real create_todo production tool."""

    @pytest.mark.asyncio
    async def test_returns_todo_dict_on_success(self):
        """create_todo must call the service and return a dict with a 'todo' key."""
        config = _make_runnable_config()
        fake_todo = _make_todo_response(title="Buy groceries")

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.create_todo_service",
                new_callable=AsyncMock,
                return_value=fake_todo,
            ),
        ]
        _apply_patches(patches)
        try:
            result = await create_todo.ainvoke(
                {"title": "Buy groceries", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert isinstance(result, dict)
        assert "todo" in result
        assert result["error"] is None
        assert result["todo"]["title"] == "Buy groceries"

    @pytest.mark.asyncio
    async def test_todo_dict_contains_required_fields(self):
        """The returned todo dict must include id, user_id, title, priority, completed."""
        config = _make_runnable_config()
        fake_todo = _make_todo_response(title="Write tests", priority=Priority.HIGH)

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.create_todo_service",
                new_callable=AsyncMock,
                return_value=fake_todo,
            ),
        ]
        _apply_patches(patches)
        try:
            result = await create_todo.ainvoke(
                {"title": "Write tests", "priority": "high", "config": config}
            )
        finally:
            _stop_patches(patches)

        todo = result["todo"]
        for field in ("id", "user_id", "title", "priority", "completed"):
            assert field in todo, f"Missing field '{field}' in todo response"
        assert todo["priority"] == Priority.HIGH.value

    @pytest.mark.asyncio
    async def test_returns_error_when_no_user_id(self):
        """Without a user_id in config, create_todo must return an auth error."""
        config: dict[str, Any] = {
            "metadata": {},
            "configurable": {"thread_id": str(uuid4())},
        }

        patches = TOOL_PATCHES
        _apply_patches(patches)
        try:
            result = await create_todo.ainvoke(
                {"title": "Ghost task", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert "error" in result
        assert result["todo"] is None
        assert "authentication" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_service_error_propagates_as_error_key(self):
        """If the underlying DB service raises, create_todo must return error, not raise."""
        config = _make_runnable_config()

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.create_todo_service",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB connection lost"),
            ),
        ]
        _apply_patches(patches)
        try:
            result = await create_todo.ainvoke(
                {"title": "Doomed task", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert "error" in result
        assert result["todo"] is None
        assert "DB connection lost" in result["error"]

    @pytest.mark.asyncio
    async def test_stream_writer_receives_todo_data(self):
        """create_todo must emit todo_data through the stream writer."""
        config = _make_runnable_config()
        fake_todo = _make_todo_response(title="Streamed task")
        mock_writer = MagicMock()

        patches = [
            patch(
                "langgraph.config.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new_callable=AsyncMock,
                return_value=_fake_subscription(),
            ),
            patch(
                "app.agents.tools.todo_tool.create_todo_service",
                new_callable=AsyncMock,
                return_value=fake_todo,
            ),
        ]
        _apply_patches(patches)
        try:
            await create_todo.ainvoke({"title": "Streamed task", "config": config})
        finally:
            _stop_patches(patches)

        calls = mock_writer.call_args_list
        emitted_keys = [list(c.args[0].keys())[0] for c in calls if c.args]
        assert "todo_data" in emitted_keys


# ---------------------------------------------------------------------------
# Tests: list_todos
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListTodosTool:
    """Tests for the real list_todos production tool."""

    @pytest.mark.asyncio
    async def test_returns_todos_list_and_count(self):
        """list_todos must return a dict with 'todos' list and 'count' integer."""
        config = _make_runnable_config()
        fake_todos = [
            _make_todo_response(title="Task A"),
            _make_todo_response(title="Task B"),
        ]

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.get_all_todos_service",
                new_callable=AsyncMock,
                return_value=fake_todos,
            ),
        ]
        _apply_patches(patches)
        try:
            result = await list_todos.ainvoke({"config": config})
        finally:
            _stop_patches(patches)

        assert isinstance(result, dict)
        assert result["error"] is None
        assert isinstance(result["todos"], list)
        assert result["count"] == 2
        titles = [t["title"] for t in result["todos"]]
        assert "Task A" in titles
        assert "Task B" in titles

    @pytest.mark.asyncio
    async def test_empty_results_return_zero_count(self):
        """When the service returns no todos, count must be 0 and todos an empty list."""
        config = _make_runnable_config()

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.get_all_todos_service",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ]
        _apply_patches(patches)
        try:
            result = await list_todos.ainvoke({"config": config})
        finally:
            _stop_patches(patches)

        assert result["count"] == 0
        assert result["todos"] == []
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_limit_capped_at_100(self):
        """list_todos must silently cap limit at 100 before passing to the service."""
        config = _make_runnable_config()

        captured_limit: list[int] = []

        async def capturing_service(
            user_id: str, limit: int = 50, **kwargs: Any
        ) -> list:
            captured_limit.append(limit)
            return []

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.get_all_todos_service",
                side_effect=capturing_service,
            ),
        ]
        _apply_patches(patches)
        try:
            await list_todos.ainvoke({"limit": 999, "config": config})
        finally:
            _stop_patches(patches)

        assert captured_limit, "service was never called"
        assert captured_limit[0] <= 100

    @pytest.mark.asyncio
    async def test_returns_error_when_no_user_id(self):
        """Without user_id, list_todos must return auth error with empty todos list."""
        config: dict[str, Any] = {
            "metadata": {},
            "configurable": {"thread_id": str(uuid4())},
        }

        patches = TOOL_PATCHES
        _apply_patches(patches)
        try:
            result = await list_todos.ainvoke({"config": config})
        finally:
            _stop_patches(patches)

        assert "error" in result
        assert result["todos"] == []
        assert "authentication" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_each_todo_in_result_is_serialisable_dict(self):
        """Every item in the returned todos list must be a plain dict (model_dump output)."""
        config = _make_runnable_config()
        fake_todos = [_make_todo_response(title=f"Task {i}") for i in range(3)]

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.get_all_todos_service",
                new_callable=AsyncMock,
                return_value=fake_todos,
            ),
        ]
        _apply_patches(patches)
        try:
            result = await list_todos.ainvoke({"config": config})
        finally:
            _stop_patches(patches)

        for item in result["todos"]:
            assert isinstance(item, dict), "Each todo must be a plain dict"
            assert "id" in item
            assert "title" in item


# ---------------------------------------------------------------------------
# Tests: search_todos
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchTodosTool:
    """Tests for the real search_todos production tool."""

    @pytest.mark.asyncio
    async def test_returns_matching_todos_and_count(self):
        """search_todos must forward the query and return matching todos with a count."""
        config = _make_runnable_config()
        fake_results = [
            _make_todo_response(title="Buy milk"),
            _make_todo_response(title="Buy eggs"),
        ]

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.search_todos_service",
                new_callable=AsyncMock,
                return_value=fake_results,
            ),
        ]
        _apply_patches(patches)
        try:
            result = await search_todos.ainvoke({"query": "Buy", "config": config})
        finally:
            _stop_patches(patches)

        assert result["error"] is None
        assert result["count"] == 2
        titles = [t["title"] for t in result["todos"]]
        assert "Buy milk" in titles
        assert "Buy eggs" in titles

    @pytest.mark.asyncio
    async def test_query_is_forwarded_to_service(self):
        """search_todos must pass the exact query string to search_todos_service."""
        config = _make_runnable_config()
        captured_query: list[str] = []

        async def capturing_service(query: str, user_id: str) -> list:
            captured_query.append(query)
            return []

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.search_todos_service",
                side_effect=capturing_service,
            ),
        ]
        _apply_patches(patches)
        try:
            await search_todos.ainvoke({"query": "dentist appointment", "config": config})
        finally:
            _stop_patches(patches)

        assert captured_query == ["dentist appointment"]

    @pytest.mark.asyncio
    async def test_no_results_returns_empty_list(self):
        """A search with no matches must return an empty list and count of 0."""
        config = _make_runnable_config()

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.search_todos_service",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ]
        _apply_patches(patches)
        try:
            result = await search_todos.ainvoke(
                {"query": "nonexistent xyz", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert result["todos"] == []
        assert result["count"] == 0
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_service_error_returns_error_key(self):
        """If search_todos_service raises, the tool must return error without re-raising."""
        config = _make_runnable_config()

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.todo_tool.search_todos_service",
                new_callable=AsyncMock,
                side_effect=ConnectionError("MongoDB unavailable"),
            ),
        ]
        _apply_patches(patches)
        try:
            result = await search_todos.ainvoke({"query": "anything", "config": config})
        finally:
            _stop_patches(patches)

        assert "error" in result
        assert result["todos"] == []
        assert "MongoDB unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_error_when_no_user_id(self):
        """Without user_id, search_todos must return auth error."""
        config: dict[str, Any] = {
            "metadata": {},
            "configurable": {"thread_id": str(uuid4())},
        }

        patches = TOOL_PATCHES
        _apply_patches(patches)
        try:
            result = await search_todos.ainvoke({"query": "anything", "config": config})
        finally:
            _stop_patches(patches)

        assert "error" in result
        assert "authentication" in result["error"].lower()
        assert result["todos"] == []


# ---------------------------------------------------------------------------
# Tests: get_weather
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetWeatherTool:
    """Tests for the real get_weather production tool."""

    @pytest.mark.asyncio
    async def test_returns_string_containing_location(self):
        """get_weather must return a string that includes the queried location name."""
        config = _make_runnable_config()
        fake_weather_data: dict[str, Any] = {
            "name": "London",
            "main": {"temp": 15.0, "humidity": 80},
            "weather": [{"main": "Clouds", "description": "overcast clouds"}],
            "forecast": [],
            "location": {"city": "London", "country": "GB", "region": "England"},
        }

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.weather_tool.user_weather",
                new_callable=AsyncMock,
                return_value=fake_weather_data,
            ),
        ]
        _apply_patches(patches)
        try:
            result = await get_weather.ainvoke(
                {"location": "London,GB", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert isinstance(result, str)
        assert "London,GB" in result

    @pytest.mark.asyncio
    async def test_weather_data_forwarded_to_stream_writer(self):
        """get_weather must emit weather_data through the stream writer."""
        config = _make_runnable_config()
        mock_writer = MagicMock()
        fake_weather: dict[str, Any] = {"name": "Paris", "main": {}, "weather": []}

        patches = [
            patch(
                "langgraph.config.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new_callable=AsyncMock,
                return_value=_fake_subscription(),
            ),
            patch(
                "app.agents.tools.weather_tool.user_weather",
                new_callable=AsyncMock,
                return_value=fake_weather,
            ),
        ]
        _apply_patches(patches)
        try:
            await get_weather.ainvoke({"location": "Paris,FR", "config": config})
        finally:
            _stop_patches(patches)

        emitted_payloads = [c.args[0] for c in mock_writer.call_args_list if c.args]
        weather_emissions = [p for p in emitted_payloads if "weather_data" in p]
        assert len(weather_emissions) >= 1

    @pytest.mark.asyncio
    async def test_user_weather_called_with_exact_location(self):
        """get_weather must forward the location argument verbatim to user_weather."""
        config = _make_runnable_config()
        captured: list[str] = []

        async def capturing_weather(location_name: str | None = None) -> str:
            captured.append(location_name or "")
            return "fake weather string"

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.weather_tool.user_weather",
                side_effect=capturing_weather,
            ),
        ]
        _apply_patches(patches)
        try:
            await get_weather.ainvoke(
                {"location": "Tokyo,JP", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert captured == ["Tokyo,JP"]

    @pytest.mark.asyncio
    async def test_weather_service_error_surfaces_in_return_value(self):
        """When user_weather returns an error string, get_weather must still return a string."""
        config = _make_runnable_config()

        patches = TOOL_PATCHES + [
            patch(
                "app.agents.tools.weather_tool.user_weather",
                new_callable=AsyncMock,
                return_value="Could not find location: InvalidCity",
            ),
        ]
        _apply_patches(patches)
        try:
            result = await get_weather.ainvoke(
                {"location": "InvalidCity", "config": config}
            )
        finally:
            _stop_patches(patches)

        assert isinstance(result, str)
        assert "InvalidCity" in result
