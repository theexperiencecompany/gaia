"""Unit tests for the todo service layer.

Persistence and caching now live in the todos/projects repositories (exercised
by the contract suite in tests/contracts). These tests mock the repository
singletons and verify the *service orchestration*: inbox assignment, workflow
queueing, search indexing, tracked-todo completion routing, response mapping,
and the ProjectService guards.
"""

from collections.abc import Coroutine
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError
from pymongo.errors import BulkWriteError, DuplicateKeyError
import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.constants.vfs import SYSTEM_USER_ID
from app.models.todo_models import (
    BulkMoveRequest,
    BulkUpdateRequest,
    ExternalRef,
    ExternalRefSource,
    PendingApprovalRef,
    Priority,
    ProjectCreate,
    ProjectDocument,
    ProjectWithCount,
    SearchMode,
    TodoDocument,
    TodoModel,
    TodoPage,
    TodoResponse,
    TodoSearchParams,
    TodoStats,
    TodoUpdate,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.todos.errors import (
    ExternalRefReopenedTwiceError,
    ExternalRefTakenError,
    SubTodoParentError,
    TrackedLabelChangeError,
    TrackedTodoWorkflowError,
)
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
from app.services.triggers.subscription_service import SubscriptionError
from app.utils import auth_utils
from app.utils.errors import AppError
from app.utils.todo_vector_utils import TodoSearchFilters
from tests.helpers import UNKNOWN_USER_ID, captured_wide_event, users_get

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_TODO_ID = str(ObjectId())
FAKE_PROJECT_ID = str(ObjectId())
FAKE_INBOX_ID = str(ObjectId())
NOW = datetime.now(UTC)
_PARENT = str(ObjectId())
_CHILD = str(ObjectId())


@pytest.fixture(autouse=True)
def _no_analytics():
    """Neutralize analytics captures for tests not asserting on them.

    capture_event resolves the PostHog provider at call time, which is not
    registered in this test module's import chain — capture-specific tests
    patch the call explicitly and assert on it.
    """
    with (
        patch("app.services.todos.todo_service.capture_event"),
        patch("app.services.todos.todo_bulk_service.capture_event"),
    ):
        yield


@pytest.fixture(autouse=True)
def _owners_are_users():
    """Answer the owner check the way the real users collection does."""
    with patch("app.utils.auth_utils.user_repository.get", new=users_get):
        yield


@pytest.fixture(autouse=True)
def _no_pending_approvals():
    """Neutralize the cross-domain ledger read; no live approvals by default."""
    with patch(
        "app.services.todos.todo_service.approval_ledger_repository.list_live_by_owners",
        new=AsyncMock(return_value=[]),
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
    parent_todo_id: str | None = None,
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
            "parent_todo_id": parent_todo_id,
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
        repo.link_workflow = AsyncMock(return_value=None)
        repo.delete = AsyncMock(return_value=True)
        repo.list_page = AsyncMock()
        repo.compute_stats = AsyncMock(return_value=TodoStats())
        repo.count_in_project = AsyncMock(return_value=0)
        repo.find_by_ids = AsyncMock(return_value=[])
        repo.bulk_update = AsyncMock(return_value=0)
        repo.bulk_delete = AsyncMock(return_value=0)
        repo.move_todos_to_project = AsyncMock(return_value=0)
        repo.find_sub_todos = AsyncMock(return_value=[])
        repo.count_open_sub_todos = AsyncMock(return_value={})
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
        patch(
            "app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock
        ) as m_store,
        patch(
            "app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock
        ) as m_update,
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.vector_search", new_callable=AsyncMock) as m_vsearch,
        patch(
            "app.services.todos.todo_service.vector_hybrid_search", new_callable=AsyncMock
        ) as m_hybrid,
    ):
        yield {
            "vector_search": m_vsearch,
            "hybrid_search": m_hybrid,
            "store_embedding": m_store,
            "update_embedding": m_update,
        }


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
        assert result.sub_todo_count == 0

    @pytest.mark.regression
    @pytest.mark.parametrize("owner", [SYSTEM_USER_ID, UNKNOWN_USER_ID])
    async def test_an_owner_that_is_not_a_user_is_refused_before_the_write(
        self, owner, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """Regression: create_todo saved whatever owner it was handed, "system" included."""
        with pytest.raises(auth_utils.OwnerNotFoundError):
            await TodoService.create_todo(TodoModel(title="Buy milk"), owner)

        mock_todo_repo.create.assert_not_awaited()

    async def test_validates_explicit_project(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.create_todo(
                TodoModel(title="x", project_id=FAKE_PROJECT_ID), FAKE_USER_ID
            )

    async def test_create_todo_indexes_and_never_generates_a_workflow(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        """create_todo is the path tracked todos take, so generation must not live in it."""
        created = _make_todo_doc(project_id=FAKE_INBOX_ID)
        mock_todo_repo.create = AsyncMock(return_value=created)
        await TodoService.create_todo(TodoModel(title="Buy milk"), FAKE_USER_ID)
        mock_workflow_queue.queue_todo_workflow_generation.assert_not_called()
        mock_vector_utils["store_embedding"].assert_awaited_once_with(
            created.id, created, FAKE_USER_ID
        )

    async def test_create_todo_with_workflow_queues_generation(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        created = _make_todo_doc(todo_id=FAKE_TODO_ID, project_id=FAKE_INBOX_ID)
        mock_todo_repo.create = AsyncMock(return_value=created)
        result = await TodoService.create_todo_with_workflow(
            TodoModel(title="Buy milk", description="2%"), FAKE_USER_ID
        )
        # Queued as a fire-and-forget background task, so assert the call, not the await.
        mock_workflow_queue.queue_todo_workflow_generation.assert_called_once_with(
            todo_id=FAKE_TODO_ID, user_id=FAKE_USER_ID, title="Buy milk", description="2%"
        )
        assert result.id == FAKE_TODO_ID

    async def test_create_todo_with_workflow_spawns_a_named_task_scoped_to_the_todo(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_todo_repo.create = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, project_id=FAKE_INBOX_ID)
        )
        with patch("app.services.todos.todo_service.spawn_logged_task") as spawn:
            await TodoService.create_todo_with_workflow(TodoModel(title="Buy milk"), FAKE_USER_ID)

        spawn.assert_called_once()
        assert spawn.call_args.args[0] == "todo_workflow_generation"
        assert spawn.call_args.kwargs == {
            "user": {"id": FAKE_USER_ID},
            "todo": {"id": FAKE_TODO_ID},
        }
        mock_workflow_queue.queue_todo_workflow_generation.assert_called_once_with(
            todo_id=FAKE_TODO_ID, user_id=FAKE_USER_ID, title="Buy milk", description=""
        )
        spawn.call_args.args[1].close()

    async def test_a_failed_generation_queue_still_returns_the_created_todo(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_todo_repo.create = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, project_id=FAKE_INBOX_ID)
        )

        def refuse_to_spawn(_operation: str, coro: Coroutine[Any, Any, Any], **_: Any) -> None:
            coro.close()
            raise RuntimeError("loop closed")

        with (
            patch(
                "app.services.todos.todo_service.spawn_logged_task",
                side_effect=refuse_to_spawn,
            ),
            patch("app.services.todos.todo_service.log") as log,
        ):
            result = await TodoService.create_todo_with_workflow(
                TodoModel(title="Buy milk"), FAKE_USER_ID
            )

        assert result.id == FAKE_TODO_ID
        log.warning.assert_called_once_with(
            "todo.workflow_queue_failed", title="Buy milk", error="loop closed"
        )

    async def test_create_todo_with_workflow_refuses_a_tracked_todo(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        with pytest.raises(TrackedTodoWorkflowError):
            await TodoService.create_todo_with_workflow(
                TodoModel(title="Nightly", labels=[GAIA_TRACKED_LABEL]), FAKE_USER_ID
            )
        mock_todo_repo.create.assert_not_awaited()
        mock_workflow_queue.queue_todo_workflow_generation.assert_not_called()

    async def test_a_classic_todo_can_be_created_already_linked(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        mock_todo_repo.create = AsyncMock(return_value=_make_todo_doc(project_id=FAKE_INBOX_ID))
        await TodoService.create_todo(TodoModel(title="Buy milk", workflow_id="wf1"), FAKE_USER_ID)
        assert mock_todo_repo.create.await_args.args[0].workflow_id == "wf1"

    async def test_a_tracked_todo_cannot_be_created_with_a_workflow(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_queue
    ):
        with pytest.raises(TrackedTodoWorkflowError):
            await TodoService.create_todo(
                TodoModel(title="Nightly", labels=[GAIA_TRACKED_LABEL], workflow_id="wf1"),
                FAKE_USER_ID,
            )
        mock_todo_repo.create.assert_not_awaited()

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
                "is_sub_todo": False,
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


_THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="thread-1")
_REGISTER = "app.services.todos.external_ref_watch.register_subscription"
_UNREGISTER = "app.services.todos.external_ref_watch.unregister_subscription"
_ON_THREAD = SubscriptionCondition(
    field_name="thread_id", operator=ConditionOperator.EQUALS, value=_THREAD.id
)


async def _registered(
    *, trigger_name: str, conditions: list[SubscriptionCondition], **_: object
) -> tuple[TriggerSubscription, None, bool]:
    """Stand in for register_subscription: the stored watch, with no repairs to report."""
    return (
        TriggerSubscription(
            trigger_name=trigger_name,
            conditions=conditions,
            action=SubscriptionAction.EXECUTE,
            resolution=SubscriptionResolution.ACCOUNT,
        ),
        None,
        True,
    )


def _completed_thread_todo(
    todo_id: str = FAKE_TODO_ID, watching: tuple[str, ...] = ()
) -> TodoDocument:
    todo = _make_todo_doc(todo_id=todo_id, completed=True)
    # Its own instance, as each document read from Mongo has: equal refs, not one object.
    todo.external_ref = _THREAD.model_copy()
    todo.trigger_subscriptions = [
        TriggerSubscription(
            trigger_name=name,
            conditions=[_ON_THREAD],
            action=SubscriptionAction.EXECUTE,
            resolution=SubscriptionResolution.ACCOUNT,
        )
        for name in watching
    ]
    return todo


class TestCreateTodoWithExternalRef:
    async def test_the_ref_is_written_by_the_insert_itself(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.create = AsyncMock(return_value=_make_todo_doc())
        await TodoService.create_todo(TodoModel(title="Reply"), FAKE_USER_ID, external_ref=_THREAD)
        assert mock_todo_repo.create.await_args.args[0].external_ref == _THREAD

    async def test_a_taken_ref_raises_with_the_open_todo_that_holds_it(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        winner = _make_todo_doc(title="Reply to Sam")
        mock_todo_repo.create = AsyncMock(side_effect=DuplicateKeyError("E11000"))
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=winner)

        with pytest.raises(ExternalRefTakenError) as raised:
            await TodoService.create_todo(
                TodoModel(title="Reply"), FAKE_USER_ID, external_ref=_THREAD
            )

        assert raised.value.existing is winner
        mock_todo_repo.find_open_by_external_ref.assert_awaited_once_with(FAKE_USER_ID, _THREAD)
        mock_vector_utils["store_embedding"].assert_not_awaited()

    async def test_a_duplicate_key_with_no_open_holder_is_not_disguised(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.create = AsyncMock(side_effect=DuplicateKeyError("E11000"))
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        with pytest.raises(DuplicateKeyError):
            await TodoService.create_todo(
                TodoModel(title="Reply"), FAKE_USER_ID, external_ref=_THREAD
            )

    async def test_a_duplicate_key_without_a_ref_propagates(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.create = AsyncMock(side_effect=DuplicateKeyError("E11000"))
        mock_todo_repo.find_open_by_external_ref = AsyncMock()
        with pytest.raises(DuplicateKeyError):
            await TodoService.create_todo(TodoModel(title="Reply"), FAKE_USER_ID)
        mock_todo_repo.find_open_by_external_ref.assert_not_awaited()


class TestCreateSubTodo:
    async def test_the_parent_is_written_by_the_insert_itself(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.create = AsyncMock(return_value=_make_todo_doc(parent_todo_id=_PARENT))

        await TodoService.create_todo(
            TodoModel(title="Reply"), FAKE_USER_ID, parent_todo_id=_PARENT
        )

        assert mock_todo_repo.create.await_args.args[0].parent_todo_id == _PARENT

    def test_a_client_cannot_name_a_parent_on_the_create_request(self):
        """Only the tracked-todo service sets a parent, after validating it."""
        assert "parent_todo_id" not in TodoModel.model_fields

    async def test_the_created_event_says_whether_it_is_a_sub_todo(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.create = AsyncMock(return_value=_make_todo_doc(parent_todo_id=_PARENT))
        with patch("app.services.todos.todo_service.capture_event") as capture:
            await TodoService.create_todo(
                TodoModel(title="Reply"), FAKE_USER_ID, parent_todo_id=_PARENT
            )

        assert capture.call_args.args[2]["is_sub_todo"] is True


class TestSubTodoCounts:
    """A parent row carries its open sub-todo count; the UI shows it as a chip."""

    async def test_each_listed_todo_carries_its_own_count(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        desk = _make_todo_doc(todo_id=_PARENT, vfs_path="/workspace/gaia-tasks/x")
        plain = _make_todo_doc()
        mock_todo_repo.list_page = AsyncMock(return_value=TodoPage(items=[desk, plain], total=2))
        mock_todo_repo.count_open_sub_todos = AsyncMock(return_value={_PARENT: 3})

        result = await TodoService.list_todos(
            FAKE_USER_ID, TodoSearchParams(mode=SearchMode.TEXT, page=1, per_page=50)
        )

        by_id = {item.id: item for item in result.data}
        assert by_id[_PARENT].sub_todo_count == 3
        assert by_id[plain.id].sub_todo_count == 0
        mock_todo_repo.count_open_sub_todos.assert_awaited_once_with(
            FAKE_USER_ID, [_PARENT, plain.id]
        )

    async def test_a_single_todo_carries_its_count_and_its_parent(
        self, mock_todo_repo, mock_project_repo
    ):
        mock_todo_repo.get = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, parent_todo_id=_PARENT)
        )
        mock_todo_repo.count_open_sub_todos = AsyncMock(return_value={FAKE_TODO_ID: 2})

        result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)

        assert result.sub_todo_count == 2
        assert result.parent_todo_id == _PARENT
        mock_todo_repo.count_open_sub_todos.assert_awaited_once_with(FAKE_USER_ID, [FAKE_TODO_ID])

    async def test_listing_one_parents_sub_todos_is_not_scoped_to_the_inbox(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        mock_todo_repo.list_page = AsyncMock(return_value=TodoPage(items=[], total=0))

        await TodoService.list_todos(
            FAKE_USER_ID,
            TodoSearchParams(mode=SearchMode.TEXT, page=1, per_page=50, parent_todo_id=_PARENT),
        )

        assert mock_todo_repo.list_page.await_args.kwargs["inbox_project_id"] is None
        assert mock_todo_repo.list_page.await_args.kwargs["params"].parent_todo_id == _PARENT


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
        assert result.sub_todo_count == 0

    async def test_enriches_workflow_categories(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        mock_todo_repo.get = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        )
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email"])]
        result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert result.workflow_categories == ["email"]
        mock_workflow_repo.assert_awaited_once_with(["wf1"], FAKE_USER_ID)

    async def test_a_workflow_linked_todo_still_carries_its_pending_approval(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        mock_todo_repo.get = AsyncMock(
            return_value=_make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        )
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email"])]
        live_row = SimpleNamespace(
            owner_id=FAKE_TODO_ID, approval_id="ap_1", conversation_id="conv-9"
        )
        with patch(
            "app.services.todos.todo_service.approval_ledger_repository.list_live_by_owners",
            new=AsyncMock(return_value=[live_row]),
        ):
            result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert result.pending_approval == PendingApprovalRef(
            approval_id="ap_1", conversation_id="conv-9"
        )


class TestListTodos:
    async def test_delegates_to_list_page(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        mock_todo_repo.list_page = AsyncMock(
            return_value=TodoPage(items=[_make_todo_doc(), _make_todo_doc()], total=2)
        )
        params = TodoSearchParams(mode=SearchMode.TEXT, page=1, per_page=50)
        result = await TodoService.list_todos(FAKE_USER_ID, params)
        assert result.meta.total == 2
        assert len(result.data) == 2

    async def test_each_listed_todo_carries_its_own_workflow_categories(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        linked = _make_todo_doc(workflow_id="wf1")
        plain = _make_todo_doc()
        mock_todo_repo.list_page = AsyncMock(return_value=TodoPage(items=[linked, plain], total=2))
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email"])]
        params = TodoSearchParams(mode=SearchMode.TEXT, page=1, per_page=50)
        result = await TodoService.list_todos(FAKE_USER_ID, params)
        by_id = {item.id: item for item in result.data}
        assert by_id[linked.id].workflow_categories == ["email"]
        assert by_id[plain.id].workflow_categories == []

    async def test_workflow_enrichment_is_scoped_to_the_requesting_user(
        self, mock_todo_repo, mock_project_repo, mock_workflow_repo
    ):
        linked = _make_todo_doc(workflow_id="wf1")
        mock_todo_repo.list_page = AsyncMock(return_value=TodoPage(items=[linked], total=1))
        mock_workflow_repo.return_value = [_workflow_doc("wf1", ["email"])]
        params = TodoSearchParams(mode=SearchMode.TEXT, page=1, per_page=50)
        await TodoService.list_todos(FAKE_USER_ID, params)
        mock_workflow_repo.assert_awaited_once_with(["wf1"], FAKE_USER_ID)

    async def test_semantic_route_uses_vector_search(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils
    ):
        mock_vector_utils["vector_search"].return_value = []
        params = TodoSearchParams(
            q="find",
            mode=SearchMode.SEMANTIC,
            page=1,
            per_page=50,
            completed=True,
            priority=Priority.HIGH,
            project_id=FAKE_PROJECT_ID,
        )
        await TodoService.list_todos(FAKE_USER_ID, params)
        mock_vector_utils["vector_search"].assert_awaited_once()
        assert mock_vector_utils["vector_search"].await_args.kwargs["user_id"] == FAKE_USER_ID
        mock_todo_repo.list_page.assert_not_called()
        # The request's narrowing reaches the vector search, priority as its stored string.
        assert mock_vector_utils["vector_search"].await_args.kwargs["filters"] == TodoSearchFilters(
            completed=True, priority="high", project_id=FAKE_PROJECT_ID
        )

    @pytest.mark.parametrize("mode", [SearchMode.SEMANTIC, SearchMode.HYBRID])
    async def test_a_search_within_one_parent_matches_its_sub_todos_by_text(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_workflow_repo, mode
    ):
        """The vector top-k cut must not come first: a parent's later-ranked children would be lost."""
        mock_todo_repo.list_page = AsyncMock(return_value=TodoPage(items=[], total=0))
        params = TodoSearchParams(q="reply", mode=mode, page=1, per_page=50, parent_todo_id=_PARENT)

        await TodoService.list_todos(FAKE_USER_ID, params)

        mock_vector_utils["vector_search"].assert_not_awaited()
        mock_vector_utils["hybrid_search"].assert_not_awaited()
        searched = mock_todo_repo.list_page.await_args.kwargs["params"]
        assert (searched.q, searched.mode, searched.parent_todo_id) == (
            "reply",
            SearchMode.TEXT,
            _PARENT,
        )


class TestUpdateTodo:
    async def test_not_found_raises(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.update = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(title="new"), FAKE_USER_ID
            )

    async def test_a_workflow_link_goes_through_link_workflow(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_repo
    ):
        linked = _make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        mock_todo_repo.link_workflow = AsyncMock(return_value=linked)
        mock_todo_repo.get = AsyncMock(return_value=linked)
        result = await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(workflow_id="wf1"), FAKE_USER_ID
        )
        mock_todo_repo.link_workflow.assert_awaited_once_with(
            FAKE_TODO_ID, user_id=FAKE_USER_ID, workflow_id="wf1"
        )
        mock_todo_repo.update.assert_not_awaited()
        assert result.workflow_id == "wf1"
        assert mock_todo_repo.get.await_args == call(FAKE_TODO_ID, user_id=FAKE_USER_ID)

    async def test_an_edited_parent_still_reports_its_open_sub_todos(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        edited = _make_todo_doc(todo_id=FAKE_TODO_ID, title="Inbox desk")
        mock_todo_repo.get = AsyncMock(return_value=edited)
        mock_todo_repo.update = AsyncMock(return_value=edited)
        mock_todo_repo.count_open_sub_todos = AsyncMock(return_value={FAKE_TODO_ID: 2})

        result = await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(title="Inbox desk"), FAKE_USER_ID
        )

        assert result.sub_todo_count == 2
        mock_todo_repo.count_open_sub_todos.assert_awaited_once_with(FAKE_USER_ID, [FAKE_TODO_ID])

    async def test_a_tracked_todo_refuses_a_workflow_link(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        tracked = _make_todo_doc(todo_id=FAKE_TODO_ID)
        tracked.labels = [GAIA_TRACKED_LABEL]
        mock_todo_repo.get = AsyncMock(return_value=tracked)
        with pytest.raises(TrackedTodoWorkflowError) as refused:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(workflow_id="wf1"), FAKE_USER_ID
            )
        mock_todo_repo.get.assert_awaited_once_with(FAKE_TODO_ID, user_id=FAKE_USER_ID)
        assert refused.value.message == (
            "Tracked todos run on the agent from their canvas and never link a workflow"
        )

    @pytest.mark.parametrize(
        ("existing_labels", "workflow_id", "new_labels"),
        [
            ([], None, [GAIA_TRACKED_LABEL]),  # tracks a classic todo
            ([], "wf1", [GAIA_TRACKED_LABEL]),  # tracks a linked todo
            ([GAIA_TRACKED_LABEL], None, ["errands"]),  # untracks a todo that keeps its canvas
        ],
    )
    async def test_a_label_edit_cannot_change_whether_a_todo_is_tracked(
        self,
        mock_todo_repo,
        mock_project_repo,
        mock_vector_utils,
        mock_sync,
        existing_labels,
        workflow_id,
        new_labels,
    ):
        existing = _make_todo_doc(
            todo_id=FAKE_TODO_ID, labels=existing_labels, workflow_id=workflow_id
        )
        mock_todo_repo.get = AsyncMock(return_value=existing)
        with pytest.raises(TrackedLabelChangeError) as refused:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(labels=new_labels), FAKE_USER_ID
            )
        assert refused.value.status_code == 400
        assert refused.value.message == "A label change cannot add or remove the tracked label"
        mock_todo_repo.get.assert_awaited_once_with(FAKE_TODO_ID, user_id=FAKE_USER_ID)
        mock_todo_repo.update.assert_not_awaited()

    async def test_linking_and_tracking_in_one_update_is_refused_before_any_write(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """Regression for #1269 review: the link landed first, then the tracked label."""
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        with pytest.raises(TrackedLabelChangeError):
            await TodoService.update_todo(
                FAKE_TODO_ID,
                TodoUpdateRequest(workflow_id="wf1", labels=[GAIA_TRACKED_LABEL]),
                FAKE_USER_ID,
            )
        mock_todo_repo.link_workflow.assert_not_awaited()
        mock_todo_repo.update.assert_not_awaited()

    async def test_a_tracked_todo_with_a_legacy_link_can_still_be_relabelled(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_repo
    ):
        """Tracked todos created before this change may still hold a workflow_id nothing reads."""
        legacy = _make_todo_doc(
            todo_id=FAKE_TODO_ID, labels=[GAIA_TRACKED_LABEL], workflow_id="wf-legacy"
        )
        mock_todo_repo.get = AsyncMock(return_value=legacy)
        mock_todo_repo.update = AsyncMock(return_value=legacy)
        labels = [GAIA_TRACKED_LABEL, "errands"]
        await TodoService.update_todo(FAKE_TODO_ID, TodoUpdateRequest(labels=labels), FAKE_USER_ID)
        assert mock_todo_repo.update.await_args.kwargs["update"].labels == labels

    async def test_relabelling_a_linked_classic_todo_is_allowed(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, mock_workflow_repo
    ):
        linked = _make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id="wf1")
        mock_todo_repo.get = AsyncMock(return_value=linked)
        mock_todo_repo.update = AsyncMock(return_value=linked)
        await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(labels=["errands"]), FAKE_USER_ID
        )
        assert mock_todo_repo.update.await_args.kwargs["update"].labels == ["errands"]

    async def test_a_link_refused_after_the_check_is_a_conflict(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """The check passed, so a refused link means the todo became tracked mid-update."""
        mock_todo_repo.get = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))
        mock_todo_repo.link_workflow = AsyncMock(return_value=None)
        with pytest.raises(TrackedTodoWorkflowError):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(workflow_id="wf1"), FAKE_USER_ID
            )
        mock_todo_repo.get.assert_awaited_once_with(FAKE_TODO_ID, user_id=FAKE_USER_ID)
        mock_todo_repo.update.assert_not_awaited()

    async def test_a_workflow_link_to_a_missing_todo_is_not_found(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        with pytest.raises(ValueError, match="not found"):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(workflow_id="wf1"), FAKE_USER_ID
            )

    async def test_a_plain_todos_display_recurrence_is_stored_exactly_as_sent(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """Mobile sends an RRULE for a plain todo; nothing runs it, so it is stored verbatim."""
        rrule = "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE"
        plain = _make_todo_doc(todo_id=FAKE_TODO_ID)
        mock_todo_repo.get = AsyncMock(return_value=plain)
        mock_todo_repo.update = AsyncMock(return_value=plain)

        await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(recurrence=rrule), FAKE_USER_ID
        )

        assert mock_todo_repo.update.await_args.kwargs["update"].recurrence == rrule

    @pytest.mark.parametrize(
        ("recurrence", "message"),
        [
            ("* * * * *", "Schedules can repeat at most once an hour."),
            ("FREQ=DAILY", "Use 5 fields: minute hour day month weekday."),
        ],
    )
    async def test_a_tracked_todos_recurrence_is_a_run_schedule_and_is_held_to_the_rule(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync, recurrence, message
    ):
        tracked = _make_todo_doc(
            todo_id=FAKE_TODO_ID, labels=[GAIA_TRACKED_LABEL], vfs_path="/workspace/t"
        )
        mock_todo_repo.get = AsyncMock(return_value=tracked)

        with pytest.raises(AppError) as refused:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(recurrence=recurrence), FAKE_USER_ID
            )

        assert refused.value.status_code == 422
        assert refused.value.message == message
        mock_todo_repo.update.assert_not_awaited()

    async def test_a_tracked_todo_accepts_an_hourly_or_shortcut_schedule(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        tracked = _make_todo_doc(todo_id=FAKE_TODO_ID, labels=[GAIA_TRACKED_LABEL])
        mock_todo_repo.get = AsyncMock(return_value=tracked)
        mock_todo_repo.update = AsyncMock(return_value=tracked)

        await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(recurrence="every_1h"), FAKE_USER_ID
        )

        assert mock_todo_repo.update.await_args.kwargs["update"].recurrence == "every_1h"

    async def test_updates_and_returns(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        updated = _make_todo_doc(todo_id=FAKE_TODO_ID, title="new")
        mock_todo_repo.update = AsyncMock(return_value=updated)
        result = await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(title="new"), FAKE_USER_ID
        )
        assert result.title == "new"
        update = mock_todo_repo.update.call_args.kwargs["update"]
        assert update.title == "new"
        mock_vector_utils["update_embedding"].assert_awaited_once_with(
            FAKE_TODO_ID, updated, FAKE_USER_ID
        )

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
        """Once the document is deleted nothing names its Composio trigger, so teardown must run before delete or it leaks forever."""
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


class TestDeletingAParentDeletesItsSubTodos:
    async def test_each_sub_todo_goes_through_the_single_delete_first(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        parent = _make_todo_doc(todo_id=_PARENT, vfs_path="/workspace/gaia-tasks/p")
        child = _make_todo_doc(todo_id=_CHILD, parent_todo_id=_PARENT, completed=True)
        docs = {_PARENT: parent, _CHILD: child}
        mock_todo_repo.get = AsyncMock(side_effect=lambda todo_id, user_id: docs.get(todo_id))
        mock_todo_repo.find_sub_todos = AsyncMock(
            side_effect=lambda user_id, parent_ids: [child] if parent_ids == [_PARENT] else []
        )

        await TodoService.delete_todo(_PARENT, FAKE_USER_ID)

        assert mock_todo_repo.delete.await_args_list == [
            call(_CHILD, user_id=FAKE_USER_ID),
            call(_PARENT, user_id=FAKE_USER_ID),
        ]
        assert mock_todo_repo.find_sub_todos.await_args_list == [
            call(FAKE_USER_ID, [_PARENT]),
            call(FAKE_USER_ID, [_CHILD]),
        ]

    async def test_a_bulk_delete_takes_the_selected_parents_sub_todos_with_it(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        child = _make_todo_doc(todo_id=_CHILD, parent_todo_id=_PARENT)
        mock_todo_repo.find_sub_todos = AsyncMock(return_value=[child])
        mock_todo_repo.bulk_delete = AsyncMock(return_value=2)

        await TodoService.bulk_delete_todos([_PARENT], FAKE_USER_ID)

        mock_todo_repo.find_sub_todos.assert_awaited_once_with(FAKE_USER_ID, [_PARENT])
        mock_todo_repo.bulk_delete.assert_awaited_once_with(FAKE_USER_ID, [_PARENT, _CHILD])

    async def test_the_agents_bulk_delete_takes_them_too(self, mock_bulk_repos):
        todo_repo, _ = mock_bulk_repos
        child = _make_todo_doc(todo_id=_CHILD, parent_todo_id=_PARENT)
        todo_repo.find_by_ids = AsyncMock(return_value=[_make_todo_doc(todo_id=_PARENT), child])
        todo_repo.find_sub_todos.return_value = [child]
        todo_repo.bulk_delete = AsyncMock(return_value=2)

        await bulk_service_delete_todos([_PARENT], FAKE_USER_ID)

        todo_repo.find_sub_todos.assert_awaited_once_with(FAKE_USER_ID, [_PARENT])
        todo_repo.find_by_ids.assert_awaited_once_with(FAKE_USER_ID, [_PARENT, _CHILD])
        todo_repo.bulk_delete.assert_awaited_once_with(FAKE_USER_ID, [_PARENT, _CHILD])


_TRACKED_PATH = "/workspace/gaia-tasks/x"
_COMPLETE_TRACKED = "app.services.tracked_todo_service.tracked_todo_service.complete_tracked_todo"


class TestBulkCompleteRunsTheTrackedLifecycle:
    """A bulk complete must close a tracked todo the way a single complete does: watches torn down, sub-todos completed."""

    async def test_a_tracked_todo_completes_through_its_lifecycle_and_plain_ones_in_bulk(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        tracked = _make_todo_doc(todo_id="t", vfs_path=_TRACKED_PATH)
        plain = _make_todo_doc(todo_id="p")
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[tracked, plain])
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        req = BulkUpdateRequest(todo_ids=["t", "p"], updates=TodoUpdateRequest(completed=True))

        with patch(_COMPLETE_TRACKED, new_callable=AsyncMock, return_value=True) as complete:
            result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)

        complete.assert_awaited_once_with("t", FAKE_USER_ID, summary="Completed via bulk operation")
        assert mock_todo_repo.bulk_update.await_args.args[1] == ["p"]
        assert sorted(result.success) == ["p", "t"]
        assert mock_todo_repo.find_by_ids.await_args_list == [
            call(FAKE_USER_ID, ["t", "p"]),
            call(FAKE_USER_ID, ["t", "p"]),
        ]

    async def test_the_rest_of_the_update_still_reaches_the_tracked_todos(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        tracked = _make_todo_doc(todo_id="t", vfs_path=_TRACKED_PATH)
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[tracked, _make_todo_doc(todo_id="p")])
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        req = BulkUpdateRequest(
            todo_ids=["t", "p"],
            updates=TodoUpdateRequest(completed=True, priority=Priority.HIGH),
        )

        with patch(_COMPLETE_TRACKED, new_callable=AsyncMock, return_value=True):
            await TodoService.bulk_update_todos(req, FAKE_USER_ID)

        tracked_write, plain_write = mock_todo_repo.bulk_update.await_args_list
        assert tracked_write.args[:2] == (FAKE_USER_ID, ["t"])
        assert tracked_write.args[2].model_dump(exclude_unset=True) == {"priority": Priority.HIGH}
        assert plain_write.args[:2] == (FAKE_USER_ID, ["p"])
        assert plain_write.args[2].model_dump(exclude_unset=True) == {
            "completed": True,
            "priority": Priority.HIGH,
        }

    async def test_only_tracked_todos_means_no_plain_write(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="t", vfs_path=_TRACKED_PATH)]
        )
        req = BulkUpdateRequest(todo_ids=["t"], updates=TodoUpdateRequest(completed=True))

        with patch(_COMPLETE_TRACKED, new_callable=AsyncMock, return_value=True):
            result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)

        mock_todo_repo.bulk_update.assert_not_awaited()
        assert result.success == ["t"]

    async def test_a_tracked_completion_that_fails_is_reported_and_the_rest_still_complete(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        docs = [_make_todo_doc(todo_id=i, vfs_path=_TRACKED_PATH) for i in ("t1", "t2")]
        mock_todo_repo.find_by_ids = AsyncMock(return_value=docs)
        req = BulkUpdateRequest(todo_ids=["t1", "t2"], updates=TodoUpdateRequest(completed=True))

        with (
            patch(
                _COMPLETE_TRACKED,
                new_callable=AsyncMock,
                side_effect=[RuntimeError("down"), True],
            ) as complete,
            patch("app.services.todos.todo_service.schedule_user_todos_sync") as sync,
        ):
            async with captured_wide_event() as event:
                result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)

        assert (result.success, result.failed) == (["t2"], ["t1"])
        assert [c.args[0] for c in complete.await_args_list] == ["t1", "t2"]
        assert event["errors"] == [
            {
                "msg": "todo.bulk_tracked_complete_failed",
                "todo_id": "t1",
                "error": "down",
                "error_type": "RuntimeError",
            }
        ]
        sync.assert_called_once_with(FAKE_USER_ID)


class TestBulkDeleteClosesTriggers:
    async def test_a_subscribed_todo_unregisters_before_the_bulk_delete(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        subscribed = _make_todo_doc(todo_id="a", vfs_path=_TRACKED_PATH)
        subscribed.trigger_subscriptions = [
            TriggerSubscription(
                trigger_name="gmail_new_message",
                action=SubscriptionAction.EXECUTE,
                resolution=SubscriptionResolution.ACCOUNT,
            )
        ]
        order: list[str] = []
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[subscribed, _make_todo_doc(todo_id="b")]
        )

        async def _delete(*_args: object) -> int:
            order.append("delete")
            return 2

        async def _teardown(*_args: object, **_kwargs: object) -> int:
            order.append("teardown")
            return 1

        mock_todo_repo.bulk_delete = AsyncMock(side_effect=_delete)
        teardown = AsyncMock(side_effect=_teardown)
        with (
            patch("app.services.todos.todo_service.teardown_subscriptions", teardown),
            patch(
                "app.services.todos.todo_service.delete_canvas_embedding", new_callable=AsyncMock
            ) as canvas,
        ):
            await TodoService.bulk_delete_todos(["a", "b"], FAKE_USER_ID)

        assert order == ["teardown", "delete"]
        teardown.assert_awaited_once_with("a", FAKE_USER_ID, reason="bulk_deleted")
        canvas.assert_awaited_once_with("a")

    async def test_a_canvas_index_that_cannot_be_dropped_does_not_stop_the_delete(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a", vfs_path=_TRACKED_PATH)]
        )
        mock_todo_repo.bulk_delete = AsyncMock(return_value=1)
        with patch(
            "app.services.todos.todo_service.delete_canvas_embedding",
            new=AsyncMock(side_effect=RuntimeError("chroma down")),
        ):
            async with captured_wide_event() as event:
                result = await TodoService.bulk_delete_todos(["a"], FAKE_USER_ID)

        mock_todo_repo.bulk_delete.assert_awaited_once_with(FAKE_USER_ID, ["a"])
        assert result.success == ["a"]
        assert event["warnings"] == [
            {"msg": "todo.canvas_embedding_delete_failed", "todo_id": "a", "error": "chroma down"}
        ]


class TestBulkOps:
    async def test_bulk_update_delegates(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.bulk_update = AsyncMock(return_value=2)
        doc_a = _make_todo_doc(todo_id="a")
        doc_b = _make_todo_doc(todo_id="b")
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[doc_a, doc_b])
        req = BulkUpdateRequest(todo_ids=["a", "b"], updates=TodoUpdateRequest(completed=True))
        result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert result.total == 2
        mock_todo_repo.bulk_update.assert_awaited_once()
        # Every modified todo is re-indexed under its own id and owner.
        assert mock_vector_utils["update_embedding"].await_args_list == [
            call("a", doc_a, FAKE_USER_ID),
            call("b", doc_b, FAKE_USER_ID),
        ]

    async def test_a_bulk_move_to_a_project_the_user_lacks_writes_nothing(
        self, mock_todo_repo, mock_project_repo
    ):
        req = BulkUpdateRequest(
            todo_ids=["a"], updates=TodoUpdateRequest(project_id=FAKE_PROJECT_ID)
        )

        with pytest.raises(ValueError) as raised:
            await TodoService.bulk_update_todos(req, FAKE_USER_ID)

        assert str(raised.value) == f"Project {FAKE_PROJECT_ID} not found"
        mock_project_repo.get.assert_awaited_once_with(FAKE_PROJECT_ID, user_id=FAKE_USER_ID)
        mock_todo_repo.bulk_update.assert_not_called()

    async def test_a_bulk_move_to_the_users_project_goes_through(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_project_repo.get = AsyncMock(
            return_value=_make_project_doc(project_id=FAKE_PROJECT_ID)
        )
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_make_todo_doc(todo_id="a")])
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        req = BulkUpdateRequest(
            todo_ids=["a"], updates=TodoUpdateRequest(project_id=FAKE_PROJECT_ID)
        )

        result = await TodoService.bulk_update_todos(req, FAKE_USER_ID)

        assert result.success == ["a"]

    async def test_bulk_update_refuses_to_link_a_workflow(self, mock_todo_repo, mock_project_repo):
        """A bulk $set of workflow_id would bypass link_workflow's tracked-todo guard."""
        req = BulkUpdateRequest(todo_ids=["a", "b"], updates=TodoUpdateRequest(workflow_id="wf1"))
        with pytest.raises(AppError) as raised:
            await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert raised.value.status_code == 400
        assert raised.value.message == "A workflow is linked one todo at a time, not in bulk"
        mock_todo_repo.bulk_update.assert_not_called()

    @pytest.mark.parametrize(
        ("existing_labels", "new_labels"),
        [
            ([], ["work", GAIA_TRACKED_LABEL]),  # would track a classic (maybe linked) todo
            ([GAIA_TRACKED_LABEL], ["work"]),  # would untrack a todo that keeps its canvas
        ],
    )
    async def test_bulk_update_refuses_to_change_whether_a_todo_is_tracked(
        self, mock_todo_repo, mock_project_repo, existing_labels, new_labels
    ):
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a", labels=existing_labels)]
        )
        req = BulkUpdateRequest(todo_ids=["a"], updates=TodoUpdateRequest(labels=new_labels))
        with pytest.raises(AppError) as raised:
            await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert raised.value.status_code == 400
        assert raised.value.message == "A label change cannot add or remove the tracked label"
        mock_todo_repo.find_by_ids.assert_awaited_once_with(FAKE_USER_ID, ["a"])
        mock_todo_repo.bulk_update.assert_not_called()

    async def test_bulk_update_may_relabel_tracked_todos_that_stay_tracked(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a", labels=[GAIA_TRACKED_LABEL])]
        )
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        labels = ["work", GAIA_TRACKED_LABEL]
        req = BulkUpdateRequest(todo_ids=["a"], updates=TodoUpdateRequest(labels=labels))
        await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert mock_todo_repo.bulk_update.await_args.args[2].labels == labels

    async def test_bulk_update_holds_a_selected_tracked_todos_schedule_to_the_rule(
        self, mock_todo_repo, mock_project_repo
    ):
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[
                _make_todo_doc(todo_id="a"),
                _make_todo_doc(todo_id="b", labels=[GAIA_TRACKED_LABEL]),
            ]
        )
        req = BulkUpdateRequest(
            todo_ids=["a", "b"], updates=TodoUpdateRequest(recurrence="* * * * *")
        )
        with pytest.raises(AppError) as refused:
            await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert refused.value.status_code == 422
        assert refused.value.message == "Schedules can repeat at most once an hour."
        mock_todo_repo.find_by_ids.assert_awaited_once_with(FAKE_USER_ID, ["a", "b"])
        mock_todo_repo.bulk_update.assert_not_called()

    async def test_bulk_update_stores_plain_todos_display_recurrence_as_sent(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        rrule = "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE"
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_make_todo_doc(todo_id="a")])
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        req = BulkUpdateRequest(todo_ids=["a"], updates=TodoUpdateRequest(recurrence=rrule))
        await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert mock_todo_repo.bulk_update.await_args.args[2].recurrence == rrule

    async def test_bulk_update_may_set_other_labels(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)
        req = BulkUpdateRequest(todo_ids=["a"], updates=TodoUpdateRequest(labels=["work"]))
        await TodoService.bulk_update_todos(req, FAKE_USER_ID)
        assert mock_todo_repo.bulk_update.await_args.args[2].labels == ["work"]

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
        mock_todo_repo.list_page = AsyncMock(
            return_value=TodoPage(items=[_make_todo_doc()], total=1)
        )
        result = await get_all_todos(FAKE_USER_ID)
        assert len(result) == 1


