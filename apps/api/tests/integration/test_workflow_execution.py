"""
Integration tests for Workflow Execution End-to-End.

Tests the real workflow service functions with mocked I/O boundaries
(MongoDB, Redis, ChromaDB, LLM). Verifies that:
- CRUD lifecycle works end-to-end through real service code
- Validation rejects invalid workflows with clear errors
- Execution tracking records state transitions accurately
- Trigger registration delegates correctly and handles failures
- Slug generation produces unique slugs for similar names
- Queue service enqueues jobs with correct parameters
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_models import (
    CreateWorkflowRequest,
    GeneratedStep,
    TriggerConfig,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowExecutionRequest,
    WorkflowStep,
)
from app.services.workflow.execution_service import (
    complete_execution,
    create_execution,
    get_workflow_executions,
)
from app.services.workflow.generation_service import (
    WorkflowGenerationService,
    enrich_steps,
    _parse_workflow_response,
)
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.workflow.service import (
    WorkflowService,
    generate_unique_workflow_slug,
)
from app.services.workflow.validators import WorkflowValidator
from app.utils.exceptions import TriggerRegistrationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_WORKFLOW_ID = "wf_abc123def456"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trigger_config(trigger_type: str = "manual", **kwargs) -> TriggerConfig:
    """Build a TriggerConfig with sensible defaults."""
    return TriggerConfig(type=trigger_type, enabled=True, **kwargs)


def _make_workflow_steps(count: int = 2) -> list[WorkflowStep]:
    """Build a list of WorkflowStep objects."""
    return [
        WorkflowStep(
            id=f"step_{i}",
            title=f"Step {i + 1}",
            category="general",
            description=f"Description for step {i + 1}",
        )
        for i in range(count)
    ]


def _make_create_request(
    title: str = "Test Workflow",
    prompt: str = "Do something useful",
    steps: list[WorkflowStep] | None = None,
    trigger_type: str = "manual",
    **trigger_kwargs,
) -> CreateWorkflowRequest:
    """Build a CreateWorkflowRequest with defaults."""
    return CreateWorkflowRequest(
        title=title,
        prompt=prompt,
        trigger_config=_make_trigger_config(trigger_type, **trigger_kwargs),
        steps=steps or _make_workflow_steps(2),
        generate_immediately=False,
    )


def _make_workflow(
    workflow_id: str = FAKE_WORKFLOW_ID,
    user_id: str = FAKE_USER_ID,
    title: str = "Test Workflow",
    activated: bool = True,
    steps: list[WorkflowStep] | None = None,
    trigger_type: str = "manual",
) -> Workflow:
    """Build a Workflow model instance for testing."""
    return Workflow(
        id=workflow_id,
        user_id=user_id,
        title=title,
        description="A test workflow",
        prompt="Do the thing",
        steps=steps if steps is not None else _make_workflow_steps(2),
        trigger_config=_make_trigger_config(trigger_type),
        activated=activated,
    )


def _workflow_as_doc(workflow: Workflow) -> dict:
    """Convert a Workflow to a MongoDB-style document dict."""
    doc = workflow.model_dump(mode="json")
    doc["_id"] = doc.pop("id")
    return doc


# ---------------------------------------------------------------------------
# TEST 1: Workflow CRUD Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowCRUDLifecycle:
    """Create workflow -> read -> update -> verify state at each step."""

    async def test_create_workflow_inserts_and_activates(self):
        """WorkflowService.create_workflow inserts into MongoDB and activates."""
        request = _make_create_request(title="My New Workflow")
        mock_collection = AsyncMock()
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = "wf_fake"
        mock_collection.insert_one = AsyncMock(return_value=mock_insert_result)
        mock_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.ChromaClient") as mock_chroma_cls,
            patch(
                "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_chroma_cls.get_langchain_client = AsyncMock(return_value=MagicMock())
            workflow = await WorkflowService.create_workflow(request, FAKE_USER_ID)

        assert workflow.title == "My New Workflow"
        assert workflow.activated is True
        assert workflow.user_id == FAKE_USER_ID
        mock_collection.insert_one.assert_awaited_once()
        # Activation update call
        mock_collection.update_one.assert_awaited_once()

    async def test_get_workflow_returns_none_when_missing(self):
        """get_workflow returns None for a non-existent workflow."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            result = await WorkflowService.get_workflow("wf_missing", FAKE_USER_ID)

        assert result is None

    async def test_get_workflow_returns_transformed_document(self):
        """get_workflow returns a Workflow model from a stored document."""
        workflow = _make_workflow()
        doc = _workflow_as_doc(workflow)

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=doc)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            result = await WorkflowService.get_workflow(FAKE_WORKFLOW_ID, FAKE_USER_ID)

        assert result is not None
        assert result.title == "Test Workflow"
        assert result.id == FAKE_WORKFLOW_ID

    async def test_update_workflow_applies_changes(self):
        """update_workflow persists field changes and returns updated workflow."""
        original = _make_workflow()
        updated_doc = _workflow_as_doc(original)
        updated_doc["title"] = "Updated Title"

        mock_collection = AsyncMock()
        # First call: get_workflow for current state
        # Second call: get_workflow after update
        mock_collection.find_one = AsyncMock(
            side_effect=[_workflow_as_doc(original), updated_doc]
        )
        mock_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        update_request = UpdateWorkflowRequest(title="Updated Title")

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.workflow_scheduler"),
        ):
            result = await WorkflowService.update_workflow(
                FAKE_WORKFLOW_ID, update_request, FAKE_USER_ID
            )

        assert result is not None
        assert result.title == "Updated Title"

    async def test_delete_workflow_removes_document(self):
        """delete_workflow removes the document and returns True."""
        workflow = _make_workflow()
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=_workflow_as_doc(workflow))
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.workflow_scheduler") as mock_scheduler,
        ):
            mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock()
            mock_scheduler.cancel_task = AsyncMock()
            result = await WorkflowService.delete_workflow(
                FAKE_WORKFLOW_ID, FAKE_USER_ID
            )

        assert result is True
        mock_collection.delete_one.assert_awaited_once()

    async def test_delete_workflow_returns_false_when_not_found(self):
        """delete_workflow returns False when the document does not exist."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.workflow_scheduler") as mock_scheduler,
        ):
            mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock()
            mock_scheduler.cancel_task = AsyncMock()
            result = await WorkflowService.delete_workflow(
                "wf_nonexistent", FAKE_USER_ID
            )

        assert result is False


# ---------------------------------------------------------------------------
# TEST 2: Workflow Validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowValidation:
    """Test that invalid workflows are rejected with clear errors."""

    def test_validate_rejects_deactivated_workflow(self):
        """A deactivated workflow cannot be executed."""
        workflow = _make_workflow(activated=False)
        with pytest.raises(ValueError, match="deactivated"):
            WorkflowValidator.validate_for_execution(workflow)

    def test_validate_rejects_workflow_without_steps(self):
        """A workflow with no steps cannot be executed."""
        workflow = _make_workflow(steps=[])
        with pytest.raises(ValueError, match="no steps"):
            WorkflowValidator.validate_for_execution(workflow)

    def test_validate_rejects_deactivated_and_stepless(self):
        """Multiple validation errors are combined in the message."""
        workflow = _make_workflow(activated=False, steps=[])
        with pytest.raises(ValueError) as exc_info:
            WorkflowValidator.validate_for_execution(workflow)
        msg = str(exc_info.value)
        assert "deactivated" in msg
        assert "no steps" in msg

    def test_validate_passes_for_valid_workflow(self):
        """A valid activated workflow with steps passes validation."""
        workflow = _make_workflow(activated=True, steps=_make_workflow_steps(3))
        # Should not raise
        WorkflowValidator.validate_for_execution(workflow)

    def test_create_request_rejects_empty_title(self):
        """CreateWorkflowRequest rejects empty/whitespace title."""
        with pytest.raises(ValueError):
            CreateWorkflowRequest(
                title="   ",
                prompt="valid prompt",
                trigger_config=_make_trigger_config(),
            )

    def test_create_request_rejects_empty_prompt(self):
        """CreateWorkflowRequest rejects empty/whitespace prompt."""
        with pytest.raises(ValueError):
            CreateWorkflowRequest(
                title="Valid Title",
                prompt="   ",
                trigger_config=_make_trigger_config(),
            )


# ---------------------------------------------------------------------------
# TEST 3: Execution Tracking
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutionTracking:
    """Start execution -> update status -> complete -> verify history."""

    async def test_create_execution_records_running_state(self):
        """create_execution inserts a record with status 'running'."""
        mock_collection = AsyncMock()
        mock_collection.insert_one = AsyncMock()

        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection",
            mock_collection,
        ):
            execution = await create_execution(
                workflow_id=FAKE_WORKFLOW_ID,
                user_id=FAKE_USER_ID,
                trigger_type="manual",
            )

        assert execution.status == "running"
        assert execution.workflow_id == FAKE_WORKFLOW_ID
        assert execution.user_id == FAKE_USER_ID
        assert execution.execution_id.startswith("exec_")
        assert execution.started_at is not None
        mock_collection.insert_one.assert_awaited_once()

    async def test_complete_execution_success(self):
        """complete_execution updates record to 'success' with duration."""
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        stored_doc = {
            "execution_id": "exec_abc123",
            "workflow_id": FAKE_WORKFLOW_ID,
            "started_at": started_at,
        }
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=stored_doc)
        mock_collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection",
            mock_collection,
        ):
            result = await complete_execution(
                execution_id="exec_abc123",
                status="success",
                summary="Completed all steps",
            )

        assert result is True
        update_call = mock_collection.update_one.call_args
        update_set = update_call[0][1]["$set"]
        assert update_set["status"] == "success"
        assert update_set["summary"] == "Completed all steps"
        assert update_set["duration_seconds"] is not None
        assert update_set["duration_seconds"] >= 0

    async def test_complete_execution_failure_with_error_message(self):
        """complete_execution records 'failed' status with error message."""
        stored_doc = {
            "execution_id": "exec_fail",
            "workflow_id": FAKE_WORKFLOW_ID,
            "started_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=stored_doc)
        mock_collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection",
            mock_collection,
        ):
            result = await complete_execution(
                execution_id="exec_fail",
                status="failed",
                error_message="Step 2 timed out",
            )

        assert result is True
        update_set = mock_collection.update_one.call_args[0][1]["$set"]
        assert update_set["status"] == "failed"
        assert update_set["error_message"] == "Step 2 timed out"

    async def test_complete_execution_returns_false_for_missing(self):
        """complete_execution returns False when execution_id is not found."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection",
            mock_collection,
        ):
            result = await complete_execution(
                execution_id="exec_nonexistent",
                status="success",
            )

        assert result is False
        mock_collection.update_one.assert_not_awaited()

    async def test_get_workflow_executions_paginates(self):
        """get_workflow_executions returns paginated results with correct metadata."""
        exec_docs = [
            {
                "execution_id": f"exec_{i}",
                "workflow_id": FAKE_WORKFLOW_ID,
                "user_id": FAKE_USER_ID,
                "status": "success",
                "started_at": datetime(2026, 1, 1, 12, i, 0, tzinfo=timezone.utc),
                "trigger_type": "manual",
            }
            for i in range(3)
        ]

        mock_cursor = AsyncMock()
        mock_cursor.__aiter__ = lambda self: aiter_docs(exec_docs)
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=5)
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection",
            mock_collection,
        ):
            response = await get_workflow_executions(
                workflow_id=FAKE_WORKFLOW_ID,
                user_id=FAKE_USER_ID,
                limit=3,
                offset=0,
            )

        assert response.total == 5
        assert len(response.executions) == 3
        assert response.has_more is True
        assert all(e.workflow_id == FAKE_WORKFLOW_ID for e in response.executions)


