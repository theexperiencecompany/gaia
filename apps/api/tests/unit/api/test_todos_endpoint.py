"""Unit tests for the /api/v1/todos endpoint module.

Every endpoint is pinned on its contract, not its shape: exact status
codes, exact response bodies, exact service/repository call arguments,
exact error strings, and exact wide-event log payloads. All external I/O
(services, repositories, redis cache, workflow queue, rate limiter) is
mocked; the endpoint's own logic — filter accumulation, special-date
derivation, error mapping, subtask verification, workflow-state
machinery — is asserted precisely.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.constants.general import MAX_PAGE_NUMBER
from app.constants.log_tags import LogTag
from app.models.todo_models import (
    BulkOperationResponse,
    PaginationMeta,
    Priority,
    ProjectResponse,
    SearchMode,
    SubTask,
    TodoCounts,
    TodoDocument,
    TodoLabelCount,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoWorkflowStatus,
    TodoWorkflowStatusResponse,
)
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowStep,
    WorkflowWithIntegrations,
)
from tests.conftest import FAKE_USER

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "app.api.v1.endpoints.todos"
USER_ID = FAKE_USER["user_id"]
NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
API = "/api/v1/todos"

# --- rate limiter: the @tiered_rate_limit decorator must not touch Redis ---
_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

# --- wide-event logger: pin every log.set / set_ns / warning payload ---
_log_patch = patch(f"{MODULE}.log", new_callable=MagicMock)
_log_mock = _log_patch.start()


@pytest.fixture(autouse=True)
def _reset_log_mock() -> None:
    _log_mock.reset_mock()
    yield
    _log_mock.reset_mock()


class _FrozenDateTime(datetime):
    """datetime stand-in pinned to NOW so date-derived filters are deterministic.

    Also enforces that the endpoint computes "today" in UTC: ``datetime.now``
    must be called with the UTC tzinfo or the test fails.
    """

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        assert tz is UTC, f"datetime.now must be called with UTC, got {tz!r}"
        return NOW


@pytest.fixture
def frozen_now() -> datetime:
    with patch(f"{MODULE}.datetime", _FrozenDateTime):
        yield NOW


@pytest.fixture
def timezone_utc(test_app: FastAPI) -> None:
    """Pin the timezone dependency so workflow tests are deterministic."""
    original = test_app.dependency_overrides.get(get_user_timezone_from_preferences)
    test_app.dependency_overrides[get_user_timezone_from_preferences] = lambda: "UTC"
    yield
    if original is None:
        test_app.dependency_overrides.pop(get_user_timezone_from_preferences, None)
    else:
        test_app.dependency_overrides[get_user_timezone_from_preferences] = original


def _empty_meta() -> PaginationMeta:
    return PaginationMeta(total=0, page=1, per_page=50, pages=0, has_next=False, has_prev=False)


def _empty_list_response() -> TodoListResponse:
    return TodoListResponse(data=[], meta=_empty_meta())


def _todo_response(todo_id: str = "todo_1", **overrides: Any) -> TodoResponse:
    """A real TodoResponse the mocked service/repository may return."""
    data: dict[str, Any] = {
        "id": todo_id,
        "user_id": USER_ID,
        "title": "Buy milk",
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return TodoResponse(**data)


def _todo_document(todo_id: str = "todo_1", **overrides: Any) -> TodoDocument:
    """A real stored TodoDocument (``from_document`` needs a real ``model_dump``)."""
    data: dict[str, Any] = {
        "id": todo_id,
        "user_id": USER_ID,
        "title": "Buy milk",
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return TodoDocument(**data)


def _bulk_response() -> BulkOperationResponse:
    return BulkOperationResponse(success=["todo_1"], failed=[], total=1, message="1 todo updated")


def _workflow(workflow_id: str = "wf_1", *, steps: list[WorkflowStep] | None = None) -> WorkflowWithIntegrations:
    """A real workflow the mocked WorkflowService may return."""
    return WorkflowWithIntegrations(
        id=workflow_id,
        user_id=USER_ID,
        title="Plan the launch",
        description="Desc",
        steps=steps
        if steps is not None
        else [WorkflowStep(id="s1", title="Draft", description="Draft the copy")],
        trigger_config=TriggerConfig(type=TriggerType.MANUAL),
    )


class TestGetTodoCounts:
    """GET /api/v1/todos/counts"""

    async def test_counts_returns_all_four_counts(self, client: AsyncClient) -> None:
        counts = TodoCounts(inbox=1, today=2, upcoming=3, completed=4, overdue=5)
        with (
            patch(
                f"{MODULE}.project_repository.get_default_inbox",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(id="inbox_1"),
            ) as get_default_inbox,
            patch(
                f"{MODULE}.todo_repository.compute_counts",
                new_callable=AsyncMock,
                return_value=counts,
            ) as compute_counts,
        ):
            resp = await client.get(f"{API}/counts")

        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "private, max-age=10"
        assert resp.json() == counts.model_dump(mode="json")
        get_default_inbox.assert_awaited_once_with(USER_ID)
        compute_counts.assert_awaited_once_with(user_id=USER_ID, inbox_project_id="inbox_1")
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "counts"}
        )

    async def test_counts_without_inbox_uses_no_inbox_found(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.project_repository.get_default_inbox",
                new_callable=AsyncMock,
                return_value=None,
            ) as get_default_inbox,
            patch(
                f"{MODULE}.todo_repository.compute_counts",
                new_callable=AsyncMock,
                return_value=TodoCounts(),
            ) as compute_counts,
        ):
            resp = await client.get(f"{API}/counts")

        assert resp.status_code == 200
        get_default_inbox.assert_awaited_once_with(USER_ID)
        compute_counts.assert_awaited_once_with(user_id=USER_ID, inbox_project_id="no_inbox_found")

    async def test_counts_failure_returns_500_with_reason(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.project_repository.get_default_inbox",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(id="inbox_1"),
            ) as get_default_inbox,
            patch(
                f"{MODULE}.todo_repository.compute_counts",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
        ):
            resp = await client.get(f"{API}/counts")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve counts: db down"
        get_default_inbox.assert_awaited_once_with(USER_ID)


class TestGetTodoLabels:
    """GET /api/v1/todos/labels"""

    async def test_labels_returns_most_used(self, client: AsyncClient) -> None:
        labels = [TodoLabelCount(name="Work", count=3), TodoLabelCount(name="Home", count=1)]
        with patch(
            f"{MODULE}.todo_repository.top_labels",
            new_callable=AsyncMock,
            return_value=labels,
        ) as top_labels:
            resp = await client.get(f"{API}/labels")

        assert resp.status_code == 200
        assert resp.json() == [label.model_dump(mode="json") for label in labels]
        top_labels.assert_awaited_once_with(user_id=USER_ID, limit=10)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "list_labels"}
        )
        _log_mock.set_ns.assert_called_once_with("todo", result_count=2)

    async def test_labels_honors_custom_limit(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.top_labels",
            new_callable=AsyncMock,
            return_value=[],
        ) as top_labels:
            resp = await client.get(f"{API}/labels?limit=5")

        assert resp.status_code == 200
        top_labels.assert_awaited_once_with(user_id=USER_ID, limit=5)


class TestListTodos:
    """GET /api/v1/todos — filter accumulation, special dates, error mapping."""

    async def test_default_request_passes_default_params(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(API)

        assert resp.status_code == 200
        assert resp.json() == _empty_list_response().model_dump(mode="json")
        list_todos.assert_awaited_once_with(USER_ID, TodoSearchParams())
        params = list_todos.await_args.args[1]
        assert params.q is None
        assert params.mode is SearchMode.HYBRID
        assert params.project_id is None
        assert params.completed is None
        assert params.priority is None
        assert params.has_due_date is None
        assert params.overdue is None
        assert params.due_date_start is None
        assert params.due_date_end is None
        assert params.labels is None
        assert params.page == 1
        assert params.per_page == 50
        assert params.include_stats is False
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "list",
                "search_mode": "hybrid",
                "query": None,
                "page": 1,
                "per_page": 50,
                "filters_applied": [],
                "project_id": None,
            },
        )
        _log_mock.set_ns.assert_called_once_with("todo", result_count=0)

    async def test_all_filters_accumulate_and_pass_through(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(
                API,
                params={
                    "q": "milk",
                    "mode": "text",
                    "project_id": "proj_1",
                    "completed": "true",
                    "priority": "high",
                    "has_due_date": "true",
                    "overdue": "true",
                    "labels": ["work", "home"],
                    "due_after": "2026-08-01T00:00:00Z",
                    "due_before": "2026-08-31T00:00:00Z",
                    "page": "2",
                    "per_page": "25",
                    "include_stats": "true",
                },
            )

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.q == "milk"
        assert params.mode is SearchMode.TEXT
        assert params.project_id == "proj_1"
        assert params.completed is True
        assert params.priority is Priority.HIGH
        assert params.has_due_date is True
        assert params.overdue is True
        assert params.labels == ["work", "home"]
        assert params.due_date_start == datetime(2026, 8, 1, tzinfo=UTC)
        assert params.due_date_end == datetime(2026, 8, 31, tzinfo=UTC)
        assert params.page == 2
        assert params.per_page == 25
        assert params.include_stats is True
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "list",
                "search_mode": "text",
                "query": "milk",
                "page": 2,
                "per_page": 25,
                "filters_applied": [
                    "query",
                    "project",
                    "completed",
                    "priority",
                    "labels",
                    "date_range",
                ],
                "project_id": "proj_1",
            },
        )

    async def test_due_today_pins_midnight_window(self, client: AsyncClient, frozen_now: datetime) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(API, params={"due_today": "true"})

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.due_date_start == datetime.combine(
            NOW.date(), datetime.min.time()
        ).replace(tzinfo=UTC)
        assert params.due_date_end == datetime.combine(
            NOW.date(), datetime.max.time()
        ).replace(tzinfo=UTC)
        assert params.due_date_start != params.due_date_end
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "list",
                "search_mode": "hybrid",
                "query": None,
                "page": 1,
                "per_page": 50,
                "filters_applied": ["due_today"],
                "project_id": None,
            },
        )

    async def test_due_this_week_sets_rolling_window(
        self, client: AsyncClient, frozen_now: datetime
    ) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(API, params={"due_this_week": "true"})

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.due_date_start == NOW
        assert params.due_date_end == NOW + timedelta(days=7)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "list",
                "search_mode": "hybrid",
                "query": None,
                "page": 1,
                "per_page": 50,
                "filters_applied": ["due_this_week"],
                "project_id": None,
            },
        )

    async def test_due_today_wins_over_due_this_week(
        self, client: AsyncClient, frozen_now: datetime
    ) -> None:
        """Both flags: the today branch must win (elif), not run after it."""
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(
                API, params={"due_today": "true", "due_this_week": "true"}
            )

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.due_date_start == datetime.combine(
            NOW.date(), datetime.min.time()
        ).replace(tzinfo=UTC)
        assert params.due_date_end == datetime.combine(
            NOW.date(), datetime.max.time()
        ).replace(tzinfo=UTC)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "list",
                "search_mode": "hybrid",
                "query": None,
                "page": 1,
                "per_page": 50,
                "filters_applied": ["due_today", "due_this_week"],
                "project_id": None,
            },
        )

    async def test_due_after_alone_counts_as_date_range(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=_empty_list_response(),
        ) as list_todos:
            resp = await client.get(API, params={"due_after": "2026-08-01T00:00:00Z"})

        assert resp.status_code == 200
        params = list_todos.await_args.args[1]
        assert params.due_date_start == datetime(2026, 8, 1, tzinfo=UTC)
        assert params.due_date_end is None
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "list",
                "search_mode": "hybrid",
                "query": None,
                "page": 1,
                "per_page": 50,
                "filters_applied": ["date_range"],
                "project_id": None,
            },
        )

    async def test_returns_todos_and_stats(self, client: AsyncClient) -> None:
        response = TodoListResponse(
            data=[_todo_response(todo_id="todo_1")],
            meta=PaginationMeta(
                total=1, page=1, per_page=50, pages=1, has_next=False, has_prev=False
            ),
        )
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            return_value=response,
        ) as list_todos:
            resp = await client.get(API)

        assert resp.status_code == 200
        assert resp.json() == response.model_dump(mode="json")
        assert resp.json()["data"][0]["id"] == "todo_1"
        list_todos.assert_awaited_once_with(USER_ID, TodoSearchParams())
        _log_mock.set_ns.assert_called_once_with("todo", result_count=1)

    async def test_service_value_error_returns_400(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            side_effect=ValueError("bad query"),
        ):
            resp = await client.get(API)

        assert resp.status_code == 400
        assert resp.json()["detail"] == "bad query"

    async def test_service_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.list_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.get(API)

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve todos"

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"{API}?page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_page_zero_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"{API}?page=0")

        assert resp.status_code == 422

    async def test_per_page_over_100_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"{API}?per_page=101")

        assert resp.status_code == 422

    async def test_invalid_mode_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"{API}?mode=bogus")

        assert resp.status_code == 422


class TestCreateTodo:
    """POST /api/v1/todos"""

    async def test_create_returns_201(self, client: AsyncClient) -> None:
        created = _todo_response(todo_id="todo_new")
        with patch(
            f"{MODULE}.TodoService.create_todo",
            new_callable=AsyncMock,
            return_value=created,
        ) as create_todo:
            resp = await client.post(API, json={"title": "Buy milk", "priority": "high"})

        assert resp.status_code == 201
        assert resp.json() == created.model_dump(mode="json")
        created_model = create_todo.await_args.args[0]
        assert isinstance(created_model, TodoModel)
        assert created_model.title == "Buy milk"
        assert created_model.priority is Priority.HIGH
        assert created_model.project_id is None
        assert create_todo.await_args.args[1] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "create",
                "priority": "high",
                "has_due_date": False,
                "project_id": None,
            },
        )

    async def test_create_with_due_date_logs_has_due_date(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.create_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(),
        ):
            resp = await client.post(
                API, json={"title": "Buy milk", "due_date": "2026-08-15T09:00:00Z"}
            )

        assert resp.status_code == 201
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={
                "operation": "create",
                "priority": "none",
                "has_due_date": True,
                "project_id": None,
            },
        )

    async def test_create_value_error_returns_400(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.create_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("no such project"),
        ):
            resp = await client.post(API, json={"title": "Buy milk"})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "no such project"

    async def test_create_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.create_todo",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(API, json={"title": "Buy milk"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to create todo"

    async def test_create_empty_title_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(API, json={"title": ""})

        assert resp.status_code == 422

    async def test_create_missing_user_id_rejected_401(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        """The tiered_rate_limit decorator rejects a principal without user_id."""
        original = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"email": "nobody@example.com"}
        try:
            resp = await client.post(API, json={"title": "Buy milk"})
        finally:
            if original is None:
                test_app.dependency_overrides.pop(get_current_user, None)
            else:
                test_app.dependency_overrides[get_current_user] = original

        assert resp.status_code == 401
        assert resp.json()["detail"] == "User ID not found"


class TestBulkUpdateTodos:
    """PUT /api/v1/todos/bulk"""

    async def test_bulk_update_passes_request(self, client: AsyncClient) -> None:
        result = _bulk_response()
        with patch(
            f"{MODULE}.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            return_value=result,
        ) as bulk_update:
            resp = await client.put(
                API + "/bulk",
                json={"todo_ids": ["t1", "t2"], "updates": {"completed": True}},
            )

        assert resp.status_code == 200
        assert resp.json() == result.model_dump(mode="json")
        request = bulk_update.await_args.args[0]
        assert request.todo_ids == ["t1", "t2"]
        assert request.updates.completed is True
        assert bulk_update.await_args.args[1] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "bulk_update", "bulk_count": 2}
        )

    async def test_bulk_update_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.put(
                API + "/bulk",
                json={"todo_ids": ["t1"], "updates": {"completed": True}},
            )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Bulk update failed"

    async def test_bulk_update_empty_ids_returns_422(self, client: AsyncClient) -> None:
        resp = await client.put(
            API + "/bulk", json={"todo_ids": [], "updates": {"completed": True}}
        )

        assert resp.status_code == 422


class TestBulkMoveTodos:
    """POST /api/v1/todos/bulk/move"""

    async def test_bulk_move_passes_request(self, client: AsyncClient) -> None:
        result = _bulk_response()
        with patch(
            f"{MODULE}.TodoService.bulk_move_todos",
            new_callable=AsyncMock,
            return_value=result,
        ) as bulk_move:
            resp = await client.post(
                API + "/bulk/move", json={"todo_ids": ["t1"], "project_id": "proj_2"}
            )

        assert resp.status_code == 200
        assert resp.json() == result.model_dump(mode="json")
        request = bulk_move.await_args.args[0]
        assert request.todo_ids == ["t1"]
        assert request.project_id == "proj_2"
        assert bulk_move.await_args.args[1] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "bulk_move", "bulk_count": 1, "project_id": "proj_2"},
        )

    async def test_bulk_move_value_error_returns_400(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.bulk_move_todos",
            new_callable=AsyncMock,
            side_effect=ValueError("cannot move to inbox"),
        ):
            resp = await client.post(
                API + "/bulk/move", json={"todo_ids": ["t1"], "project_id": "proj_2"}
            )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "cannot move to inbox"

    async def test_bulk_move_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.bulk_move_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(
                API + "/bulk/move", json={"todo_ids": ["t1"], "project_id": "proj_2"}
            )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Bulk move failed"

    async def test_bulk_move_missing_project_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(API + "/bulk/move", json={"todo_ids": ["t1"]})

        assert resp.status_code == 422


class TestBulkDeleteTodos:
    """DELETE /api/v1/todos/bulk"""

    async def test_bulk_delete_passes_ids(self, client: AsyncClient) -> None:
        result = _bulk_response()
        with patch(
            f"{MODULE}.TodoService.bulk_delete_todos",
            new_callable=AsyncMock,
            return_value=result,
        ) as bulk_delete:
            resp = await client.request("DELETE", API + "/bulk", json=["t1", "t2"])

        assert resp.status_code == 200
        assert resp.json() == result.model_dump(mode="json")
        bulk_delete.assert_awaited_once_with(["t1", "t2"], USER_ID)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "bulk_delete", "bulk_count": 2}
        )

    async def test_bulk_delete_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.bulk_delete_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.request("DELETE", API + "/bulk", json=["t1"])

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Bulk delete failed"

    async def test_bulk_delete_empty_ids_returns_422(self, client: AsyncClient) -> None:
        resp = await client.request("DELETE", API + "/bulk", json=[])

        assert resp.status_code == 422


class TestBulkCompleteTodos:
    """POST /api/v1/todos/bulk/complete"""

    async def test_bulk_complete_builds_completed_update(self, client: AsyncClient) -> None:
        result = _bulk_response()
        with patch(
            f"{MODULE}.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            return_value=result,
        ) as bulk_update:
            resp = await client.post(API + "/bulk/complete", json=["t1", "t2"])

        assert resp.status_code == 200
        assert resp.json() == result.model_dump(mode="json")
        request = bulk_update.await_args.args[0]
        assert request.todo_ids == ["t1", "t2"]
        assert request.updates.completed is True
        assert request.updates.priority is None
        assert bulk_update.await_args.args[1] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "bulk_complete", "bulk_count": 2}
        )

    async def test_bulk_complete_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.bulk_update_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(API + "/bulk/complete", json=["t1"])

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Bulk complete failed"

    async def test_bulk_complete_empty_ids_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(API + "/bulk/complete", json=[])

        assert resp.status_code == 422


class TestGetTodo:
    """GET /api/v1/todos/{todo_id}"""

    async def test_get_returns_todo(self, client: AsyncClient) -> None:
        todo = _todo_response(todo_id="todo_1")
        with patch(
            f"{MODULE}.TodoService.get_todo",
            new_callable=AsyncMock,
            return_value=todo,
        ) as get_todo:
            resp = await client.get(f"{API}/todo_1")

        assert resp.status_code == 200
        assert resp.json() == todo.model_dump(mode="json")
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "get", "id": "todo_1"}
        )

    async def test_get_missing_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ):
            resp = await client.get(f"{API}/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo not found"

    async def test_get_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.get(f"{API}/todo_1")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve todo"


class TestGetTodoCanvas:
    """GET /api/v1/todos/{todo_id}/canvas"""

    async def test_canvas_returns_content(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.read_canvas",
            new_callable=AsyncMock,
            return_value="# Plan\n- step one",
        ) as read_canvas:
            resp = await client.get(f"{API}/todo_1/canvas")

        assert resp.status_code == 200
        assert resp.json() == {"content": "# Plan\n- step one"}
        read_canvas.assert_awaited_once_with("todo_1", USER_ID)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "get_canvas", "id": "todo_1"},
        )

    async def test_canvas_missing_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{MODULE}.read_canvas", new_callable=AsyncMock, return_value=None):
            resp = await client.get(f"{API}/todo_1/canvas")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo not found"


class TestUpdateTodo:
    """PUT /api/v1/todos/{todo_id}"""

    async def test_update_passes_request(self, client: AsyncClient) -> None:
        updated = _todo_response(todo_id="todo_1", title="New title")
        with patch(
            f"{MODULE}.TodoService.update_todo",
            new_callable=AsyncMock,
            return_value=updated,
        ) as update_todo:
            resp = await client.put(
                f"{API}/todo_1", json={"title": "New title", "priority": "low"}
            )

        assert resp.status_code == 200
        assert resp.json() == updated.model_dump(mode="json")
        update_todo.assert_awaited_once()
        assert update_todo.await_args.args[0] == "todo_1"
        assert update_todo.await_args.args[1].title == "New title"
        assert update_todo.await_args.args[1].priority is Priority.LOW
        assert update_todo.await_args.args[2] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "update", "id": "todo_1", "completion_toggled": False},
        )

    async def test_update_completion_toggled_logs_true(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.update_todo",
            new_callable=AsyncMock,
            return_value=_todo_response(completed=True),
        ):
            resp = await client.put(f"{API}/todo_1", json={"completed": True})

        assert resp.status_code == 200
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "update", "id": "todo_1", "completion_toggled": True},
        )

    async def test_update_scheduled_reschedules_tracked_todo(self, client: AsyncClient) -> None:
        scheduled_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
        with (
            patch(
                f"{MODULE}.TodoService.update_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(vfs_path="vfs/todo_1", scheduled_at=scheduled_at),
            ),
            patch(
                f"{MODULE}.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
            ) as reschedule,
        ):
            resp = await client.put(
                f"{API}/todo_1", json={"scheduled_at": scheduled_at.isoformat()}
            )

        assert resp.status_code == 200
        reschedule.assert_awaited_once_with("todo_1", scheduled_at)

    async def test_update_scheduled_without_vfs_path_skips_reschedule(
        self, client: AsyncClient
    ) -> None:
        scheduled_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
        with (
            patch(
                f"{MODULE}.TodoService.update_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(vfs_path=None, scheduled_at=scheduled_at),
            ),
            patch(
                f"{MODULE}.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
            ) as reschedule,
        ):
            resp = await client.put(
                f"{API}/todo_1", json={"scheduled_at": scheduled_at.isoformat()}
            )

        assert resp.status_code == 200
        reschedule.assert_not_awaited()

    async def test_update_vfs_path_without_scheduled_skips_reschedule(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                f"{MODULE}.TodoService.update_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(vfs_path="vfs/todo_1", scheduled_at=None),
            ),
            patch(
                f"{MODULE}.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
            ) as reschedule,
        ):
            resp = await client.put(f"{API}/todo_1", json={"title": "Renamed"})

        assert resp.status_code == 200
        reschedule.assert_not_awaited()

    async def test_update_reschedule_failure_logs_warning_but_succeeds(
        self, client: AsyncClient
    ) -> None:
        scheduled_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
        with (
            patch(
                f"{MODULE}.TodoService.update_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(vfs_path="vfs/todo_1", scheduled_at=scheduled_at),
            ),
            patch(
                f"{MODULE}.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
                side_effect=RuntimeError("arq down"),
            ),
        ):
            resp = await client.put(
                f"{API}/todo_1", json={"scheduled_at": scheduled_at.isoformat()}
            )

        assert resp.status_code == 200
        _log_mock.warning.assert_called_once_with(
            f"{LogTag.TODO} Failed to reschedule todo after update",
            todo_id="todo_1",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="arq down",
        )

    async def test_update_missing_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.update_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ):
            resp = await client.put(f"{API}/missing", json={"title": "X"})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo not found"

    async def test_update_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.update_todo",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.put(f"{API}/todo_1", json={"title": "X"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to update todo"


class TestDeleteTodo:
    """DELETE /api/v1/todos/{todo_id}"""

    async def test_delete_returns_204(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.delete_todo",
            new_callable=AsyncMock,
        ) as delete_todo:
            resp = await client.delete(f"{API}/todo_1")

        assert resp.status_code == 204
        assert resp.content == b""
        delete_todo.assert_awaited_once_with("todo_1", USER_ID)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "delete", "id": "todo_1"}
        )

    async def test_delete_missing_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.delete_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ):
            resp = await client.delete(f"{API}/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo not found"

    async def test_delete_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.TodoService.delete_todo",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.delete(f"{API}/todo_1")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to delete todo"


class TestGenerateWorkflow:
    """POST /api/v1/todos/{todo_id}/workflow"""

    async def test_generate_queues_background_generation(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(title="Launch", description="Ship it"),
            ) as get_todo,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock) as delete_cache,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ) as queue,
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "generating"
        assert body["todo_id"] == "todo_1"
        assert body["workflow"] is None
        assert (
            body["message"]
            == "Workflow generation started. Listen for 'workflow.generated' WebSocket event."
        )
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        delete_cache.assert_awaited_once_with(f"workflow_status:{USER_ID}:todo_1")
        queue.assert_awaited_once_with(
            todo_id="todo_1", user_id=USER_ID, title="Launch", description="Ship it"
        )
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "generate_workflow", "id": "todo_1"}
        )

    async def test_generate_without_description_passes_empty(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(title="Launch", description=None),
            ) as get_todo,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ) as queue,
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == "generating"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        queue.assert_awaited_once_with(
            todo_id="todo_1", user_id=USER_ID, title="Launch", description=""
        )

    async def test_generate_existing_workflow_returns_exists(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        existing = _workflow()
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ) as get_todo,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=existing,
            ) as get_workflow,
            patch(
                f"{MODULE}.WorkflowService.delete_workflow",
                new_callable=AsyncMock,
            ) as delete_workflow,
            patch(
                f"{MODULE}.todo_repository.clear_workflow_id",
                new_callable=AsyncMock,
            ) as clear_workflow_id,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock) as delete_cache,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
            ) as queue,
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "exists"
        assert body["workflow"]["id"] == "wf_1"
        assert body["workflow"]["title"] == "Plan the launch"
        assert body["message"] == "Workflow already exists for this todo"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        get_workflow.assert_awaited_once_with("wf_1", USER_ID)
        delete_workflow.assert_not_awaited()
        clear_workflow_id.assert_not_awaited()
        delete_cache.assert_not_awaited()
        queue.assert_not_awaited()

    async def test_generate_empty_workflow_is_replaced(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        """An existing workflow with no steps is deleted and regenerated."""
        empty = _workflow(steps=[])
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ) as get_todo,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=empty,
            ),
            patch(
                f"{MODULE}.WorkflowService.delete_workflow",
                new_callable=AsyncMock,
            ) as delete_workflow,
            patch(
                f"{MODULE}.todo_repository.clear_workflow_id",
                new_callable=AsyncMock,
            ) as clear_workflow_id,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ) as queue,
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == "generating"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        delete_workflow.assert_awaited_once_with("wf_1", USER_ID)
        clear_workflow_id.assert_awaited_once_with("todo_1", user_id=USER_ID)
        queue.assert_awaited_once()

    async def test_generate_workflow_without_id_skips_delete(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ) as get_todo,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=_workflow(workflow_id=None, steps=[]),
            ),
            patch(
                f"{MODULE}.WorkflowService.delete_workflow",
                new_callable=AsyncMock,
            ) as delete_workflow,
            patch(
                f"{MODULE}.todo_repository.clear_workflow_id",
                new_callable=AsyncMock,
            ) as clear_workflow_id,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == "generating"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        delete_workflow.assert_not_awaited()
        clear_workflow_id.assert_awaited_once_with("todo_1", user_id=USER_ID)

    async def test_generate_queue_failure_returns_500(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(),
            ) as get_todo,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to queue workflow generation"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)

    async def test_generate_missing_todo_returns_404(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        with patch(
            f"{MODULE}.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=ValueError("Todo not found"),
        ) as get_todo:
            resp = await client.post(f"{API}/missing/workflow")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo not found"
        get_todo.assert_awaited_once_with("missing", USER_ID)

    async def test_generate_failure_returns_500(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        with patch(
            f"{MODULE}.TodoService.get_todo",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ) as get_todo:
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to generate workflow"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)

    async def test_generate_missing_workflow_is_regenerated(
        self, client: AsyncClient, timezone_utc: None
    ) -> None:
        """A dangling workflow_id with no stored workflow falls through to queueing.

        The EXISTS check must not dereference a None workflow (``and`` chain
        short-circuits) — the regenerated flow must succeed.
        """
        with (
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ),
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.WorkflowService.delete_workflow",
                new_callable=AsyncMock,
            ) as delete_workflow,
            patch(
                f"{MODULE}.todo_repository.clear_workflow_id",
                new_callable=AsyncMock,
            ) as clear_workflow_id,
            patch(f"{MODULE}.delete_cache", new_callable=AsyncMock),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_todo_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ) as queue,
        ):
            resp = await client.post(f"{API}/todo_1/workflow")

        assert resp.status_code == 200
        assert resp.json()["status"] == "generating"
        delete_workflow.assert_not_awaited()
        clear_workflow_id.assert_awaited_once_with("todo_1", user_id=USER_ID)
        queue.assert_awaited_once()


class TestGetWorkflowStatus:
    """GET /api/v1/todos/{todo_id}/workflow-status"""

    async def test_status_serves_cached_value(self, client: AsyncClient) -> None:
        cached = TodoWorkflowStatusResponse(
            todo_id="todo_1",
            has_workflow=True,
            is_generating=False,
            workflow_status=TodoWorkflowStatus.COMPLETED,
            workflow=_workflow(),
        )
        with (
            patch(
                f"{MODULE}.get_cache",
                new_callable=AsyncMock,
                return_value=cached,
            ) as get_cache,
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
            ) as get_todo,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_cache,
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "private, max-age=15"
        # Pin the exact wire-level header value (httpx normalizes names to
        # lowercase in .raw), not just the case-insensitive lookup value.
        assert (b"cache-control", b"private, max-age=15") in resp.headers.raw
        body = resp.json()
        assert body["todo_id"] == "todo_1"
        assert body["has_workflow"] is True
        assert body["is_generating"] is False
        assert body["workflow_status"] == "completed"
        assert body["workflow"]["id"] == "wf_1"
        get_cache.assert_awaited_once_with(
            f"workflow_status:{USER_ID}:todo_1", model=TodoWorkflowStatusResponse
        )
        get_todo.assert_not_awaited()
        set_cache.assert_not_awaited()
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "get_workflow_status", "id": "todo_1"},
        )

    async def test_status_not_started_caches_result(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id=None),
            ) as get_todo,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                return_value=False,
            ) as is_generating,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
            ) as get_workflow,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_cache,
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "todo_id": "todo_1",
            "has_workflow": False,
            "is_generating": False,
            "workflow_status": "not_started",
            "workflow": None,
        }
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        is_generating.assert_awaited_once_with("todo_1")
        get_workflow.assert_not_awaited()
        set_cache.assert_awaited_once()
        args, kwargs = set_cache.await_args
        assert args[0] == f"workflow_status:{USER_ID}:todo_1"
        assert kwargs["ttl"] == 60
        assert kwargs["model"] is TodoWorkflowStatusResponse
        assert args[1].workflow_status is TodoWorkflowStatus.NOT_STARTED
        assert args[1].workflow is None

    async def test_status_generating_flag_wins(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id=None),
            ) as get_todo,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                return_value=True,
            ) as is_generating,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
            ) as get_workflow,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_cache,
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_status"] == "generating"
        assert body["is_generating"] is True
        assert body["has_workflow"] is False
        assert body["workflow"] is None
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        is_generating.assert_awaited_once_with("todo_1")
        get_workflow.assert_not_awaited()
        set_cache.assert_not_awaited()

    async def test_status_completed_with_steps(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ) as get_todo,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                return_value=False,
            ) as is_generating,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=_workflow(),
            ) as get_workflow,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_cache,
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_status"] == "completed"
        assert body["has_workflow"] is True
        assert body["is_generating"] is False
        assert body["workflow"]["id"] == "wf_1"
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        is_generating.assert_awaited_once_with("todo_1")
        get_workflow.assert_awaited_once_with("wf_1", USER_ID)
        set_cache.assert_awaited_once()

    async def test_status_empty_steps_but_generating(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ) as get_todo,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ) as is_generating,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=_workflow(steps=[]),
            ),
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_cache,
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_status"] == "generating"
        assert body["is_generating"] is True
        assert body["has_workflow"] is False
        assert body["workflow"] is None
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        assert all(call.args == ("todo_1",) for call in is_generating.await_args_list)
        set_cache.assert_not_awaited()

    async def test_status_empty_steps_and_not_generating_is_failed(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                return_value=_todo_response(workflow_id="wf_1"),
            ) as get_todo,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.is_workflow_generating",
                new_callable=AsyncMock,
                side_effect=[False, False],
            ) as is_generating,
            patch(
                f"{MODULE}.WorkflowService.get_workflow",
                new_callable=AsyncMock,
                return_value=_workflow(steps=[]),
            ),
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_cache,
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_status"] == "failed"
        assert body["has_workflow"] is False
        assert body["is_generating"] is False
        get_todo.assert_awaited_once_with("todo_1", USER_ID)
        assert all(call.args == ("todo_1",) for call in is_generating.await_args_list)
        set_cache.assert_awaited_once()

    async def test_status_missing_todo_returns_404(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                side_effect=ValueError("Todo not found"),
            ) as get_todo,
        ):
            resp = await client.get(f"{API}/missing/workflow-status")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo not found"
        get_todo.assert_awaited_once_with("missing", USER_ID)

    async def test_status_failure_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(
                f"{MODULE}.TodoService.get_todo",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            resp = await client.get(f"{API}/todo_1/workflow-status")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to get workflow status"


class TestListProjects:
    """GET /api/v1/projects"""

    async def test_list_projects(self, client: AsyncClient) -> None:
        project = ProjectResponse(
            id="proj_1",
            user_id=USER_ID,
            name="Work",
            created_at=NOW,
            updated_at=NOW,
        )
        with patch(
            f"{MODULE}.ProjectService.list_projects",
            new_callable=AsyncMock,
            return_value=[project],
        ) as list_projects:
            resp = await client.get("/api/v1/projects")

        assert resp.status_code == 200
        assert resp.json() == [project.model_dump(mode="json")]
        list_projects.assert_awaited_once_with(USER_ID)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "list_projects"}
        )

    async def test_list_projects_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.list_projects",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.get("/api/v1/projects")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve projects"


class TestCreateProject:
    """POST /api/v1/projects"""

    async def test_create_project_returns_201(self, client: AsyncClient) -> None:
        created = ProjectResponse(
            id="proj_new",
            user_id=USER_ID,
            name="Work",
            created_at=NOW,
            updated_at=NOW,
        )
        with patch(
            f"{MODULE}.ProjectService.create_project",
            new_callable=AsyncMock,
            return_value=created,
        ) as create_project:
            resp = await client.post("/api/v1/projects", json={"name": "Work"})

        assert resp.status_code == 201
        assert resp.json() == created.model_dump(mode="json")
        create_project.assert_awaited_once()
        assert create_project.await_args.args[0].name == "Work"
        assert create_project.await_args.args[1] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "create_project"}
        )

    async def test_create_project_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.create_project",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post("/api/v1/projects", json={"name": "Work"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to create project"

    async def test_create_project_empty_name_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/projects", json={"name": ""})

        assert resp.status_code == 422


class TestUpdateProject:
    """PUT /api/v1/projects/{project_id}"""

    async def test_update_project(self, client: AsyncClient) -> None:
        updated = ProjectResponse(
            id="proj_1",
            user_id=USER_ID,
            name="Renamed",
            color="#ff0000",
            created_at=NOW,
            updated_at=NOW,
        )
        with patch(
            f"{MODULE}.ProjectService.update_project",
            new_callable=AsyncMock,
            return_value=updated,
        ) as update_project:
            resp = await client.put(
                "/api/v1/projects/proj_1", json={"name": "Renamed", "color": "#ff0000"}
            )

        assert resp.status_code == 200
        assert resp.json() == updated.model_dump(mode="json")
        update_project.assert_awaited_once()
        assert update_project.await_args.args[0] == "proj_1"
        assert update_project.await_args.args[1].name == "Renamed"
        assert update_project.await_args.args[1].color == "#ff0000"
        assert update_project.await_args.args[2] == USER_ID
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "update_project", "project_id": "proj_1"},
        )

    async def test_update_inbox_returns_400(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.update_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot update default Inbox project"),
        ):
            resp = await client.put("/api/v1/projects/inbox", json={"name": "X"})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot update default Inbox project"

    async def test_update_missing_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.update_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Project not found"),
        ):
            resp = await client.put("/api/v1/projects/missing", json={"name": "X"})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"

    async def test_update_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.update_project",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.put("/api/v1/projects/proj_1", json={"name": "X"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to update project"


class TestDeleteProject:
    """DELETE /api/v1/projects/{project_id}"""

    async def test_delete_project_returns_204(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.delete_project",
            new_callable=AsyncMock,
        ) as delete_project:
            resp = await client.delete("/api/v1/projects/proj_1")

        assert resp.status_code == 204
        assert resp.content == b""
        delete_project.assert_awaited_once_with("proj_1", USER_ID)
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID},
            todo={"operation": "delete_project", "project_id": "proj_1"},
        )

    async def test_delete_inbox_returns_400(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.delete_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Cannot delete default Inbox project"),
        ):
            resp = await client.delete("/api/v1/projects/inbox")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot delete default Inbox project"

    async def test_delete_missing_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.delete_project",
            new_callable=AsyncMock,
            side_effect=ValueError("Project not found"),
        ):
            resp = await client.delete("/api/v1/projects/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"

    async def test_delete_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.ProjectService.delete_project",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.delete("/api/v1/projects/proj_1")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to delete project"


class TestCreateSubtask:
    """POST /api/v1/todos/{todo_id}/subtasks"""

    async def test_create_subtask_appends(self, client: AsyncClient) -> None:
        doc = _todo_document(
            subtasks=[SubTask(id="st_1", title="Sub task", completed=False, created_at=NOW)]
        )
        with patch(
            f"{MODULE}.todo_repository.add_subtask",
            new_callable=AsyncMock,
            return_value=doc,
        ) as add_subtask:
            resp = await client.post(f"{API}/todo_1/subtasks", json={"title": "Sub task"})

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "todo_1"
        assert body["title"] == "Buy milk"
        assert body["subtasks"][0]["id"] == "st_1"
        assert body["subtasks"][0]["title"] == "Sub task"
        assert body["subtasks"][0]["completed"] is False
        add_subtask.assert_awaited_once()
        assert add_subtask.await_args.args[0] == "todo_1"
        assert add_subtask.await_args.kwargs["user_id"] == USER_ID
        subtask = add_subtask.await_args.kwargs["subtask"]
        assert isinstance(subtask, SubTask)
        assert subtask.title == "Sub task"
        assert subtask.completed is False
        # A real uuid4 string (36 chars), not a collapsed literal.
        assert len(subtask.id) == 36
        assert subtask.id.count("-") == 4
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "create_subtask", "id": "todo_1"}
        )

    async def test_create_subtask_missing_todo_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.add_subtask",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(f"{API}/missing/subtasks", json={"title": "Sub"})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo missing not found"

    async def test_create_subtask_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.add_subtask",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(f"{API}/todo_1/subtasks", json={"title": "Sub"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to create subtask"

    async def test_create_subtask_missing_title_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/todo_1/subtasks", json={})

        assert resp.status_code == 422


class TestUpdateSubtask:
    """PUT /api/v1/todos/{todo_id}/subtasks/{subtask_id}"""

    async def test_update_subtask_fields(self, client: AsyncClient) -> None:
        doc = _todo_document(
            subtasks=[SubTask(id="st_1", title="Renamed", completed=True, created_at=NOW)]
        )
        with patch(
            f"{MODULE}.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            return_value=doc,
        ) as set_subtask_fields:
            resp = await client.put(
                f"{API}/todo_1/subtasks/st_1", json={"title": "Renamed", "completed": True}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["subtasks"][0]["id"] == "st_1"
        assert body["subtasks"][0]["title"] == "Renamed"
        assert body["subtasks"][0]["completed"] is True
        set_subtask_fields.assert_awaited_once_with(
            "todo_1",
            user_id=USER_ID,
            subtask_id="st_1",
            title="Renamed",
            completed=True,
        )
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "update_subtask", "id": "todo_1"}
        )

    async def test_update_subtask_missing_subtask_returns_404(self, client: AsyncClient) -> None:
        # The repository "succeeds" but no subtask matched → endpoint must 404.
        doc = _todo_document(subtasks=[SubTask(id="other", title="Other", created_at=NOW)])
        with patch(
            f"{MODULE}.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            return_value=doc,
        ):
            resp = await client.put(
                f"{API}/todo_1/subtasks/st_1", json={"title": "Renamed"}
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Subtask not found"

    async def test_update_subtask_missing_todo_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.put(
                f"{API}/missing/subtasks/st_1", json={"title": "Renamed"}
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo missing not found"

    async def test_update_subtask_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.set_subtask_fields",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.put(
                f"{API}/todo_1/subtasks/st_1", json={"title": "Renamed"}
            )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to update subtask"


class TestDeleteSubtask:
    """DELETE /api/v1/todos/{todo_id}/subtasks/{subtask_id}"""

    async def test_delete_subtask(self, client: AsyncClient) -> None:
        doc = _todo_document(subtasks=[])
        with patch(
            f"{MODULE}.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            return_value=doc,
        ) as remove_subtask:
            resp = await client.delete(f"{API}/todo_1/subtasks/st_1")

        assert resp.status_code == 200
        assert resp.json()["subtasks"] == []
        remove_subtask.assert_awaited_once_with(
            "todo_1", user_id=USER_ID, subtask_id="st_1"
        )
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "delete_subtask", "id": "todo_1"}
        )

    async def test_delete_subtask_still_present_returns_404(self, client: AsyncClient) -> None:
        # The repository "succeeds" but the subtask remains → endpoint must 404.
        doc = _todo_document(
            subtasks=[SubTask(id="st_1", title="Still here", created_at=NOW)]
        )
        with patch(
            f"{MODULE}.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            return_value=doc,
        ):
            resp = await client.delete(f"{API}/todo_1/subtasks/st_1")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Subtask not found"

    async def test_delete_subtask_missing_todo_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.delete(f"{API}/missing/subtasks/st_1")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo missing not found"

    async def test_delete_subtask_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.remove_subtask",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.delete(f"{API}/todo_1/subtasks/st_1")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to delete subtask"


class TestToggleSubtaskCompletion:
    """POST /api/v1/todos/{todo_id}/subtasks/{subtask_id}/toggle"""

    async def test_toggle_marks_completed(self, client: AsyncClient) -> None:
        todo = _todo_document(
            subtasks=[SubTask(id="st_1", title="Sub", completed=False, created_at=NOW)]
        )
        updated = _todo_document(
            subtasks=[SubTask(id="st_1", title="Sub", completed=True, created_at=NOW)]
        )
        with (
            patch(
                f"{MODULE}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=todo,
            ) as repo_get,
            patch(
                f"{MODULE}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=updated,
            ) as set_subtask_fields,
        ):
            resp = await client.post(f"{API}/todo_1/subtasks/st_1/toggle")

        assert resp.status_code == 200
        assert resp.json()["subtasks"][0]["completed"] is True
        repo_get.assert_awaited_once_with("todo_1", user_id=USER_ID)
        set_subtask_fields.assert_awaited_once_with(
            "todo_1",
            user_id=USER_ID,
            subtask_id="st_1",
            completed=True,
        )
        _log_mock.set.assert_called_once_with(
            user={"id": USER_ID}, todo={"operation": "toggle_subtask", "id": "todo_1"}
        )

    async def test_toggle_marks_incomplete(self, client: AsyncClient) -> None:
        todo = _todo_document(
            subtasks=[SubTask(id="st_1", title="Sub", completed=True, created_at=NOW)]
        )
        updated = _todo_document(
            subtasks=[SubTask(id="st_1", title="Sub", completed=False, created_at=NOW)]
        )
        with (
            patch(
                f"{MODULE}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=todo,
            ) as repo_get,
            patch(
                f"{MODULE}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=updated,
            ) as set_subtask_fields,
        ):
            resp = await client.post(f"{API}/todo_1/subtasks/st_1/toggle")

        assert resp.status_code == 200
        assert resp.json()["subtasks"][0]["completed"] is False
        repo_get.assert_awaited_once_with("todo_1", user_id=USER_ID)
        set_subtask_fields.assert_awaited_once_with(
            "todo_1", user_id=USER_ID, subtask_id="st_1", completed=False
        )

    async def test_toggle_missing_todo_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ) as repo_get:
            resp = await client.post(f"{API}/missing/subtasks/st_1/toggle")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo missing not found"
        repo_get.assert_awaited_once_with("missing", user_id=USER_ID)

    async def test_toggle_missing_subtask_returns_404(self, client: AsyncClient) -> None:
        todo = _todo_document(subtasks=[SubTask(id="other", title="Other", created_at=NOW)])
        with patch(
            f"{MODULE}.todo_repository.get",
            new_callable=AsyncMock,
            return_value=todo,
        ) as repo_get:
            resp = await client.post(f"{API}/todo_1/subtasks/st_1/toggle")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Subtask not found"
        repo_get.assert_awaited_once_with("todo_1", user_id=USER_ID)

    async def test_toggle_repository_returns_none_returns_404(self, client: AsyncClient) -> None:
        todo = _todo_document(
            subtasks=[SubTask(id="st_1", title="Sub", completed=False, created_at=NOW)]
        )
        with (
            patch(
                f"{MODULE}.todo_repository.get",
                new_callable=AsyncMock,
                return_value=todo,
            ) as repo_get,
            patch(
                f"{MODULE}.todo_repository.set_subtask_fields",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.post(f"{API}/todo_1/subtasks/st_1/toggle")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Todo todo_1 not found"
        repo_get.assert_awaited_once_with("todo_1", user_id=USER_ID)

    async def test_toggle_failure_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.todo_repository.get",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(f"{API}/todo_1/subtasks/st_1/toggle")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to toggle subtask"