# ===========================================================================
# todo_bulk_service
# ===========================================================================


@pytest.fixture
def mock_bulk_repos(mock_vector_utils, mock_sync):
    # The agent's bulk complete/delete run through TodoService: one repository for both modules.
    todo_repo = MagicMock()
    todo_repo.find_by_ids = AsyncMock(return_value=[])
    todo_repo.bulk_update = AsyncMock(return_value=0)
    todo_repo.bulk_delete = AsyncMock(return_value=0)
    todo_repo.find_sub_todos = AsyncMock(return_value=[])
    with (
        patch("app.services.todos.todo_service.todo_repository", todo_repo),
        patch("app.services.todos.todo_bulk_service.todo_repository", todo_repo),
        patch("app.services.todos.todo_bulk_service.project_repository") as project_repo,
    ):
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
        assert [todo.id for todo in result.todos] == ["a", "b"]
        assert result.failed == []

    async def test_a_tracked_todo_that_fails_is_named_and_not_returned_as_done(
        self, mock_bulk_repos
    ):
        todo_repo, _ = mock_bulk_repos
        docs = [
            _make_todo_doc(todo_id="a", vfs_path="file:///a"),
            _make_todo_doc(todo_id="b", vfs_path="file:///b"),
        ]
        todo_repo.find_by_ids = AsyncMock(
            side_effect=lambda _user, ids: [doc for doc in docs if doc.id in ids]
        )
        with patch(
            _COMPLETE_TRACKED, new_callable=AsyncMock, side_effect=[RuntimeError("down"), True]
        ):
            result = await bulk_complete_todos(["a", "b"], FAKE_USER_ID)

        assert [todo.id for todo in result.todos] == ["b"]
        assert result.failed == ["a"]
        assert todo_repo.find_by_ids.await_args == call(FAKE_USER_ID, ["b"])

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
        """Tracked todos count through their completion lifecycle — the reported count is modified + tracked, not a plain update count."""
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
            patch(_COMPLETE_TRACKED, new_callable=AsyncMock) as mock_tracked,
        ):
            await bulk_complete_todos(["a", "b"], FAKE_USER_ID)
        mock_tracked.assert_awaited_once_with(
            "b", FAKE_USER_ID, summary="Completed via bulk operation"
        )
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
        with patch("app.services.todos.todo_service.capture_event") as mock_capture:
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
        """Teardown must use the deleted doc's own id/user and the bulk-delete reason — once gone, a wrong id or reason leaks the trigger."""
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
        with patch("app.services.todos.todo_service.teardown_subscriptions", teardown):
            await bulk_service_delete_todos(["a", "b"], FAKE_USER_ID)
        # Only the subscribed doc tears down, and with its exact id/user/reason.
        teardown.assert_awaited_once_with("a", FAKE_USER_ID, reason="bulk_deleted")


