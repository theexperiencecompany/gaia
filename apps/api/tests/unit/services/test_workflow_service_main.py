"""Comprehensive unit tests for the main WorkflowService (service.py).

Covers:
  - WorkflowService.create_workflow (success, validation errors, saga rollback,
    trigger registration, scheduling, generation queueing, ChromaDB failures)
  - WorkflowService.get_workflow (found, not found, transform error)
  - WorkflowService.list_workflows (pagination, filtering, malformed docs)
  - WorkflowService.update_workflow (success, not found, trigger re-registration,
    schedule changes, DB failure compensation)
  - WorkflowService.delete_workflow (success, not found, trigger cleanup)
  - WorkflowService.execute_workflow (success, not found, validation failures,
    queue failures)
  - WorkflowService.get_workflow_status (success, not found)
  - WorkflowService.activate_workflow (success, not found, trigger registration
    failure, DB update failure rollback)
  - WorkflowService.deactivate_workflow (success, not found, trigger unregistration)
  - WorkflowService.regenerate_workflow_steps (success, not found, LLM failure)
  - WorkflowService.increment_execution_count (success, not found, DB error)
  - WorkflowService._generate_workflow_steps (success, LLM failure, error persistence)
  - generate_unique_workflow_slug (unique, collision, empty title)

Also covers:
  - WorkflowGenerationService.generate_steps_with_llm (structured output, fallback,
    retry, empty steps, max retries)
  - WorkflowGenerationService.generate_workflow_prompt (success, LLM failure)
  - WorkflowScheduler (schedule, cancel, reschedule, get_task, get_pending_task,
    update_task_status, get_workflow_status)
  - WorkflowQueueService (queue_workflow_generation, queue_workflow_execution,
    queue_scheduled_workflow_execution, queue_workflow_regeneration,
    queue_todo_workflow_generation, is_workflow_generating,
    clear_workflow_generating_flag)
  - TriggerService (get_all_workflow_triggers, get_trigger_by_slug,
    register_triggers, unregister_triggers, reference counting)
  - WorkflowValidator (validate_for_execution: pass, deactivated, no steps,
    no trigger config, multiple errors)
  - generation_service helpers (enrich_steps, _parse_workflow_response,
    _build_trigger_hint, _build_available_triggers)
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.workflow_models import (
    CreateWorkflowRequest,
    GeneratedStep,
    GeneratedWorkflow,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
    WorkflowStep,
)
from app.models.workflow_execution_models import (
    WorkflowExecution,
    WorkflowExecutionsResponse,
)
from app.services.workflow.service import (
    WorkflowService,
    generate_unique_workflow_slug,
)
from app.services.workflow.generation_service import (
    WorkflowGenerationService,
    enrich_steps,
    _parse_workflow_response,
    _build_trigger_hint,
    _build_available_triggers,
)
from app.services.workflow.execution_service import (
    create_execution,
    complete_execution,
    get_workflow_executions,
)
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.workflow.trigger_service import TriggerService
from app.services.workflow.validators import WorkflowValidator
from app.utils.exceptions import TriggerRegistrationError


# ---------------------------------------------------------------------------
# Shared helpers / constants
# ---------------------------------------------------------------------------

WORKFLOW_ID = "wf_test_abc12345"
USER_ID = "user_test_456"
EXECUTION_ID = "exec_test_789abc"


def _make_trigger_config(
    *,
    trigger_type: TriggerType = TriggerType.MANUAL,
    enabled: bool = True,
    cron_expression: Optional[str] = None,
    trigger_name: Optional[str] = None,
    composio_trigger_ids: Optional[List[str]] = None,
    next_run: Optional[datetime] = None,
) -> TriggerConfig:
    """Build a TriggerConfig for testing."""
    return TriggerConfig(
        type=trigger_type,
        enabled=enabled,
        cron_expression=cron_expression,
        trigger_name=trigger_name,
        composio_trigger_ids=composio_trigger_ids,
        next_run=next_run,
    )


def _make_workflow(
    *,
    workflow_id: Optional[str] = WORKFLOW_ID,
    activated: bool = True,
    steps: Optional[list] = None,
    trigger_config: Optional[TriggerConfig] = None,
    description: str = "Test description",
    prompt: str = "Execute test workflow",
    user_id: str = USER_ID,
    is_todo_workflow: bool = False,
    error_message: Optional[str] = None,
) -> Workflow:
    """Build a minimal valid Workflow for testing."""
    if steps is None:
        steps = [WorkflowStep(id="step_0", title="Step 1", description="Do something")]
    if trigger_config is None:
        trigger_config = _make_trigger_config()
    return Workflow(
        id=workflow_id,
        user_id=user_id,
        title="Test Workflow",
        description=description,
        prompt=prompt,
        activated=activated,
        steps=steps,
        trigger_config=trigger_config,
        is_todo_workflow=is_todo_workflow,
        error_message=error_message,
    )


def _make_create_request(
    *,
    title: str = "New Workflow",
    prompt: str = "Do something useful",
    description: Optional[str] = "A test workflow",
    trigger_config: Optional[TriggerConfig] = None,
    steps: Optional[List[WorkflowStep]] = None,
    generate_immediately: bool = False,
) -> CreateWorkflowRequest:
    """Build a CreateWorkflowRequest for testing."""
    if trigger_config is None:
        trigger_config = _make_trigger_config()
    return CreateWorkflowRequest(
        title=title,
        prompt=prompt,
        description=description,
        trigger_config=trigger_config,
        steps=steps,
        generate_immediately=generate_immediately,
    )


def _make_update_request(**kwargs) -> UpdateWorkflowRequest:
    """Build an UpdateWorkflowRequest for testing."""
    return UpdateWorkflowRequest(**kwargs)


def _workflow_doc(workflow: Optional[Workflow] = None) -> dict:
    """Convert a Workflow to a MongoDB-style document dict."""
    wf = workflow or _make_workflow()
    doc = wf.model_dump(mode="json")
    doc["_id"] = doc["id"]
    return doc


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_insert_result(inserted_id: str = WORKFLOW_ID) -> MagicMock:
    """Create a mock InsertOneResult."""
    result = MagicMock()
    result.inserted_id = inserted_id
    return result


def _mock_update_result(matched: int = 1, modified: int = 1) -> MagicMock:
    """Create a mock UpdateResult."""
    result = MagicMock()
    result.matched_count = matched
    result.modified_count = modified
    return result


def _mock_delete_result(deleted: int = 1) -> MagicMock:
    """Create a mock DeleteResult."""
    result = MagicMock()
    result.deleted_count = deleted
    return result


# ===========================================================================
# WorkflowValidator tests
# ===========================================================================


class TestWorkflowValidator:
    """Tests for WorkflowValidator.validate_for_execution."""

    def test_valid_workflow_passes(self):
        workflow = _make_workflow(activated=True)
        # Should not raise
        WorkflowValidator.validate_for_execution(workflow)

    def test_deactivated_workflow_fails(self):
        workflow = _make_workflow(activated=False)
        with pytest.raises(ValueError, match="deactivated"):
            WorkflowValidator.validate_for_execution(workflow)

    def test_no_steps_fails(self):
        workflow = _make_workflow(steps=[])
        with pytest.raises(ValueError, match="no steps"):
            WorkflowValidator.validate_for_execution(workflow)

    def test_deactivated_and_no_steps_reports_both(self):
        workflow = _make_workflow(activated=False, steps=[])
        with pytest.raises(ValueError) as exc_info:
            WorkflowValidator.validate_for_execution(workflow)
        assert "deactivated" in str(exc_info.value)
        assert "no steps" in str(exc_info.value)


# ===========================================================================
# generate_unique_workflow_slug tests
# ===========================================================================


class TestGenerateUniqueWorkflowSlug:
    """Tests for generate_unique_workflow_slug."""

    @patch("app.services.workflow.service.workflows_collection")
    async def test_unique_slug_first_try(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)
        slug = await generate_unique_workflow_slug("My Test Workflow")
        assert slug == "mytestworkflow"

    @patch("app.services.workflow.service.workflows_collection")
    async def test_slug_collision_appends_suffix(self, mock_collection):
        # First call returns existing, second returns None
        mock_collection.find_one = AsyncMock(side_effect=[{"slug": "myworkflow"}, None])
        slug = await generate_unique_workflow_slug("My Workflow")
        assert slug == "myworkflow-1"

    @patch("app.services.workflow.service.workflows_collection")
    async def test_slug_multiple_collisions(self, mock_collection):
        mock_collection.find_one = AsyncMock(
            side_effect=[
                {"slug": "myworkflow"},
                {"slug": "myworkflow-1"},
                None,
            ]
        )
        slug = await generate_unique_workflow_slug("My Workflow")
        assert slug == "myworkflow-2"

    @patch("app.services.workflow.service.slugify", return_value="")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_empty_title_falls_back_to_workflow(
        self, mock_collection, _mock_slugify
    ):
        mock_collection.find_one = AsyncMock(return_value=None)
        slug = await generate_unique_workflow_slug("")
        assert slug == "workflow"

    @patch("app.services.workflow.service.workflows_collection")
    async def test_exclude_id_passed_to_query(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)
        await generate_unique_workflow_slug("Test", exclude_id="wf_existing")
        call_args = mock_collection.find_one.call_args[0][0]
        assert call_args["_id"] == {"$ne": "wf_existing"}


# ===========================================================================
# WorkflowService.create_workflow tests
# ===========================================================================


class TestCreateWorkflow:
    """Tests for WorkflowService.create_workflow."""

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_manual_workflow_success(
        self, mock_collection, mock_chroma, mock_scheduler, mock_queue
    ):
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())

        mock_chroma_client = MagicMock()
        mock_chroma.get_langchain_client = AsyncMock(return_value=mock_chroma_client)

        request = _make_create_request()
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert isinstance(result, Workflow)
        assert result.title == "New Workflow"
        assert result.activated is True
        mock_collection.insert_one.assert_awaited_once()
        mock_queue.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_with_pre_existing_steps_skips_generation(
        self, mock_collection, mock_chroma, mock_scheduler, mock_queue
    ):
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        steps = [
            WorkflowStep(id="s1", title="Pre-existing", description="Already defined")
        ]
        request = _make_create_request(steps=steps)
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert isinstance(result, Workflow)
        # Should NOT queue generation when steps are provided
        mock_queue.assert_not_awaited()

    @patch(
        "app.services.workflow.service.WorkflowService._generate_workflow_steps",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_with_generate_immediately(
        self, mock_collection, mock_chroma, mock_scheduler, mock_get, mock_gen
    ):
        generated_wf = _make_workflow()
        mock_get.return_value = generated_wf
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request(generate_immediately=True)
        result = await WorkflowService.create_workflow(request, USER_ID)

        mock_gen.assert_awaited_once()
        assert result == generated_wf

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_schedule_workflow_schedules_execution(
        self, mock_collection, mock_chroma, mock_scheduler
    ):
        next_run = datetime.now(timezone.utc) + timedelta(hours=1)
        trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            next_run=next_run,
        )
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        request = _make_create_request(
            trigger_config=trigger,
            steps=[WorkflowStep(id="s1", title="s", description="d")],
        )
        await WorkflowService.create_workflow(
            request, USER_ID, user_timezone="America/New_York"
        )

        mock_scheduler.schedule_workflow_execution.assert_awaited_once()

    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
        return_value=["trigger_1"],
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_integration_workflow_registers_triggers(
        self, mock_collection, mock_chroma, mock_scheduler, mock_register
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="calendar_event_created",
        )
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request(
            trigger_config=trigger,
            steps=[WorkflowStep(id="s1", title="s", description="d")],
        )
        result = await WorkflowService.create_workflow(request, USER_ID)

        mock_register.assert_awaited_once()
        assert result.activated is True

    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_rollback_on_trigger_registration_error(
        self, mock_collection, mock_chroma, mock_scheduler, mock_register
    ):
        mock_register.side_effect = TriggerRegistrationError(
            "Registration failed", trigger_name="test_trigger"
        )
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="test_trigger",
        )
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_collection.delete_one = AsyncMock()
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request(trigger_config=trigger)
        with pytest.raises(TriggerRegistrationError):
            await WorkflowService.create_workflow(request, USER_ID)

        # Verify rollback occurred
        mock_collection.delete_one.assert_awaited_once()

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_fails_on_db_insert(
        self, mock_collection, mock_chroma, mock_scheduler
    ):
        bad_result = MagicMock()
        bad_result.inserted_id = None
        mock_collection.insert_one = AsyncMock(return_value=bad_result)
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request()
        with pytest.raises(ValueError, match="Failed to create workflow"):
            await WorkflowService.create_workflow(request, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_chroma_failure_non_critical(
        self, mock_collection, mock_chroma, mock_scheduler, mock_queue
    ):
        """ChromaDB failure should not prevent workflow creation."""
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_chroma.get_langchain_client = AsyncMock(
            side_effect=Exception("ChromaDB down")
        )

        request = _make_create_request()
        result = await WorkflowService.create_workflow(request, USER_ID)

        # Workflow should still be created successfully
        assert isinstance(result, Workflow)

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_queue_generation_failure_still_returns_workflow(
        self, mock_collection, mock_chroma, mock_scheduler, mock_queue
    ):
        """If queueing generation fails, the workflow is still returned."""
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request()
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert isinstance(result, Workflow)

    @patch(
        "app.services.workflow.service.TriggerService.unregister_triggers",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch("app.services.workflow.service.workflows_collection")
    async def test_create_cleanup_on_generic_error_after_trigger_registration(
        self, mock_collection, mock_chroma, mock_scheduler, mock_unregister
    ):
        """If a generic error occurs after triggers are registered, both triggers and workflow are cleaned up."""
        mock_collection.insert_one = AsyncMock(return_value=_mock_insert_result())
        # update_one for activation succeeds, but later code raises
        mock_collection.update_one = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        mock_collection.delete_one = AsyncMock()
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        trigger = _make_trigger_config(
            trigger_type=TriggerType.MANUAL,
        )
        request = _make_create_request(trigger_config=trigger)

        with pytest.raises(Exception, match="Unexpected error"):
            await WorkflowService.create_workflow(request, USER_ID)

        mock_collection.delete_one.assert_awaited()


# ===========================================================================
# WorkflowService.get_workflow tests
# ===========================================================================


class TestGetWorkflow:
    """Tests for WorkflowService.get_workflow."""

    @patch("app.services.workflow.service.workflows_collection")
    async def test_get_workflow_found(self, mock_collection):
        wf = _make_workflow()
        doc = _workflow_doc(wf)
        mock_collection.find_one = AsyncMock(return_value=doc)

        result = await WorkflowService.get_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        assert result.title == "Test Workflow"
        mock_collection.find_one.assert_awaited_once_with(
            {"_id": WORKFLOW_ID, "user_id": USER_ID}
        )

    @patch("app.services.workflow.service.workflows_collection")
    async def test_get_workflow_not_found(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        result = await WorkflowService.get_workflow("nonexistent", USER_ID)
        assert result is None

    @patch("app.services.workflow.service.workflows_collection")
    async def test_get_workflow_db_error_raises(self, mock_collection):
        mock_collection.find_one = AsyncMock(
            side_effect=Exception("DB connection lost")
        )

        with pytest.raises(Exception, match="DB connection lost"):
            await WorkflowService.get_workflow(WORKFLOW_ID, USER_ID)


# ===========================================================================
# WorkflowService.list_workflows tests
# ===========================================================================


class TestListWorkflows:
    """Tests for WorkflowService.list_workflows."""

    @patch("app.services.workflow.service.workflows_collection")
    async def test_list_workflows_returns_workflows(self, mock_collection):
        wf = _make_workflow()
        doc = _workflow_doc(wf)

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[doc])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await WorkflowService.list_workflows(USER_ID)
        assert len(result) == 1
        assert isinstance(result[0], Workflow)

    @patch("app.services.workflow.service.workflows_collection")
    async def test_list_workflows_empty(self, mock_collection):
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await WorkflowService.list_workflows(USER_ID)
        assert result == []

    @patch("app.services.workflow.service.workflows_collection")
    async def test_list_workflows_excludes_todo_workflows_by_default(
        self, mock_collection
    ):
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        await WorkflowService.list_workflows(USER_ID, exclude_todo_workflows=True)

        query = mock_collection.find.call_args[0][0]
        assert "$or" in query

    @patch("app.services.workflow.service.workflows_collection")
    async def test_list_workflows_includes_todo_workflows_when_false(
        self, mock_collection
    ):
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        await WorkflowService.list_workflows(USER_ID, exclude_todo_workflows=False)

        query = mock_collection.find.call_args[0][0]
        assert "$or" not in query

    @patch("app.services.workflow.service.workflows_collection")
    async def test_list_workflows_skips_malformed_docs(self, mock_collection):
        """Malformed documents should be skipped, not crash the entire listing."""
        good_doc = _workflow_doc(_make_workflow())
        bad_doc = {"_id": "bad", "user_id": USER_ID}  # Missing required fields

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[good_doc, bad_doc])
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await WorkflowService.list_workflows(USER_ID)
        # Only the good document should be returned
        assert len(result) == 1

    @patch("app.services.workflow.service.workflows_collection")
    async def test_list_workflows_db_error_raises(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        with pytest.raises(Exception, match="DB error"):
            await WorkflowService.list_workflows(USER_ID)


# ===========================================================================
# WorkflowService.update_workflow tests
# ===========================================================================


class TestUpdateWorkflow:
    """Tests for WorkflowService.update_workflow."""

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_update_title_success(self, mock_collection, mock_get):
        wf = _make_workflow()
        updated_wf = _make_workflow()
        updated_wf.title = "Updated Title"
        mock_get.side_effect = [wf, updated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())

        request = _make_update_request(title="Updated Title")
        result = await WorkflowService.update_workflow(WORKFLOW_ID, request, USER_ID)

        assert result is not None
        assert result.title == "Updated Title"

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_update_workflow_not_found(self, mock_get):
        mock_get.return_value = None

        request = _make_update_request(title="Updated")
        result = await WorkflowService.update_workflow("nonexistent", request, USER_ID)

        assert result is None

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_update_matched_count_zero_returns_none(
        self, mock_collection, mock_get
    ):
        mock_get.return_value = _make_workflow()
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(matched=0)
        )

        request = _make_update_request(title="Updated")
        result = await WorkflowService.update_workflow(WORKFLOW_ID, request, USER_ID)

        assert result is None

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_update_trigger_config_reschedules(
        self, mock_collection, mock_get, mock_scheduler
    ):
        next_run = datetime.now(timezone.utc) + timedelta(hours=2)
        old_trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 8 * * *",
        )
        new_trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 10 * * *",
            next_run=next_run,
        )
        wf = _make_workflow(trigger_config=old_trigger, activated=True)
        updated_wf = _make_workflow(trigger_config=new_trigger)
        mock_get.side_effect = [wf, updated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_scheduler.reschedule_workflow = AsyncMock(return_value=True)

        request = _make_update_request(trigger_config=new_trigger)
        result = await WorkflowService.update_workflow(
            WORKFLOW_ID, request, USER_ID, user_timezone="UTC"
        )

        mock_scheduler.reschedule_workflow.assert_awaited_once()
        assert result is not None

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_update_disable_schedule_cancels(
        self, mock_collection, mock_get, mock_scheduler
    ):
        old_trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 8 * * *",
            enabled=True,
        )
        new_trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 8 * * *",
            enabled=False,
        )
        wf = _make_workflow(trigger_config=old_trigger)
        updated_wf = _make_workflow(trigger_config=new_trigger)
        mock_get.side_effect = [wf, updated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )

        request = _make_update_request(trigger_config=new_trigger)
        await WorkflowService.update_workflow(WORKFLOW_ID, request, USER_ID)

        mock_scheduler.cancel_scheduled_workflow_execution.assert_awaited_once()

    @patch(
        "app.services.workflow.service.TriggerService.unregister_triggers",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
        return_value=["new_trigger_id"],
    )
    @patch(
        "app.services.workflow.service.WorkflowService._register_integration_triggers",
        new_callable=AsyncMock,
        return_value=["new_trigger_id"],
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_update_integration_trigger_re_registers(
        self,
        mock_collection,
        mock_get,
        mock_scheduler,
        mock_register_int,
        mock_register,
        mock_unregister,
    ):
        old_trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="old_trigger",
            composio_trigger_ids=["old_id_1"],
        )
        new_trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="new_trigger",
        )
        wf = _make_workflow(trigger_config=old_trigger, activated=True)
        updated_wf = _make_workflow(trigger_config=new_trigger)
        mock_get.side_effect = [wf, updated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())

        request = _make_update_request(trigger_config=new_trigger)
        result = await WorkflowService.update_workflow(WORKFLOW_ID, request, USER_ID)

        # New triggers registered, old unregistered
        mock_register_int.assert_awaited_once()
        mock_unregister.assert_awaited_once()
        assert result is not None


# ===========================================================================
# WorkflowService.delete_workflow tests
# ===========================================================================


class TestDeleteWorkflow:
    """Tests for WorkflowService.delete_workflow."""

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_delete_success(self, mock_collection, mock_get, mock_scheduler):
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_collection.delete_one = AsyncMock(return_value=_mock_delete_result(1))
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True
        mock_collection.delete_one.assert_awaited_once()

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_delete_not_found(self, mock_collection, mock_get, mock_scheduler):
        mock_get.return_value = None
        mock_collection.delete_one = AsyncMock(return_value=_mock_delete_result(0))
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        result = await WorkflowService.delete_workflow("nonexistent", USER_ID)
        assert result is False

    @patch(
        "app.services.workflow.service.TriggerService.unregister_triggers",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_delete_with_integration_triggers_unregisters(
        self, mock_collection, mock_get, mock_scheduler, mock_unregister
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="calendar_event",
            composio_trigger_ids=["tid_1", "tid_2"],
        )
        wf = _make_workflow(trigger_config=trigger)
        mock_get.return_value = wf
        mock_collection.delete_one = AsyncMock(return_value=_mock_delete_result(1))
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True
        mock_unregister.assert_awaited_once()

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_delete_cancel_task_failure_non_critical(
        self, mock_collection, mock_get, mock_scheduler
    ):
        """cancel_task failure should not prevent deletion."""
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_collection.delete_one = AsyncMock(return_value=_mock_delete_result(1))
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )
        mock_scheduler.cancel_task = AsyncMock(side_effect=Exception("ARQ error"))

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_delete_db_error_raises(
        self, mock_collection, mock_get, mock_scheduler
    ):
        mock_get.return_value = _make_workflow()
        mock_collection.delete_one = AsyncMock(side_effect=Exception("DB error"))
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        with pytest.raises(Exception, match="DB error"):
            await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_delete_with_triggers_but_no_trigger_name_skips_unregister(
        self, mock_collection, mock_get, mock_scheduler
    ):
        """If trigger_ids exist but trigger_name is None, unregister is skipped."""
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name=None,
            composio_trigger_ids=["tid_1"],
        )
        wf = _make_workflow(trigger_config=trigger)
        mock_get.return_value = wf
        mock_collection.delete_one = AsyncMock(return_value=_mock_delete_result(1))
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )
        mock_scheduler.cancel_task = AsyncMock(return_value=True)

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True


# ===========================================================================
# WorkflowService.execute_workflow tests
# ===========================================================================


class TestExecuteWorkflow:
    """Tests for WorkflowService.execute_workflow."""

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_execution",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_execute_success(self, mock_collection, mock_get, mock_queue):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf
        mock_collection.find_one_and_update = AsyncMock(return_value=_workflow_doc(wf))

        request = WorkflowExecutionRequest(context={"key": "value"})
        result = await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

        assert isinstance(result, WorkflowExecutionResponse)
        assert result.execution_id.startswith("exec_")
        assert result.message == "Workflow execution started"
        mock_queue.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_execute_workflow_not_found(self, mock_get):
        mock_get.return_value = None

        request = WorkflowExecutionRequest()
        with pytest.raises(ValueError, match="not found"):
            await WorkflowService.execute_workflow("nonexistent", request, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_execute_deactivated_workflow(self, mock_get):
        wf = _make_workflow(activated=False)
        mock_get.return_value = wf

        request = WorkflowExecutionRequest()
        with pytest.raises(ValueError, match="deactivated"):
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_execute_no_steps_workflow(self, mock_get):
        wf = _make_workflow(steps=[])
        mock_get.return_value = wf

        request = WorkflowExecutionRequest()
        with pytest.raises(ValueError, match="no steps"):
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_execution",
        new_callable=AsyncMock,
        return_value=False,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_execute_queue_failure(self, mock_collection, mock_get, mock_queue):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf
        mock_collection.find_one_and_update = AsyncMock(return_value=_workflow_doc(wf))

        request = WorkflowExecutionRequest()
        with pytest.raises(ValueError, match="Failed to queue"):
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_execute_update_timestamp_failure(self, mock_collection, mock_get):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf
        mock_collection.find_one_and_update = AsyncMock(return_value=None)

        request = WorkflowExecutionRequest()
        with pytest.raises(ValueError, match="Failed to update"):
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)


# ===========================================================================
# WorkflowService.get_workflow_status tests
# ===========================================================================


class TestGetWorkflowStatus:
    """Tests for WorkflowService.get_workflow_status."""

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_status_success(self, mock_get):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf

        result = await WorkflowService.get_workflow_status(WORKFLOW_ID, USER_ID)
        assert isinstance(result, WorkflowStatusResponse)
        assert result.workflow_id == WORKFLOW_ID
        assert result.activated is True
        assert result.total_steps == 1

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_status_not_found(self, mock_get):
        mock_get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await WorkflowService.get_workflow_status("nonexistent", USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_status_with_error_message(self, mock_get):
        wf = _make_workflow(error_message="Generation failed")
        mock_get.return_value = wf

        result = await WorkflowService.get_workflow_status(WORKFLOW_ID, USER_ID)
        assert result.error_message == "Generation failed"


# ===========================================================================
# WorkflowService.activate_workflow tests
# ===========================================================================


class TestActivateWorkflow:
    """Tests for WorkflowService.activate_workflow."""

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_activate_manual_workflow(
        self, mock_collection, mock_get, mock_scheduler
    ):
        wf = _make_workflow(activated=False)
        activated_wf = _make_workflow(activated=True)
        mock_get.side_effect = [wf, activated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())

        result = await WorkflowService.activate_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        assert result.activated is True

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_activate_not_found(self, mock_get):
        mock_get.return_value = None

        result = await WorkflowService.activate_workflow("nonexistent", USER_ID)
        assert result is None

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_activate_db_update_no_match_returns_none(
        self, mock_collection, mock_get
    ):
        wf = _make_workflow(activated=False)
        mock_get.return_value = wf
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(matched=0)
        )

        result = await WorkflowService.activate_workflow(WORKFLOW_ID, USER_ID)
        assert result is None

    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_activate_trigger_registration_failure_raises(
        self, mock_get, mock_register
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="test_trigger",
        )
        wf = _make_workflow(activated=False, trigger_config=trigger)
        mock_get.return_value = wf
        mock_register.side_effect = TriggerRegistrationError(
            "Failed", trigger_name="test_trigger"
        )

        with pytest.raises(TriggerRegistrationError):
            await WorkflowService.activate_workflow(WORKFLOW_ID, USER_ID)

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_activate_schedule_workflow_schedules_execution(
        self, mock_collection, mock_get, mock_scheduler
    ):
        next_run = datetime.now(timezone.utc) + timedelta(hours=1)
        trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            next_run=next_run,
        )
        wf = _make_workflow(activated=False, trigger_config=trigger)
        activated_wf = _make_workflow(activated=True, trigger_config=trigger)
        mock_get.side_effect = [wf, activated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        result = await WorkflowService.activate_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        mock_scheduler.schedule_workflow_execution.assert_awaited_once()


# ===========================================================================
# WorkflowService.deactivate_workflow tests
# ===========================================================================


class TestDeactivateWorkflow:
    """Tests for WorkflowService.deactivate_workflow."""

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_deactivate_success(self, mock_collection, mock_get, mock_scheduler):
        wf = _make_workflow(activated=True)
        deactivated_wf = _make_workflow(activated=False)
        mock_get.side_effect = [wf, deactivated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )

        result = await WorkflowService.deactivate_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        mock_scheduler.cancel_scheduled_workflow_execution.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_deactivate_not_found(self, mock_get):
        mock_get.return_value = None

        result = await WorkflowService.deactivate_workflow("nonexistent", USER_ID)
        assert result is None

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_deactivate_db_update_no_match(
        self, mock_collection, mock_get, mock_scheduler
    ):
        wf = _make_workflow(activated=True)
        mock_get.side_effect = [wf]
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(matched=0)
        )
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )

        result = await WorkflowService.deactivate_workflow(WORKFLOW_ID, USER_ID)
        assert result is None

    @patch(
        "app.services.workflow.service.TriggerService.unregister_triggers",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_deactivate_with_integration_triggers_unregisters(
        self, mock_collection, mock_get, mock_scheduler, mock_unregister
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="calendar_event",
            composio_trigger_ids=["tid_1"],
        )
        wf = _make_workflow(activated=True, trigger_config=trigger)
        deactivated_wf = _make_workflow(activated=False, trigger_config=trigger)
        mock_get.side_effect = [wf, deactivated_wf]
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())
        mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock(
            return_value=True
        )

        result = await WorkflowService.deactivate_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        mock_unregister.assert_awaited_once()


# ===========================================================================
# WorkflowService.regenerate_workflow_steps tests
# ===========================================================================


class TestRegenerateWorkflowSteps:
    """Tests for WorkflowService.regenerate_workflow_steps."""

    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_regenerate_success(self, mock_collection, mock_get, mock_gen):
        wf = _make_workflow()
        mock_get.return_value = wf
        new_steps = [
            {
                "id": "step_0",
                "title": "New Step",
                "category": "gaia",
                "description": "New",
            }
        ]
        mock_gen.return_value = new_steps

        updated_doc = _workflow_doc(wf)
        updated_doc["steps"] = new_steps
        mock_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        result = await WorkflowService.regenerate_workflow_steps(WORKFLOW_ID, USER_ID)
        assert result is not None
        mock_gen.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_regenerate_not_found(self, mock_get):
        mock_get.return_value = None

        result = await WorkflowService.regenerate_workflow_steps("nonexistent", USER_ID)
        assert result is None

    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_regenerate_llm_failure_raises(self, mock_get, mock_gen):
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_gen.side_effect = RuntimeError("LLM failed")

        with pytest.raises(RuntimeError, match="LLM failed"):
            await WorkflowService.regenerate_workflow_steps(WORKFLOW_ID, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_regenerate_db_returns_none(
        self, mock_collection, mock_get, mock_gen
    ):
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_gen.return_value = [
            {"id": "step_0", "title": "T", "category": "c", "description": "d"}
        ]
        mock_collection.find_one_and_update = AsyncMock(return_value=None)

        result = await WorkflowService.regenerate_workflow_steps(WORKFLOW_ID, USER_ID)
        assert result is None


# ===========================================================================
# WorkflowService.increment_execution_count tests
# ===========================================================================


class TestIncrementExecutionCount:
    """Tests for WorkflowService.increment_execution_count."""

    @patch("app.services.workflow.service.workflows_collection")
    async def test_increment_success(self, mock_collection):
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())

        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=True
        )
        assert result is True

        # Check that both total and successful are incremented
        call_args = mock_collection.update_one.call_args
        inc_data = call_args[0][1]["$inc"]
        assert inc_data["total_executions"] == 1
        assert inc_data["successful_executions"] == 1

    @patch("app.services.workflow.service.workflows_collection")
    async def test_increment_failure_only_total(self, mock_collection):
        mock_collection.update_one = AsyncMock(return_value=_mock_update_result())

        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=False
        )
        assert result is True

        call_args = mock_collection.update_one.call_args
        inc_data = call_args[0][1]["$inc"]
        assert inc_data["total_executions"] == 1
        assert "successful_executions" not in inc_data

    @patch("app.services.workflow.service.workflows_collection")
    async def test_increment_workflow_not_found(self, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(matched=0)
        )

        result = await WorkflowService.increment_execution_count("nonexistent", USER_ID)
        assert result is False

    @patch("app.services.workflow.service.workflows_collection")
    async def test_increment_db_error_returns_false(self, mock_collection):
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

        result = await WorkflowService.increment_execution_count(WORKFLOW_ID, USER_ID)
        assert result is False


# ===========================================================================
# WorkflowService._generate_workflow_steps tests
# ===========================================================================


class TestGenerateWorkflowSteps:
    """Tests for WorkflowService._generate_workflow_steps (internal)."""

    @patch(
        "app.services.workflow.service.handle_workflow_error", new_callable=AsyncMock
    )
    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_generate_steps_success(
        self, mock_collection, mock_get, mock_gen, mock_error_handler
    ):
        wf = _make_workflow()
        mock_get.return_value = wf
        steps_data = [
            {"id": "step_0", "title": "S", "category": "gaia", "description": "D"}
        ]
        mock_gen.return_value = steps_data
        mock_collection.find_one_and_update = AsyncMock(return_value=_workflow_doc(wf))

        await WorkflowService._generate_workflow_steps(WORKFLOW_ID, USER_ID)

        mock_gen.assert_awaited_once()
        # Should be called at least twice: once at start and once to save steps
        assert mock_collection.find_one_and_update.await_count >= 2

    @patch(
        "app.services.workflow.service.handle_workflow_error", new_callable=AsyncMock
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_generate_steps_workflow_not_found_returns_early(
        self, mock_collection, mock_get, mock_error_handler
    ):
        mock_get.return_value = None
        mock_collection.find_one_and_update = AsyncMock(return_value=None)

        # Should not raise, just return
        await WorkflowService._generate_workflow_steps(WORKFLOW_ID, USER_ID)
        mock_error_handler.assert_not_awaited()

    @patch(
        "app.services.workflow.service.handle_workflow_error", new_callable=AsyncMock
    )
    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflows_collection")
    async def test_generate_steps_llm_failure_persists_error(
        self, mock_collection, mock_get, mock_gen, mock_error_handler
    ):
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_gen.side_effect = RuntimeError("LLM quota exceeded")
        mock_collection.find_one_and_update = AsyncMock(return_value=None)

        await WorkflowService._generate_workflow_steps(WORKFLOW_ID, USER_ID)

        # Error should be persisted to the database
        update_calls = mock_collection.find_one_and_update.await_args_list
        # One of the calls should set error_message
        error_set_calls = [
            c
            for c in update_calls
            if "$set" in c[0][1] and "error_message" in c[0][1]["$set"]
        ]
        assert len(error_set_calls) >= 1
        mock_error_handler.assert_awaited_once()


# ===========================================================================
# WorkflowService._register_integration_triggers tests
# ===========================================================================


class TestRegisterIntegrationTriggers:
    """Tests for WorkflowService._register_integration_triggers."""

    async def test_non_integration_trigger_returns_empty(self):
        trigger = _make_trigger_config(trigger_type=TriggerType.MANUAL)
        result = await WorkflowService._register_integration_triggers(
            WORKFLOW_ID, USER_ID, trigger
        )
        assert result == []

    async def test_integration_trigger_without_name_raises(self):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION, trigger_name=None
        )
        with pytest.raises(TriggerRegistrationError, match="trigger_name"):
            await WorkflowService._register_integration_triggers(
                WORKFLOW_ID, USER_ID, trigger
            )

    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
        return_value=["tid_1"],
    )
    async def test_integration_trigger_success(self, mock_register):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION, trigger_name="calendar_event"
        )
        result = await WorkflowService._register_integration_triggers(
            WORKFLOW_ID, USER_ID, trigger
        )
        assert result == ["tid_1"]
        mock_register.assert_awaited_once()


# ===========================================================================
# generation_service helper tests
# ===========================================================================


class TestEnrichSteps:
    """Tests for enrich_steps."""

    def test_enrich_adds_ids(self):
        steps = [
            GeneratedStep(title="Step A", category="gmail", description="Send email"),
            GeneratedStep(title="Step B", category="gaia", description="Summarize"),
        ]
        result = enrich_steps(steps)
        assert len(result) == 2
        assert result[0]["id"] == "step_0"
        assert result[1]["id"] == "step_1"
        assert result[0]["title"] == "Step A"
        assert result[0]["category"] == "gmail"

    def test_enrich_empty_list(self):
        result = enrich_steps([])
        assert result == []


class TestParseWorkflowResponse:
    """Tests for _parse_workflow_response."""

    def test_parse_clean_json(self):
        content = (
            '{"steps": [{"title": "Test", "category": "gaia", "description": "Do it"}]}'
        )
        result = _parse_workflow_response(content)
        assert isinstance(result, GeneratedWorkflow)
        assert len(result.steps) == 1

    def test_parse_json_with_markdown_fences(self):
        content = '```json\n{"steps": [{"title": "Test", "category": "gaia", "description": "Do it"}]}\n```'
        result = _parse_workflow_response(content)
        assert isinstance(result, GeneratedWorkflow)
        assert len(result.steps) == 1

    def test_parse_json_with_bare_fences(self):
        content = (
            '```\n{"steps": [{"title": "T", "category": "c", "description": "d"}]}\n```'
        )
        result = _parse_workflow_response(content)
        assert isinstance(result, GeneratedWorkflow)

    def test_parse_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_workflow_response("not valid json at all")


class TestBuildTriggerHint:
    """Tests for _build_trigger_hint."""

    def test_no_config_returns_default(self):
        result = _build_trigger_hint(None)
        assert "No trigger selected" in result

    def test_schedule_with_cron(self):
        config = {"type": "schedule", "cron_expression": "0 9 * * *"}
        result = _build_trigger_hint(config)
        assert "scheduled trigger" in result
        assert "0 9 * * *" in result

    def test_schedule_without_cron(self):
        config = {"type": "schedule"}
        result = _build_trigger_hint(config)
        assert "scheduled trigger" in result

    def test_manual(self):
        result = _build_trigger_hint({"type": "manual"})
        assert "manual trigger" in result

    def test_integration_with_name(self):
        config = {"type": "integration", "trigger_name": "gmail_new_message"}
        result = _build_trigger_hint(config)
        assert "gmail_new_message" in result

    def test_unknown_type(self):
        result = _build_trigger_hint({"type": "webhook"})
        assert "webhook" in result


class TestBuildAvailableTriggers:
    """Tests for _build_available_triggers."""

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    def test_empty_integrations(self):
        result = _build_available_triggers()
        assert result == ""


# ===========================================================================
# WorkflowGenerationService.generate_steps_with_llm tests
# ===========================================================================


class TestGenerateStepsWithLLM:
    """Tests for WorkflowGenerationService.generate_steps_with_llm."""

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    @patch("app.agents.tools.core.registry.get_tool_registry", new_callable=AsyncMock)
    async def test_generate_with_structured_output(
        self, mock_registry_fn, mock_init_llm
    ):
        # Setup tool registry mock
        mock_registry = MagicMock()
        mock_category = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_category.get_tool_objects.return_value = [mock_tool]
        mock_registry.get_all_category_objects.return_value = {
            "test_cat": mock_category
        }
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        # Setup LLM mock with structured output
        generated = GeneratedWorkflow(
            steps=[
                GeneratedStep(
                    title="Step 1", category="gaia", description="Do something"
                )
            ]
        )
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=generated)
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_init_llm.return_value = mock_llm

        result = await WorkflowGenerationService.generate_steps_with_llm(
            "Test prompt", "Test Title"
        )

        assert len(result) == 1
        assert result[0]["id"] == "step_0"
        assert result[0]["title"] == "Step 1"

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    @patch("app.agents.tools.core.registry.get_tool_registry", new_callable=AsyncMock)
    async def test_generate_fallback_text_parsing(
        self, mock_registry_fn, mock_init_llm
    ):
        """When with_structured_output is not available, fall back to text parsing."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        # LLM without with_structured_output
        mock_llm = MagicMock(spec=[])  # No attributes at all
        mock_response = MagicMock()
        mock_response.content = '{"steps": [{"title": "Parsed", "category": "gaia", "description": "From text"}]}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        result = await WorkflowGenerationService.generate_steps_with_llm(
            "Test prompt", "Test Title"
        )

        assert len(result) == 1
        assert result[0]["title"] == "Parsed"

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    @patch("app.agents.tools.core.registry.get_tool_registry", new_callable=AsyncMock)
    async def test_generate_empty_steps_retries_then_fails(
        self, mock_registry_fn, mock_init_llm
    ):
        """If LLM returns empty steps, retry and ultimately raise RuntimeError."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        empty_result = GeneratedWorkflow(steps=[])
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=empty_result)
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_init_llm.return_value = mock_llm

        with pytest.raises(RuntimeError, match="failed"):
            await WorkflowGenerationService.generate_steps_with_llm(
                "Test prompt", "Test Title"
            )

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    @patch("app.agents.tools.core.registry.get_tool_registry", new_callable=AsyncMock)
    async def test_generate_llm_exception_retries(
        self, mock_registry_fn, mock_init_llm
    ):
        """LLM exceptions should be retried up to _MAX_GENERATION_ATTEMPTS."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_init_llm.return_value = mock_llm

        with pytest.raises(RuntimeError, match="failed"):
            await WorkflowGenerationService.generate_steps_with_llm(
                "Test prompt", "Test Title"
            )

        # Should have been called twice (max attempts = 2)
        assert mock_structured_llm.ainvoke.await_count == 2

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    @patch("app.agents.tools.core.registry.get_tool_registry", new_callable=AsyncMock)
    async def test_generate_with_description(self, mock_registry_fn, mock_init_llm):
        """Description should be appended to the prompt context."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        generated = GeneratedWorkflow(
            steps=[GeneratedStep(title="S1", category="gaia", description="D")]
        )
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=generated)
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_init_llm.return_value = mock_llm

        await WorkflowGenerationService.generate_steps_with_llm(
            "Prompt text", "Title", description="Short description"
        )

        # Verify description was included in the formatted prompt
        invoke_arg = mock_structured_llm.ainvoke.call_args[0][0]
        assert "Short description" in invoke_arg

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    @patch("app.agents.tools.core.registry.get_tool_registry", new_callable=AsyncMock)
    async def test_generate_structured_output_not_implemented_fallback(
        self, mock_registry_fn, mock_init_llm
    ):
        """If with_structured_output raises NotImplementedError, fall back to text."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError(
            "Not supported"
        )
        mock_response = MagicMock()
        mock_response.content = '{"steps": [{"title": "Fallback", "category": "gaia", "description": "Worked"}]}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        result = await WorkflowGenerationService.generate_steps_with_llm(
            "Prompt", "Title"
        )
        assert len(result) == 1
        assert result[0]["title"] == "Fallback"