async def aiter_docs(docs):
    """Async iterator helper for mock cursors."""
    for doc in docs:
        yield doc


# ---------------------------------------------------------------------------
# TEST 4: Trigger Registration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTriggerRegistration:
    """Register a trigger -> verify stored -> handle failures."""

    async def test_register_integration_triggers_calls_trigger_service(self):
        """_register_integration_triggers delegates to TriggerService for integration type."""
        trigger_config = _make_trigger_config(
            trigger_type="integration",
            trigger_name="calendar_event_created",
        )

        with patch(
            "app.services.workflow.service.TriggerService.register_triggers",
            new_callable=AsyncMock,
            return_value=["trigger_id_1", "trigger_id_2"],
        ) as mock_register:
            result = await WorkflowService._register_integration_triggers(
                workflow_id=FAKE_WORKFLOW_ID,
                user_id=FAKE_USER_ID,
                trigger_config=trigger_config,
            )

        assert result == ["trigger_id_1", "trigger_id_2"]
        mock_register.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            workflow_id=FAKE_WORKFLOW_ID,
            trigger_name="calendar_event_created",
            trigger_config=trigger_config,
            raise_on_failure=True,
        )

    async def test_register_skips_non_integration_triggers(self):
        """_register_integration_triggers returns empty list for manual triggers."""
        trigger_config = _make_trigger_config(trigger_type="manual")

        result = await WorkflowService._register_integration_triggers(
            workflow_id=FAKE_WORKFLOW_ID,
            user_id=FAKE_USER_ID,
            trigger_config=trigger_config,
        )

        assert result == []

    async def test_register_raises_when_trigger_name_missing(self):
        """_register_integration_triggers raises when integration trigger has no name."""

        trigger_config = _make_trigger_config(
            trigger_type="integration",
            trigger_name=None,
        )

        with pytest.raises(TriggerRegistrationError, match="trigger_name"):
            await WorkflowService._register_integration_triggers(
                workflow_id=FAKE_WORKFLOW_ID,
                user_id=FAKE_USER_ID,
                trigger_config=trigger_config,
            )

    async def test_create_workflow_rolls_back_on_trigger_failure(self):
        """If trigger registration fails, the pending workflow is deleted."""

        request = _make_create_request(
            trigger_type="integration",
            trigger_name="calendar_event_created",
        )
        mock_collection = AsyncMock()
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = "wf_rollback"
        mock_collection.insert_one = AsyncMock(return_value=mock_insert_result)
        mock_collection.delete_one = AsyncMock()

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.ChromaClient") as mock_chroma_cls,
            patch(
                "app.services.workflow.service.TriggerService.register_triggers",
                new_callable=AsyncMock,
                side_effect=TriggerRegistrationError(
                    "Registration failed", "calendar_event_created"
                ),
            ),
        ):
            mock_chroma_cls.get_langchain_client = AsyncMock(return_value=MagicMock())
            with pytest.raises(TriggerRegistrationError):
                await WorkflowService.create_workflow(request, FAKE_USER_ID)

        # Verify rollback: workflow was deleted
        mock_collection.delete_one.assert_awaited_once()


