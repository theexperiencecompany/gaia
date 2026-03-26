"""Unit tests for workflow execution service and related workflow services.

Covers:
  - app/services/workflow/execution_service.py
  - app/services/workflow/validators.py
  - app/services/workflow/queue_service.py
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Direct imports from the modules under test.
# Deleting any of these source files will cause ImportError here.
# ---------------------------------------------------------------------------
from app.services.workflow.execution_service import (
    create_execution,
    complete_execution,
    get_workflow_executions,
)
from app.services.workflow.validators import WorkflowValidator
from app.services.workflow.queue_service import WorkflowQueueService
from app.models.workflow_execution_models import (
    WorkflowExecution,
    WorkflowExecutionsResponse,
)
from app.models.workflow_models import (
    Workflow,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

WORKFLOW_ID = "wf_test_abc123"
USER_ID = "user_test_456"
EXECUTION_ID = "exec_test_789abc"


def _make_workflow(
    *,
    activated: bool = True,
    steps: list | None = None,
    trigger_config: TriggerConfig | None = None,
) -> Workflow:
    """Build a minimal valid Workflow for testing."""
    if steps is None:
        steps = [WorkflowStep(title="Step 1", description="Do something")]
    if trigger_config is None:
        trigger_config = TriggerConfig(type=TriggerType.MANUAL)
    return Workflow(
        user_id=USER_ID,
        title="Test Workflow",
        prompt="Execute test workflow",
        activated=activated,
        steps=steps,
        trigger_config=trigger_config,
    )


def _make_execution_doc(
    *,
    execution_id: str = EXECUTION_ID,
    started_at: datetime | None = None,
    status: str = "running",
) -> dict:
    """Build a raw MongoDB execution document."""
    return {
        "execution_id": execution_id,
        "workflow_id": WORKFLOW_ID,
        "user_id": USER_ID,
        "status": status,
        "started_at": started_at or datetime.now(timezone.utc),
        "completed_at": None,
        "duration_seconds": None,
        "conversation_id": None,
        "summary": None,
        "error_message": None,
        "trigger_type": "manual",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_executions_collection():
    """Patch the workflow_executions_collection used by execution_service."""
    with patch(
        "app.services.workflow.execution_service.workflow_executions_collection"
    ) as mock_col:
        yield mock_col


@pytest.fixture
def mock_redis_pool():
    """Patch RedisPoolManager.get_pool used by WorkflowQueueService."""
    with patch(
        "app.services.workflow.queue_service.RedisPoolManager.get_pool"
    ) as mock_get_pool:
        mock_pool = AsyncMock()
        mock_get_pool.return_value = mock_pool
        yield mock_pool


# ---------------------------------------------------------------------------
# create_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateExecution:
    async def test_inserts_execution_record_with_running_status(
        self, mock_executions_collection
    ):
        mock_executions_collection.insert_one = AsyncMock()

        await create_execution(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
        )

        mock_executions_collection.insert_one.assert_awaited_once()
        inserted_doc = mock_executions_collection.insert_one.call_args[0][0]
        assert inserted_doc["status"] == "running"
        assert inserted_doc["workflow_id"] == WORKFLOW_ID
        assert inserted_doc["user_id"] == USER_ID
        assert inserted_doc["trigger_type"] == "manual"

    async def test_returns_workflow_execution_instance(
        self, mock_executions_collection
    ):
        mock_executions_collection.insert_one = AsyncMock()

        result = await create_execution(workflow_id=WORKFLOW_ID, user_id=USER_ID)

        assert isinstance(result, WorkflowExecution)
        assert result.status == "running"

    async def test_execution_id_has_exec_prefix(self, mock_executions_collection):
        mock_executions_collection.insert_one = AsyncMock()

        result = await create_execution(WORKFLOW_ID, USER_ID)

        assert result.execution_id.startswith("exec_")

    async def test_execution_id_is_unique_each_call(self, mock_executions_collection):
        mock_executions_collection.insert_one = AsyncMock()

        result1 = await create_execution(WORKFLOW_ID, USER_ID)
        result2 = await create_execution(WORKFLOW_ID, USER_ID)

        assert result1.execution_id != result2.execution_id

    async def test_respects_custom_trigger_type(self, mock_executions_collection):
        mock_executions_collection.insert_one = AsyncMock()

        result = await create_execution(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            trigger_type="gmail",
        )

        assert result.trigger_type == "gmail"
        doc = mock_executions_collection.insert_one.call_args[0][0]
        assert doc["trigger_type"] == "gmail"

    async def test_stores_conversation_id_when_provided(
        self, mock_executions_collection
    ):
        mock_executions_collection.insert_one = AsyncMock()

        result = await create_execution(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            conversation_id="conv_abc",
        )

        assert result.conversation_id == "conv_abc"
        doc = mock_executions_collection.insert_one.call_args[0][0]
        assert doc["conversation_id"] == "conv_abc"

    async def test_started_at_is_recent_utc_datetime(self, mock_executions_collection):
        mock_executions_collection.insert_one = AsyncMock()
        before = datetime.now(timezone.utc)

        result = await create_execution(WORKFLOW_ID, USER_ID)

        after = datetime.now(timezone.utc)
        assert before <= result.started_at <= after
        assert result.started_at.tzinfo is not None


# ---------------------------------------------------------------------------
# complete_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteExecution:
    async def test_updates_status_and_completed_at(self, mock_executions_collection):
        started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc(started_at=started_at)
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        result = await complete_execution(EXECUTION_ID, status="success")

        assert result is True
        mock_executions_collection.update_one.assert_awaited_once()
        update_filter, update_body = mock_executions_collection.update_one.call_args[0]
        assert update_filter == {"execution_id": EXECUTION_ID}
        update_set = update_body["$set"]
        assert update_set["status"] == "success"
        assert "completed_at" in update_set

    async def test_calculates_duration_from_started_at(
        self, mock_executions_collection
    ):
        started_at = datetime.now(timezone.utc) - timedelta(seconds=45)
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc(started_at=started_at)
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        await complete_execution(EXECUTION_ID, status="success")

        update_set = mock_executions_collection.update_one.call_args[0][1]["$set"]
        # Duration should be roughly 45 seconds (allow ±5s tolerance)
        assert update_set["duration_seconds"] is not None
        assert 40 <= update_set["duration_seconds"] <= 50

    async def test_stores_summary_when_provided(self, mock_executions_collection):
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc()
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        await complete_execution(EXECUTION_ID, status="success", summary="Did 3 things")

        update_set = mock_executions_collection.update_one.call_args[0][1]["$set"]
        assert update_set["summary"] == "Did 3 things"

    async def test_stores_error_message_when_provided(self, mock_executions_collection):
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc()
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        await complete_execution(
            EXECUTION_ID, status="failed", error_message="Tool call failed"
        )

        update_set = mock_executions_collection.update_one.call_args[0][1]["$set"]
        assert update_set["error_message"] == "Tool call failed"

    async def test_sets_conversation_id_when_provided(self, mock_executions_collection):
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc()
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        await complete_execution(
            EXECUTION_ID, status="success", conversation_id="conv_xyz"
        )

        update_set = mock_executions_collection.update_one.call_args[0][1]["$set"]
        assert update_set["conversation_id"] == "conv_xyz"

    async def test_returns_false_when_execution_not_found(
        self, mock_executions_collection
    ):
        mock_executions_collection.find_one = AsyncMock(return_value=None)

        result = await complete_execution("exec_nonexistent", status="success")

        assert result is False
        mock_executions_collection.update_one.assert_not_called()

    async def test_returns_false_when_update_modifies_nothing(
        self, mock_executions_collection
    ):
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc()
        )
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        result = await complete_execution(EXECUTION_ID, status="success")

        assert result is False

    async def test_duration_is_none_when_started_at_missing(
        self, mock_executions_collection
    ):
        doc = _make_execution_doc()
        doc["started_at"] = None  # simulate missing field
        mock_executions_collection.find_one = AsyncMock(return_value=doc)
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        await complete_execution(EXECUTION_ID, status="success")

        update_set = mock_executions_collection.update_one.call_args[0][1]["$set"]
        assert update_set["duration_seconds"] is None

    async def test_omits_optional_fields_not_provided(self, mock_executions_collection):
        mock_executions_collection.find_one = AsyncMock(
            return_value=_make_execution_doc()
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_executions_collection.update_one = AsyncMock(return_value=mock_result)

        await complete_execution(EXECUTION_ID, status="success")

        update_set = mock_executions_collection.update_one.call_args[0][1]["$set"]
        assert "summary" not in update_set
        assert "error_message" not in update_set
        assert "conversation_id" not in update_set


# ---------------------------------------------------------------------------
# get_workflow_executions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflowExecutions:
    def _make_async_cursor(self, docs: list) -> MagicMock:
        """Create a mock async cursor that yields the given docs."""
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor

        async def async_iter(_):
            for doc in docs:
                yield doc

        cursor.__aiter__ = async_iter
        return cursor

    async def test_returns_workflow_executions_response(
        self, mock_executions_collection
    ):
        mock_executions_collection.count_documents = AsyncMock(return_value=1)
        doc = _make_execution_doc()
        mock_executions_collection.find.return_value = self._make_async_cursor([doc])

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID)

        assert isinstance(result, WorkflowExecutionsResponse)
        assert result.total == 1
        assert len(result.executions) == 1
        assert isinstance(result.executions[0], WorkflowExecution)

    async def test_queries_by_workflow_and_user_id(self, mock_executions_collection):
        mock_executions_collection.count_documents = AsyncMock(return_value=0)
        mock_executions_collection.find.return_value = self._make_async_cursor([])

        await get_workflow_executions(WORKFLOW_ID, USER_ID)

        query = mock_executions_collection.count_documents.call_args[0][0]
        assert query["workflow_id"] == WORKFLOW_ID
        assert query["user_id"] == USER_ID

    async def test_has_more_is_true_when_more_docs_exist(
        self, mock_executions_collection
    ):
        mock_executions_collection.count_documents = AsyncMock(return_value=5)
        docs = [_make_execution_doc(execution_id=f"exec_{i}") for i in range(2)]
        mock_executions_collection.find.return_value = self._make_async_cursor(docs)

        # offset=0, limit=2, total=5 → has_more=True
        result = await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=2, offset=0)

        assert result.has_more is True

    async def test_has_more_is_false_when_all_docs_fetched(
        self, mock_executions_collection
    ):
        mock_executions_collection.count_documents = AsyncMock(return_value=2)
        docs = [_make_execution_doc(execution_id=f"exec_{i}") for i in range(2)]
        mock_executions_collection.find.return_value = self._make_async_cursor(docs)

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=10, offset=0)

        assert result.has_more is False

    async def test_removes_mongodb_id_field_from_docs(self, mock_executions_collection):
        mock_executions_collection.count_documents = AsyncMock(return_value=1)
        doc = _make_execution_doc()
        doc["_id"] = "some_object_id"  # simulate MongoDB _id
        mock_executions_collection.find.return_value = self._make_async_cursor([doc])

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID)

        # WorkflowExecution should not have _id – if it did, Pydantic would raise
        assert len(result.executions) == 1

    async def test_returns_empty_list_when_no_executions(
        self, mock_executions_collection
    ):
        mock_executions_collection.count_documents = AsyncMock(return_value=0)
        mock_executions_collection.find.return_value = self._make_async_cursor([])

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID)

        assert result.total == 0
        assert result.executions == []
        assert result.has_more is False

    async def test_applies_limit_and_offset_to_cursor(self, mock_executions_collection):
        mock_executions_collection.count_documents = AsyncMock(return_value=10)
        cursor = self._make_async_cursor([])
        mock_executions_collection.find.return_value = cursor

        await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=5, offset=3)

        cursor.skip.assert_called_once_with(3)
        cursor.limit.assert_called_once_with(5)

    async def test_sorts_by_started_at_descending(self, mock_executions_collection):
        mock_executions_collection.count_documents = AsyncMock(return_value=0)
        cursor = self._make_async_cursor([])
        mock_executions_collection.find.return_value = cursor

        await get_workflow_executions(WORKFLOW_ID, USER_ID)

        cursor.sort.assert_called_once_with("started_at", -1)


# ---------------------------------------------------------------------------
# WorkflowValidator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowValidator:
    def test_passes_for_valid_activated_workflow(self):
        wf = _make_workflow(activated=True)
        # Must not raise for a valid, activated workflow with steps and trigger_config.
        WorkflowValidator.validate_for_execution(wf)

    def test_raises_when_workflow_is_deactivated(self):
        wf = _make_workflow(activated=False)
        with pytest.raises(ValueError):
            WorkflowValidator.validate_for_execution(wf)

    def test_raises_when_steps_are_empty(self):
        wf = _make_workflow(steps=[])
        with pytest.raises(ValueError):
            WorkflowValidator.validate_for_execution(wf)

    def test_raises_when_trigger_config_is_none(self):
        wf = _make_workflow()
        # Force trigger_config to None post-construction to test the validator
        object.__setattr__(wf, "trigger_config", None)
        with pytest.raises(ValueError):
            WorkflowValidator.validate_for_execution(wf)

    def test_raises_with_message_for_invalid_workflow(self):
        # validate_for_execution should raise ValidationError with a descriptive
        # message when called without instantiation on an invalid workflow.
        wf = _make_workflow(activated=False)
        with pytest.raises(ValueError, match="Workflow validation failed"):
            WorkflowValidator.validate_for_execution(wf)


# ---------------------------------------------------------------------------
# WorkflowQueueService
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowQueueServiceGeneration:
    async def test_queue_generation_returns_true_on_success(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_abc"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await WorkflowQueueService.queue_workflow_generation(
            workflow_id=WORKFLOW_ID, user_id=USER_ID
        )

        assert result is True
        mock_redis_pool.enqueue_job.assert_awaited_once_with(
            "generate_workflow_steps", WORKFLOW_ID, USER_ID
        )

    async def test_queue_generation_returns_false_when_job_is_none(
        self, mock_redis_pool
    ):
        mock_redis_pool.enqueue_job = AsyncMock(return_value=None)

        result = await WorkflowQueueService.queue_workflow_generation(
            WORKFLOW_ID, USER_ID
        )

        assert result is False

    async def test_queue_generation_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(
            side_effect=ConnectionError("redis down")
        )

        result = await WorkflowQueueService.queue_workflow_generation(
            WORKFLOW_ID, USER_ID
        )

        assert result is False


@pytest.mark.unit
class TestWorkflowQueueServiceExecution:
    async def test_queue_execution_returns_true_on_success(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_xyz"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await WorkflowQueueService.queue_workflow_execution(
            workflow_id=WORKFLOW_ID, user_id=USER_ID
        )

        assert result is True
        mock_redis_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", WORKFLOW_ID, {}
        )

    async def test_queue_execution_passes_context(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_ctx"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        ctx = {"trigger_data": {"email_id": "msg1"}}
        await WorkflowQueueService.queue_workflow_execution(
            WORKFLOW_ID, USER_ID, context=ctx
        )

        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[2] == ctx

    async def test_queue_execution_uses_empty_dict_when_no_context(
        self, mock_redis_pool
    ):
        mock_job = MagicMock()
        mock_job.job_id = "job_no_ctx"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID)

        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[2] == {}

    async def test_queue_execution_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(side_effect=Exception("redis timeout"))

        result = await WorkflowQueueService.queue_workflow_execution(
            WORKFLOW_ID, USER_ID
        )

        assert result is False


@pytest.mark.unit
class TestWorkflowQueueServiceScheduled:
    async def test_queue_scheduled_execution_passes_defer_until(self, mock_redis_pool):
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_job = MagicMock()
        mock_job.job_id = "job_sched"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await WorkflowQueueService.queue_scheduled_workflow_execution(
            workflow_id=WORKFLOW_ID, scheduled_at=scheduled_at
        )

        assert result is True
        kwargs = mock_redis_pool.enqueue_job.call_args[1]
        assert kwargs["_defer_until"] == scheduled_at

    async def test_queue_scheduled_returns_false_when_job_none(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(return_value=None)
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)

        result = await WorkflowQueueService.queue_scheduled_workflow_execution(
            WORKFLOW_ID, scheduled_at
        )

        assert result is False

    async def test_queue_scheduled_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(side_effect=Exception("unavailable"))
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)

        result = await WorkflowQueueService.queue_scheduled_workflow_execution(
            WORKFLOW_ID, scheduled_at
        )

        assert result is False


@pytest.mark.unit
class TestWorkflowQueueServiceRegeneration:
    async def test_queue_regeneration_passes_all_params(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_regen"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await WorkflowQueueService.queue_workflow_regeneration(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            regeneration_reason="User requested changes",
            force_different_tools=True,
        )

        assert result is True
        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[0] == "regenerate_workflow_steps"
        assert args[1] == WORKFLOW_ID
        assert args[2] == USER_ID
        assert args[3] == "User requested changes"
        assert args[4] is True

    async def test_queue_regeneration_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(side_effect=Exception("pool exhausted"))

        result = await WorkflowQueueService.queue_workflow_regeneration(
            WORKFLOW_ID, USER_ID, "reason"
        )

        assert result is False


@pytest.mark.unit
class TestWorkflowQueueServiceTodo:
    async def test_queue_todo_generation_sets_redis_flag(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_todo"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis_pool.set = AsyncMock()

        todo_id = "todo_abc123"
        result = await WorkflowQueueService.queue_todo_workflow_generation(
            todo_id=todo_id,
            user_id=USER_ID,
            title="Buy groceries",
            description="Milk, eggs",
        )

        assert result is True
        mock_redis_pool.set.assert_awaited_once_with(
            f"todo_workflow_generating:{todo_id}", "1", ex=300
        )

    async def test_queue_todo_generation_uses_correct_task_name(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_todo2"
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis_pool.set = AsyncMock()

        await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_x", USER_ID, "Title"
        )

        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[0] == "process_workflow_generation_task"

    async def test_queue_todo_generation_returns_false_when_job_none(
        self, mock_redis_pool
    ):
        mock_redis_pool.enqueue_job = AsyncMock(return_value=None)

        result = await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_x", USER_ID, "Title"
        )

        assert result is False

    async def test_queue_todo_generation_returns_false_on_exception(
        self, mock_redis_pool
    ):
        mock_redis_pool.enqueue_job = AsyncMock(
            side_effect=Exception("connection refused")
        )

        result = await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_x", USER_ID, "Title"
        )

        assert result is False


@pytest.mark.unit
class TestWorkflowQueueServiceFlags:
    async def test_is_workflow_generating_returns_true_when_flag_set(
        self, mock_redis_pool
    ):
        mock_redis_pool.get = AsyncMock(return_value="1")

        result = await WorkflowQueueService.is_workflow_generating("todo_abc")

        assert result is True
        mock_redis_pool.get.assert_awaited_once_with(
            "todo_workflow_generating:todo_abc"
        )

    async def test_is_workflow_generating_returns_false_when_flag_absent(
        self, mock_redis_pool
    ):
        mock_redis_pool.get = AsyncMock(return_value=None)

        result = await WorkflowQueueService.is_workflow_generating("todo_abc")

        assert result is False

    async def test_is_workflow_generating_returns_false_on_exception(
        self, mock_redis_pool
    ):
        mock_redis_pool.get = AsyncMock(side_effect=Exception("timeout"))

        result = await WorkflowQueueService.is_workflow_generating("todo_abc")

        assert result is False

    async def test_clear_generating_flag_deletes_redis_key(self, mock_redis_pool):
        mock_redis_pool.delete = AsyncMock()

        await WorkflowQueueService.clear_workflow_generating_flag("todo_abc")

        mock_redis_pool.delete.assert_awaited_once_with(
            "todo_workflow_generating:todo_abc"
        )

    async def test_clear_generating_flag_silently_handles_exception(
        self, mock_redis_pool
    ):
        mock_redis_pool.delete = AsyncMock(side_effect=Exception("connection lost"))

        # Should not raise
        await WorkflowQueueService.clear_workflow_generating_flag("todo_abc")