# ===========================================================================
# WorkflowGenerationService.generate_workflow_prompt tests
# ===========================================================================


class TestGenerateWorkflowPrompt:
    """Tests for WorkflowGenerationService.generate_workflow_prompt."""

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.prompt_output_parser")
    @patch("app.services.workflow.generation_service.init_llm")
    async def test_generate_prompt_success(self, mock_init_llm, mock_parser):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "parsed content"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        mock_parsed = MagicMock()
        mock_parsed.instructions = "Step-by-step instructions here"
        mock_parsed.trigger_type = "schedule"
        mock_parsed.cron_expression = "0 9 * * 1-5"
        mock_parsed.trigger_name = None
        mock_parser.parse.return_value = mock_parsed
        mock_parser.get_format_instructions.return_value = "Format: JSON"

        result = await WorkflowGenerationService.generate_workflow_prompt(
            title="Morning Briefing",
            description="Daily summary",
        )

        assert result["prompt"] == "Step-by-step instructions here"
        assert result["suggested_trigger"] is not None
        assert result["suggested_trigger"].type == "schedule"
        assert result["suggested_trigger"].cron_expression == "0 9 * * 1-5"

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.prompt_output_parser")
    @patch("app.services.workflow.generation_service.init_llm")
    async def test_generate_prompt_manual_no_suggested_trigger(
        self, mock_init_llm, mock_parser
    ):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "content"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        mock_parsed = MagicMock()
        mock_parsed.instructions = "Manual instructions"
        mock_parsed.trigger_type = "manual"
        mock_parsed.cron_expression = None
        mock_parsed.trigger_name = None
        mock_parser.parse.return_value = mock_parsed
        mock_parser.get_format_instructions.return_value = ""

        result = await WorkflowGenerationService.generate_workflow_prompt(title="Task")

        assert result["prompt"] == "Manual instructions"
        assert result["suggested_trigger"] is not None
        assert result["suggested_trigger"].type == "manual"

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.prompt_output_parser")
    @patch("app.services.workflow.generation_service.init_llm")
    async def test_generate_prompt_invalid_trigger_type_no_suggestion(
        self, mock_init_llm, mock_parser
    ):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "content"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        mock_parsed = MagicMock()
        mock_parsed.instructions = "Instructions"
        mock_parsed.trigger_type = "webhook"  # Not in the valid set
        mock_parsed.cron_expression = None
        mock_parsed.trigger_name = None
        mock_parser.parse.return_value = mock_parsed
        mock_parser.get_format_instructions.return_value = ""

        result = await WorkflowGenerationService.generate_workflow_prompt(title="Task")

        assert result["prompt"] == "Instructions"
        assert result["suggested_trigger"] is None

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch("app.services.workflow.generation_service.init_llm")
    async def test_generate_prompt_llm_failure_raises(self, mock_init_llm):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))
        mock_init_llm.return_value = mock_llm

        with pytest.raises(Exception, match="LLM unavailable"):
            await WorkflowGenerationService.generate_workflow_prompt(title="Test")