# ---------------------------------------------------------------------------
# TEST 5: Multi-step Workflow Execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMultiStepWorkflowExecution:
    """Create workflow with ordered steps -> execute -> verify ordering."""

    async def test_execute_workflow_queues_job_for_activated_workflow(self):
        """execute_workflow queues the job when workflow is valid and activated."""
        workflow = _make_workflow(
            activated=True,
            steps=_make_workflow_steps(3),
        )
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=_workflow_as_doc(workflow))
        mock_collection.find_one_and_update = AsyncMock(
            return_value=_workflow_as_doc(workflow)
        )

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch(
                "app.services.workflow.service.WorkflowQueueService.queue_workflow_execution",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_queue,
        ):
            response = await WorkflowService.execute_workflow(
                FAKE_WORKFLOW_ID,
                WorkflowExecutionRequest(),
                FAKE_USER_ID,
            )

        assert response.execution_id.startswith("exec_")
        assert response.message == "Workflow execution started"
        mock_queue.assert_awaited_once()

    async def test_execute_workflow_rejects_deactivated(self):
        """execute_workflow raises ValueError for deactivated workflows."""
        workflow = _make_workflow(activated=False)
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=_workflow_as_doc(workflow))

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            with pytest.raises(ValueError, match="deactivated"):
                await WorkflowService.execute_workflow(
                    FAKE_WORKFLOW_ID,
                    WorkflowExecutionRequest(),
                    FAKE_USER_ID,
                )

    async def test_execute_workflow_raises_for_missing_workflow(self):
        """execute_workflow raises ValueError when workflow not found."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            with pytest.raises(ValueError, match="not found"):
                await WorkflowService.execute_workflow(
                    "wf_ghost",
                    WorkflowExecutionRequest(),
                    FAKE_USER_ID,
                )

    def test_enrich_steps_preserves_order_and_assigns_ids(self):
        """enrich_steps assigns sequential IDs and preserves step order."""

        generated = [
            GeneratedStep(
                title="Fetch data", category="api", description="Get the data"
            ),
            GeneratedStep(
                title="Process data",
                category="gaia",
                description="Transform the data",
            ),
            GeneratedStep(
                title="Send report",
                category="gmail",
                description="Email the results",
            ),
        ]

        enriched = enrich_steps(generated)

        assert len(enriched) == 3
        assert enriched[0]["id"] == "step_0"
        assert enriched[1]["id"] == "step_1"
        assert enriched[2]["id"] == "step_2"
        assert enriched[0]["title"] == "Fetch data"
        assert enriched[1]["title"] == "Process data"
        assert enriched[2]["title"] == "Send report"
        assert enriched[2]["category"] == "gmail"


# ---------------------------------------------------------------------------
# TEST 6: Execution Failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutionFailure:
    """Simulate failure mid-execution -> verify partial state is recorded."""

    async def test_execution_failure_records_error_state(self):
        """A failed execution stores error_message and status='failed'."""
        started_at = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        stored_doc = {
            "execution_id": "exec_mid_fail",
            "workflow_id": FAKE_WORKFLOW_ID,
            "started_at": started_at,
            "status": "running",
        }

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=stored_doc)
        mock_collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        with patch(
            "app.services.workflow.execution_service.workflow_executions_collection",
            mock_collection,
        ):
            result = await complete_execution(
                execution_id="exec_mid_fail",
                status="failed",
                error_message="LLM API rate limit exceeded at step 3",
            )

        assert result is True
        update_set = mock_collection.update_one.call_args[0][1]["$set"]
        assert update_set["status"] == "failed"
        assert "rate limit" in update_set["error_message"]
        assert update_set["completed_at"] is not None
        assert update_set["duration_seconds"] is not None

    async def test_execution_count_incremented_on_failure(self):
        """increment_execution_count increments total but not successful on failure."""
        mock_collection = AsyncMock()
        mock_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            result = await WorkflowService.increment_execution_count(
                FAKE_WORKFLOW_ID, FAKE_USER_ID, is_successful=False
            )

        assert result is True
        update_call = mock_collection.update_one.call_args
        inc_data = update_call[0][1]["$inc"]
        assert inc_data["total_executions"] == 1
        assert "successful_executions" not in inc_data

    async def test_execution_count_incremented_on_success(self):
        """increment_execution_count increments both total and successful on success."""
        mock_collection = AsyncMock()
        mock_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            result = await WorkflowService.increment_execution_count(
                FAKE_WORKFLOW_ID, FAKE_USER_ID, is_successful=True
            )

        assert result is True
        inc_data = mock_collection.update_one.call_args[0][1]["$inc"]
        assert inc_data["total_executions"] == 1
        assert inc_data["successful_executions"] == 1


# ---------------------------------------------------------------------------
# TEST 7: Slug Generation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSlugGeneration:
    """Create workflows with similar names -> verify unique slugs."""

    async def test_generate_unique_slug_returns_base_when_available(self):
        """First slug for a title is just the slugified base."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            slug = await generate_unique_workflow_slug("My Awesome Workflow")

        assert slug == "myawesomeworkflow"

    async def test_generate_unique_slug_appends_suffix_on_collision(self):
        """When the base slug is taken, a numeric suffix is appended."""
        call_count = 0

        async def find_one_side_effect(query):
            nonlocal call_count
            call_count += 1
            # First two calls: slug exists. Third: slug is free.
            if call_count <= 2:
                return {"_id": "existing", "slug": query["slug"]}
            return None

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(side_effect=find_one_side_effect)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            slug = await generate_unique_workflow_slug("Daily Report")

        assert slug == "dailyreport-2"

    async def test_generate_unique_slug_handles_empty_title(self):
        """An empty/invalid title falls back to 'workflow' base."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            slug = await generate_unique_workflow_slug("")

        assert slug == "workflow"

    async def test_generate_unique_slug_excludes_own_id(self):
        """When exclude_id is provided, the query excludes that workflow."""
        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.service.workflows_collection",
            mock_collection,
        ):
            await generate_unique_workflow_slug("Test Workflow", exclude_id="wf_self")

        query_arg = mock_collection.find_one.call_args[0][0]
        assert query_arg["_id"] == {"$ne": "wf_self"}


# ---------------------------------------------------------------------------
# TEST 8: Queue Service
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestQueueService:
    """Enqueue workflow -> verify it appears in queue with correct params."""

    async def test_queue_workflow_generation(self):
        """queue_workflow_generation enqueues with correct function name and args."""
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_gen_123"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await WorkflowQueueService.queue_workflow_generation(
                FAKE_WORKFLOW_ID, FAKE_USER_ID
            )

        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "generate_workflow_steps", FAKE_WORKFLOW_ID, FAKE_USER_ID
        )

    async def test_queue_workflow_execution(self):
        """queue_workflow_execution enqueues with context."""
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_exec_456"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        context = {"source": "api"}

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await WorkflowQueueService.queue_workflow_execution(
                FAKE_WORKFLOW_ID, FAKE_USER_ID, context=context
            )

        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", FAKE_WORKFLOW_ID, {"source": "api"}
        )

    async def test_queue_workflow_execution_returns_false_on_failure(self):
        """queue_workflow_execution returns False when enqueue returns None."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await WorkflowQueueService.queue_workflow_execution(
                FAKE_WORKFLOW_ID, FAKE_USER_ID
            )

        assert result is False

    async def test_queue_workflow_execution_returns_false_on_redis_error(self):
        """queue_workflow_execution returns False when Redis throws."""
        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Redis unreachable"),
        ):
            result = await WorkflowQueueService.queue_workflow_execution(
                FAKE_WORKFLOW_ID, FAKE_USER_ID
            )

        assert result is False

    async def test_queue_scheduled_workflow_execution(self):
        """queue_scheduled_workflow_execution passes defer_until."""
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_sched_789"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        scheduled_at = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await WorkflowQueueService.queue_scheduled_workflow_execution(
                FAKE_WORKFLOW_ID, scheduled_at
            )

        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id",
            FAKE_WORKFLOW_ID,
            {},
            _defer_until=scheduled_at,
        )

    async def test_queue_regeneration(self):
        """queue_workflow_regeneration enqueues with reason and force flag."""
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_regen_101"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await WorkflowQueueService.queue_workflow_regeneration(
                FAKE_WORKFLOW_ID,
                FAKE_USER_ID,
                regeneration_reason="User requested different approach",
                force_different_tools=True,
            )

        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "regenerate_workflow_steps",
            FAKE_WORKFLOW_ID,
            FAKE_USER_ID,
            "User requested different approach",
            True,
        )


