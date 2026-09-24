"""Endpoint tests for /api/v1/todos.

Covers the MAX_PAGE_NUMBER page bound on the todo list endpoint, the
happy path with the service faked, and analytics captures on mutations.
"""

from datetime import UTC, datetime, timedelta, tzinfo
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.constants.general import MAX_PAGE_NUMBER
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import (
    BulkOperationResponse,
    BulkUpdateRequest,
    PaginationMeta,
    Priority,
    ProjectResponse,
    SearchMode,
    SubTask,
    TodoDocument,
    TodoListParams,
    TodoListResponse,
    TodoResponse,
    TodoUpdateRequest,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.todos.todo_service import TrackedTodoWorkflowError

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


def _project_response(name: str = "Work") -> ProjectResponse:
    return ProjectResponse(
        id="p1",
        user_id="507f1f77bcf86cd799439011",
        name=name,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _empty_list_response() -> TodoListResponse:
    return TodoListResponse(
        data=[],
        meta=PaginationMeta(total=0, page=1, per_page=50, pages=0, has_next=False, has_prev=False),
    )


class TestListTodos:
    """GET /api/v1/todos."""

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

    async def test_list_passes_resolved_dates_to_service(self, client: AsyncClient) -> None:
        with patch(
            f"{TODOS_ENDPOINT}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(
                "/api/v1/todos?page=2&per_page=10"
                "&due_after=2026-01-01T00:00:00Z&due_before=2026-02-01T00:00:00Z"
            )

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.page == 2
        assert params.per_page == 10
        # The explicit range must survive resolution into the search params.
        assert params.due_date_start == datetime(2026, 1, 1, tzinfo=UTC)
        assert params.due_date_end == datetime(2026, 2, 1, tzinfo=UTC)

    async def test_list_logs_the_search_context(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{TODOS_ENDPOINT}.TodoService.list_todos",
                new_callable=AsyncMock,
                return_value=_empty_list_response(),
            ),
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.get(
                "/api/v1/todos?q=launch&mode=semantic&project_id=p1&page=2&per_page=10"
            )

        assert resp.status_code == 200
        # Every key here is consumed by dashboards/alerts, so a renamed key or a
        # dropped filter set is a silent observability regression.
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={
                "operation": "list",
                "search_mode": "semantic",
                "query": "launch",
                "page": 2,
                "per_page": 10,
                "filters_applied": ["query", "project"],
                "project_id": "p1",
            },
        )


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
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.post(
                "/api/v1/todos/bulk/complete",
                json=["todo-1", "todo-2"],
            )

        assert resp.status_code == 200
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "bulk_complete", "bulk_count": 2},
        )
        mock_capture.assert_called_once_with(AnalyticsEvents.TODO_TOGGLED, {"bulk_count": 2})
        mock_bulk.assert_awaited_once_with(
            BulkUpdateRequest(
                todo_ids=["todo-1", "todo-2"],
                updates=TodoUpdateRequest(completed=True),
            ),
            "507f1f77bcf86cd799439011",
        )

    async def test_toggle_subtask_captures_todo_completed(self, client: AsyncClient) -> None:
        doc = TodoDocument(
            id="todo-1",
            user_id="507f1f77bcf86cd799439011",
            title="Test todo",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, tzinfo=UTC),
            subtasks=[SubTask(id="sub-1", title="Buy milk", completed=False)],
        )
        updated_doc = doc.model_copy(deep=True)
        updated_doc.subtasks[0].completed = True
        with (
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=doc,
            ) as get,
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=updated_doc,
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks/sub-1/toggle")

        assert resp.status_code == 200
        get.assert_awaited_once_with("todo-1", user_id="507f1f77bcf86cd799439011")
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "toggle_subtask", "id": "todo-1"},
        )
        mock_capture.assert_called_once_with(
            AnalyticsEvents.TODO_TOGGLED,
            {"is_subtask": True, "completed": True},
        )


