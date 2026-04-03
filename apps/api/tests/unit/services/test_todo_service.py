"""Unit tests for the todo service layer.

Covers:
- TodoService: CRUD, bulk ops, search, stats, caching, reindexing
- ProjectService: CRUD, cache, default inbox protection
- Compatibility wrappers (module-level functions)
- todo_bulk_service: bulk_complete, bulk_move, bulk_delete
- todo_count_service: update_project_todo_count, sync_all_project_counts
- sync_service: sync_goal_node_completion, sync_subtask_to_goal_completion,
                create_goal_project_and_todo, _get_or_create_goals_project,
                cache invalidation helpers
"""

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.models.todo_models import (
    BulkMoveRequest,
    BulkOperationResponse,
    BulkUpdateRequest,
    PaginationMeta,
    Priority,
    ProjectCreate,
    ProjectResponse,
    SearchMode,
    SubTask,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoStats,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.services.todos.sync_service import (
    _get_or_create_goals_project,
    _invalidate_goal_caches,
    _invalidate_project_caches,
    _invalidate_todo_caches,
    create_goal_project_and_todo,
    sync_goal_node_completion,
    sync_subtask_to_goal_completion,
)
from app.services.todos.todo_bulk_service import (
    bulk_complete_todos,
    bulk_delete_todos as bulk_service_delete_todos,
    bulk_move_todos as bulk_service_move_todos,
)
from app.services.todos.todo_count_service import (
    sync_all_project_counts,
    update_project_todo_count,
)
from app.services.todos.todo_service import (
    ProjectService,
    TodoService,
    _get_workflow_categories_for_todos,
)

# Also test the compatibility wrappers at module level
from app.services.todos.todo_service import (
    bulk_index_existing_todos,
    create_project,
    create_todo,
    delete_project,
    delete_todo,
    get_all_labels,
    get_all_projects,
    get_all_todos,
    get_todo,
    get_todo_stats,
    get_todos_by_date_range,
    get_todos_by_label,
    hybrid_search_todos,
    search_todos,
    semantic_search_todos,
    update_project,
    update_todo,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_USER_ID_2 = "507f1f77bcf86cd799439022"
FAKE_TODO_ID = str(ObjectId())
FAKE_PROJECT_ID = str(ObjectId())
FAKE_INBOX_ID = str(ObjectId())
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_todo_doc(
    todo_id: str | None = None,
    user_id: str = FAKE_USER_ID,
    title: str = "Test Todo",
    completed: bool = False,
    project_id: str | None = None,
    priority: str = "none",
    labels: list[str] | None = None,
    subtasks: list[dict] | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Build a MongoDB todo document dict."""
    oid = ObjectId(todo_id) if todo_id else ObjectId()
    return {
        "_id": oid,
        "user_id": user_id,
        "title": title,
        "description": f"Description for {title}",
        "completed": completed,
        "project_id": project_id or FAKE_PROJECT_ID,
        "priority": priority,
        "labels": labels or [],
        "subtasks": subtasks or [],
        "due_date": None,
        "due_date_timezone": None,
        "workflow_id": workflow_id,
        "workflow_activated": True,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": None,
    }


def _make_project_doc(
    project_id: str | None = None,
    user_id: str = FAKE_USER_ID,
    name: str = "My Project",
    is_default: bool = False,
    color: str = "#FF0000",
) -> dict[str, Any]:
    oid = ObjectId(project_id) if project_id else ObjectId()
    return {
        "_id": oid,
        "user_id": user_id,
        "name": name,
        "description": f"Description for {name}",
        "color": color,
        "is_default": is_default,
        "created_at": NOW,
        "updated_at": NOW,
    }


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_todos_collection():
    with patch("app.services.todos.todo_service.todos_collection") as mock_col:
        # Default: return a cursor-like object from find()
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_col.find = MagicMock(return_value=mock_cursor)
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()
        mock_col.update_one = AsyncMock()
        mock_col.update_many = AsyncMock()
        mock_col.delete_one = AsyncMock()
        mock_col.delete_many = AsyncMock()
        mock_col.count_documents = AsyncMock(return_value=0)
        mock_col.aggregate = MagicMock()
        yield mock_col


@pytest.fixture
def mock_projects_collection():
    with patch("app.services.todos.todo_service.projects_collection") as mock_col:
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()
        mock_col.update_one = AsyncMock()
        mock_col.delete_one = AsyncMock()
        mock_col.find = MagicMock()
        mock_col.aggregate = MagicMock()
        mock_col.count_documents = AsyncMock(return_value=0)
        mock_col.find_one_and_update = AsyncMock(return_value=None)
        yield mock_col


@pytest.fixture
def mock_workflows_collection():
    with patch("app.services.todos.todo_service.workflows_collection") as mock_col:
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_col.find = MagicMock(return_value=mock_cursor)
        yield mock_col


@pytest.fixture
def mock_cache():
    with (
        patch(
            "app.services.todos.todo_service.get_cache",
            new_callable=AsyncMock,
        ) as m_get,
        patch(
            "app.services.todos.todo_service.set_cache",
            new_callable=AsyncMock,
        ) as m_set,
        patch(
            "app.services.todos.todo_service.delete_cache",
            new_callable=AsyncMock,
        ) as m_del,
        patch(
            "app.services.todos.todo_service.delete_cache_by_pattern",
            new_callable=AsyncMock,
        ) as m_del_pattern,
    ):
        m_get.return_value = None
        yield m_get, m_set, m_del, m_del_pattern


@pytest.fixture
def mock_vector_utils():
    with (
        patch(
            "app.services.todos.todo_service.store_todo_embedding",
            new_callable=AsyncMock,
        ) as m_store,
        patch(
            "app.services.todos.todo_service.update_todo_embedding",
            new_callable=AsyncMock,
        ) as m_update,
        patch(
            "app.services.todos.todo_service.delete_todo_embedding",
            new_callable=AsyncMock,
        ) as m_delete,
        patch(
            "app.services.todos.todo_service.bulk_index_todos",
            new_callable=AsyncMock,
        ) as m_bulk,
        patch(
            "app.services.todos.todo_service.vector_search",
            new_callable=AsyncMock,
        ) as m_vsearch,
        patch(
            "app.services.todos.todo_service.vector_hybrid_search",
            new_callable=AsyncMock,
        ) as m_hybrid,
    ):
        yield {
            "store": m_store,
            "update": m_update,
            "delete": m_delete,
            "bulk": m_bulk,
            "vector_search": m_vsearch,
            "hybrid_search": m_hybrid,
        }


@pytest.fixture
def mock_workflow_queue():
    with patch(
        "app.services.todos.todo_service.WorkflowQueueService",
    ) as mock_cls:
        mock_cls.queue_todo_workflow_generation = AsyncMock()
        yield mock_cls


@pytest.fixture
def mock_sync_subtask():
    with patch(
        "app.services.todos.todo_service.sync_subtask_to_goal_completion",
        new_callable=AsyncMock,
    ) as m:
        yield m


# ===========================================================================
# _get_workflow_categories_for_todos
# ===========================================================================


@pytest.mark.unit
class TestGetWorkflowCategories:
    async def test_no_todos_with_workflow_returns_empty(
        self, mock_workflows_collection
    ):
        todos = [_make_todo_doc()]  # no workflow_id
        result = await _get_workflow_categories_for_todos(todos, FAKE_USER_ID)
        assert result == {}

    async def test_empty_list_returns_empty(self, mock_workflows_collection):
        result = await _get_workflow_categories_for_todos([], FAKE_USER_ID)
        assert result == {}

    async def test_returns_categories_for_linked_workflows(
        self, mock_workflows_collection
    ):
        wf_id = "wf_123"
        todo = _make_todo_doc(workflow_id=wf_id)
        todo_id = str(todo["_id"])

        workflow_doc = {
            "_id": wf_id,
            "user_id": FAKE_USER_ID,
            "steps": [
                {"category": "email"},
                {"category": "calendar"},
                {"category": "email"},  # duplicate
            ],
        }

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[workflow_doc])
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        result = await _get_workflow_categories_for_todos([todo], FAKE_USER_ID)

        assert todo_id in result
        # Duplicates deduplicated
        assert result[todo_id] == ["email", "calendar"]

    async def test_categories_limited_to_three(self, mock_workflows_collection):
        wf_id = "wf_456"
        todo = _make_todo_doc(workflow_id=wf_id)

        workflow_doc = {
            "_id": wf_id,
            "user_id": FAKE_USER_ID,
            "steps": [
                {"category": "a"},
                {"category": "b"},
                {"category": "c"},
                {"category": "d"},
            ],
        }

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[workflow_doc])
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        result = await _get_workflow_categories_for_todos([todo], FAKE_USER_ID)
        todo_id = str(todo["_id"])
        assert len(result[todo_id]) == 3

    async def test_skips_steps_without_category(self, mock_workflows_collection):
        wf_id = "wf_789"
        todo = _make_todo_doc(workflow_id=wf_id)

        workflow_doc = {
            "_id": wf_id,
            "user_id": FAKE_USER_ID,
            "steps": [{"category": "email"}, {"no_category_key": True}, {}],
        }

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[workflow_doc])
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        result = await _get_workflow_categories_for_todos([todo], FAKE_USER_ID)
        todo_id = str(todo["_id"])
        assert result[todo_id] == ["email"]


# ===========================================================================
# TodoService._invalidate_cache
# ===========================================================================


@pytest.mark.unit
class TestInvalidateCache:
    async def test_update_minor_clears_individual_todo_cache(self, mock_cache):
        _, _, m_del, m_del_pattern = mock_cache
        await TodoService._invalidate_cache(
            FAKE_USER_ID, todo_id=FAKE_TODO_ID, operation="update_minor"
        )
        m_del.assert_any_await(f"todo:{FAKE_USER_ID}:{FAKE_TODO_ID}")
        # Should NOT clear list patterns
        m_del_pattern.assert_any_await  # stats/counts only

    async def test_update_clears_individual_and_list_caches(self, mock_cache):
        _, _, m_del, m_del_pattern = mock_cache
        await TodoService._invalidate_cache(
            FAKE_USER_ID, todo_id=FAKE_TODO_ID, operation="update"
        )
        m_del.assert_any_await(f"todo:{FAKE_USER_ID}:{FAKE_TODO_ID}")
        m_del_pattern.assert_any_await(f"todos:{FAKE_USER_ID}:*")

    async def test_delete_clears_individual_and_list_caches(self, mock_cache):
        _, _, m_del, m_del_pattern = mock_cache
        await TodoService._invalidate_cache(
            FAKE_USER_ID, todo_id=FAKE_TODO_ID, operation="delete"
        )
        m_del.assert_any_await(f"todo:{FAKE_USER_ID}:{FAKE_TODO_ID}")
        m_del_pattern.assert_any_await(f"todos:{FAKE_USER_ID}:*")

    async def test_create_clears_all_caches(self, mock_cache):
        _, _, _, m_del_pattern = mock_cache
        await TodoService._invalidate_cache(FAKE_USER_ID, operation="create")
        m_del_pattern.assert_any_await(f"todos:{FAKE_USER_ID}:*")
        m_del_pattern.assert_any_await(f"todo:{FAKE_USER_ID}:*")

    async def test_project_cache_invalidated_when_project_id_given(self, mock_cache):
        _, _, m_del, _ = mock_cache
        await TodoService._invalidate_cache(
            FAKE_USER_ID, project_id=FAKE_PROJECT_ID, operation="create"
        )
        m_del.assert_any_await(f"projects:{FAKE_USER_ID}")

    async def test_cache_failure_is_swallowed(self, mock_cache):
        _, _, m_del, _ = mock_cache
        m_del.side_effect = Exception("Redis down")
        # Should not raise
        await TodoService._invalidate_cache(FAKE_USER_ID, operation="create")


# ===========================================================================
# TodoService._get_or_create_inbox
# ===========================================================================


@pytest.mark.unit
class TestGetOrCreateInbox:
    async def test_returns_existing_inbox(self, mock_projects_collection):
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )
        result = await TodoService._get_or_create_inbox(FAKE_USER_ID)
        assert result == str(inbox_oid)

    async def test_creates_inbox_when_none_exists(self, mock_projects_collection):
        mock_projects_collection.find_one = AsyncMock(return_value=None)
        insert_result = MagicMock()
        insert_result.inserted_id = ObjectId()
        mock_projects_collection.insert_one = AsyncMock(return_value=insert_result)

        result = await TodoService._get_or_create_inbox(FAKE_USER_ID)
        assert result == str(insert_result.inserted_id)
        mock_projects_collection.insert_one.assert_awaited_once()
        call_doc = mock_projects_collection.insert_one.call_args[0][0]
        assert call_doc["is_default"] is True
        assert call_doc["name"] == "Inbox"


# ===========================================================================
# TodoService._build_query
# ===========================================================================


@pytest.mark.unit
class TestBuildQuery:
    async def test_default_query_uses_inbox(self, mock_projects_collection):
        """When no filters are specified the query defaults to inbox project."""
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )
        params = TodoSearchParams()
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["user_id"] == FAKE_USER_ID
        assert "project_id" in query

    async def test_text_search_adds_or_clause(self, mock_projects_collection):
        params = TodoSearchParams(q="urgent", mode=SearchMode.TEXT)
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert "$or" in query
        assert any("title" in cond for cond in query["$or"])

    async def test_project_id_filter(self, mock_projects_collection):
        params = TodoSearchParams(project_id="proj_123")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["project_id"] == "proj_123"

    async def test_completed_filter(self, mock_projects_collection):
        params = TodoSearchParams(completed=True, project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["completed"] is True

    async def test_priority_filter(self, mock_projects_collection):
        params = TodoSearchParams(priority=Priority.HIGH, project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["priority"] == "high"

    async def test_labels_filter(self, mock_projects_collection):
        params = TodoSearchParams(labels=["work", "urgent"], project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["labels"] == {"$in": ["work", "urgent"]}

    async def test_has_due_date_true(self, mock_projects_collection):
        params = TodoSearchParams(has_due_date=True, project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["due_date"] == {"$ne": None}

    async def test_has_due_date_false(self, mock_projects_collection):
        params = TodoSearchParams(has_due_date=False, project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["due_date"] is None

    async def test_due_date_range(self, mock_projects_collection):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 12, 31, tzinfo=timezone.utc)
        params = TodoSearchParams(
            due_date_start=start, due_date_end=end, project_id="x"
        )
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert query["due_date"]["$gte"] == start
        assert query["due_date"]["$lte"] == end

    async def test_overdue_true(self, mock_projects_collection):
        params = TodoSearchParams(overdue=True, project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert "$lt" in query["due_date"]
        assert query["completed"] is False

    async def test_overdue_false_with_has_due_date_not_false(
        self, mock_projects_collection
    ):
        params = TodoSearchParams(overdue=False, project_id="x")
        query = await TodoService._build_query(FAKE_USER_ID, params)
        assert "$or" in query

    async def test_no_inbox_default_when_filters_applied(
        self, mock_projects_collection
    ):
        """When any filter like completed is set, don't default to inbox."""
        params = TodoSearchParams(completed=False)
        query = await TodoService._build_query(FAKE_USER_ID, params)
        # project_id should not be forced to inbox
        assert query.get("completed") is False


# ===========================================================================
# TodoService.create_todo
# ===========================================================================


@pytest.mark.unit
class TestCreateTodo:
    async def test_success_without_project(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        """Creates todo in inbox when no project_id provided."""
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_todos_collection.insert_one = AsyncMock(return_value=mock_result)

        todo_doc = _make_todo_doc(todo_id=str(inserted_id))
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        todo_input = TodoModel(title="Buy groceries")

        with patch(
            "app.services.workflow.queue_service.WorkflowQueueService"
        ) as mock_wq:
            mock_wq.queue_todo_workflow_generation = AsyncMock()
            result = await TodoService.create_todo(todo_input, FAKE_USER_ID)

        assert isinstance(result, TodoResponse)
        assert result.title == "Test Todo"  # from the mock doc
        mock_todos_collection.insert_one.assert_awaited_once()

    async def test_success_with_explicit_project(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        """Creates todo in specified project after verifying it exists."""
        proj_oid = ObjectId(FAKE_PROJECT_ID)
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": proj_oid, "user_id": FAKE_USER_ID}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_todos_collection.insert_one = AsyncMock(return_value=mock_result)

        todo_doc = _make_todo_doc(todo_id=str(inserted_id), project_id=FAKE_PROJECT_ID)
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        todo_input = TodoModel(title="With project", project_id=FAKE_PROJECT_ID)

        with patch(
            "app.services.workflow.queue_service.WorkflowQueueService"
        ) as mock_wq:
            mock_wq.queue_todo_workflow_generation = AsyncMock()
            result = await TodoService.create_todo(todo_input, FAKE_USER_ID)

        assert isinstance(result, TodoResponse)

    async def test_invalid_project_raises_value_error(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        mock_projects_collection.find_one = AsyncMock(return_value=None)

        todo_input = TodoModel(title="Bad project", project_id=FAKE_PROJECT_ID)

        with pytest.raises(ValueError, match="not found"):
            await TodoService.create_todo(todo_input, FAKE_USER_ID)

    async def test_subtasks_get_ids_assigned(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_todos_collection.insert_one = AsyncMock(return_value=mock_result)

        todo_doc = _make_todo_doc(
            todo_id=str(inserted_id),
            subtasks=[{"id": "sub1", "title": "Step 1", "completed": False}],
        )
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        subtask = SubTask(title="Step 1")
        todo_input = TodoModel(title="With subtask", subtasks=[subtask])

        with patch(
            "app.services.workflow.queue_service.WorkflowQueueService"
        ) as mock_wq:
            mock_wq.queue_todo_workflow_generation = AsyncMock()
            result = await TodoService.create_todo(todo_input, FAKE_USER_ID)

        assert isinstance(result, TodoResponse)
        # Verify the dict passed to insert_one had subtask IDs generated
        insert_call = mock_todos_collection.insert_one.call_args[0][0]
        for st in insert_call["subtasks"]:
            assert st.get("id")

    async def test_insert_returns_none_raises_value_error(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_todos_collection.insert_one = AsyncMock(return_value=mock_result)
        # find_one returns None after insert (shouldn't happen but guards exist)
        mock_todos_collection.find_one = AsyncMock(return_value=None)

        todo_input = TodoModel(title="Ghost insert")

        with (
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService"
            ) as mock_wq,
            pytest.raises(ValueError, match="Failed to create todo"),
        ):
            mock_wq.queue_todo_workflow_generation = AsyncMock()
            await TodoService.create_todo(todo_input, FAKE_USER_ID)

    async def test_vector_index_failure_does_not_raise(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        """Embedding failure is logged but does not prevent todo creation."""
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_todos_collection.insert_one = AsyncMock(return_value=mock_result)

        todo_doc = _make_todo_doc(todo_id=str(inserted_id))
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        with (
            patch(
                "app.services.todos.todo_service.store_todo_embedding",
                new_callable=AsyncMock,
                side_effect=Exception("Embedding service down"),
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService"
            ) as mock_wq,
        ):
            mock_wq.queue_todo_workflow_generation = AsyncMock()
            result = await TodoService.create_todo(
                TodoModel(title="Still works"), FAKE_USER_ID
            )

        assert isinstance(result, TodoResponse)

    async def test_with_labels(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_todos_collection.insert_one = AsyncMock(return_value=mock_result)

        todo_doc = _make_todo_doc(todo_id=str(inserted_id), labels=["work", "urgent"])
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        todo_input = TodoModel(title="Labeled todo", labels=["work", "urgent"])

        with patch(
            "app.services.workflow.queue_service.WorkflowQueueService"
        ) as mock_wq:
            mock_wq.queue_todo_workflow_generation = AsyncMock()
            result = await TodoService.create_todo(todo_input, FAKE_USER_ID)

        assert result.labels == ["work", "urgent"]


# ===========================================================================
# TodoService.get_todo
# ===========================================================================


@pytest.mark.unit
class TestGetTodo:
    async def test_cache_hit_returns_cached(
        self, mock_todos_collection, mock_cache, mock_workflows_collection
    ):
        m_get, _, _, _ = mock_cache
        cached = {
            "id": FAKE_TODO_ID,
            "user_id": FAKE_USER_ID,
            "title": "Cached Todo",
            "description": None,
            "completed": False,
            "project_id": FAKE_PROJECT_ID,
            "priority": "none",
            "labels": [],
            "subtasks": [],
            "due_date": None,
            "due_date_timezone": None,
            "workflow_id": None,
            "workflow_activated": True,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
            "completed_at": None,
            "workflow_categories": [],
        }
        m_get.return_value = cached

        result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert isinstance(result, TodoResponse)
        assert result.title == "Cached Todo"
        mock_todos_collection.find_one.assert_not_awaited()

    async def test_found_in_db(
        self, mock_todos_collection, mock_cache, mock_workflows_collection
    ):
        m_get, m_set, _, _ = mock_cache
        m_get.return_value = None

        todo_doc = _make_todo_doc(todo_id=FAKE_TODO_ID)
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert isinstance(result, TodoResponse)
        assert result.id == FAKE_TODO_ID
        m_set.assert_awaited_once()

    async def test_not_found_raises_value_error(
        self, mock_todos_collection, mock_cache, mock_workflows_collection
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None
        mock_todos_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)

    async def test_enriches_with_workflow_categories(
        self, mock_todos_collection, mock_cache, mock_workflows_collection
    ):
        """Workflow categories are enriched on get_todo when workflow_id is present.

        Note: serialize_document() mutates the todo dict by popping _id, so we
        patch _get_workflow_categories_for_todos to return the expected mapping
        directly, avoiding the mutation side-effect.
        """
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        wf_id = "wf_test"
        todo_doc = _make_todo_doc(todo_id=FAKE_TODO_ID, workflow_id=wf_id)
        mock_todos_collection.find_one = AsyncMock(return_value=todo_doc)

        with patch(
            "app.services.todos.todo_service._get_workflow_categories_for_todos",
            new_callable=AsyncMock,
            return_value={FAKE_TODO_ID: ["email"]},
        ):
            result = await TodoService.get_todo(FAKE_TODO_ID, FAKE_USER_ID)
        assert result.workflow_categories == ["email"]


# ===========================================================================
# TodoService.list_todos
# ===========================================================================


@pytest.mark.unit
class TestListTodos:
    async def test_returns_paginated_response(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_workflows_collection,
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        # Setup inbox
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        mock_todos_collection.count_documents = AsyncMock(return_value=25)

        todos = [_make_todo_doc() for _ in range(10)]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=todos)
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        params = TodoSearchParams(page=1, per_page=10)
        result = await TodoService.list_todos(FAKE_USER_ID, params)

        assert isinstance(result, TodoListResponse)
        assert result.meta.total == 25
        assert result.meta.pages == 3
        assert result.meta.has_next is True
        assert result.meta.has_prev is False
        assert len(result.data) == 10

    async def test_cache_hit(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_workflows_collection,
    ):
        m_get, _, _, _ = mock_cache
        cached_response = {
            "data": [],
            "meta": {
                "total": 0,
                "page": 1,
                "per_page": 50,
                "pages": 0,
                "has_next": False,
                "has_prev": False,
            },
            "stats": None,
        }
        m_get.return_value = cached_response

        params = TodoSearchParams(project_id="proj_123")
        result = await TodoService.list_todos(FAKE_USER_ID, params)

        assert isinstance(result, TodoListResponse)
        assert result.meta.total == 0
        mock_todos_collection.find.assert_not_called()

    async def test_include_stats(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_workflows_collection,
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )
        mock_todos_collection.count_documents = AsyncMock(return_value=0)

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        # Mock aggregation for stats
        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[])
        mock_todos_collection.aggregate = MagicMock(return_value=agg_cursor)

        params = TodoSearchParams(include_stats=True)
        result = await TodoService.list_todos(FAKE_USER_ID, params)

        assert result.stats is not None

    async def test_semantic_search_delegates(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_workflows_collection,
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        mock_vector_utils["vector_search"].return_value = []

        params = TodoSearchParams(q="find me", mode=SearchMode.SEMANTIC)
        result = await TodoService.list_todos(FAKE_USER_ID, params)

        assert isinstance(result, TodoListResponse)
        mock_vector_utils["vector_search"].assert_awaited_once()

    async def test_hybrid_search_delegates(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_workflows_collection,
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        mock_vector_utils["hybrid_search"].return_value = []

        params = TodoSearchParams(q="find me", mode=SearchMode.HYBRID)
        result = await TodoService.list_todos(FAKE_USER_ID, params)

        assert isinstance(result, TodoListResponse)
        mock_vector_utils["hybrid_search"].assert_awaited_once()

    async def test_search_with_no_query_returns_empty(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_workflows_collection,
    ):
        """_search_todos returns empty result when q is None but mode is SEMANTIC."""
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        params = TodoSearchParams(q=None, mode=SearchMode.SEMANTIC)
        result = await TodoService.list_todos(FAKE_USER_ID, params)

        # Falls through to normal list since q is None
        # (only semantic/hybrid with q set triggers _search_todos)
        assert isinstance(result, TodoListResponse)

    async def test_text_search_with_query(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_workflows_collection,
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        mock_todos_collection.count_documents = AsyncMock(return_value=1)

        todo_doc = _make_todo_doc(title="urgent task")
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[todo_doc])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        params = TodoSearchParams(q="urgent", mode=SearchMode.TEXT)
        result = await TodoService.list_todos(FAKE_USER_ID, params)
        assert len(result.data) == 1


# ===========================================================================
# TodoService.update_todo
# ===========================================================================


@pytest.mark.unit
class TestUpdateTodo:
    async def test_success_partial_update(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID, title="Updated Title")
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        updates = TodoUpdateRequest(title="Updated Title")
        result = await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        assert isinstance(result, TodoResponse)
        mock_todos_collection.find_one_and_update.assert_awaited_once()

    async def test_not_found_raises_value_error(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=None)

        updates = TodoUpdateRequest(title="Nope")
        with pytest.raises(ValueError, match="not found"):
            await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

    async def test_completion_sets_completed_at(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID, completed=True)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        updates = TodoUpdateRequest(completed=True)
        await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        call_args = mock_todos_collection.find_one_and_update.call_args
        set_dict = call_args[0][1]["$set"]
        assert "completed_at" in set_dict
        assert set_dict["completed_at"] is not None

    async def test_uncomplete_clears_completed_at(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID, completed=False)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        updates = TodoUpdateRequest(completed=False)
        await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        call_args = mock_todos_collection.find_one_and_update.call_args
        set_dict = call_args[0][1]["$set"]
        assert set_dict["completed_at"] is None

    async def test_invalid_project_raises_value_error(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        mock_projects_collection.find_one = AsyncMock(return_value=None)

        updates = TodoUpdateRequest(project_id=FAKE_PROJECT_ID)
        with pytest.raises(ValueError, match="not found"):
            await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

    async def test_subtask_update_triggers_sync(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        subtask_id = str(uuid.uuid4())
        subtasks = [{"id": subtask_id, "title": "Step", "completed": True}]

        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID, subtasks=subtasks)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        updates = TodoUpdateRequest(
            subtasks=[SubTask(id=subtask_id, title="Step", completed=True)]
        )
        await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        mock_sync_subtask.assert_awaited()

    async def test_minor_update_uses_minor_cache_invalidation(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        """Title-only update should use update_minor cache strategy."""
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        _, _, m_del, m_del_pattern = mock_cache
        updates = TodoUpdateRequest(title="New title only")
        await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        # update_minor should clear individual cache but not list patterns
        m_del.assert_any_await(f"todo:{FAKE_USER_ID}:{FAKE_TODO_ID}")

    async def test_visibility_update_uses_full_cache_invalidation(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        """Priority change affects list ordering — should clear all list caches."""
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        _, _, _, m_del_pattern = mock_cache
        updates = TodoUpdateRequest(priority=Priority.HIGH)
        await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        m_del_pattern.assert_any_await(f"todos:{FAKE_USER_ID}:*")

    async def test_vector_index_failure_does_not_raise(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_sync_subtask,
    ):
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        with patch(
            "app.services.todos.todo_service.update_todo_embedding",
            new_callable=AsyncMock,
            side_effect=Exception("Vector fail"),
        ):
            updates = TodoUpdateRequest(title="Still works")
            result = await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)
            assert isinstance(result, TodoResponse)

    async def test_subtask_ids_assigned_when_missing(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
        mock_sync_subtask,
    ):
        updated_doc = _make_todo_doc(todo_id=FAKE_TODO_ID)
        mock_todos_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        updates = TodoUpdateRequest(subtasks=[SubTask(title="No ID subtask")])
        await TodoService.update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)

        call_args = mock_todos_collection.find_one_and_update.call_args
        set_dict = call_args[0][1]["$set"]
        for st in set_dict["subtasks"]:
            assert st.get("id"), "Subtask should have been assigned an ID"


# ===========================================================================
# TodoService.delete_todo
# ===========================================================================


@pytest.mark.unit
class TestDeleteTodo:
    async def test_success(self, mock_todos_collection, mock_cache, mock_vector_utils):
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_todos_collection.delete_one = AsyncMock(return_value=mock_result)

        await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)

        mock_todos_collection.delete_one.assert_awaited_once()
        mock_vector_utils["delete"].assert_awaited_once_with(FAKE_TODO_ID)

    async def test_not_found_raises_value_error(
        self, mock_todos_collection, mock_cache, mock_vector_utils
    ):
        mock_result = MagicMock()
        mock_result.deleted_count = 0
        mock_todos_collection.delete_one = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="not found"):
            await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)

    async def test_vector_delete_failure_does_not_raise(
        self, mock_todos_collection, mock_cache
    ):
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_todos_collection.delete_one = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.todos.todo_service.delete_todo_embedding",
            new_callable=AsyncMock,
            side_effect=Exception("Index fail"),
        ):
            await TodoService.delete_todo(FAKE_TODO_ID, FAKE_USER_ID)


# ===========================================================================
# TodoService.bulk_update_todos
# ===========================================================================


@pytest.mark.unit
class TestBulkUpdateTodos:
    async def test_success(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        todo_ids = [str(ObjectId()), str(ObjectId())]
        mock_result = MagicMock()
        mock_result.modified_count = 2
        mock_todos_collection.update_many = AsyncMock(return_value=mock_result)

        # Mock fetch for reindexing
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[_make_todo_doc(tid) for tid in todo_ids]
        )
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        request = BulkUpdateRequest(
            todo_ids=todo_ids,
            updates=TodoUpdateRequest(priority=Priority.HIGH),
        )
        result = await TodoService.bulk_update_todos(request, FAKE_USER_ID)

        assert isinstance(result, BulkOperationResponse)
        assert result.total == 2
        assert "Updated 2 todos" in result.message

    async def test_no_updates_provided(self, mock_todos_collection, mock_cache):
        request = BulkUpdateRequest(
            todo_ids=[str(ObjectId())],
            updates=TodoUpdateRequest(),
        )
        result = await TodoService.bulk_update_todos(request, FAKE_USER_ID)

        assert result.message == "No updates provided"
        assert result.success == []
        mock_todos_collection.update_many.assert_not_awaited()

    async def test_invalid_project_raises_value_error(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        mock_projects_collection.find_one = AsyncMock(return_value=None)
        request = BulkUpdateRequest(
            todo_ids=[str(ObjectId())],
            updates=TodoUpdateRequest(project_id=FAKE_PROJECT_ID),
        )

        with pytest.raises(ValueError, match="not found"):
            await TodoService.bulk_update_todos(request, FAKE_USER_ID)

    async def test_subtasks_in_bulk_update(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
        mock_vector_utils,
    ):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_todos_collection.update_many = AsyncMock(return_value=mock_result)

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[_make_todo_doc()])
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        request = BulkUpdateRequest(
            todo_ids=[str(ObjectId())],
            updates=TodoUpdateRequest(subtasks=[SubTask(title="Bulk step")]),
        )
        result = await TodoService.bulk_update_todos(request, FAKE_USER_ID)
        assert result.total == 1


# ===========================================================================
# TodoService.bulk_delete_todos
# ===========================================================================


@pytest.mark.unit
class TestBulkDeleteTodos:
    async def test_success(self, mock_todos_collection, mock_cache, mock_vector_utils):
        todo_ids = [str(ObjectId()), str(ObjectId())]

        # Mock pre-delete fetch
        todos_docs = [_make_todo_doc(tid) for tid in todo_ids]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=todos_docs)
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        mock_result = MagicMock()
        mock_result.deleted_count = 2
        mock_todos_collection.delete_many = AsyncMock(return_value=mock_result)

        result = await TodoService.bulk_delete_todos(todo_ids, FAKE_USER_ID)

        assert isinstance(result, BulkOperationResponse)
        assert "Deleted 2 todos" in result.message

    async def test_vector_cleanup_failure_swallowed(
        self, mock_todos_collection, mock_cache
    ):
        todo_ids = [str(ObjectId())]

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[_make_todo_doc(todo_ids[0])])
        mock_todos_collection.find = MagicMock(return_value=mock_cursor)

        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_todos_collection.delete_many = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.todos.todo_service.delete_todo_embedding",
            new_callable=AsyncMock,
            side_effect=Exception("Cleanup fail"),
        ):
            result = await TodoService.bulk_delete_todos(todo_ids, FAKE_USER_ID)
            assert result.total == 1


# ===========================================================================
# TodoService.bulk_move_todos
# ===========================================================================


@pytest.mark.unit
class TestBulkMoveTodos:
    async def test_success(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        target_project_oid = ObjectId(FAKE_PROJECT_ID)
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": target_project_oid, "user_id": FAKE_USER_ID}
        )

        todo_ids = [str(ObjectId()), str(ObjectId())]
        mock_result = MagicMock()
        mock_result.modified_count = 2
        mock_todos_collection.update_many = AsyncMock(return_value=mock_result)

        request = BulkMoveRequest(todo_ids=todo_ids, project_id=FAKE_PROJECT_ID)
        result = await TodoService.bulk_move_todos(request, FAKE_USER_ID)

        assert isinstance(result, BulkOperationResponse)
        assert "Moved 2 todos" in result.message

    async def test_invalid_project_raises_value_error(
        self, mock_todos_collection, mock_projects_collection, mock_cache
    ):
        mock_projects_collection.find_one = AsyncMock(return_value=None)

        request = BulkMoveRequest(
            todo_ids=[str(ObjectId())], project_id=FAKE_PROJECT_ID
        )

        with pytest.raises(ValueError, match="not found"):
            await TodoService.bulk_move_todos(request, FAKE_USER_ID)

    async def test_zero_modified_returns_empty_success(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        target_project_oid = ObjectId(FAKE_PROJECT_ID)
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": target_project_oid, "user_id": FAKE_USER_ID}
        )

        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_todos_collection.update_many = AsyncMock(return_value=mock_result)

        request = BulkMoveRequest(
            todo_ids=[str(ObjectId())], project_id=FAKE_PROJECT_ID
        )
        result = await TodoService.bulk_move_todos(request, FAKE_USER_ID)
        assert result.success == []


# ===========================================================================
# TodoService._calculate_stats
# ===========================================================================


@pytest.mark.unit
class TestCalculateStats:
    async def test_returns_cached_stats(self, mock_todos_collection, mock_cache):
        m_get, _, _, _ = mock_cache
        cached_stats = {
            "total": 10,
            "completed": 5,
            "pending": 5,
            "overdue": 1,
            "by_priority": {"high": 3},
            "by_project": {},
            "completion_rate": 50.0,
            "labels": None,
        }
        m_get.return_value = cached_stats

        result = await TodoService._calculate_stats(FAKE_USER_ID)
        assert isinstance(result, TodoStats)
        assert result.total == 10

    async def test_computes_from_aggregation(self, mock_todos_collection, mock_cache):
        m_get, m_set, _, _ = mock_cache
        m_get.return_value = None

        agg_result = [
            {
                "total": [{"count": 20}],
                "completed": [{"count": 8}],
                "overdue": [{"count": 2}],
                "by_priority": [
                    {"_id": "high", "count": 5},
                    {"_id": "low", "count": 15},
                ],
                "by_project": [{"_id": "proj_1", "count": 20}],
                "labels": [
                    {"_id": "work", "count": 10},
                    {"_id": "personal", "count": 5},
                ],
            }
        ]
        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=agg_result)
        mock_todos_collection.aggregate = MagicMock(return_value=agg_cursor)

        result = await TodoService._calculate_stats(FAKE_USER_ID)

        assert result.total == 20
        assert result.completed == 8
        assert result.pending == 12
        assert result.overdue == 2
        assert result.completion_rate == pytest.approx(40.0)
        assert result.by_priority == {"high": 5, "low": 15}
        assert result.labels is not None
        assert len(result.labels) == 2
        m_set.assert_awaited_once()

    async def test_empty_aggregation_returns_default_stats(
        self, mock_todos_collection, mock_cache
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[])
        mock_todos_collection.aggregate = MagicMock(return_value=agg_cursor)

        result = await TodoService._calculate_stats(FAKE_USER_ID)
        assert result.total == 0
        assert result.completion_rate == pytest.approx(0.0)

    async def test_zero_total_no_division_error(
        self, mock_todos_collection, mock_cache
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        agg_result = [
            {
                "total": [],
                "completed": [],
                "overdue": [],
                "by_priority": [],
                "by_project": [],
                "labels": [],
            }
        ]
        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=agg_result)
        mock_todos_collection.aggregate = MagicMock(return_value=agg_cursor)

        result = await TodoService._calculate_stats(FAKE_USER_ID)
        assert result.total == 0
        assert result.completion_rate == pytest.approx(0.0)


# ===========================================================================
# TodoService._search_todos
# ===========================================================================


@pytest.mark.unit
class TestSearchTodos:
    async def test_empty_query_returns_empty_list(
        self, mock_todos_collection, mock_cache
    ):
        params = TodoSearchParams(q=None, mode=SearchMode.SEMANTIC)
        result = await TodoService._search_todos(FAKE_USER_ID, params)
        assert result.meta.total == 0
        assert result.data == []

    async def test_semantic_search_pagination(
        self, mock_todos_collection, mock_cache, mock_vector_utils
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        # Return 15 results; request page 2 with per_page=10
        fake_responses = [
            TodoResponse(
                id=str(ObjectId()),
                user_id=FAKE_USER_ID,
                title=f"Result {i}",
                labels=[],
                subtasks=[],
                priority=Priority.NONE,
                completed=False,
                project_id=FAKE_PROJECT_ID,
                created_at=NOW,
                updated_at=NOW,
            )
            for i in range(15)
        ]
        mock_vector_utils["vector_search"].return_value = fake_responses

        params = TodoSearchParams(
            q="test query", mode=SearchMode.SEMANTIC, page=2, per_page=10
        )
        result = await TodoService._search_todos(FAKE_USER_ID, params)

        assert result.meta.total == 15
        assert len(result.data) == 5  # Remaining items on page 2
        assert result.meta.has_prev is True

    async def test_hybrid_search_with_stats(
        self, mock_todos_collection, mock_cache, mock_vector_utils
    ):
        m_get, _, _, _ = mock_cache
        m_get.return_value = None

        mock_vector_utils["hybrid_search"].return_value = []

        # Mock stats aggregation
        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[])
        mock_todos_collection.aggregate = MagicMock(return_value=agg_cursor)

        params = TodoSearchParams(
            q="hybrid test", mode=SearchMode.HYBRID, include_stats=True
        )
        result = await TodoService._search_todos(FAKE_USER_ID, params)
        assert result.stats is not None


# ===========================================================================
# TodoService.reindex_todos
# ===========================================================================


@pytest.mark.unit
class TestReindexTodos:
    async def test_delegates_to_bulk_index(self, mock_vector_utils):
        mock_vector_utils["bulk"].return_value = 42

        result = await TodoService.reindex_todos(FAKE_USER_ID, batch_size=50)

        assert result["indexed"] == 42
        assert result["status"] == "completed"
        mock_vector_utils["bulk"].assert_awaited_once_with(FAKE_USER_ID, 50)


# ===========================================================================
# ProjectService
# ===========================================================================


@pytest.mark.unit
class TestProjectServiceCreate:
    async def test_success(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        # Inbox exists
        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_projects_collection.insert_one = AsyncMock(return_value=mock_result)

        project_doc = _make_project_doc(project_id=str(inserted_id))

        # find_one after insert
        async def _find_one_side_effect(query, *args, **kwargs):
            if "is_default" in query:
                return {"_id": inbox_oid, "is_default": True}
            return project_doc

        mock_projects_collection.find_one = AsyncMock(side_effect=_find_one_side_effect)

        mock_todos_collection.count_documents = AsyncMock(return_value=0)

        project_input = ProjectCreate(name="Work", color="#FF0000")
        result = await ProjectService.create_project(project_input, FAKE_USER_ID)

        assert isinstance(result, ProjectResponse)
        assert result.todo_count == 0

    async def test_insert_failure_raises_value_error(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        inbox_oid = ObjectId()

        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_projects_collection.insert_one = AsyncMock(return_value=mock_result)

        # find_one returns inbox for _get_or_create_inbox, None for the created project
        call_count = 0

        async def _find_one_side_effect(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"_id": inbox_oid, "is_default": True}
            return None

        mock_projects_collection.find_one = AsyncMock(side_effect=_find_one_side_effect)

        with pytest.raises(ValueError, match="Failed to create project"):
            await ProjectService.create_project(
                ProjectCreate(name="Broken"), FAKE_USER_ID
            )


@pytest.mark.unit
class TestProjectServiceList:
    async def test_cache_hit(self, mock_projects_collection, mock_cache):
        m_get, _, _, _ = mock_cache
        cached = [
            {
                "id": str(ObjectId()),
                "user_id": FAKE_USER_ID,
                "name": "Inbox",
                "description": None,
                "color": "#6B7280",
                "is_default": True,
                "todo_count": 5,
                "created_at": NOW.isoformat(),
                "updated_at": NOW.isoformat(),
            }
        ]
        m_get.return_value = cached

        result = await ProjectService.list_projects(FAKE_USER_ID)
        assert len(result) == 1
        assert isinstance(result[0], ProjectResponse)

    async def test_fetches_from_db_and_caches(
        self, mock_projects_collection, mock_cache
    ):
        m_get, m_set, _, _ = mock_cache
        m_get.return_value = None

        inbox_oid = ObjectId()
        mock_projects_collection.find_one = AsyncMock(
            return_value={"_id": inbox_oid, "is_default": True}
        )

        project_docs = [
            {
                **_make_project_doc(is_default=True, name="Inbox"),
                "todo_count": 3,
            }
        ]
        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=project_docs)
        mock_projects_collection.aggregate = MagicMock(return_value=agg_cursor)

        result = await ProjectService.list_projects(FAKE_USER_ID)
        assert len(result) == 1
        m_set.assert_awaited_once()


@pytest.mark.unit
class TestProjectServiceUpdate:
    async def test_success(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        existing = _make_project_doc(project_id=FAKE_PROJECT_ID, is_default=False)
        updated = {**existing, "name": "Renamed"}

        mock_projects_collection.find_one = AsyncMock(return_value=existing)
        mock_projects_collection.find_one_and_update = AsyncMock(return_value=updated)
        mock_todos_collection.count_documents = AsyncMock(return_value=10)

        result = await ProjectService.update_project(
            FAKE_PROJECT_ID,
            UpdateProjectRequest(name="Renamed"),
            FAKE_USER_ID,
        )
        assert isinstance(result, ProjectResponse)

    async def test_not_found_raises_value_error(
        self, mock_projects_collection, mock_cache
    ):
        mock_projects_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await ProjectService.update_project(
                FAKE_PROJECT_ID,
                UpdateProjectRequest(name="X"),
                FAKE_USER_ID,
            )

    async def test_cannot_update_default_inbox(
        self, mock_projects_collection, mock_cache
    ):
        inbox_doc = _make_project_doc(
            project_id=FAKE_PROJECT_ID, is_default=True, name="Inbox"
        )
        mock_projects_collection.find_one = AsyncMock(return_value=inbox_doc)

        with pytest.raises(ValueError, match="Cannot update default"):
            await ProjectService.update_project(
                FAKE_PROJECT_ID,
                UpdateProjectRequest(name="Hack Inbox"),
                FAKE_USER_ID,
            )


@pytest.mark.unit
class TestProjectServiceDelete:
    async def test_success_moves_todos_to_inbox(
        self,
        mock_todos_collection,
        mock_projects_collection,
        mock_cache,
    ):
        project_doc = _make_project_doc(project_id=FAKE_PROJECT_ID, is_default=False)

        inbox_oid = ObjectId()
        call_count = 0

        async def _find_one_side_effect(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return project_doc
            # Second call: _get_or_create_inbox
            return {"_id": inbox_oid, "is_default": True}

        mock_projects_collection.find_one = AsyncMock(side_effect=_find_one_side_effect)
        mock_todos_collection.update_many = AsyncMock()
        mock_projects_collection.delete_one = AsyncMock()

        await ProjectService.delete_project(FAKE_PROJECT_ID, FAKE_USER_ID)

        mock_todos_collection.update_many.assert_awaited_once()
        mock_projects_collection.delete_one.assert_awaited_once()

    async def test_not_found_raises_value_error(
        self, mock_projects_collection, mock_cache
    ):
        mock_projects_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await ProjectService.delete_project(FAKE_PROJECT_ID, FAKE_USER_ID)

    async def test_cannot_delete_default_inbox(
        self, mock_projects_collection, mock_cache
    ):
        inbox_doc = _make_project_doc(
            project_id=FAKE_PROJECT_ID, is_default=True, name="Inbox"
        )
        mock_projects_collection.find_one = AsyncMock(return_value=inbox_doc)

        with pytest.raises(ValueError, match="Cannot delete default"):
            await ProjectService.delete_project(FAKE_PROJECT_ID, FAKE_USER_ID)


# ===========================================================================
# Compatibility wrapper functions
# ===========================================================================


@pytest.mark.unit
class TestCompatibilityWrappers:
    async def test_create_todo_wrapper(self):
        with patch.object(
            TodoService, "create_todo", new_callable=AsyncMock
        ) as mock_create:
            mock_response = MagicMock(spec=TodoResponse)
            mock_create.return_value = mock_response

            todo_input = TodoModel(title="Wrapper test")
            result = await create_todo(todo_input, FAKE_USER_ID)

            assert result == mock_response
            mock_create.assert_awaited_once_with(todo_input, FAKE_USER_ID)

    async def test_get_todo_wrapper(self):
        with patch.object(TodoService, "get_todo", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock(spec=TodoResponse)
            mock_get.return_value = mock_response

            result = await get_todo(FAKE_TODO_ID, FAKE_USER_ID)
            assert result == mock_response

    async def test_get_all_todos_wrapper(self):
        with patch.object(
            TodoService, "list_todos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=1,
                    per_page=50,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )
            result = await get_all_todos(FAKE_USER_ID, limit=10)
            assert result == []

    async def test_update_todo_wrapper(self):
        with patch.object(
            TodoService, "update_todo", new_callable=AsyncMock
        ) as mock_update:
            mock_response = MagicMock(spec=TodoResponse)
            mock_update.return_value = mock_response
            updates = TodoUpdateRequest(title="Wrap")
            result = await update_todo(FAKE_TODO_ID, updates, FAKE_USER_ID)
            assert result == mock_response

    async def test_delete_todo_wrapper(self):
        with patch.object(
            TodoService, "delete_todo", new_callable=AsyncMock
        ) as mock_del:
            await delete_todo(FAKE_TODO_ID, FAKE_USER_ID)
            mock_del.assert_awaited_once()

    async def test_search_todos_wrapper(self):
        with patch.object(
            TodoService, "list_todos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=1,
                    per_page=100,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )
            result = await search_todos("query", FAKE_USER_ID)
            assert result == []

    async def test_get_todo_stats_wrapper(self):
        with patch.object(
            TodoService, "_calculate_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = TodoStats(total=5, completed=2, pending=3)
            result = await get_todo_stats(FAKE_USER_ID)
            assert result["total"] == 5

    async def test_get_todos_by_date_range_wrapper(self):
        with patch.object(
            TodoService, "list_todos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=1,
                    per_page=100,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            end = datetime(2026, 12, 31, tzinfo=timezone.utc)
            result = await get_todos_by_date_range(FAKE_USER_ID, start, end)
            assert result == []

    async def test_get_all_labels_wrapper(self):
        with patch.object(
            TodoService, "_calculate_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = TodoStats(labels=[{"name": "work", "count": 5}])
            result = await get_all_labels(FAKE_USER_ID)
            assert len(result) == 1
            assert result[0]["name"] == "work"

    async def test_get_all_labels_empty(self):
        with patch.object(
            TodoService, "_calculate_stats", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = TodoStats()
            result = await get_all_labels(FAKE_USER_ID)
            assert result == []

    async def test_get_todos_by_label_wrapper(self):
        with patch.object(
            TodoService, "list_todos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=1,
                    per_page=100,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )
            result = await get_todos_by_label(FAKE_USER_ID, "work")
            assert result == []

    async def test_semantic_search_todos_wrapper(self):
        with patch.object(
            TodoService, "list_todos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=1,
                    per_page=20,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )
            result = await semantic_search_todos("test", FAKE_USER_ID)
            assert result == []
            # Verify mode was set to SEMANTIC
            call_args = mock_list.call_args[0]
            assert call_args[1].mode == SearchMode.SEMANTIC

    async def test_hybrid_search_todos_wrapper(self):
        with patch.object(
            TodoService, "list_todos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=1,
                    per_page=20,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )
            result = await hybrid_search_todos("test", FAKE_USER_ID)
            assert result == []
            call_args = mock_list.call_args[0]
            assert call_args[1].mode == SearchMode.HYBRID

    async def test_create_project_wrapper(self):
        with patch.object(
            ProjectService, "create_project", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = MagicMock(spec=ProjectResponse)
            await create_project(ProjectCreate(name="Wrap"), FAKE_USER_ID)
            mock_create.assert_awaited_once()

    async def test_get_all_projects_wrapper(self):
        with patch.object(
            ProjectService, "list_projects", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = []
            result = await get_all_projects(FAKE_USER_ID)
            assert result == []

    async def test_update_project_wrapper(self):
        with patch.object(
            ProjectService, "update_project", new_callable=AsyncMock
        ) as mock_up:
            mock_up.return_value = MagicMock(spec=ProjectResponse)
            await update_project(
                FAKE_PROJECT_ID,
                UpdateProjectRequest(name="X"),
                FAKE_USER_ID,
            )
            mock_up.assert_awaited_once()

    async def test_delete_project_wrapper(self):
        with patch.object(
            ProjectService, "delete_project", new_callable=AsyncMock
        ) as mock_del:
            await delete_project(FAKE_PROJECT_ID, FAKE_USER_ID)
            mock_del.assert_awaited_once()

    async def test_bulk_index_existing_todos_wrapper(self):
        with patch.object(
            TodoService, "reindex_todos", new_callable=AsyncMock
        ) as mock_reindex:
            mock_reindex.return_value = {"indexed": 10}
            result = await bulk_index_existing_todos(FAKE_USER_ID, 50)
            assert result == {"indexed": 10}


# ===========================================================================
# todo_bulk_service (standalone functions)
# ===========================================================================


@pytest.fixture
def mock_bulk_todos_collection():
    with patch("app.services.todos.todo_bulk_service.todos_collection") as mock_col:
        mock_col.update_many = AsyncMock()
        mock_col.delete_many = AsyncMock()
        mock_col.find_one = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_col.find = MagicMock(return_value=mock_cursor)
        yield mock_col


@pytest.fixture
def mock_bulk_cache():
    with patch(
        "app.services.todos.todo_bulk_service.delete_cache",
        new_callable=AsyncMock,
    ) as m_del:
        yield m_del


@pytest.mark.unit
class TestBulkCompleteTodos:
    async def test_success(self, mock_bulk_todos_collection, mock_bulk_cache):
        todo_ids = [str(ObjectId()), str(ObjectId())]

        mock_result = MagicMock()
        mock_result.modified_count = 2
        mock_bulk_todos_collection.update_many = AsyncMock(return_value=mock_result)

        todos = [_make_todo_doc(tid) for tid in todo_ids]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=todos)
        mock_bulk_todos_collection.find = MagicMock(return_value=mock_cursor)

        result = await bulk_complete_todos(todo_ids, FAKE_USER_ID)
        assert len(result) == 2
        assert all(isinstance(r, TodoResponse) for r in result)

    async def test_none_modified_raises_404(
        self, mock_bulk_todos_collection, mock_bulk_cache
    ):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_bulk_todos_collection.update_many = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await bulk_complete_todos([str(ObjectId())], FAKE_USER_ID)
        assert exc_info.value.status_code == 404

    async def test_db_error_raises_500(
        self, mock_bulk_todos_collection, mock_bulk_cache
    ):
        mock_bulk_todos_collection.update_many = AsyncMock(
            side_effect=Exception("DB error")
        )

        with pytest.raises(HTTPException) as exc_info:
            await bulk_complete_todos([str(ObjectId())], FAKE_USER_ID)
        assert exc_info.value.status_code == 500


@pytest.mark.unit
class TestBulkServiceMoveTodos:
    async def test_success(self, mock_bulk_todos_collection, mock_bulk_cache):
        with patch("app.db.mongodb.collections.projects_collection") as mock_projects:
            mock_projects.find_one = AsyncMock(
                return_value={
                    "_id": ObjectId(FAKE_PROJECT_ID),
                    "user_id": FAKE_USER_ID,
                }
            )

            todo_ids = [str(ObjectId())]

            # Old todos query
            old_cursor = AsyncMock()
            old_cursor.to_list = AsyncMock(
                return_value=[{"_id": ObjectId(todo_ids[0]), "project_id": "old_proj"}]
            )

            # Updated todos query
            updated_cursor = AsyncMock()
            updated_cursor.to_list = AsyncMock(
                return_value=[_make_todo_doc(todo_ids[0])]
            )

            # Two find calls: first for old project IDs, second for updated todos
            mock_bulk_todos_collection.find = MagicMock(
                side_effect=[old_cursor, updated_cursor]
            )

            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_bulk_todos_collection.update_many = AsyncMock(return_value=mock_result)

            result = await bulk_service_move_todos(
                todo_ids, FAKE_PROJECT_ID, FAKE_USER_ID
            )
            assert len(result) == 1

    async def test_project_not_found_raises_404(
        self, mock_bulk_todos_collection, mock_bulk_cache
    ):
        with patch("app.db.mongodb.collections.projects_collection") as mock_projects:
            mock_projects.find_one = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await bulk_service_move_todos(
                    [str(ObjectId())], FAKE_PROJECT_ID, FAKE_USER_ID
                )
            assert exc_info.value.status_code == 404

    async def test_none_modified_raises_404(
        self, mock_bulk_todos_collection, mock_bulk_cache
    ):
        with patch("app.db.mongodb.collections.projects_collection") as mock_projects:
            mock_projects.find_one = AsyncMock(
                return_value={
                    "_id": ObjectId(FAKE_PROJECT_ID),
                    "user_id": FAKE_USER_ID,
                }
            )

            old_cursor = AsyncMock()
            old_cursor.to_list = AsyncMock(return_value=[])
            mock_bulk_todos_collection.find = MagicMock(return_value=old_cursor)

            mock_result = MagicMock()
            mock_result.modified_count = 0
            mock_bulk_todos_collection.update_many = AsyncMock(return_value=mock_result)

            with pytest.raises(HTTPException) as exc_info:
                await bulk_service_move_todos(
                    [str(ObjectId())], FAKE_PROJECT_ID, FAKE_USER_ID
                )
            assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestBulkServiceDeleteTodos:
    async def test_success(self, mock_bulk_todos_collection, mock_bulk_cache):
        todo_ids = [str(ObjectId())]

        # Pre-delete fetch
        pre_cursor = AsyncMock()
        pre_cursor.to_list = AsyncMock(
            return_value=[{"_id": ObjectId(todo_ids[0]), "project_id": FAKE_PROJECT_ID}]
        )
        mock_bulk_todos_collection.find = MagicMock(return_value=pre_cursor)

        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_bulk_todos_collection.delete_many = AsyncMock(return_value=mock_result)

        await bulk_service_delete_todos(todo_ids, FAKE_USER_ID)
        mock_bulk_todos_collection.delete_many.assert_awaited_once()

    async def test_none_deleted_raises_404(
        self, mock_bulk_todos_collection, mock_bulk_cache
    ):
        pre_cursor = AsyncMock()
        pre_cursor.to_list = AsyncMock(return_value=[])
        mock_bulk_todos_collection.find = MagicMock(return_value=pre_cursor)

        mock_result = MagicMock()
        mock_result.deleted_count = 0
        mock_bulk_todos_collection.delete_many = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await bulk_service_delete_todos([str(ObjectId())], FAKE_USER_ID)
        assert exc_info.value.status_code == 404

    async def test_db_error_raises_500(
        self, mock_bulk_todos_collection, mock_bulk_cache
    ):
        pre_cursor = AsyncMock()
        pre_cursor.to_list = AsyncMock(return_value=[])
        mock_bulk_todos_collection.find = MagicMock(return_value=pre_cursor)

        mock_bulk_todos_collection.delete_many = AsyncMock(
            side_effect=Exception("DB error")
        )

        with pytest.raises(HTTPException) as exc_info:
            await bulk_service_delete_todos([str(ObjectId())], FAKE_USER_ID)
        assert exc_info.value.status_code == 500


# ===========================================================================
# todo_count_service
# ===========================================================================


@pytest.fixture
def mock_count_todos_collection():
    with patch("app.services.todos.todo_count_service.todos_collection") as mock_col:
        mock_col.count_documents = AsyncMock(return_value=0)
        yield mock_col


@pytest.fixture
def mock_count_projects_collection():
    with patch("app.services.todos.todo_count_service.projects_collection") as mock_col:
        mock_col.update_one = AsyncMock()
        mock_col.find = MagicMock()
        yield mock_col


@pytest.mark.unit
class TestUpdateProjectTodoCount:
    async def test_updates_count(
        self, mock_count_todos_collection, mock_count_projects_collection
    ):
        mock_count_todos_collection.count_documents = AsyncMock(return_value=7)

        await update_project_todo_count(FAKE_PROJECT_ID, FAKE_USER_ID)

        mock_count_projects_collection.update_one.assert_awaited_once()
        call_args = mock_count_projects_collection.update_one.call_args
        assert call_args[0][1] == {"$set": {"todo_count": 7}}

    async def test_exception_is_caught(
        self, mock_count_todos_collection, mock_count_projects_collection
    ):
        mock_count_todos_collection.count_documents = AsyncMock(
            side_effect=Exception("DB down")
        )
        # Should not raise
        await update_project_todo_count(FAKE_PROJECT_ID, FAKE_USER_ID)


@pytest.mark.unit
class TestSyncAllProjectCounts:
    async def test_syncs_all_projects(
        self, mock_count_todos_collection, mock_count_projects_collection
    ):
        projects = [
            {"_id": ObjectId(), "is_default": False},
            {"_id": ObjectId(), "is_default": True},
        ]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=projects)
        mock_count_projects_collection.find = MagicMock(return_value=mock_cursor)

        mock_count_todos_collection.count_documents = AsyncMock(return_value=3)

        await sync_all_project_counts(FAKE_USER_ID)

        assert mock_count_projects_collection.update_one.await_count == 2

    async def test_exception_is_caught(
        self, mock_count_todos_collection, mock_count_projects_collection
    ):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(side_effect=Exception("DB down"))
        mock_count_projects_collection.find = MagicMock(return_value=mock_cursor)

        # Should not raise
        await sync_all_project_counts(FAKE_USER_ID)


# ===========================================================================
# sync_service
# ===========================================================================


@pytest.fixture
def mock_sync_goals_collection():
    with patch("app.services.todos.sync_service.goals_collection") as mock_col:
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.update_one = AsyncMock()
        yield mock_col


@pytest.fixture
def mock_sync_todos_collection():
    with patch("app.services.todos.sync_service.todos_collection") as mock_col:
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.update_one = AsyncMock()
        yield mock_col


@pytest.fixture
def mock_sync_projects_collection():
    with patch("app.services.todos.sync_service.projects_collection") as mock_col:
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()
        yield mock_col


@pytest.fixture
def mock_sync_cache():
    with (
        patch(
            "app.services.todos.sync_service.delete_cache",
            new_callable=AsyncMock,
        ) as m_del,
        patch(
            "app.services.todos.sync_service.delete_cache_by_pattern",
            new_callable=AsyncMock,
        ) as m_del_pattern,
    ):
        yield m_del, m_del_pattern


@pytest.mark.unit
class TestSyncGoalNodeCompletion:
    async def test_success(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        goal_id = str(ObjectId())
        node_id = "node_1"
        subtask_id = "sub_1"
        todo_id = str(ObjectId())

        goal_doc = {
            "_id": ObjectId(goal_id),
            "user_id": FAKE_USER_ID,
            "todo_id": todo_id,
            "roadmap": {
                "nodes": [
                    {
                        "id": node_id,
                        "data": {
                            "label": "Step 1",
                            "subtask_id": subtask_id,
                            "isComplete": False,
                        },
                    }
                ]
            },
        }
        mock_sync_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_sync_todos_collection.update_one = AsyncMock(return_value=mock_result)

        # After update, fetch todo for project_id
        mock_sync_todos_collection.find_one = AsyncMock(
            return_value={"project_id": FAKE_PROJECT_ID}
        )

        result = await sync_goal_node_completion(goal_id, node_id, True, FAKE_USER_ID)
        assert result is True

    async def test_goal_not_found_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        mock_sync_goals_collection.find_one = AsyncMock(return_value=None)

        result = await sync_goal_node_completion(
            str(ObjectId()), "node_1", True, FAKE_USER_ID
        )
        assert result is False

    async def test_node_not_found_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        goal_doc = {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "todo_id": str(ObjectId()),
            "roadmap": {"nodes": [{"id": "other_node", "data": {}}]},
        }
        mock_sync_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        result = await sync_goal_node_completion(
            str(goal_doc["_id"]), "missing_node", True, FAKE_USER_ID
        )
        assert result is False

    async def test_missing_subtask_id_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        goal_doc = {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "todo_id": str(ObjectId()),
            "roadmap": {
                "nodes": [
                    {
                        "id": "node_1",
                        "data": {"label": "No subtask_id"},
                    }
                ]
            },
        }
        mock_sync_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        result = await sync_goal_node_completion(
            str(goal_doc["_id"]), "node_1", True, FAKE_USER_ID
        )
        assert result is False

    async def test_no_todo_modified_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        goal_doc = {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "todo_id": str(ObjectId()),
            "roadmap": {
                "nodes": [
                    {
                        "id": "node_1",
                        "data": {"subtask_id": "sub_1"},
                    }
                ]
            },
        }
        mock_sync_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_sync_todos_collection.update_one = AsyncMock(return_value=mock_result)

        result = await sync_goal_node_completion(
            str(goal_doc["_id"]), "node_1", True, FAKE_USER_ID
        )
        assert result is False

    async def test_exception_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        mock_sync_goals_collection.find_one = AsyncMock(
            side_effect=Exception("DB error")
        )

        result = await sync_goal_node_completion(
            str(ObjectId()), "node_1", True, FAKE_USER_ID
        )
        assert result is False


@pytest.mark.unit
class TestSyncSubtaskToGoalCompletion:
    async def test_success(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        goal_oid = ObjectId()
        goal_doc = {
            "_id": goal_oid,
            "todo_project_id": FAKE_PROJECT_ID,
        }
        mock_sync_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_sync_goals_collection.update_one = AsyncMock(return_value=mock_result)

        result = await sync_subtask_to_goal_completion(
            FAKE_TODO_ID, "sub_1", True, FAKE_USER_ID
        )
        assert result is True

    async def test_goal_not_found_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        mock_sync_goals_collection.find_one = AsyncMock(return_value=None)

        result = await sync_subtask_to_goal_completion(
            FAKE_TODO_ID, "sub_1", True, FAKE_USER_ID
        )
        assert result is False

    async def test_no_node_modified_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        goal_doc = {"_id": ObjectId(), "todo_project_id": None}
        mock_sync_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_sync_goals_collection.update_one = AsyncMock(return_value=mock_result)

        result = await sync_subtask_to_goal_completion(
            FAKE_TODO_ID, "sub_1", True, FAKE_USER_ID
        )
        assert result is False

    async def test_exception_returns_false(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_cache,
    ):
        mock_sync_goals_collection.find_one = AsyncMock(
            side_effect=Exception("DB error")
        )

        result = await sync_subtask_to_goal_completion(
            FAKE_TODO_ID, "sub_1", True, FAKE_USER_ID
        )
        assert result is False


@pytest.mark.unit
class TestCreateGoalProjectAndTodo:
    async def test_success(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_projects_collection,
        mock_sync_cache,
    ):
        goal_id = str(ObjectId())
        project_oid = ObjectId()

        # Goals project exists
        mock_sync_projects_collection.find_one = AsyncMock(
            return_value={"_id": project_oid}
        )

        roadmap_data = {
            "nodes": [
                {
                    "id": "n1",
                    "data": {"title": "Step 1", "isComplete": False},
                },
                {
                    "id": "n2",
                    "data": {"type": "start"},
                },  # Should be skipped
            ],
            "edges": [],
        }

        with patch("app.services.todos.todo_service.TodoService") as mock_todo_svc:
            mock_response = MagicMock(spec=TodoResponse)
            mock_response.id = str(ObjectId())
            mock_todo_svc.create_todo = AsyncMock(return_value=mock_response)

            result = await create_goal_project_and_todo(
                goal_id=goal_id,
                goal_title="My Goal",
                roadmap_data=roadmap_data,
                user_id=FAKE_USER_ID,
                labels=["goal"],
                priority=Priority.HIGH,
            )

        assert result == str(project_oid)
        mock_sync_goals_collection.update_one.assert_awaited_once()

    async def test_exception_propagates(
        self,
        mock_sync_goals_collection,
        mock_sync_todos_collection,
        mock_sync_projects_collection,
        mock_sync_cache,
    ):
        mock_sync_projects_collection.find_one = AsyncMock(
            side_effect=Exception("DB down")
        )

        with pytest.raises(Exception, match="DB down"):
            await create_goal_project_and_todo(
                goal_id=str(ObjectId()),
                goal_title="Broken",
                roadmap_data={"nodes": [], "edges": []},
                user_id=FAKE_USER_ID,
            )


@pytest.mark.unit
class TestGetOrCreateGoalsProject:
    async def test_returns_existing(
        self, mock_sync_projects_collection, mock_sync_cache
    ):
        project_oid = ObjectId()
        mock_sync_projects_collection.find_one = AsyncMock(
            return_value={"_id": project_oid}
        )

        result = await _get_or_create_goals_project(FAKE_USER_ID)
        assert result == str(project_oid)

    async def test_creates_new_project(
        self, mock_sync_projects_collection, mock_sync_cache
    ):
        mock_sync_projects_collection.find_one = AsyncMock(return_value=None)

        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_sync_projects_collection.insert_one = AsyncMock(return_value=mock_result)

        result = await _get_or_create_goals_project(FAKE_USER_ID)
        assert result == str(mock_result.inserted_id)
        mock_sync_projects_collection.insert_one.assert_awaited_once()
        call_doc = mock_sync_projects_collection.insert_one.call_args[0][0]
        assert call_doc["name"] == "Goals"
        assert call_doc["color"] == "#8B5CF6"


# ===========================================================================
# sync_service cache invalidation helpers
# ===========================================================================


@pytest.mark.unit
class TestSyncCacheInvalidation:
    async def test_invalidate_todo_caches(self, mock_sync_cache):
        m_del, m_del_pattern = mock_sync_cache
        await _invalidate_todo_caches(FAKE_USER_ID, FAKE_PROJECT_ID, FAKE_TODO_ID)
        m_del.assert_any_await(f"stats:{FAKE_USER_ID}")
        m_del.assert_any_await(f"todo:{FAKE_USER_ID}:{FAKE_TODO_ID}")
        m_del.assert_any_await(f"projects:{FAKE_USER_ID}")

    async def test_invalidate_todo_caches_without_project(self, mock_sync_cache):
        m_del, m_del_pattern = mock_sync_cache
        await _invalidate_todo_caches(FAKE_USER_ID)
        m_del.assert_any_await(f"stats:{FAKE_USER_ID}")

    async def test_invalidate_todo_caches_exception_swallowed(self, mock_sync_cache):
        m_del, _ = mock_sync_cache
        m_del.side_effect = Exception("Redis down")
        # Should not raise
        await _invalidate_todo_caches(FAKE_USER_ID)

    async def test_invalidate_goal_caches(self, mock_sync_cache):
        m_del, _ = mock_sync_cache
        goal_id = str(ObjectId())
        await _invalidate_goal_caches(FAKE_USER_ID, goal_id)
        m_del.assert_any_await(f"goals_cache:{FAKE_USER_ID}")
        m_del.assert_any_await(f"goal_stats_cache:{FAKE_USER_ID}")
        m_del.assert_any_await(f"goal_cache:{goal_id}")

    async def test_invalidate_goal_caches_without_goal_id(self, mock_sync_cache):
        m_del, _ = mock_sync_cache
        await _invalidate_goal_caches(FAKE_USER_ID)
        m_del.assert_any_await(f"goals_cache:{FAKE_USER_ID}")

    async def test_invalidate_goal_caches_exception_swallowed(self, mock_sync_cache):
        m_del, _ = mock_sync_cache
        m_del.side_effect = Exception("Redis down")
        await _invalidate_goal_caches(FAKE_USER_ID)

    async def test_invalidate_project_caches(self, mock_sync_cache):
        m_del, m_del_pattern = mock_sync_cache
        await _invalidate_project_caches(FAKE_USER_ID, FAKE_PROJECT_ID)
        m_del.assert_any_await(f"projects:{FAKE_USER_ID}")
        m_del_pattern.assert_any_await(f"*:project:{FAKE_PROJECT_ID}*")

    async def test_invalidate_project_caches_without_project_id(self, mock_sync_cache):
        m_del, m_del_pattern = mock_sync_cache
        await _invalidate_project_caches(FAKE_USER_ID)
        m_del.assert_any_await(f"projects:{FAKE_USER_ID}")

    async def test_invalidate_project_caches_exception_swallowed(self, mock_sync_cache):
        m_del, _ = mock_sync_cache
        m_del.side_effect = Exception("Redis down")
        await _invalidate_project_caches(FAKE_USER_ID)