# ---------------------------------------------------------------------------
# TEST 9: Generation Service (parse and enrich)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGenerationServiceParsing:
    """Test the generation service parsing and enrichment logic."""

    def test_parse_workflow_response_strips_markdown_fences(self):
        """_parse_workflow_response handles ```json ... ``` wrapping."""
        raw = '```json\n{"steps": [{"title": "Step 1", "category": "gaia", "description": "Do thing"}]}\n```'
        result = _parse_workflow_response(raw)
        assert len(result.steps) == 1
        assert result.steps[0].title == "Step 1"

    def test_parse_workflow_response_handles_plain_json(self):
        """_parse_workflow_response handles plain JSON without fences."""
        raw = '{"steps": [{"title": "A", "category": "b", "description": "c"}]}'
        result = _parse_workflow_response(raw)
        assert len(result.steps) == 1

    def test_parse_workflow_response_raises_on_invalid_json(self):
        """_parse_workflow_response raises on malformed JSON."""
        with pytest.raises(Exception):
            _parse_workflow_response("not json at all")

    async def test_generate_steps_raises_after_retries(self):
        """generate_steps_with_llm raises RuntimeError after max retries."""
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(side_effect=NotImplementedError)
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="bad json"))

        mock_registry = MagicMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})
        mock_registry.get_core_tools = MagicMock(return_value=[])

        with (
            patch(
                "app.services.workflow.generation_service.init_llm",
                return_value=mock_llm,
            ),
            patch(
                "app.agents.tools.core.registry.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.workflow.generation_service.generate_trigger_context",
                return_value="manual trigger",
            ),
            patch(
                "app.services.workflow.generation_service.OAUTH_INTEGRATIONS",
                [],
            ),
        ):
            with pytest.raises(RuntimeError, match="failed"):
                await WorkflowGenerationService.generate_steps_with_llm(
                    prompt="Test prompt",
                    title="Test Workflow",
                )