class TestTodoWideEventContext:
    """The user and todo namespaces the bulk-move, project and subtask routes stamp.

    These are the only record of who did what on a route whose response body
    carries no operation name, so a renamed key or a dropped namespace is a
    silent observability regression.
    """

    async def test_bulk_move_stamps_the_move(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{TODOS_ENDPOINT}.TodoService.bulk_move_todos",
                new_callable=AsyncMock,
                return_value=BulkOperationResponse(success=["t1"], total=1, message="ok"),
            ),
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.post(
                "/api/v1/todos/bulk/move",
                json={"todo_ids": ["t1", "t2"], "project_id": "p1"},
            )

        assert resp.status_code == 200
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "bulk_move", "bulk_count": 2, "project_id": "p1"},
        )

    async def test_create_project_stamps_the_operation(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{TODOS_ENDPOINT}.ProjectService.create_project",
                new_callable=AsyncMock,
                return_value=_project_response(),
            ),
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.post("/api/v1/projects", json={"name": "Work"})

        assert resp.status_code == 201
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "create_project"},
        )

    async def test_update_project_stamps_the_target(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{TODOS_ENDPOINT}.ProjectService.update_project",
                new_callable=AsyncMock,
                return_value=_project_response(name="Renamed"),
            ),
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.put("/api/v1/projects/p1", json={"name": "Renamed"})

        assert resp.status_code == 200
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "update_project", "project_id": "p1"},
        )

    async def test_delete_project_stamps_the_target(self, client: AsyncClient) -> None:
        with (
            patch(f"{TODOS_ENDPOINT}.ProjectService.delete_project", new_callable=AsyncMock),
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.delete("/api/v1/projects/p1")

        assert resp.status_code == 204
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "delete_project", "project_id": "p1"},
        )

    async def test_create_subtask_stamps_the_parent_todo(self, client: AsyncClient) -> None:
        doc = TodoDocument(
            id="todo-1",
            user_id="507f1f77bcf86cd799439011",
            title="Test todo",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, tzinfo=UTC),
            subtasks=[SubTask(id="sub-1", title="Buy milk", completed=False)],
        )
        with (
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.add_subtask",
                new_callable=AsyncMock,
                return_value=doc,
            ) as add_subtask,
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.post("/api/v1/todos/todo-1/subtasks", json={"title": "Buy milk"})

        assert resp.status_code == 201
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "create_subtask", "id": "todo-1"},
        )
        assert add_subtask.await_args.kwargs["user_id"] == "507f1f77bcf86cd799439011"


class TestListQueryHelpers:
    """The list endpoint's filter labels and due-date resolution, read off TodoListParams."""

    def test_no_filters_applied(self):
        assert TodoListParams().filters_applied == []

    def test_every_filter_applied(self):
        params = TodoListParams(
            q="launch",
            project_id="p1",
            completed=False,
            priority=Priority.HIGH,
            labels=["work"],
            due_today=True,
            due_after=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert params.filters_applied == [
            "query",
            "project",
            "completed",
            "priority",
            "labels",
            "due_today",
            "date_range",
        ]

    def test_due_this_week_only(self):
        assert TodoListParams(due_this_week=True).filters_applied == ["due_this_week"]

    def test_date_range_from_due_before_only(self):
        params = TodoListParams(due_before=datetime(2026, 1, 1, tzinfo=UTC))

        assert params.filters_applied == ["date_range"]

    def test_due_today_is_the_utc_day_bounds(self):
        search = TodoListParams(due_today=True).to_search_params()
        start, end = search.due_date_start, search.due_date_end

        today = datetime.now(UTC).date()
        assert start == datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
        assert end == datetime.combine(today, datetime.max.time()).replace(tzinfo=UTC)
        # Aware UTC, not a naive local datetime — the bounds are timezone-tagged.
        assert start is not None and start.tzinfo is UTC
        assert end is not None and end.tzinfo is UTC

    def test_due_today_asks_for_utc_now(self, monkeypatch: pytest.MonkeyPatch):
        now_calls: list[tzinfo | None] = []

        class _RecordingDatetime(datetime):
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> datetime:
                now_calls.append(tz)
                return super().now(tz)

        monkeypatch.setattr("app.models.todo_models.datetime", _RecordingDatetime)

        TodoListParams(due_today=True).to_search_params()

        # A naive local ``datetime.now()`` would silently shift the day bounds
        # for non-UTC deployments; the tz is the observable contract here.
        assert now_calls == [UTC]

    def test_due_this_week_is_a_seven_day_window(self):
        search = TodoListParams(due_this_week=True).to_search_params()
        start, end = search.due_date_start, search.due_date_end

        assert start is not None and end is not None
        assert end - start == timedelta(days=7)
        assert start.tzinfo is UTC and end.tzinfo is UTC

    def test_explicit_range_passes_through(self):
        after = datetime(2026, 1, 1, tzinfo=UTC)
        before = datetime(2026, 2, 1, tzinfo=UTC)

        search = TodoListParams(due_after=after, due_before=before).to_search_params()

        assert (search.due_date_start, search.due_date_end) == (after, before)

    def test_no_date_filter_is_none(self):
        search = TodoListParams().to_search_params()

        assert (search.due_date_start, search.due_date_end) == (None, None)

    def test_search_params_maps_every_field(self):
        after = datetime(2026, 1, 1, tzinfo=UTC)
        before = datetime(2026, 2, 1, tzinfo=UTC)
        params = TodoListParams(
            q="x",
            mode=SearchMode.TEXT,
            project_id="p1",
            completed=True,
            priority=Priority.HIGH,
            has_due_date=True,
            overdue=True,
            labels=["work"],
            page=3,
            per_page=25,
            include_stats=True,
            due_after=after,
            due_before=before,
        ).to_search_params()

        assert params.q == "x"
        assert params.mode == SearchMode.TEXT
        assert params.project_id == "p1"
        assert params.completed is True
        assert params.priority == Priority.HIGH
        assert params.has_due_date is True
        assert params.overdue is True
        assert params.labels == ["work"]
        assert params.page == 3
        assert params.per_page == 25
        assert params.include_stats is True
        assert params.due_date_start == after
        assert params.due_date_end == before


class TestGenerateTodoWorkflow:
    async def test_a_tracked_todo_is_refused_and_nothing_is_queued(
        self, client: AsyncClient
    ) -> None:
        tracked = _todo_response().model_copy(update={"labels": [GAIA_TRACKED_LABEL]})
        queue = AsyncMock(return_value=True)
        with (
            patch(f"{TODOS_ENDPOINT}.TodoService.get_todo", new=AsyncMock(return_value=tracked)),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new=queue,
            ),
        ):
            resp = await client.post("/api/v1/todos/todo-1/workflow")

        assert resp.status_code == 409
        queue.assert_not_awaited()


