"""Unit tests for the todo service layer.

Persistence and caching now live in the todos/projects repositories (exercised
by the contract suite in ``tests/contracts``). These tests mock the repository
singletons and verify the *service orchestration*: inbox assignment, workflow
queueing, search indexing, tracked-todo completion routing, response mapping,
and the ProjectService guards.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.todo_models import (
    BulkMoveRequest,
    BulkUpdateRequest,
    Priority,
    ProjectCreate,
    ProjectDocument,
    ProjectWithCount,
    SearchMode,
    TodoDocument,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoStats,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.todos.todo_bulk_service import (
    bulk_complete_todos,
    bulk_delete_todos as bulk_service_delete_todos,
    bulk_move_todos as bulk_service_move_todos,
)
from app.services.todos.todo_service import (
    ProjectService,
    TodoService,
    _get_workflow_categories_for_todos,
    create_project,
    delete_project,
    get_all_projects,
    get_all_todos,
    get_todo,
    update_project,
)

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_TODO_ID = str(ObjectId())
FAKE_PROJECT_ID = str(ObjectId())
FAKE_INBOX_ID = str(ObjectId())
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _no_analytics():
    """Neutralize analytics captures for tests not asserting on them.

    ``capture_event`` resolves the PostHog provider at call time, which is not
    registered in this test module's import chain — capture-specific tests
    patch the call explicitly and assert on it.
    """
    with (
        patch("app.services.todos.todo_service.capture_event"),
        patch("app.services.todos.todo_bulk_service.capture_event"),
    ):
        yield


def _make_todo_doc(
    *,
    todo_id: str | None = None,
    user_id: str = FAKE_USER_ID,
    title: str = "Test Todo",
    completed: bool = False,
    project_id: str | None = None,
    priority: str = "none",
    labels: list[str] | None = None,
    subtasks: list[dict] | None = None,
    workflow_id: str | None = None,
    vfs_path: str | None = None,
) -> TodoDocument:
    return TodoDocument.model_validate(
        {
            "id": todo_id or str(ObjectId()),
            "user_id": user_id,
            "title": title,
            "description": f"Description for {title}",
            "completed": completed,
            "project_id": project_id or FAKE_PROJECT_ID,
            "priority": priority,
            "labels": labels or [],
            "subtasks": subtasks or [],
            "workflow_id": workflow_id,
            "vfs_path": vfs_path,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


def _make_project_doc(
    project_id: str | None = None,
    user_id: str = FAKE_USER_ID,
    name: str = "My Project",
    is_default: bool = False,
    color: str = "#FF0000",
    todo_count: int | None = None,
) -> ProjectDocument:
    data = {
        "id": project_id or str(ObjectId()),
        "user_id": user_id,
        "name": name,
        "description": f"Description for {name}",
        "color": color,
        "is_default": is_default,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if todo_count is not None:
        return ProjectWithCount.model_validate({**data, "todo_count": todo_count})
    return ProjectDocument.model_validate(data)


@pytest.fixture
def mock_todo_repo():
    with patch("app.services.todos.todo_service.todo_repository") as repo:
        repo.create = AsyncMock()
        repo.get = AsyncMock(return_value=None)
        repo.update = AsyncMock(return_value=None)
        repo.delete = AsyncMock(return_value=True)
        repo.list_page = AsyncMock()
        repo.compute_stats = AsyncMock(return_value=TodoStats())
        repo.count_in_project = AsyncMock(return_value=0)
        repo.find_by_ids = AsyncMock(return_value=[])
        repo.bulk_update = AsyncMock(return_value=0)
        repo.bulk_delete = AsyncMock(return_value=0)
        repo.move_todos_to_project = AsyncMock(return_value=0)
        yield repo


@pytest.fixture
def mock_project_repo():
    with patch("app.services.todos.todo_service.project_repository") as repo:
        inbox = _make_project_doc(project_id=FAKE_INBOX_ID, name="Inbox", is_default=True)
        repo.get = AsyncMock(return_value=None)
        repo.get_or_create_inbox = AsyncMock(return_value=inbox)
        repo.get_default_inbox = AsyncMock(return_value=inbox)
        repo.create = AsyncMock()
        repo.update = AsyncMock(return_value=None)
        repo.delete = AsyncMock(return_value=True)
        repo.list_with_counts = AsyncMock(return_value=[])
        yield repo


@pytest.fixture
def mock_workflow_repo():
    """Patch the cross-domain workflow repository read the todo enrichment uses."""
    with patch(
        "app.services.todos.todo_service.workflow_repository.find_by_ids_for_user",
        new_callable=AsyncMock,
        return_value=[],
    ) as m:
        yield m


def _workflow_doc(wf_id: str, categories: list[str]):
    from app.models.workflow_models import (
        TriggerConfig,
        TriggerType,
        WorkflowDocument,
        WorkflowStep,
    )

    return WorkflowDocument(
        id=wf_id,
        user_id=FAKE_USER_ID,
        title="wf",
        prompt="p",
        steps=[
            WorkflowStep(title=f"s{i}", description="d", category=c)
            for i, c in enumerate(categories)
        ],
        trigger_config=TriggerConfig(type=TriggerType.MANUAL),
    )


@pytest.fixture
def mock_vector_utils():
    with (
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.vector_search", new_callable=AsyncMock) as m_vsearch,
        patch(
            "app.services.todos.todo_service.vector_hybrid_search", new_callable=AsyncMock
        ) as m_hybrid,
    ):
        yield {"vector_search": m_vsearch, "hybrid_search": m_hybrid}


@pytest.fixture
def mock_sync():
    with patch("app.services.todos.todo_service.schedule_user_todos_sync"):
        yield


@pytest.fixture
def mock_workflow_queue():
    with patch("app.services.workflow.queue_service.WorkflowQueueService") as mock_cls:
        mock_cls.queue_todo_workflow_generation = AsyncMock()
        yield mock_cls


# ===========================================================================
# _get_workflow_categories_for_todos
# ===========================================================================


class TestGetWorkflowCategories:
    async def test_no_todos_with_workflow_returns_empty(self, mock_workflow_repo):
        todos = [_make_todo_doc(workflow_id=None)]
        result = await _get_workflow_categories_for_todos(todos, FAKE_USER_ID)
        assert result == {}
        mock_workflow_repo.assert_not_awaited()  # no linked workflows → no repo hit

    async def test_returns_categories_for_linked_workflows(self, mock_workflow_repo):
        todo = _make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email", "calendar"])]
        result = await _get_workflow_categories_for_todos([todo], FAKE_USER_ID)
        assert result[FAKE_TODO_ID] == ["email", "calendar"]
        mock_workflow_repo.assert_awaited_once_with(["wf1"], FAKE_USER_ID)

    async def test_categories_limited_to_three(self, mock_workflow_repo):
        todo = _make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["a", "b", "c", "d", "e"])]
        result = await _get_workflow_categories_for_todos([todo], FAKE_USER_ID)
        assert result[FAKE_TODO_ID] == ["a", "b", "c"]

    async def test_dedupes_and_skips_empty_categories(self, mock_workflow_repo):
        todo = _make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        # An empty-string category is filtered; duplicates collapse to one.
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email", "", "email"])]
        result = await _get_workflow_categories_for_todos([todo], FAKE_USER_ID)
        assert result[FAKE_TODO_ID] == ["email"]


# ===========================================================================
# TodoService CRUD
# ===========================================================================


class TestCreateTodo:
    async def test_assigns_inbox_when_no_project(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_todo_repo.create = AsyncMock(return_value=_make_todo_doc(project_id=FAKE_INBOX_ID))
        result = await TodoService.create_todo(TodoModel(title="Buy milk"), FAKE_USER_ID)
        mock_project_repo.get_or_create_inbox.assert_awaited_once_with(FAKE_USER_ID)
        created_doc = mock_todo_repo.create.call_args[0][0]
        assert created_doc.project_id == FAKE_INBOX_ID
        assert isinstance(result, TodoResponse)

    async def test_validates_explicit_project(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.create_todo(
                TodoModel(title="x", project_id=FAKE_PROJECT_ID), FAKE_USER_ID
            )

    async def test_queues_workflow_and_indexes(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        created = _make_todo_doc(project_id=FAKE_INBOX_ID)
        mock_todo_repo.create = AsyncMock(return_value=created)
        await TodoService.create_todo(TodoModel(title="Buy milk"), FAKE_USER_ID)
        # Queued as a fire-and-forget background task, so assert the call, not the await.
        mock_workflow_queue.queue_todo_workflow_generation.assert_called_once()

    async def test_captures_todo_created(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        created = _make_todo_doc(
            project_id=FAKE_INBOX_ID,
            priority="high",
            labels=["home", "errand"],
            subtasks=[{"id": "s1", "title": "sub", "completed": False}],
        )
        mock_todo_repo.create = AsyncMock(return_value=created)
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
            await TodoService.create_todo(
                TodoModel(title="Buy milk", priority=Priority.HIGH), FAKE_USER_ID
            )
        mock_capture.assert_called_once_with(
            FAKE_USER_ID,
            AnalyticsEvents.TODO_CREATED,
            {
                "priority": "high",
                "has_due_date": False,
                "has_description": True,
                "labels_count": 2,
                "subtasks_count": 1,
                # No project on the request — the Inbox default must not read as
                # the user having chosen one.
                "has_project": False,
            },
        )

    async def test_captures_todo_created_with_chosen_project(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID, name="Work")
        )
        mock_todo_repo.create = AsyncMock(return_value=_make_todo_doc(project_id=FAKE_PROJECT_ID))
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
            await TodoService.create_todo(
                TodoModel(title="Buy milk", project_id=FAKE_PROJECT_ID), FAKE_USER_ID
            )
        assert mock_capture.call_args.args[2]["has_project"] is True


class TestGetTodo:
    async def test_not_found_raises(self, mock_todo_repo, mock_project_repo):
        mock_todo_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)

    async def test_returns_response(self, mock_todo_repo, mock_project_repo):
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert isinstance(result, TodoResponse)
        assert result.id == FAKE_TODO_ID

    async def test_enriches_workflow_categories(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        mock_todo_repo.get = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        )
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email"])]
        result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert result.workflow_categories == ["email"]


class TestListTodos:
    async def test_delegates_to_list_page(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        from app.models.todo_models import TodoPage

        mock_todo_repo.list_page = AsyncMock(
            return_value=TodoPage(items=[_make_todo_doc(), _make_todo_doc()], total=2)
        )
        params = TodoSearchParams(mode=SearchMode.TEXT, page=1, per_page=50)
        result = await TodoService.list_todos(FAKE_USER_ID, params)
        assert result.meta.total == 2
        assert len(result.data) == 2

    async def test_semantic_route_uses_vector_search(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils
    ):
        mock_vector_utils["vector_search"].return_value = []
        params = TodoSearchParams(q="find", mode=SearchMode.SEMANTIC, page=1, per_page=50)
        await TodoService.list_todos(FAKE_USER_ID, params)
        mock_vector_utils["vector_search"].assert_awaited_once()
        mock_todo_repo.list_page.assert_not_called()


class TestUpdateTodo:
    async def test_not_found_raises(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.update = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(title="new"), FAKE_USER_ID
            )

    async def test_updates_and_returns(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.update = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, title="new")
        )
        result = await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(title="new"), FAKE_USER_ID
        )
        assert result.title == "new"
        update = mock_todo_repo.update.call_args.kwargs["update"]
        assert update.title == "new"

    async def test_captures_todo_updated(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.update = AsyncMock(
            return_value=_make_todo_doc(
                todo_id=FAKE_TODO_ID,
                title="new",
                priority="high",
                subtasks=[{"id": "s1", "title": "sub", "completed": False}],
            )
        )
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(title="new"), FAKE_USER_ID
            )
        mock_capture.assert_called_once_with(
            FAKE_USER_ID,
            AnalyticsEvents.TODO_UPDATED,
            {
                "changed_field_count": 1,
                "changed_fields": ["title"],
                "todo_id": FAKE_TODO_ID,
                "priority": "high",
                "has_due_date": False,
                "has_subtasks": True,
            },
        )

    async def test_captures_completed_toggle(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.update = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, completed=True, priority="medium")
        )
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=True), FAKE_USER_ID
            )
        mock_capture.assert_called_once_with(
            FAKE_USER_ID,
            AnalyticsEvents.TODO_TOGGLED,
            {
                "completed": True,
                "todo_id": FAKE_TODO_ID,
                "priority": "medium",
                "has_due_date": False,
            },
        )

    async def test_completing_tracked_routes_through_service(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        tracked = _make_todo_doc(todo_id=FAKE_TODO_ID, vfs_path="/users/u/todos/t")
        mock_todo_repo.get = AsyncMock(return_value=tracked)
        mock_todo_repo.update = AsyncMock(return_value=tracked)
        with patch("app.services.tracked_todo_service.tracked_todo_service") as mock_tracked:
            mock_tracked.complete_tracked_todo = AsyncMock(return_value=True)
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=True), FAKE_USER_ID
            )
            mock_tracked.complete_tracked_todo.assert_awaited_once()


class TestDeleteTodo:
    async def test_not_found_raises(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)

    async def test_deletes(self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync):
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        mock_todo_repo.delete = AsyncMock(return_value=True)
        await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)
        mock_todo_repo.delete.assert_awaited_once_with(FAKE_TODO_ID, user_id=FAKE_USER_ID)

    async def test_captures_todo_deleted(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        mock_todo_repo.delete = AsyncMock(return_value=True)
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
            await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)
        mock_capture.assert_called_once_with(
            FAKE_USER_ID, AnalyticsEvents.TODO_DELETED, {"todo_id": FAKE_TODO_ID}
        )

    async def test_a_subscribed_todo_unregisters_before_the_document_goes(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """Once the document is deleted nothing names its Composio trigger, so a
        teardown that ran after the delete — or not at all — leaks it forever."""
        doc = _make_todo_doc(todo_id=FAKE_TODO_ID)
        doc.trigger_subscriptions = [
            TriggerSubscription(
                trigger_name="gmail_new_message",
                action=SubscriptionAction.EXECUTE,
                resolution=SubscriptionResolution.ACCOUNT,
            )
        ]
        mock_todo_repo.get = AsyncMock(return_value=doc)
        order: list[str] = []

        async def _teardown(*_args: object, **_kwargs: object) -> int:
            order.append("teardown")
            return 1

        async def _delete(*_args: object, **_kwargs: object) -> bool:
            order.append("delete")
            return True

        mock_todo_repo.delete = AsyncMock(side_effect=_delete)
        teardown = AsyncMock(side_effect=_teardown)
        with patch("app.services.todos.todo_service.teardown_subscriptions", teardown):
            await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)

        assert order == ["teardown", "delete"]
        # The teardown must name this doc's own id/user and the delete reason —
        # a wrong id or reason unregisters nothing and leaks the trigger.
        teardown.assert_awaited_once_with(FAKE_TODO_ID, FAKE_USER_ID, reason="deleted")

    async def test_an_unsubscribed_todo_skips_teardown(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        mock_todo_repo.delete = AsyncMock(return_value=True)
        teardown = AsyncMock()
        with patch("app.services.todos.todo_service.teardown_subscriptions", teardown):
            await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)

        teardown.assert_not_awaited()


class TestBulkOps:
    async def test_bulk_update_delegates(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.bulk_update = AsyncMock(return_value=2)
        req = BulkUpdateRequest(todo_ids=["a", "b"], updates=TodoUpdateRequest(completed=True))
        result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert result.total == 2
        mock_todo_repo.bulk_update.assert_awaited_once()

    async def test_bulk_update_no_fields_is_noop(self, mock_todo_repo, mock_project_repo):
        req = BulkUpdateRequest(todo_ids=["a"], updates=TodoUpdateRequest())
        result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert "No updates" in result.message
        mock_todo_repo.bulk_update.assert_not_called()

    async def test_bulk_delete_delegates(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.bulk_delete = AsyncMock(return_value=2)
        result = await TodoService.bulk_delete_todos(["a", "b"], FAKE_USER_ID)
        assert result.total == 2

    async def test_bulk_delete_captures_count(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.bulk_delete = AsyncMock(return_value=2)
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
            await TodoService.bulk_delete_todos(["a", "b"], FAKE_USER_ID)
        mock_capture.assert_called_once_with(
            FAKE_USER_ID, AnalyticsEvents.TODO_DELETED, {"count": 2}
        )

    async def test_bulk_move_validates_project(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.bulk_move_todos(
                BulkMoveRequest(todo_ids=["a"], project_id=FAKE_PROJECT_ID), FAKE_USER_ID
            )

    async def test_bulk_move_delegates(self, mock_todo_repo, mock_project_repo, mock_sync):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID)
        )
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        result = await TodoService.bulk_move_todos(
            BulkMoveRequest(todo_ids=["a"], project_id=FAKE_PROJECT_ID), FAKE_USER_ID
        )
        assert "Moved 1" in result.message


# ===========================================================================
# ProjectService
# ===========================================================================


class TestProjectService:
    async def test_create_returns_response_with_count(self, mock_todo_repo, mock_project_repo):
        created = _make_project_doc(project_id=FAKE_PROJECT_ID, name="Work")
        mock_project_repo.create = AsyncMock(return_value=created)
        mock_todo_repo.count_in_project = AsyncMock(return_value=3)
        result = await ProjectService.create_project(ProjectCreate(name="Work"), FAKE_USER_ID)
        assert result.name == "Work"
        assert result.todo_count == 3

    async def test_list_maps_counts(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.list_with_counts = AsyncMock(
            return_value=[_make_project_doc(name="A", todo_count=5)]
        )
        result = await ProjectService.list_projects(FAKE_USER_ID)
        assert result[0].todo_count == 5

    async def test_update_default_inbox_rejected(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_INBOX_ID, is_default=True)
        )
        with pytest.raises(ValueError, match="Cannot update"):
            await ProjectService.update_project(
                FAKE_INBOX_ID, UpdateProjectRequest(name="x"), FAKE_USER_ID
            )

    async def test_update_not_found(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await ProjectService.update_project(
                FAKE_PROJECT_ID, UpdateProjectRequest(name="x"), FAKE_USER_ID
            )

    async def test_update_delegates(self, mock_todo_repo, mock_project_repo):
        existing = _make_project_doc(project_id=FAKE_PROJECT_ID, name="Old")
        mock_project_repo.get = AsyncMock(return_value=existing)
        mock_project_repo.update = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID, name="New")
        )
        result = await ProjectService.update_project(
            FAKE_PROJECT_ID, UpdateProjectRequest(name="New"), FAKE_USER_ID
        )
        assert result.name == "New"

    async def test_delete_default_inbox_rejected(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_INBOX_ID, is_default=True)
        )
        with pytest.raises(ValueError, match="Cannot delete"):
            await ProjectService.delete_project(FAKE_INBOX_ID, FAKE_USER_ID)

    async def test_delete_moves_todos_to_inbox(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID)
        )
        await ProjectService.delete_project(FAKE_PROJECT_ID, FAKE_USER_ID)
        mock_todo_repo.move_todos_to_project.assert_awaited_once_with(
            FAKE_USER_ID, FAKE_PROJECT_ID, FAKE_INBOX_ID
        )
        mock_project_repo.delete.assert_awaited_once_with(FAKE_PROJECT_ID, user_id=FAKE_USER_ID)


# ===========================================================================
# Compatibility wrappers
# ===========================================================================


class TestCompatibilityWrappers:
    async def test_get_todo_wrapper(self, mock_todo_repo, mock_project_repo):
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        result = await get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert result.id == FAKE_TODO_ID

    async def test_get_all_projects_wrapper(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.list_with_counts = AsyncMock(
            return_value=[_make_project_doc(name="A", todo_count=1)]
        )
        result = await get_all_projects(FAKE_USER_ID)
        assert result[0].name == "A"

    async def test_create_project_wrapper(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.create = AsyncMock(return_value=_make_project_doc(name="Work"))
        result = await create_project(ProjectCreate(name="Work"), FAKE_USER_ID)
        assert result.name == "Work"

    async def test_update_project_wrapper(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID)
        )
        mock_project_repo.update = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID, name="New")
        )
        result = await update_project(
            FAKE_PROJECT_ID, UpdateProjectRequest(name="New"), FAKE_USER_ID
        )
        assert result.name == "New"

    async def test_delete_project_wrapper(self, mock_todo_repo, mock_project_repo):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID)
        )
        await delete_project(FAKE_PROJECT_ID, FAKE_USER_ID)
        mock_project_repo.delete.assert_awaited_once()

    async def test_get_all_todos_wrapper(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        from app.models.todo_models import TodoPage

        mock_todo_repo.list_page = AsyncMock(
            return_value=TodoPage(items=[_make_todo_doc()], total=1)
        )
        result = await get_all_todos(FAKE_USER_ID)
        assert len(result) == 1


# ===========================================================================
# todo_bulk_service
# ===========================================================================


@pytest.fixture
def mock_bulk_repos():
    with (
        patch("app.services.todos.todo_bulk_service.todo_repository") as todo_repo,
        patch("app.services.todos.todo_bulk_service.project_repository") as project_repo,
        patch(
            "app.services.todos.todo_bulk_service.delete_canvas_embedding", new_callable=AsyncMock
        ),
    ):
        todo_repo.find_by_ids = AsyncMock(return_value=[])
        todo_repo.bulk_update = AsyncMock(return_value=0)
        todo_repo.bulk_delete = AsyncMock(return_value=0)
        project_repo.get = AsyncMock(return_value=None)
        yield todo_repo, project_repo


class TestBulkServiceComplete:
    async def test_completes_plain_todos(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        ids = ["a", "b"]
        todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a"), _make_todo_doc(todo_id="b")]
        )
        todo_repo.bulk_update = AsyncMock(return_value=2)
        result = await bulk_complete_todos(ids, FAKE_USER_ID)
        assert len(result) == 2

    async def test_captures_completed_count(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a"), _make_todo_doc(todo_id="b")]
        )
        todo_repo.bulk_update = AsyncMock(return_value=2)
        with patch("app.services.todos.todo_bulk_service.capture_event") as mock_capture:
            await bulk_complete_todos(["a", "b"], FAKE_USER_ID)
        mock_capture.assert_called_once_with(
            FAKE_USER_ID, AnalyticsEvents.TODO_TOGGLED, {"count": 2}
        )

    async def test_captures_completed_count_with_tracked_todos(self, mock_bulk_repos):
        """Tracked todos count through their completion lifecycle — the
        reported count is modified + tracked, not a plain update count."""
        todo_repo, _ = mock_bulk_repos
        todo_repo.find_by_ids = AsyncMock(
            return_value=[
                _make_todo_doc(todo_id="a"),
                _make_todo_doc(todo_id="b", vfs_path="file:///x"),
            ]
        )
        todo_repo.bulk_update = AsyncMock(return_value=1)
        with (
            patch("app.services.todos.todo_bulk_service.capture_event") as mock_capture,
            patch(
                "app.services.todos.todo_bulk_service.tracked_todo_service.complete_tracked_todo",
                new_callable=AsyncMock,
            ) as mock_tracked,
        ):
            await bulk_complete_todos(["a", "b"], FAKE_USER_ID)
        mock_tracked.assert_awaited_once_with("b", FAKE_USER_ID, "Completed via bulk operation")
        mock_capture.assert_called_once_with(
            FAKE_USER_ID, AnalyticsEvents.TODO_TOGGLED, {"count": 2}
        )

    async def test_no_todos_raises_404(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        todo_repo.find_by_ids = AsyncMock(return_value=[])
        with pytest.raises(HTTPException) as exc:
            await bulk_complete_todos(["a"], FAKE_USER_ID)
        assert exc.value.status_code == 404


class TestBulkServiceMove:
    async def test_missing_project_raises_404(self, mock_bulk_repos):
        _, project_repo = mock_bulk_repos
        project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await bulk_service_move_todos(["a"], FAKE_PROJECT_ID, FAKE_USER_ID)
        assert exc.value.status_code == 404

    async def test_moves(self, mock_bulk_repos):
        todo_repo, project_repo = mock_bulk_repos
        project_repo.get = AsyncMock(return_value=_make_project_doc(project_id=FAKE_PROJECT_ID))
        todo_repo.bulk_update = AsyncMock(return_value=1)
        todo_repo.find_by_ids = AsyncMock(return_value=[_make_todo_doc(todo_id="a")])
        result = await bulk_service_move_todos(["a"], FAKE_PROJECT_ID, FAKE_USER_ID)
        assert len(result) == 1


class TestBulkServiceDelete:
    async def test_deletes(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        todo_repo.find_by_ids = AsyncMock(return_value=[_make_todo_doc(todo_id="a")])
        todo_repo.bulk_delete = AsyncMock(return_value=1)
        await bulk_service_delete_todos(["a"], FAKE_USER_ID)
        todo_repo.bulk_delete.assert_awaited_once()

    async def test_captures_deleted_count(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a"), _make_todo_doc(todo_id="b")]
        )
        todo_repo.bulk_delete = AsyncMock(return_value=2)
        with patch("app.services.todos.todo_bulk_service.capture_event") as mock_capture:
            await bulk_service_delete_todos(["a", "b"], FAKE_USER_ID)
        mock_capture.assert_called_once_with(
            FAKE_USER_ID, AnalyticsEvents.TODO_DELETED, {"count": 2}
        )

    async def test_no_todos_raises_404(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        todo_repo.find_by_ids = AsyncMock(return_value=[])
        todo_repo.bulk_delete = AsyncMock(return_value=0)
        with pytest.raises(HTTPException) as exc:
            await bulk_service_delete_todos(["a"], FAKE_USER_ID)
        assert exc.value.status_code == 404

    async def test_subscribed_todo_tears_down_before_delete(self, mock_bulk_repos):
        """A subscribed todo must unregister its Composio trigger with the
        deleted-doc's own id/user and the bulk-delete reason — once the document
        is gone nothing names the trigger, so a wrong id or reason leaks it."""
        todo_repo, _ = mock_bulk_repos
        subscribed = _make_todo_doc(todo_id="a")
        subscribed.trigger_subscriptions = [
            TriggerSubscription(
                trigger_name="gmail_new_message",
                action=SubscriptionAction.EXECUTE,
                resolution=SubscriptionResolution.ACCOUNT,
            )
        ]
        plain = _make_todo_doc(todo_id="b")
        todo_repo.find_by_ids = AsyncMock(return_value=[subscribed, plain])
        todo_repo.bulk_delete = AsyncMock(return_value=2)
        teardown = AsyncMock(return_value=1)
        with patch("app.services.todos.todo_bulk_service.teardown_subscriptions", teardown):
            await bulk_service_delete_todos(["a", "b"], FAKE_USER_ID)
        # Only the subscribed doc tears down, and with its exact id/user/reason.
        teardown.assert_awaited_once_with("a", FAKE_USER_ID, reason="bulk_deleted")