# ---------------------------------------------------------------------------
# TEST 10: Activate / Deactivate Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestActivateDeactivateLifecycle:
    """Test workflow activation and deactivation flows."""

    async def test_activate_workflow_enables_and_registers_triggers(self):
        """activate_workflow sets activated=True and registers integration triggers."""
        workflow = _make_workflow(activated=False, trigger_type="manual")
        doc = _workflow_as_doc(workflow)
        activated_doc = {**doc, "activated": True}

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(side_effect=[doc, activated_doc])
        mock_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.workflow_scheduler"),
        ):
            result = await WorkflowService.activate_workflow(
                FAKE_WORKFLOW_ID, FAKE_USER_ID
            )

        assert result is not None
        assert result.activated is True

    async def test_deactivate_workflow_disables_and_cancels(self):
        """deactivate_workflow sets activated=False and cancels scheduling."""
        workflow = _make_workflow(activated=True)
        doc = _workflow_as_doc(workflow)
        deactivated_doc = {**doc, "activated": False}

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(side_effect=[doc, deactivated_doc])
        mock_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        with (
            patch(
                "app.services.workflow.service.workflows_collection",
                mock_collection,
            ),
            patch("app.services.workflow.service.workflow_scheduler") as mock_scheduler,
        ):
            mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock()
            result = await WorkflowService.deactivate_workflow(
                FAKE_WORKFLOW_ID, FAKE_USER_ID
            )

        assert result is not None
        assert result.activated is False
        mock_scheduler.cancel_scheduled_workflow_execution.assert_awaited_once_with(
            FAKE_WORKFLOW_ID
        )
