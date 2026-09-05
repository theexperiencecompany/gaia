"""Endpoint tests for /api/v1/todos.

Covers the MAX_PAGE_NUMBER page bound on the todo list endpoint, the
happy path with the service faked, analytics captures on mutations, and the
``TodoListQuery`` wire model this endpoint is the only consumer of.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from httpx import AsyncClient
import pytest
import time_machine

from app.api.v1.endpoints import todos as todos_endpoint
from app.constants.general import MAX_PAGE_NUMBER
from app.models.todo_models import (
    BulkOperationResponse,
    BulkUpdateRequest,
    PaginationMeta,
    Priority,
    SearchMode,
    SubTask,
    TodoDocument,
    TodoListQuery,
    TodoListResponse,
    TodoResponse,
    TodoSearchParams,
    TodoUpdateRequest,
)
from app.services.analytics_service import AnalyticsEvents
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

TODOS_ENDPOINT = "app.api.v1.endpoints.todos"
ANALYTICS_PATCH = "app.api.v1.endpoints.todos.capture_context_event"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


def _todo_response() -> TodoResponse:
    return TodoResponse(
        id="todo-1",
        user_id="507f1f77bcf86cd799439011",
        title="Test todo",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _todo_with_subtask(*, completed: bool) -> TodoDocument:
    return TodoDocument(
        id="todo-1",
        user_id="507f1f77bcf86cd799439011",
        title="Test todo",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        subtasks=[SubTask(id="sub-1", title="Buy milk", completed=completed)],
    )


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

    async def test_query_params_bind_into_search_params(self, client: AsyncClient) -> None:
        """Repeated ``labels`` and the ``due_today`` shortcut must survive the hop
        from the query string into the service's TodoSearchParams."""
        with patch(
            f"{TODOS_ENDPOINT}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(
                "/api/v1/todos?labels=work&labels=urgent&due_today=true&mode=text&per_page=7"
            )

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.labels == ["work", "urgent"]
        assert params.mode == SearchMode.TEXT
        assert params.per_page == 7
        today = datetime.now(UTC).date()
        assert params.due_date_start == datetime.combine(today, datetime.min.time()).replace(
            tzinfo=UTC
        )
        assert params.due_date_end == datetime.combine(today, datetime.max.time()).replace(
            tzinfo=UTC
        )

    async def test_wide_event_names_the_whole_search_context(self) -> None:
        """The ``todo`` namespace is this endpoint's observability contract.

        Called directly rather than over HTTP: the test app strips the logging
        middleware, so there is no wide-event boundary on the ASGI path and
        every ``log.set`` inside the handler is discarded.
        """
        query = TodoListQuery(
            q="taxes",
            mode=SearchMode.TEXT,
            project_id="proj-1",
            page=2,
            per_page=7,
        )
        with patch(
            f"{TODOS_ENDPOINT}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ):
            async with captured_wide_event() as event:
                await todos_endpoint.list_todos(query=query, user=FAKE_USER)

        assert event["todo"] == {
            "operation": "list",
            "search_mode": "text",
            "query": "taxes",
            "page": 2,
            "per_page": 7,
            "filters_applied": ["query", "project"],
            "project_id": "proj-1",
            "result_count": 0,
        }


class TestTodoListQuery:
    """``TodoListQuery`` — the ``GET /todos`` wire model and its two derivations.

    ``applied_filters`` names the filters on the wide event and ``to_search_params``
    resolves the day/week shortcuts into the service-facing window; this endpoint
    is their only caller.
    """

    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [
            ("q", "taxes", ["query"]),
            ("project_id", "proj-1", ["project"]),
            ("completed", False, ["completed"]),
            ("completed", True, ["completed"]),
            ("priority", Priority.HIGH, ["priority"]),
            ("labels", ["work"], ["labels"]),
            ("due_today", True, ["due_today"]),
            ("due_this_week", True, ["due_this_week"]),
            ("due_after", datetime(2026, 1, 15, tzinfo=UTC), ["date_range"]),
            ("due_before", datetime(2026, 1, 22, tzinfo=UTC), ["date_range"]),
        ],
    )
    def test_applied_filters_names_only_the_filter_that_was_set(
        self, field: str, value: Any, expected: list[str]
    ) -> None:
        assert TodoListQuery(**{field: value}).applied_filters() == expected

    def test_applied_filters_is_empty_for_an_unfiltered_query(self) -> None:
        assert TodoListQuery().applied_filters() == []

    def test_applied_filters_keeps_every_name_when_everything_is_set(self) -> None:
        query = TodoListQuery(
            q="taxes",
            project_id="proj-1",
            completed=True,
            priority=Priority.HIGH,
            labels=["work"],
            due_today=True,
            due_this_week=True,
            due_after=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert query.applied_filters() == [
            "query",
            "project",
            "completed",
            "priority",
            "labels",
            "due_today",
            "due_this_week",
            "date_range",
        ]

    def test_to_search_params_carries_every_wire_field(self) -> None:
        due_after = datetime(2026, 1, 15, tzinfo=UTC)
        due_before = datetime(2026, 1, 22, tzinfo=UTC)
        query = TodoListQuery(
            q="taxes",
            mode=SearchMode.SEMANTIC,
            project_id="proj-1",
            completed=True,
            priority=Priority.HIGH,
            has_due_date=True,
            overdue=False,
            labels=["work", "urgent"],
            due_after=due_after,
            due_before=due_before,
            page=3,
            per_page=7,
            include_stats=True,
        )

        assert query.to_search_params() == TodoSearchParams(
            q="taxes",
            mode=SearchMode.SEMANTIC,
            project_id="proj-1",
            completed=True,
            priority=Priority.HIGH,
            has_due_date=True,
            overdue=False,
            due_date_start=due_after,
            due_date_end=due_before,
            labels=["work", "urgent"],
            page=3,
            per_page=7,
            include_stats=True,
        )

    def test_due_today_window_follows_utc_not_the_server_clock(self) -> None:
        """23:30 UTC is already tomorrow on a +05:00 host — the window must not move.

        A local-clock ``datetime.now()`` here would hand back tomorrow's window for
        every user during those five hours, and it reads as correct on any
        UTC-configured runner, so the host timezone has to be moved to catch it.
        """
        with time_machine.travel(
            datetime(2026, 1, 16, 4, 30, tzinfo=ZoneInfo("Asia/Karachi")), tick=False
        ):
            params = TodoListQuery(due_today=True).to_search_params()

        assert params.due_date_start == datetime(2026, 1, 15, 0, 0, 0, 0, tzinfo=UTC)
        assert params.due_date_end == datetime(2026, 1, 15, 23, 59, 59, 999999, tzinfo=UTC)

    def test_due_this_week_is_a_seven_day_window_starting_now(self) -> None:
        before = datetime.now(UTC)
        params = TodoListQuery(due_this_week=True).to_search_params()
        after = datetime.now(UTC)

        assert params.due_date_start is not None
        assert params.due_date_end is not None
        assert params.due_date_start.tzinfo is not None
        assert before <= params.due_date_start <= after
        assert params.due_date_end - params.due_date_start == timedelta(days=7)

    def test_explicit_date_range_survives_when_no_shortcut_is_set(self) -> None:
        due_after = datetime(2026, 1, 15, tzinfo=UTC)
        due_before = datetime(2026, 1, 22, tzinfo=UTC)

        params = TodoListQuery(due_after=due_after, due_before=due_before).to_search_params()

        assert params.due_date_start == due_after
        assert params.due_date_end == due_before


class TestTodoAnalytics:
    """Analytics captures on todo endpoints without a service-layer capture.

    Single-todo mutations are captured inside TodoService (covered by
    test_todo_service.py); these assert the endpoint-only bulk and subtask
    captures.
    """

    async def test_bulk_complete_captures_todo_completed(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{TODOS_ENDPOINT}.TodoService.bulk_update_todos",
                new_callable=AsyncMock,
                return_value=BulkOperationResponse(total=2, message="ok"),
            ) as mock_bulk,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post(
                "/api/v1/todos/bulk/complete",
                json=["todo-1", "todo-2"],
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.TODO_TOGGLED, {"bulk_count": 2})
        mock_bulk.assert_awaited_once_with(
            BulkUpdateRequest(
                todo_ids=["todo-1", "todo-2"],
                updates=TodoUpdateRequest(completed=True),
            ),
            "507f1f77bcf86cd799439011",
        )

    async def test_toggle_subtask_captures_todo_completed(self, client: AsyncClient) -> None:
        doc = _todo_with_subtask(completed=False)
        updated_doc = doc.model_copy(deep=True)
        updated_doc.subtasks[0].completed = True
        with (
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ) as mock_set_fields,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.TODO_TOGGLED,
            {"is_subtask": True, "completed": True},
        )
        mock_set_fields.assert_awaited_once_with(
            "todo-1",
            user_id="507f1f77bcf86cd799439011",
            subtask_id="sub-1",
            completed=True,
        )

    async def test_toggle_subtask_flips_a_completed_subtask_back_off(
        self, client: AsyncClient
    ) -> None:
        """The write is the negation of the CURRENT state, not a hardcoded True."""
        doc = _todo_with_subtask(completed=True)
        updated_doc = doc.model_copy(deep=True)
        updated_doc.subtasks[0].completed = False
        with (
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ) as mock_set_fields,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 200
        mock_set_fields.assert_awaited_once_with(
            "todo-1",
            user_id="507f1f77bcf86cd799439011",
            subtask_id="sub-1",
            completed=False,
        )
        mock_capture.assert_called_once_with(
            AnalyticsEvents.TODO_TOGGLED,
            {"is_subtask": True, "completed": False},
        )