# ===========================================================================
# WorkflowScheduler tests
# ===========================================================================


class TestWorkflowScheduler:
    """Tests for WorkflowScheduler."""

    def test_get_job_name(self):
        scheduler = WorkflowScheduler()
        assert scheduler.get_job_name() == "execute_workflow_by_id"

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_task_found(self, mock_collection):
        doc = _workflow_doc(_make_workflow())
        mock_collection.find_one = AsyncMock(return_value=doc)

        scheduler = WorkflowScheduler()
        result = await scheduler.get_task(WORKFLOW_ID)

        assert result is not None
        assert isinstance(result, Workflow)

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_task_not_found(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        scheduler = WorkflowScheduler()
        result = await scheduler.get_task("nonexistent")
        assert result is None

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_task_with_user_id(self, mock_collection):
        doc = _workflow_doc(_make_workflow())
        mock_collection.find_one = AsyncMock(return_value=doc)

        scheduler = WorkflowScheduler()
        await scheduler.get_task(WORKFLOW_ID, user_id=USER_ID)

        query = mock_collection.find_one.call_args[0][0]
        assert query["user_id"] == USER_ID

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_task_db_error_returns_none(self, mock_collection):
        mock_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        scheduler = WorkflowScheduler()
        result = await scheduler.get_task(WORKFLOW_ID)
        assert result is None

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_update_task_status_success(self, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=1)
        )

        scheduler = WorkflowScheduler()
        from app.models.scheduler_models import ScheduledTaskStatus

        result = await scheduler.update_task_status(
            WORKFLOW_ID, ScheduledTaskStatus.EXECUTING
        )
        assert result is True

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_update_task_status_not_found(self, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=0)
        )

        scheduler = WorkflowScheduler()
        from app.models.scheduler_models import ScheduledTaskStatus

        result = await scheduler.update_task_status(
            "nonexistent", ScheduledTaskStatus.EXECUTING
        )
        assert result is False

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_update_task_status_with_user_id(self, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=1)
        )

        scheduler = WorkflowScheduler()
        from app.models.scheduler_models import ScheduledTaskStatus

        await scheduler.update_task_status(
            WORKFLOW_ID, ScheduledTaskStatus.SCHEDULED, user_id=USER_ID
        )

        query = mock_collection.update_one.call_args[0][0]
        assert query["user_id"] == USER_ID

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_update_task_status_db_error_returns_false(self, mock_collection):
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

        scheduler = WorkflowScheduler()
        from app.models.scheduler_models import ScheduledTaskStatus

        result = await scheduler.update_task_status(
            WORKFLOW_ID, ScheduledTaskStatus.EXECUTING
        )
        assert result is False

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_update_task_status_with_extra_data(self, mock_collection):
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=1)
        )

        scheduler = WorkflowScheduler()
        from app.models.scheduler_models import ScheduledTaskStatus

        await scheduler.update_task_status(
            WORKFLOW_ID,
            ScheduledTaskStatus.COMPLETED,
            update_data={"occurrence_count": 5},
        )

        update_fields = mock_collection.update_one.call_args[0][1]["$set"]
        assert update_fields["occurrence_count"] == 5

    async def test_schedule_workflow_execution_success(self):
        scheduler = WorkflowScheduler()
        scheduler.schedule_task = AsyncMock(return_value=True)

        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await scheduler.schedule_workflow_execution(
            WORKFLOW_ID, USER_ID, scheduled_at, repeat="0 9 * * *"
        )
        assert result is True
        scheduler.schedule_task.assert_awaited_once()

    async def test_schedule_workflow_execution_failure(self):
        scheduler = WorkflowScheduler()
        scheduler.schedule_task = AsyncMock(return_value=False)

        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await scheduler.schedule_workflow_execution(
            WORKFLOW_ID, USER_ID, scheduled_at
        )
        assert result is False

    async def test_schedule_workflow_execution_exception_returns_false(self):
        scheduler = WorkflowScheduler()
        scheduler.schedule_task = AsyncMock(side_effect=Exception("Redis down"))

        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await scheduler.schedule_workflow_execution(
            WORKFLOW_ID, USER_ID, scheduled_at
        )
        assert result is False

    async def test_cancel_scheduled_workflow_execution_success(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=True)
        scheduler.cancel_task = AsyncMock(return_value=True)

        result = await scheduler.cancel_scheduled_workflow_execution(WORKFLOW_ID)
        assert result is True

    async def test_cancel_scheduled_workflow_db_only(self):
        """DB cancel succeeds but ARQ cancel fails."""
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=True)
        scheduler.cancel_task = AsyncMock(return_value=False)

        result = await scheduler.cancel_scheduled_workflow_execution(WORKFLOW_ID)
        assert result is True  # Returns db_success

    async def test_cancel_scheduled_workflow_both_fail(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=False)
        scheduler.cancel_task = AsyncMock(return_value=False)

        result = await scheduler.cancel_scheduled_workflow_execution(WORKFLOW_ID)
        assert result is False

    async def test_cancel_scheduled_workflow_exception_returns_false(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(side_effect=Exception("Error"))

        result = await scheduler.cancel_scheduled_workflow_execution(WORKFLOW_ID)
        assert result is False

    async def test_reschedule_workflow_success(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=True)
        scheduler.reschedule_task = AsyncMock(return_value=True)

        new_time = datetime.now(timezone.utc) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(
            WORKFLOW_ID, new_time, repeat="0 10 * * *"
        )
        assert result is True

    async def test_reschedule_workflow_db_failure(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=False)

        new_time = datetime.now(timezone.utc) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time)
        assert result is False

    async def test_reschedule_workflow_arq_failure(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=True)
        scheduler.reschedule_task = AsyncMock(return_value=False)

        new_time = datetime.now(timezone.utc) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time)
        assert result is False

    async def test_reschedule_workflow_exception_returns_false(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(side_effect=Exception("Error"))

        new_time = datetime.now(timezone.utc) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time)
        assert result is False

    async def test_get_workflow_status_found(self):
        scheduler = WorkflowScheduler()
        wf = _make_workflow()
        scheduler.get_task = AsyncMock(return_value=wf)

        result = await scheduler.get_workflow_status(WORKFLOW_ID)
        assert result is not None

    async def test_get_workflow_status_not_found(self):
        scheduler = WorkflowScheduler()
        scheduler.get_task = AsyncMock(return_value=None)

        result = await scheduler.get_workflow_status(WORKFLOW_ID)
        assert result is None

    async def test_get_workflow_status_error_returns_none(self):
        scheduler = WorkflowScheduler()
        scheduler.get_task = AsyncMock(side_effect=Exception("Error"))

        result = await scheduler.get_workflow_status(WORKFLOW_ID)
        assert result is None

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_pending_task_returns_workflows(self, mock_collection):
        doc = _workflow_doc(_make_workflow())
        mock_cursor = MagicMock()
        mock_cursor.__aiter__ = MagicMock(return_value=iter([doc]))

        # Make it async iterable
        async def async_iter():
            yield doc

        mock_cursor.__aiter__ = lambda self: async_iter()

        mock_collection.find = MagicMock(return_value=mock_cursor)

        scheduler = WorkflowScheduler()
        # Use a proper async iterator mock
        async_docs = [doc]

        class AsyncIterator:
            def __init__(self, items):
                self.items = iter(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.items)
                except StopIteration:
                    raise StopAsyncIteration

        mock_collection.find = MagicMock(return_value=AsyncIterator(async_docs))

        now = datetime.now(timezone.utc)
        result = await scheduler.get_pending_task(now)
        assert len(result) == 1

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_pending_task_empty(self, mock_collection):
        class EmptyAsyncIterator:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        mock_collection.find = MagicMock(return_value=EmptyAsyncIterator())

        scheduler = WorkflowScheduler()
        now = datetime.now(timezone.utc)
        result = await scheduler.get_pending_task(now)
        assert result == []

    @patch("app.services.workflow.scheduler.workflows_collection")
    async def test_get_pending_task_db_error(self, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        scheduler = WorkflowScheduler()
        now = datetime.now(timezone.utc)
        result = await scheduler.get_pending_task(now)
        assert result == []

    async def test_execute_task_with_workflow(self):
        """execute_task with a valid Workflow should attempt execution."""
        scheduler = WorkflowScheduler()
        wf = _make_workflow()

        with patch(
            "app.workers.tasks.execute_workflow_as_chat", new_callable=AsyncMock
        ) as mock_exec:
            with patch(
                "app.workers.tasks.workflow_tasks.create_workflow_completion_notification",
                new_callable=AsyncMock,
            ):
                mock_exec.return_value = ["message1"]

                result = await scheduler.execute_task(wf)
                assert result.success is True

    async def test_execute_task_with_non_workflow_fails(self):
        """execute_task with a non-Workflow object should fail."""
        scheduler = WorkflowScheduler()
        fake_task = MagicMock()
        fake_task.id = "task_123"

        result = await scheduler.execute_task(fake_task)
        assert result.success is False


# ===========================================================================
# WorkflowQueueService tests
# ===========================================================================


class TestWorkflowQueueService:
    """Tests for WorkflowQueueService."""

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_generation_success(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_123"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_generation(
            WORKFLOW_ID, USER_ID
        )
        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "generate_workflow_steps", WORKFLOW_ID, USER_ID
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_generation_no_job(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_generation(
            WORKFLOW_ID, USER_ID
        )
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_generation_exception(self, mock_redis):
        mock_redis.get_pool = AsyncMock(side_effect=Exception("Redis down"))

        result = await WorkflowQueueService.queue_workflow_generation(
            WORKFLOW_ID, USER_ID
        )
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_execution_success(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_456"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_execution(
            WORKFLOW_ID, USER_ID, context={"key": "val"}
        )
        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", WORKFLOW_ID, {"key": "val"}
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_execution_no_context(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_789"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_execution(
            WORKFLOW_ID, USER_ID
        )
        assert result is True
        # context defaults to empty dict
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", WORKFLOW_ID, {}
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_execution_failure(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_execution(
            WORKFLOW_ID, USER_ID
        )
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_scheduled_execution_success(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_sched"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await WorkflowQueueService.queue_scheduled_workflow_execution(
            WORKFLOW_ID, scheduled_at
        )
        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", WORKFLOW_ID, {}, _defer_until=scheduled_at
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_scheduled_execution_failure(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await WorkflowQueueService.queue_scheduled_workflow_execution(
            WORKFLOW_ID, scheduled_at
        )
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_regeneration_success(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_regen"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_regeneration(
            WORKFLOW_ID, USER_ID, "User requested changes", True
        )
        assert result is True

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_regeneration_failure(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_regeneration(
            WORKFLOW_ID, USER_ID, "reason"
        )
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_todo_workflow_generation_success(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_todo"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_pool.set = AsyncMock()
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_123", USER_ID, "Buy groceries", "Weekly shopping"
        )
        assert result is True
        # Should set Redis flag
        mock_pool.set.assert_awaited_once()

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_todo_workflow_generation_failure(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_todo_workflow_generation(
            "todo_123", USER_ID, "title"
        )
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_is_workflow_generating_true(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.get = AsyncMock(return_value=b"1")
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.is_workflow_generating("todo_123")
        assert result is True

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_is_workflow_generating_false(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.get = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.is_workflow_generating("todo_123")
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_is_workflow_generating_exception_returns_false(self, mock_redis):
        mock_redis.get_pool = AsyncMock(side_effect=Exception("Redis error"))

        result = await WorkflowQueueService.is_workflow_generating("todo_123")
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_clear_workflow_generating_flag(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.delete = AsyncMock()
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        await WorkflowQueueService.clear_workflow_generating_flag("todo_123")
        mock_pool.delete.assert_awaited_once_with("todo_workflow_generating:todo_123")

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_clear_workflow_generating_flag_exception_swallowed(self, mock_redis):
        mock_redis.get_pool = AsyncMock(side_effect=Exception("Redis error"))

        # Should not raise
        await WorkflowQueueService.clear_workflow_generating_flag("todo_123")


# ===========================================================================
# TriggerService tests
# ===========================================================================


class TestTriggerService:
    """Tests for TriggerService."""

    @patch("app.services.workflow.trigger_service.OAUTH_INTEGRATIONS", [])
    async def test_get_all_workflow_triggers_empty(self):
        result = await TriggerService.get_all_workflow_triggers()
        assert result == []

    @patch("app.services.workflow.trigger_service.OAUTH_INTEGRATIONS", [])
    def test_get_trigger_by_slug_not_found(self):
        result = TriggerService.get_trigger_by_slug("nonexistent")
        assert result is None

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_trigger_reference_count(self, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=3)

        count = await TriggerService.get_trigger_reference_count("trigger_123")
        assert count == 3

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_trigger_reference_count_error_returns_zero(
        self, mock_collection
    ):
        mock_collection.count_documents = AsyncMock(side_effect=Exception("DB error"))

        count = await TriggerService.get_trigger_reference_count("trigger_123")
        assert count == 0

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_triggers_safe_to_delete_all_safe(self, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=0)

        safe = await TriggerService.get_triggers_safe_to_delete(["t1", "t2"])
        assert safe == ["t1", "t2"]

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_triggers_safe_to_delete_none_safe(self, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=2)

        safe = await TriggerService.get_triggers_safe_to_delete(["t1"])
        assert safe == []

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_triggers_safe_to_delete_partial(self, mock_collection):
        # t1 has references, t2 does not
        mock_collection.count_documents = AsyncMock(side_effect=[1, 0])

        safe = await TriggerService.get_triggers_safe_to_delete(["t1", "t2"])
        assert safe == ["t2"]

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_triggers_safe_to_delete_with_excluding_workflow_id(
        self, mock_collection
    ):
        mock_collection.count_documents = AsyncMock(return_value=0)

        await TriggerService.get_triggers_safe_to_delete(
            ["t1"], excluding_workflow_id="wf_123"
        )

        query = mock_collection.count_documents.call_args[0][0]
        assert query["_id"] == {"$ne": "wf_123"}

    @patch("app.services.workflow.trigger_service.workflows_collection")
    async def test_get_triggers_safe_to_delete_error_skips(self, mock_collection):
        """On error, trigger should not be included in safe-to-delete list."""
        mock_collection.count_documents = AsyncMock(side_effect=Exception("DB error"))

        safe = await TriggerService.get_triggers_safe_to_delete(["t1"])
        assert safe == []

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_no_handler(self, mock_get_handler):
        mock_get_handler.return_value = None
        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)

        result = await TriggerService.register_triggers(
            USER_ID, WORKFLOW_ID, "unknown_trigger", trigger
        )
        assert result == []

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_no_handler_raise_on_failure(
        self, mock_get_handler
    ):
        mock_get_handler.return_value = None
        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)

        with pytest.raises(TriggerRegistrationError):
            await TriggerService.register_triggers(
                USER_ID, WORKFLOW_ID, "unknown", trigger, raise_on_failure=True
            )

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_success(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(return_value=["tid_1", "tid_2"])
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        result = await TriggerService.register_triggers(
            USER_ID, WORKFLOW_ID, "calendar_event", trigger
        )
        assert result == ["tid_1", "tid_2"]

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_empty_result_raise_on_failure(
        self, mock_get_handler
    ):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(return_value=[])
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        with pytest.raises(TriggerRegistrationError, match="Failed to register"):
            await TriggerService.register_triggers(
                USER_ID, WORKFLOW_ID, "calendar_event", trigger, raise_on_failure=True
            )

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_type_error_re_raised(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(side_effect=TypeError("Wrong type"))
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        with pytest.raises(TypeError, match="Wrong type"):
            await TriggerService.register_triggers(
                USER_ID, WORKFLOW_ID, "trigger", trigger
            )

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_generic_exception_raise_on_failure(
        self, mock_get_handler
    ):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(side_effect=RuntimeError("API down"))
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        with pytest.raises(TriggerRegistrationError):
            await TriggerService.register_triggers(
                USER_ID, WORKFLOW_ID, "trigger", trigger, raise_on_failure=True
            )

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_generic_exception_no_raise(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(side_effect=RuntimeError("API down"))
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        result = await TriggerService.register_triggers(
            USER_ID, WORKFLOW_ID, "trigger", trigger, raise_on_failure=False
        )
        assert result == []

    async def test_unregister_triggers_empty_list(self):
        result = await TriggerService.unregister_triggers(USER_ID, "trigger", [])
        assert result is True

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_unregister_triggers_no_handler(self, mock_get_handler):
        mock_get_handler.return_value = None

        result = await TriggerService.unregister_triggers(USER_ID, "unknown", ["tid_1"])
        assert result is False

    @patch(
        "app.services.workflow.trigger_service.TriggerService.get_triggers_safe_to_delete",
        new_callable=AsyncMock,
        return_value=["tid_1"],
    )
    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_unregister_triggers_success(self, mock_get_handler, mock_safe):
        mock_handler = MagicMock()
        mock_handler.unregister = AsyncMock(return_value=True)
        mock_get_handler.return_value = mock_handler

        result = await TriggerService.unregister_triggers(
            USER_ID, "calendar_event", ["tid_1"], workflow_id=WORKFLOW_ID
        )
        assert result is True
        mock_handler.unregister.assert_awaited_once_with(USER_ID, ["tid_1"])

    @patch(
        "app.services.workflow.trigger_service.TriggerService.get_triggers_safe_to_delete",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_unregister_triggers_none_safe_to_delete(
        self, mock_get_handler, mock_safe
    ):
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        result = await TriggerService.unregister_triggers(
            USER_ID, "calendar_event", ["tid_1"]
        )
        assert result is True
        # Handler.unregister should not be called
        mock_handler.unregister.assert_not_called()

    @patch(
        "app.services.workflow.trigger_service.TriggerService.get_triggers_safe_to_delete",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_unregister_triggers_exception_returns_false(
        self, mock_get_handler, mock_safe
    ):
        mock_safe.side_effect = Exception("DB error")
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        result = await TriggerService.unregister_triggers(USER_ID, "trigger", ["tid_1"])
        assert result is False


# ===========================================================================
# execution_service tests
# ===========================================================================


class TestExecutionService:
    """Tests for execution_service functions."""

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_create_execution_success(self, mock_collection):
        mock_collection.insert_one = AsyncMock()

        result = await create_execution(WORKFLOW_ID, USER_ID, trigger_type="schedule")
        assert isinstance(result, WorkflowExecution)
        assert result.workflow_id == WORKFLOW_ID
        assert result.status == "running"
        assert result.trigger_type == "schedule"
        assert result.execution_id.startswith("exec_")

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_create_execution_with_conversation_id(self, mock_collection):
        mock_collection.insert_one = AsyncMock()

        result = await create_execution(
            WORKFLOW_ID, USER_ID, conversation_id="conv_123"
        )
        assert result.conversation_id == "conv_123"

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_complete_execution_success(self, mock_collection):
        started = datetime.now(timezone.utc) - timedelta(seconds=30)
        mock_collection.find_one = AsyncMock(
            return_value={
                "execution_id": EXECUTION_ID,
                "workflow_id": WORKFLOW_ID,
                "started_at": started,
            }
        )
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=1)
        )

        result = await complete_execution(EXECUTION_ID, "success", summary="All done")
        assert result is True

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_complete_execution_not_found(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        result = await complete_execution(EXECUTION_ID, "failed")
        assert result is False

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_complete_execution_with_error(self, mock_collection):
        started = datetime.now(timezone.utc) - timedelta(seconds=5)
        mock_collection.find_one = AsyncMock(
            return_value={
                "execution_id": EXECUTION_ID,
                "workflow_id": WORKFLOW_ID,
                "started_at": started,
            }
        )
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=1)
        )

        result = await complete_execution(
            EXECUTION_ID, "failed", error_message="Step 3 failed"
        )
        assert result is True

        # Verify error_message was included in update
        update_data = mock_collection.update_one.call_args[0][1]["$set"]
        assert update_data["error_message"] == "Step 3 failed"

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_complete_execution_no_started_at(self, mock_collection):
        """If started_at is missing, duration_seconds should be None."""
        mock_collection.find_one = AsyncMock(
            return_value={
                "execution_id": EXECUTION_ID,
                "workflow_id": WORKFLOW_ID,
                "started_at": None,
            }
        )
        mock_collection.update_one = AsyncMock(
            return_value=_mock_update_result(modified=1)
        )

        result = await complete_execution(EXECUTION_ID, "success")
        assert result is True

        update_data = mock_collection.update_one.call_args[0][1]["$set"]
        assert update_data["duration_seconds"] is None

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_get_workflow_executions_with_pagination(self, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=25)

        exec_doc = {
            "execution_id": EXECUTION_ID,
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "status": "success",
            "started_at": datetime.now(timezone.utc),
            "trigger_type": "manual",
        }

        class AsyncCursor:
            def __init__(self, items):
                self.items = iter(items)

            def sort(self, *args, **kwargs):
                return self

            def skip(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.items)
                except StopIteration:
                    raise StopAsyncIteration

        mock_collection.find = MagicMock(return_value=AsyncCursor([exec_doc]))

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID, limit=10, offset=0)
        assert isinstance(result, WorkflowExecutionsResponse)
        assert result.total == 25
        assert result.has_more is True
        assert len(result.executions) == 1

    @patch("app.services.workflow.execution_service.workflow_executions_collection")
    async def test_get_workflow_executions_empty(self, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=0)

        class EmptyAsyncCursor:
            def sort(self, *args, **kwargs):
                return self

            def skip(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        mock_collection.find = MagicMock(return_value=EmptyAsyncCursor())

        result = await get_workflow_executions(WORKFLOW_ID, USER_ID)
        assert result.total == 0
        assert result.has_more is False
        assert result.executions == []