class TestTodoUpdateCannotLinkAWorkflow:
    def test_the_generic_update_rejects_workflow_id(self):
        """Only link_workflow may write workflow_id, so it cannot bypass the tracked-todo guard."""
        with pytest.raises(ValidationError):
            TodoUpdate(workflow_id="wf1")


class TestReopenUnderItsParent:
    """A sub-todo reopened under a completed parent would run outside the parent's cascade."""

    @staticmethod
    def _family(parent_completed: bool) -> list[TodoDocument]:
        parent = _make_todo_doc(todo_id=_PARENT, completed=parent_completed)
        child = _make_todo_doc(todo_id=FAKE_TODO_ID, completed=True, parent_todo_id=_PARENT)
        return [child, parent]

    def _repo_answering(self, repo: MagicMock, family: list[TodoDocument]) -> None:
        repo.find_by_ids = AsyncMock(
            side_effect=lambda user, ids: (
                [doc for doc in family if doc.id in ids] if user == FAKE_USER_ID else []
            )
        )

    async def test_a_single_reopen_is_refused_and_writes_nothing(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        self._repo_answering(mock_todo_repo, self._family(parent_completed=True))

        with pytest.raises(SubTodoParentError) as refused:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        assert refused.value.message == (
            f"Sub-todo {FAKE_TODO_ID} cannot reopen while its parent is completed; "
            "reopen the parent first."
        )
        mock_todo_repo.update.assert_not_awaited()

    async def test_a_bulk_reopen_is_refused_and_writes_nothing(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        sibling = _make_todo_doc(todo_id="sibling", completed=True, parent_todo_id=_PARENT)
        self._repo_answering(mock_todo_repo, [*self._family(parent_completed=True), sibling])

        with pytest.raises(SubTodoParentError) as refused:
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(
                    todo_ids=[FAKE_TODO_ID, "sibling"], updates=TodoUpdateRequest(completed=False)
                ),
                FAKE_USER_ID,
            )

        assert refused.value.message.startswith(f"Sub-todo {FAKE_TODO_ID}, sibling cannot reopen")

        mock_todo_repo.bulk_update.assert_not_awaited()

    async def test_under_an_open_parent_the_reopen_goes_through(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        self._repo_answering(mock_todo_repo, self._family(parent_completed=False))
        mock_todo_repo.update = AsyncMock(return_value=self._family(False)[0])

        await TodoService.update_todo(
            FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
        )

        mock_todo_repo.update.assert_awaited_once()


class TestReopenOfATakenRef:
    """Reopening a todo whose outside object already has an open todo is a named conflict."""

    async def test_update_names_the_open_todo_holding_the_ref(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        reopened = _make_todo_doc(todo_id=FAKE_TODO_ID, completed=True)
        reopened.external_ref = _THREAD
        holder = _make_todo_doc(title="Reply to Sam")
        mock_todo_repo.get = AsyncMock(return_value=reopened)
        mock_todo_repo.update = AsyncMock(side_effect=DuplicateKeyError("E11000"))
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=holder)

        with pytest.raises(ExternalRefTakenError) as raised:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        assert raised.value.existing is holder
        assert raised.value.status_code == 409
        assert holder.id in raised.value.message and "Reply to Sam" in raised.value.message
        mock_todo_repo.find_open_by_external_ref.assert_awaited_once_with(FAKE_USER_ID, _THREAD)
        mock_todo_repo.update.assert_awaited_once_with(
            FAKE_TODO_ID,
            user_id=FAKE_USER_ID,
            update=TodoUpdate(completed=False, completed_at=None),
        )
        mock_todo_repo.get.assert_awaited_once_with(FAKE_TODO_ID, user_id=FAKE_USER_ID)

    async def test_an_update_rejected_with_no_open_holder_is_not_disguised(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        reopened = _make_todo_doc(todo_id=FAKE_TODO_ID, completed=True)
        reopened.external_ref = _THREAD
        mock_todo_repo.get = AsyncMock(return_value=reopened)
        mock_todo_repo.update = AsyncMock(side_effect=DuplicateKeyError("E11000"))
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)

        with pytest.raises(DuplicateKeyError):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

    async def test_bulk_reopen_is_refused_before_any_write(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        reopened = _make_todo_doc(todo_id="b", completed=True)
        reopened.external_ref = _THREAD
        holder = _make_todo_doc(title="Reply to Sam")
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[_make_todo_doc(todo_id="a", completed=True), reopened]
        )
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=holder)

        with pytest.raises(ExternalRefTakenError) as raised:
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(todo_ids=["a", "b"], updates=TodoUpdateRequest(completed=False)),
                FAKE_USER_ID,
            )

        assert raised.value.existing is holder
        mock_todo_repo.bulk_update.assert_not_awaited()
        # One read checks the parents, one checks the refs; neither writes.
        assert mock_todo_repo.find_by_ids.await_args_list == [call(FAKE_USER_ID, ["a", "b"])] * 2
        mock_todo_repo.find_open_by_external_ref.assert_awaited_once_with(FAKE_USER_ID, _THREAD)

    async def test_bulk_reopen_of_free_refs_writes(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        reopened = _make_todo_doc(todo_id="b", completed=True)
        reopened.external_ref = _THREAD
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[reopened])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)

        with patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered):
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(todo_ids=["b"], updates=TodoUpdateRequest(completed=False)),
                FAKE_USER_ID,
            )

        mock_todo_repo.bulk_update.assert_awaited_once_with(
            FAKE_USER_ID, ["b"], TodoUpdate(completed=False)
        )

    async def test_an_open_todo_in_a_bulk_reopen_is_not_its_own_conflict(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """The open todo holding a ref is found by it; only a completed one can be refused."""
        already_open = _make_todo_doc(todo_id="b")
        already_open.external_ref = _THREAD
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[already_open])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=already_open)
        mock_todo_repo.bulk_update = AsyncMock(return_value=0)

        await TodoService.bulk_update_todos(
            BulkUpdateRequest(todo_ids=["b"], updates=TodoUpdateRequest(completed=False)),
            FAKE_USER_ID,
        )

        mock_todo_repo.bulk_update.assert_awaited_once()

    async def test_a_bulk_write_that_loses_the_race_is_still_named(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """Another reopen can take the ref between the check and the write."""
        reopened = _make_todo_doc(todo_id="b", completed=True)
        reopened.external_ref = _THREAD
        holder = _make_todo_doc(title="Reply to Sam")
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[reopened])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(side_effect=[None, holder])
        mock_todo_repo.bulk_update = AsyncMock(
            side_effect=BulkWriteError({"writeErrors": [{"code": 11000}]})
        )

        created: list[TriggerSubscription] = []

        async def register(
            **kwargs: object,
        ) -> tuple[TriggerSubscription, None, bool]:
            subscription, outcome, created_flag = await _registered(**kwargs)
            created.append(subscription)
            return subscription, outcome, created_flag

        with (
            patch(_REGISTER, new_callable=AsyncMock, side_effect=register),
            patch(_UNREGISTER, new_callable=AsyncMock) as unregister,
            pytest.raises(ExternalRefTakenError) as raised,
        ):
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(todo_ids=["b"], updates=TodoUpdateRequest(completed=False)),
                FAKE_USER_ID,
            )

        assert raised.value.existing is holder
        assert mock_todo_repo.find_by_ids.await_args_list == [call(FAKE_USER_ID, ["b"])] * 4
        assert len(created) == 2
        assert unregister.await_args_list == [call("b", FAKE_USER_ID, sub.id) for sub in created]
        assert mock_todo_repo.find_open_by_external_ref.await_args_list == [
            call(FAKE_USER_ID, _THREAD),
            call(FAKE_USER_ID, _THREAD),
        ]

    async def test_a_bulk_write_that_fails_for_another_reason_propagates(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        failure = BulkWriteError({"writeErrors": [{"code": 2}]})
        mock_todo_repo.bulk_update = AsyncMock(side_effect=failure)

        with pytest.raises(BulkWriteError) as raised:
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(todo_ids=["b"], updates=TodoUpdateRequest(completed=False)),
                FAKE_USER_ID,
            )

        assert raised.value is failure