class TestUpdateTodoWorkflowLink:
    async def test_linking_a_workflow_to_a_tracked_todo_is_409(self, client: AsyncClient) -> None:
        with patch(
            f"{TODOS_ENDPOINT}.TodoService.update_todo",
            new=AsyncMock(side_effect=TrackedTodoWorkflowError()),
        ):
            resp = await client.put("/api/v1/todos/todo-1", json={"workflow_id": "wf1"})

        assert resp.status_code == 409


class TestTodoCanvas:
    async def test_returns_canvas_and_activity(self, client: AsyncClient) -> None:
        doc = TodoDocument(
            id="todo-1",
            user_id="507f1f77bcf86cd799439011",
            title="Fix the thing",
            canvas_content="# Fix the thing",
            activity_content="- 2026-09-01T09:00:00+00:00 started",
        )
        with (
            patch(
                f"{TODOS_ENDPOINT}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=doc,
            ) as get,
            patch(f"{TODOS_ENDPOINT}.log.set") as set_log,
        ):
            resp = await client.get("/api/v1/todos/todo-1/canvas")

        assert resp.status_code == 200
        set_log.assert_any_call(
            user={"id": "507f1f77bcf86cd799439011"},
            todo={"operation": "get_canvas", "id": "todo-1"},
        )
        assert resp.json() == {
            "content": "# Fix the thing",
            "activity": "- 2026-09-01T09:00:00+00:00 started",
        }
        get.assert_awaited_once_with("todo-1", user_id="507f1f77bcf86cd799439011")

    async def test_unset_bodies_read_as_empty(self, client: AsyncClient) -> None:
        doc = TodoDocument(id="todo-1", user_id="507f1f77bcf86cd799439011", title="t")
        with patch(
            f"{TODOS_ENDPOINT}.todo_repository.get",
            new_callable=AsyncMock,
            return_value=doc,
        ) as get:
            resp = await client.get("/api/v1/todos/todo-1/canvas")

        assert resp.json() == {"content": "", "activity": ""}
        get.assert_awaited_once_with("todo-1", user_id="507f1f77bcf86cd799439011")

    async def test_missing_todo_is_404(self, client: AsyncClient) -> None:
        with patch(
            f"{TODOS_ENDPOINT}.todo_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ) as get:
            resp = await client.get("/api/v1/todos/todo-1/canvas")

        assert resp.status_code == 404
        assert resp.json()["message"] == "Todo not found"
        get.assert_awaited_once_with("todo-1", user_id="507f1f77bcf86cd799439011")
