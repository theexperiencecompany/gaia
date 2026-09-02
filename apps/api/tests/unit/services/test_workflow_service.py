"""Unit tests for workflow execution service and related workflow services.

Covers:
  - app/services/workflow/execution_service.py
  - app/services/workflow/validators.py
  - app/services/workflow/queue_service.py
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_execution_models import (
    WorkflowExecution,
    WorkflowExecutionDocument,
    WorkflowExecutionsResponse,
)
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)

# ---------------------------------------------------------------------------
# Direct imports from the modules under test.
# Deleting any of these source files will cause ImportError here.
# ---------------------------------------------------------------------------
from app.services.workflow.execution_service import (
    complete_execution,
    create_execution,
    get_workflow_executions,
)
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.workflow.validators import WorkflowValidator

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


def _make_execution(
    *,
    execution_id: str = EXECUTION_ID,
    started_at: datetime | None = None,
    status: str = "running",
    duration_seconds: float | None = None,
    **overrides: object,
) -> WorkflowExecutionDocument:
    """Build a typed execution document — what the repository returns."""
    data: dict[str, object] = {
        "execution_id": execution_id,
        "workflow_id": WORKFLOW_ID,
        "user_id": USER_ID,
        "status": status,
        "started_at": started_at or datetime.now(UTC),
        "duration_seconds": duration_seconds,
    }
    data.update(overrides)
    return WorkflowExecutionDocument.model_validate(data)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_executions_repo():
    """Patch the repository singleton used by execution_service.

    Services mock the repository, never the DB — the persistence behavior (id
    round-trip, duration, sorting, pagination) is covered by the repository's
    contract suite, so these tests assert only the service's own behavior.
    """
    with patch(
        "app.services.workflow.execution_service.workflow_executions_repository"
    ) as mock_repo:
        yield mock_repo


@pytest.fixture
def mock_redis_pool(route_enqueue_via_pool):
    """Patch RedisPoolManager.get_pool used by WorkflowQueueService.

    ``route_enqueue_via_pool`` (shared conftest) routes the wide-event enqueue
    wrapper through pool.enqueue_job, so the tests' existing pool mocks and
    assertions stay authoritative.
    """
    with patch("app.services.workflow.queue_service.RedisPoolManager.get_pool") as mock_get_pool:
        mock_pool = AsyncMock()
        mock_get_pool.return_value = mock_pool
        yield mock_pool


# ---------------------------------------------------------------------------
# create_execution
# ---------------------------------------------------------------------------


class TestCreateExecution:
    async def test_builds_running_execution_and_returns_it(self, mock_executions_repo):
        mock_executions_repo.create = AsyncMock(side_effect=lambda doc: doc)

        result = await create_execution(workflow_id=WORKFLOW_ID, user_id=USER_ID)

        assert isinstance(result, WorkflowExecution)
        assert result.status == "running"
        assert result.workflow_id == WORKFLOW_ID
        assert result.user_id == USER_ID
        assert result.trigger_type == "manual"
        # The service builds the document and hands it to the repository verbatim.
        created_doc = mock_executions_repo.create.call_args[0][0]
        assert created_doc.execution_id == result.execution_id

    async def test_execution_id_has_exec_prefix(self, mock_executions_repo):
        mock_executions_repo.create = AsyncMock(side_effect=lambda doc: doc)

        result = await create_execution(WORKFLOW_ID, USER_ID)

        assert result.execution_id.startswith("exec_")

    async def test_execution_id_is_unique_each_call(self, mock_executions_repo):
        mock_executions_repo.create = AsyncMock(side_effect=lambda doc: doc)

        result1 = await create_execution(WORKFLOW_ID, USER_ID)
        result2 = await create_execution(WORKFLOW_ID, USER_ID)

        assert result1.execution_id != result2.execution_id

    async def test_respects_custom_trigger_type(self, mock_executions_repo):
        mock_executions_repo.create = AsyncMock(side_effect=lambda doc: doc)

        result = await create_execution(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            trigger_type="gmail",
        )

        assert result.trigger_type == "gmail"

    async def test_stores_conversation_id_when_provided(self, mock_executions_repo):
        mock_executions_repo.create = AsyncMock(side_effect=lambda doc: doc)

        result = await create_execution(
            workflow_id=WORKFLOW_ID,
            user_id=USER_ID,
            conversation_id="conv_abc",
        )

        assert result.conversation_id == "conv_abc"

    async def test_started_at_is_recent_utc_datetime(self, mock_executions_repo):
        mock_executions_repo.create = AsyncMock(side_effect=lambda doc: doc)
        before = datetime.now(UTC)

        result = await create_execution(WORKFLOW_ID, USER_ID)

        after = datetime.now(UTC)
        assert before <= result.started_at <= after
        assert result.started_at.tzinfo is not None


# ---------------------------------------------------------------------------
# complete_execution
# ---------------------------------------------------------------------------


class TestCompleteExecution:
    async def test_returns_true_and_forwards_completion_fields(self, mock_executions_repo):
        mock_executions_repo.complete = AsyncMock(
            return_value=_make_execution(status="success", duration_seconds=30.0)
        )

        result = await complete_execution(EXECUTION_ID, status="success", summary="Did 3 things")

        assert result is True
        mock_executions_repo.complete.assert_awaited_once_with(
            EXECUTION_ID,
            status="success",
            summary="Did 3 things",
            error_message=None,
            conversation_id=None,
            trace=None,
        )

    async def test_forwards_error_message(self, mock_executions_repo):
        mock_executions_repo.complete = AsyncMock(
            return_value=_make_execution(status="failed", error_message="Tool call failed")
        )

        await complete_execution(EXECUTION_ID, status="failed", error_message="Tool call failed")

        assert mock_executions_repo.complete.call_args.kwargs["error_message"] == "Tool call failed"

    async def test_forwards_conversation_id(self, mock_executions_repo):
        mock_executions_repo.complete = AsyncMock(
            return_value=_make_execution(conversation_id="conv_xyz")
        )

        await complete_execution(EXECUTION_ID, status="success", conversation_id="conv_xyz")

        assert mock_executions_repo.complete.call_args.kwargs["conversation_id"] == "conv_xyz"

    async def test_returns_false_when_execution_not_found(self, mock_executions_repo):
        mock_executions_repo.complete = AsyncMock(return_value=None)

        result = await complete_execution("exec_nonexistent", status="success")

        assert result is False

    async def test_returns_true_when_duration_is_none(self, mock_executions_repo):
        mock_executions_repo.complete = AsyncMock(
            return_value=_make_execution(status="success", duration_seconds=None)
        )

        result = await complete_execution(EXECUTION_ID, status="success")

        assert result is True


# ---------------------------------------------------------------------------
# get_workflow_executions
# ---------------------------------------------------------------------------


class TestGetWorkflowExecutions:
    async def test_wraps_repository_page_in_response(self, mock_executions_repo):
        mock_executions_repo.list_for_workflow = AsyncMock(
            return_value=([_make_execution(status="success")], 1)
        )

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID)

        assert isinstance(result, WorkflowExecutionsResponse)
        assert result.total == 1
        assert len(result.executions) == 1
        assert isinstance(result.executions[0], WorkflowExecution)

    async def test_forwards_workflow_user_limit_and_offset(self, mock_executions_repo):
        mock_executions_repo.list_for_workflow = AsyncMock(return_value=([], 0))

        await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=5, offset=3)

        mock_executions_repo.list_for_workflow.assert_awaited_once_with(
            WORKFLOW_ID, USER_ID, limit=5, offset=3
        )

    async def test_has_more_is_true_when_more_docs_exist(self, mock_executions_repo):
        docs = [_make_execution(execution_id=f"exec_{i}") for i in range(2)]
        mock_executions_repo.list_for_workflow = AsyncMock(return_value=(docs, 5))

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=2, offset=0)

        assert result.has_more is True

    async def test_has_more_is_false_when_all_docs_fetched(self, mock_executions_repo):
        docs = [_make_execution(execution_id=f"exec_{i}") for i in range(2)]
        mock_executions_repo.list_for_workflow = AsyncMock(return_value=(docs, 2))

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=10, offset=0)

        assert result.has_more is False

    async def test_returns_empty_list_when_no_executions(self, mock_executions_repo):
        mock_executions_repo.list_for_workflow = AsyncMock(return_value=([], 0))

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID)

        assert result.total == 0
        assert result.executions == []
        assert result.has_more is False


# ---------------------------------------------------------------------------
# WorkflowValidator
# ---------------------------------------------------------------------------


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


class TestWorkflowQueueServiceGeneration:
    async def test_queue_generation_returns_true_on_success(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_abc"
        mock_redis_pool.enqueue_job.return_value = mock_job

        result = await WorkflowQueueService.queue_workflow_generation(
            workflow_id=WORKFLOW_ID, user_id=USER_ID
        )

        assert result is True
        mock_redis_pool.enqueue_job.assert_awaited_once_with(
            "generate_workflow_steps", WORKFLOW_ID, USER_ID
        )

    async def test_queue_generation_returns_false_when_job_is_none(self, mock_redis_pool):
        mock_redis_pool.enqueue_job.return_value = None

        result = await WorkflowQueueService.queue_workflow_generation(WORKFLOW_ID, USER_ID)

        assert result is False

    async def test_queue_generation_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job.side_effect = ConnectionError("redis down")

        result = await WorkflowQueueService.queue_workflow_generation(WORKFLOW_ID, USER_ID)

        assert result is False


class TestWorkflowQueueServiceExecution:
    async def test_queue_execution_returns_true_on_success(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_xyz"
        mock_redis_pool.enqueue_job.return_value = mock_job

        result = await WorkflowQueueService.queue_workflow_execution(
            workflow_id=WORKFLOW_ID, user_id=USER_ID
        )

        assert result is True
        args, kwargs = mock_redis_pool.enqueue_job.call_args
        assert args == ("execute_workflow_by_id", WORKFLOW_ID, {})
        # Enqueued with a deterministic _job_id so a duplicate enqueue dedupes.
        assert kwargs["_job_id"].startswith("execute_workflow_by_id:")

    async def test_queue_execution_dedup_key_is_deterministic_and_context_scoped(
        self, mock_redis_pool
    ):
        mock_redis_pool.enqueue_job.return_value = MagicMock(job_id="j")

        async def job_id_for(context):
            mock_redis_pool.reset_mock()
            await WorkflowQueueService.queue_workflow_execution(
                WORKFLOW_ID, USER_ID, context=context
            )
            return mock_redis_pool.enqueue_job.call_args.kwargs["_job_id"]

        same_a = await job_id_for({})
        same_b = await job_id_for({})
        evt1 = await job_id_for({"trigger_data": {"email_id": "E1"}})
        evt2 = await job_id_for({"trigger_data": {"email_id": "E2"}})

        # Identical requests dedupe; distinct trigger events must NOT.
        assert same_a == same_b
        assert evt1 != evt2 != same_a

    async def test_queue_execution_deduped_enqueue_is_not_an_error(self, mock_redis_pool):
        # ARQ returns None when a job with the same _job_id is already queued —
        # that's a successful dedupe, not a failure.
        mock_redis_pool.enqueue_job.return_value = None

        result = await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID)

        assert result is True

    async def test_queue_execution_passes_context(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_ctx"
        mock_redis_pool.enqueue_job.return_value = mock_job

        ctx = {"trigger_data": {"email_id": "msg1"}}
        await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID, context=ctx)

        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[2] == ctx

    async def test_queue_execution_uses_empty_dict_when_no_context(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_no_ctx"
        mock_redis_pool.enqueue_job.return_value = mock_job

        await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID)

        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[2] == {}

    async def test_queue_execution_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job.side_effect = Exception("redis timeout")

        result = await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID)

        assert result is False


class TestWorkflowQueueServiceTodo:
    async def test_queue_todo_generation_sets_redis_flag(self, mock_redis_pool):
        mock_job = MagicMock()
        mock_job.job_id = "job_todo"
        mock_redis_pool.enqueue_job.return_value = mock_job
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
        mock_redis_pool.enqueue_job.return_value = mock_job
        mock_redis_pool.set = AsyncMock()

        await WorkflowQueueService.queue_todo_workflow_generation("todo_x", USER_ID, "Title")

        args = mock_redis_pool.enqueue_job.call_args[0]
        assert args[0] == "process_workflow_generation_task"

    async def test_queue_todo_generation_returns_false_when_job_none(self, mock_redis_pool):
        mock_redis_pool.enqueue_job.return_value = None

        result = await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_x", USER_ID, "Title"
        )

        assert result is False

    async def test_queue_todo_generation_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job.side_effect = Exception("connection refused")

        result = await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_x", USER_ID, "Title"
        )

        assert result is False


class TestWorkflowQueueServiceFlags:
    async def test_is_workflow_generating_returns_true_when_flag_set(self, mock_redis_pool):
        mock_redis_pool.get = AsyncMock(return_value="1")

        result = await WorkflowQueueService.is_workflow_generating("todo_abc")

        assert result is True
        mock_redis_pool.get.assert_awaited_once_with("todo_workflow_generating:todo_abc")

    async def test_is_workflow_generating_returns_false_when_flag_absent(self, mock_redis_pool):
        mock_redis_pool.get = AsyncMock(return_value=None)

        result = await WorkflowQueueService.is_workflow_generating("todo_abc")

        assert result is False

    async def test_is_workflow_generating_returns_false_on_exception(self, mock_redis_pool):
        mock_redis_pool.get = AsyncMock(side_effect=Exception("timeout"))

        result = await WorkflowQueueService.is_workflow_generating("todo_abc")

        assert result is False

    async def test_clear_generating_flag_deletes_redis_key(self, mock_redis_pool):
        mock_redis_pool.delete = AsyncMock()

        await WorkflowQueueService.clear_workflow_generating_flag("todo_abc")

        mock_redis_pool.delete.assert_awaited_once_with("todo_workflow_generating:todo_abc")

    async def test_clear_generating_flag_silently_handles_exception(self, mock_redis_pool):
        mock_redis_pool.delete = AsyncMock(side_effect=Exception("connection lost"))

        # Should not raise
        await WorkflowQueueService.clear_workflow_generating_flag("todo_abc")