class TestReopenWatchesTheRefAgain:
    """Completion tore the watches down, so reopening a thread todo must set them back up."""

    async def test_reopening_a_thread_todo_watches_its_thread_both_ways_again(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_completed_thread_todo()])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        mock_todo_repo.update = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))

        with patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        assert sorted(c.kwargs["trigger_name"] for c in register.await_args_list) == sorted(
            [GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME]
        )
        for c in register.await_args_list:
            assert c.kwargs["todo_id"] == FAKE_TODO_ID
            assert c.kwargs["user_id"] == FAKE_USER_ID
            assert c.kwargs["conditions"] == [_ON_THREAD]
            assert c.kwargs["action"] is SubscriptionAction.EXECUTE
        assert (
            mock_todo_repo.find_by_ids.await_args_list == [call(FAKE_USER_ID, [FAKE_TODO_ID])] * 2
        )
        mock_todo_repo.find_open_by_external_ref.assert_awaited_once_with(FAKE_USER_ID, _THREAD)

    async def test_a_reopen_adds_only_the_watch_the_todo_lost(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """A bulk completion skips teardown, so its todo can come back still watching."""
        done = _completed_thread_todo(watching=(GMAIL_NEW_MESSAGE_TRIGGER_NAME,))
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[done])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        mock_todo_repo.update = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))

        with patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        register.assert_awaited_once()
        assert register.await_args.kwargs["trigger_name"] == GMAIL_EMAIL_SENT_TRIGGER_NAME

    async def test_a_reopen_that_does_not_land_removes_only_the_watch_it_added(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        done = _completed_thread_todo(watching=(GMAIL_NEW_MESSAGE_TRIGGER_NAME,))
        kept_watch = done.trigger_subscriptions[0]
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[done])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        mock_todo_repo.update = AsyncMock(side_effect=RuntimeError("mongo down"))
        created: list[TriggerSubscription] = []

        async def register(
            **kwargs: object,
        ) -> tuple[TriggerSubscription, None, bool]:
            subscription, outcome, created_flag = await _registered(**kwargs)
            created.append(subscription)
            return subscription, outcome, created_flag

        with (
            patch(_REGISTER, new_callable=AsyncMock, side_effect=register),
            patch(_UNREGISTER, new_callable=AsyncMock) as unregister,
            pytest.raises(RuntimeError),
        ):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        (added,) = created
        unregister.assert_awaited_once_with(FAKE_TODO_ID, FAKE_USER_ID, added.id)
        assert added.id != kept_watch.id

    async def test_a_watch_on_another_thread_is_not_this_threads_watch(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        done = _completed_thread_todo()
        done.trigger_subscriptions = [
            TriggerSubscription(
                trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
                conditions=[_ON_THREAD.model_copy(update={"value": "other-thread"})],
                action=SubscriptionAction.EXECUTE,
                resolution=SubscriptionResolution.ACCOUNT,
            )
        ]
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[done])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        mock_todo_repo.update = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))

        with patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register:
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        assert register.await_count == 2

    async def test_a_watch_that_cannot_be_set_leaves_the_todo_completed(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_completed_thread_todo()])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)

        with (
            patch(_REGISTER, new_callable=AsyncMock, side_effect=SubscriptionError("down")),
            pytest.raises(SubscriptionError),
        ):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        mock_todo_repo.update.assert_not_awaited()

    async def test_a_reopen_refused_for_a_taken_thread_sets_no_watch(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        holder = _make_todo_doc(title="Reply to Sam")
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_completed_thread_todo()])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=holder)

        with (
            patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register,
            pytest.raises(ExternalRefTakenError) as raised,
        ):
            await TodoService.update_todo(
                FAKE_TODO_ID, TodoUpdateRequest(completed=False), FAKE_USER_ID
            )

        assert raised.value.existing is holder
        register.assert_not_awaited()
        mock_todo_repo.update.assert_not_awaited()

    async def test_an_edit_that_does_not_reopen_touches_no_watch(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_completed_thread_todo()])
        mock_todo_repo.update = AsyncMock(return_value=_make_todo_doc(todo_id=FAKE_TODO_ID))

        with patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register:
            await TodoService.update_todo(FAKE_TODO_ID, TodoUpdateRequest(title="x"), FAKE_USER_ID)

        register.assert_not_awaited()
        mock_todo_repo.find_by_ids.assert_not_awaited()

    async def test_a_bulk_reopen_watches_each_thread_again(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        mock_todo_repo.find_by_ids = AsyncMock(return_value=[_completed_thread_todo("b")])
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)
        mock_todo_repo.bulk_update = AsyncMock(return_value=1)

        with patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register:
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(todo_ids=["b"], updates=TodoUpdateRequest(completed=False)),
                FAKE_USER_ID,
            )

        assert {c.kwargs["todo_id"] for c in register.await_args_list} == {"b"}
        assert register.await_count == 2

    async def test_a_bulk_reopen_of_two_todos_about_one_thread_writes_nothing(
        self, mock_todo_repo, mock_project_repo, mock_vector_utils, mock_sync
    ):
        """Neither is open, so each passes the holder check; the ordered write would half-land."""
        mock_todo_repo.find_by_ids = AsyncMock(
            return_value=[
                _completed_thread_todo("a"),
                _make_todo_doc(todo_id="c", completed=True),
                _completed_thread_todo("b"),
            ]
        )
        mock_todo_repo.find_open_by_external_ref = AsyncMock(return_value=None)

        with (
            patch(_REGISTER, new_callable=AsyncMock, side_effect=_registered) as register,
            pytest.raises(ExternalRefReopenedTwiceError) as raised,
        ):
            await TodoService.bulk_update_todos(
                BulkUpdateRequest(
                    todo_ids=["a", "c", "b"], updates=TodoUpdateRequest(completed=False)
                ),
                FAKE_USER_ID,
            )

        assert raised.value.status_code == 409
        assert raised.value.code == "external_ref_reopened_twice"
        assert raised.value.public == {"todo_ids": ["a", "b"]}
        assert raised.value.message == (
            "Two of the selected todos track the same thing; only one can be reopened"
        )
        mock_todo_repo.bulk_update.assert_not_awaited()
        register.assert_not_awaited()
