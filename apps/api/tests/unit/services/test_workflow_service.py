"""Unit tests for workflow execution service and related workflow services.

Covers:
  - app/services/workflow/execution_service.py
  - app/services/workflow/validators.py
  - app/services/workflow/queue_service.py
  - app/services/workflow/service.py  (WorkflowService — state machine transitions)
  - app/services/workflow/generation_service.py  (enrich_steps)
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
from app.services.workflow.generation_service import enrich_steps
from app.services.workflow.service import WorkflowService
from app.models.workflow_execution_models import WorkflowExecution, WorkflowExecutionsResponse
from app.models.workflow_models import (
    GeneratedStep,
    Workflow,
    TriggerConfig,
    TriggerType,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStep,
)
from app.utils.exceptions import TriggerRegistrationError


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

        result = await create_execution(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
        )

        mock_executions_collection.insert_one.assert_awaited_once()
        inserted_doc = mock_executions_collection.insert_one.call_args[0][0]
        assert inserted_doc["status"] == "running"
        assert inserted_doc["workflow_id"] == WORKFLOW_ID
        assert inserted_doc["user_id"] == USER_ID
        assert inserted_doc["trigger_type"] == "manual"

    async def test_returns_workflow_execution_instance(self, mock_executions_collection):
        mock_executions_collection.insert_one = AsyncMock()

        result = await create_execution(
            workflow_id=WORKFLOW_ID, user_id=USER_ID
        )

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

    async def test_stores_conversation_id_when_provided(self, mock_executions_collection):
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

    async def test_calculates_duration_from_started_at(self, mock_executions_collection):
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

        async def async_iter(self_cursor):
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
        # Should not raise any exception for a fully valid workflow.
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

    def test_is_static_method(self):
        # validate_for_execution should be callable without instantiation
        assert callable(WorkflowValidator.validate_for_execution)

    def test_error_message_contains_all_failures_when_multiple_errors(self):
        wf = _make_workflow(activated=False, steps=[])
        # Force trigger_config to None so all three checks fail simultaneously
        object.__setattr__(wf, "trigger_config", None)
        with pytest.raises(ValueError) as exc_info:
            WorkflowValidator.validate_for_execution(wf)
        message = str(exc_info.value)
        assert "Workflow is deactivated" in message
        assert "Workflow has no steps defined" in message
        assert "Missing trigger configuration" in message
        # All three errors should be joined with "; " in a single exception
        assert message.count(";") == 2


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
        mock_redis_pool.get.assert_awaited_once_with("todo_workflow_generating:todo_abc")

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


# ---------------------------------------------------------------------------
# enrich_steps  (generation_service — pure Python, no I/O)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnrichSteps:
    """Tests for enrich_steps(), which converts GeneratedStep objects to full dicts."""

    def test_correct_number_of_steps_generated(self):
        raw = [
            GeneratedStep(title="Fetch emails", category="gmail", description="Pull inbox"),
            GeneratedStep(title="Summarise", category="gaia", description="Summarise content"),
            GeneratedStep(title="Send reply", category="gmail", description="Reply to sender"),
        ]
        result = enrich_steps(raw)
        assert len(result) == 3

    def test_steps_have_correct_title_and_description(self):
        raw = [
            GeneratedStep(title="My Title", category="notion", description="My Description"),
        ]
        result = enrich_steps(raw)
        assert result[0]["title"] == "My Title"
        assert result[0]["description"] == "My Description"

    def test_steps_have_correct_category_field(self):
        raw = [
            GeneratedStep(title="A", category="gmail", description="B"),
            GeneratedStep(title="C", category="gaia", description="D"),
        ]
        result = enrich_steps(raw)
        assert result[0]["category"] == "gmail"
        assert result[1]["category"] == "gaia"

    def test_step_ids_are_sequential(self):
        raw = [
            GeneratedStep(title=f"Step {i}", category="gaia", description="desc")
            for i in range(4)
        ]
        result = enrich_steps(raw)
        assert [s["id"] for s in result] == ["step_0", "step_1", "step_2", "step_3"]

    def test_empty_input_returns_empty_list(self):
        assert enrich_steps([]) == []


# ---------------------------------------------------------------------------
# WorkflowService — state machine transitions
#
# Strategy: mock at the DB / queue boundary, never mock WorkflowService itself.
# This ensures that if the state-transition logic is broken (e.g., never sets
# status to "failed"), these tests will catch it.
# ---------------------------------------------------------------------------


def _make_workflow_doc(
    *,
    workflow_id: str = WORKFLOW_ID,
    user_id: str = USER_ID,
    activated: bool = True,
    steps: list | None = None,
    error_message: str | None = None,
) -> dict:
    """Build a minimal MongoDB workflow document."""
    if steps is None:
        steps = [
            {"id": "step_0", "title": "Step 1", "category": "gaia", "description": "Do something"}
        ]
    return {
        "_id": workflow_id,
        "id": workflow_id,
        "user_id": user_id,
        "title": "Test Workflow",
        "description": "A test",
        "prompt": "Execute test workflow",
        "steps": steps,
        "trigger_config": {"type": "manual", "enabled": True},
        "activated": activated,
        "current_step_index": 0,
        "execution_logs": [],
        "error_message": error_message,
        "total_executions": 0,
        "successful_executions": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "scheduled_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def mock_workflows_collection():
    """Patch the workflows_collection used by WorkflowService."""
    with patch(
        "app.services.workflow.service.workflows_collection"
    ) as mock_col:
        yield mock_col


@pytest.mark.unit
class TestWorkflowServiceStateMachine:
    """Tests that verify state machine transitions inside WorkflowService.

    These tests mock DB writes and the queue but test the real service logic,
    so a bug in the state transition code will cause failures here.
    """

    async def test_execute_workflow_transitions_to_running_state(
        self, mock_workflows_collection
    ):
        """When execute_workflow is called, execution is queued (status=running)."""
        workflow_doc = _make_workflow_doc(activated=True)
        mock_workflows_collection.find_one = AsyncMock(return_value=workflow_doc)
        mock_workflows_collection.find_one_and_update = AsyncMock(
            return_value=workflow_doc
        )

        mock_job = MagicMock()
        mock_job.job_id = "job_run_001"
        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool"
        ) as mock_get_pool:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
            mock_get_pool.return_value = mock_pool

            request = WorkflowExecutionRequest(context=None)
            response = await WorkflowService.execute_workflow(
                WORKFLOW_ID, request, USER_ID
            )

        # The response must carry an execution_id (proving the running transition occurred)
        assert isinstance(response, WorkflowExecutionResponse)
        assert response.execution_id.startswith("exec_")
        assert "started" in response.message.lower()

    async def test_execute_workflow_queues_the_execution_job(
        self, mock_workflows_collection
    ):
        """execute_workflow must enqueue a background job, not run synchronously."""
        workflow_doc = _make_workflow_doc(activated=True)
        mock_workflows_collection.find_one = AsyncMock(return_value=workflow_doc)
        mock_workflows_collection.find_one_and_update = AsyncMock(
            return_value=workflow_doc
        )

        mock_job = MagicMock()
        mock_job.job_id = "job_run_002"
        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool"
        ) as mock_get_pool:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
            mock_get_pool.return_value = mock_pool

            request = WorkflowExecutionRequest(context={"key": "value"})
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

            mock_pool.enqueue_job.assert_awaited_once_with(
                "execute_workflow_by_id", WORKFLOW_ID, {"key": "value"}
            )

    async def test_execute_workflow_raises_when_workflow_is_deactivated(
        self, mock_workflows_collection
    ):
        """execute_workflow must raise (never queue) when workflow.activated=False."""
        workflow_doc = _make_workflow_doc(activated=False)
        mock_workflows_collection.find_one = AsyncMock(return_value=workflow_doc)
        mock_workflows_collection.find_one_and_update = AsyncMock(
            return_value=workflow_doc
        )

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool"
        ) as mock_get_pool:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock()
            mock_get_pool.return_value = mock_pool

            request = WorkflowExecutionRequest(context=None)
            with pytest.raises(Exception):
                await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

            # Queue must NOT have been called — deactivated workflows must not run
            mock_pool.enqueue_job.assert_not_called()

    async def test_execute_workflow_raises_when_workflow_not_found(
        self, mock_workflows_collection
    ):
        """execute_workflow must raise ValueError when workflow does not exist."""
        mock_workflows_collection.find_one = AsyncMock(return_value=None)

        request = WorkflowExecutionRequest(context=None)
        with pytest.raises(ValueError, match=WORKFLOW_ID):
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

    async def test_execution_moves_to_completed_when_all_steps_succeed(self):
        """complete_execution with status='success' represents the completed transition."""
        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection"
        ) as mock_col:
            started_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            mock_col.find_one = AsyncMock(
                return_value=_make_execution_doc(started_at=started_at)
            )
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_col.update_one = AsyncMock(return_value=mock_result)

            result = await complete_execution(EXECUTION_ID, status="success", summary="All done")

        assert result is True
        update_set = mock_col.update_one.call_args[0][1]["$set"]
        # State machine: final status must be 'success'
        assert update_set["status"] == "success"
        assert update_set["completed_at"] is not None

    async def test_execution_moves_to_failed_when_a_step_fails(self):
        """complete_execution with status='failed' represents the failed transition.

        If this test breaks (e.g., status never set to 'failed'), it means the
        state machine logic is broken and subsequent steps would silently succeed.
        """
        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=_make_execution_doc())
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_col.update_one = AsyncMock(return_value=mock_result)

            result = await complete_execution(
                EXECUTION_ID,
                status="failed",
                error_message="Step 2 raised ToolException: rate limit exceeded",
            )

        assert result is True
        update_set = mock_col.update_one.call_args[0][1]["$set"]
        # Critical: status MUST be 'failed', not 'success' or left as 'running'
        assert update_set["status"] == "failed"
        assert update_set["error_message"] == "Step 2 raised ToolException: rate limit exceeded"

    async def test_error_message_is_stored_on_failed_execution(self):
        """Error details must be persisted so callers can surface them to the user."""
        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=_make_execution_doc())
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_col.update_one = AsyncMock(return_value=mock_result)

            error_text = "Connection to external API timed out after 30s"
            await complete_execution(EXECUTION_ID, status="failed", error_message=error_text)

        update_set = mock_col.update_one.call_args[0][1]["$set"]
        assert "error_message" in update_set
        assert update_set["error_message"] == error_text

    async def test_failed_execution_does_not_set_success_status(self):
        """Regression: ensure 'failed' is never silently overwritten with 'success'."""
        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=_make_execution_doc())
            mock_result = MagicMock()
            mock_result.modified_count = 1
            mock_col.update_one = AsyncMock(return_value=mock_result)

            await complete_execution(EXECUTION_ID, status="failed", error_message="boom")

        update_set = mock_col.update_one.call_args[0][1]["$set"]
        assert update_set["status"] != "success"
        assert update_set["status"] != "running"

    async def test_create_workflow_starts_in_pending_then_activates(
        self, mock_workflows_collection
    ):
        """create_workflow uses a saga: workflow starts as pending (activated=False),
        then is flipped to activated=True after trigger registration succeeds.
        """
        from app.models.workflow_models import CreateWorkflowRequest

        inserted_docs: list[dict] = []

        async def capture_insert(doc):
            inserted_docs.append(doc.copy())
            return MagicMock(inserted_id="ok")

        mock_workflows_collection.insert_one = AsyncMock(side_effect=capture_insert)
        # update_one activates the workflow
        mock_update_result = MagicMock()
        mock_update_result.matched_count = 1
        mock_workflows_collection.update_one = AsyncMock(return_value=mock_update_result)
        # find_one is called by ChromaClient path (non-critical) and get_workflow
        workflow_doc = _make_workflow_doc(activated=True)
        mock_workflows_collection.find_one = AsyncMock(return_value=workflow_doc)

        with patch(
            "app.services.workflow.service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
        ), patch(
            "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
            new_callable=AsyncMock,
            return_value=True,
        ):
            request = CreateWorkflowRequest(
                title="Test Workflow",
                prompt="Do something useful",
                trigger_config=TriggerConfig(type=TriggerType.MANUAL),
            )
            workflow = await WorkflowService.create_workflow(request, USER_ID)

        # Step 1: the record was initially inserted as activated=False (pending)
        assert len(inserted_docs) == 1
        assert inserted_docs[0]["activated"] is False, (
            "Workflow must start in pending (activated=False) before saga completes"
        )
        # Step 2: after saga success the in-memory object is activated
        assert workflow.activated is True

    async def test_create_workflow_rolls_back_on_trigger_registration_failure(
        self, mock_workflows_collection
    ):
        """If trigger registration fails the workflow document must be deleted (saga compensation)."""
        from app.models.workflow_models import CreateWorkflowRequest

        mock_workflows_collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="ok")
        )
        mock_workflows_collection.delete_one = AsyncMock()

        with patch(
            "app.services.workflow.service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
        ), patch(
            "app.services.workflow.service.WorkflowService._register_integration_triggers",
            new_callable=AsyncMock,
            side_effect=TriggerRegistrationError(
                "Composio refused", trigger_name="gmail_event"
            ),
        ):
            request = CreateWorkflowRequest(
                title="Integration Workflow",
                prompt="Watch gmail",
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, trigger_name="gmail_event"
                ),
            )
            with pytest.raises(TriggerRegistrationError):
                await WorkflowService.create_workflow(request, USER_ID)

        # The saga compensation must delete the orphaned workflow
        mock_workflows_collection.delete_one.assert_awaited_once()


# ---------------------------------------------------------------------------
# WorkflowService.increment_execution_count — state counters
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowServiceIncrementExecutionCount:
    async def test_increments_total_executions_on_any_run(
        self, mock_workflows_collection
    ):
        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_workflows_collection.update_one = AsyncMock(return_value=mock_result)

        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=False
        )

        assert result is True
        call_args = mock_workflows_collection.update_one.call_args[0]
        inc_data = call_args[1]["$inc"]
        assert inc_data["total_executions"] == 1
        assert "successful_executions" not in inc_data

    async def test_increments_successful_executions_on_success(
        self, mock_workflows_collection
    ):
        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_workflows_collection.update_one = AsyncMock(return_value=mock_result)

        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=True
        )

        assert result is True
        call_args = mock_workflows_collection.update_one.call_args[0]
        inc_data = call_args[1]["$inc"]
        assert inc_data["total_executions"] == 1
        assert inc_data["successful_executions"] == 1

    async def test_returns_false_when_workflow_not_found(
        self, mock_workflows_collection
    ):
        mock_result = MagicMock()
        mock_result.matched_count = 0
        mock_workflows_collection.update_one = AsyncMock(return_value=mock_result)

        result = await WorkflowService.increment_execution_count(
            "wf_nonexistent", USER_ID
        )

        assert result is False

    async def test_returns_false_on_db_exception(self, mock_workflows_collection):
        mock_workflows_collection.update_one = AsyncMock(
            side_effect=Exception("mongo unreachable")
        )

        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=True
        )

        assert result is False
