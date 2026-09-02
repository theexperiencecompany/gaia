"""
Integration tests for Workflow Execution End-to-End.

Sibling: ``tests/e2e/test_workflow_execution.py`` drives the real compiled
agent graphs end to end; this file pins the workflow service layer itself
(mocked I/O boundaries only).

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

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.exceptions import OutputParserException
import pytest

from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.models.workflow_models import (
    CreateWorkflowRequest,
    GeneratedStep,
    TriggerConfig,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowDocument,
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
)
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.workflow.service import (
    WorkflowService,
    generate_unique_workflow_slug,
)
from app.services.workflow.validators import WorkflowValidator
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import get_trace_id, wide_task

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_WORKFLOW_ID = "wf_abc123def456"

# The workflow service routes every DB op through this module-level repository
# singleton; tests patch its async methods rather than a raw Mongo collection.
_REPO = "app.services.workflow.service.workflow_repository"
_GET_WORKFLOW = "app.services.workflow.service.WorkflowService.get_workflow"
# Execution tracking routes through its own repository singleton.
_EXEC_REPO = "app.services.workflow.execution_service.workflow_executions_repository"

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


def _make_workflow_doc(**overrides) -> WorkflowDocument:
    """Build a WorkflowDocument (the repository's return type) from the Workflow
    factory — repository methods return typed models, not raw dicts."""
    return WorkflowDocument(**_make_workflow(**overrides).model_dump())


# ---------------------------------------------------------------------------
# TEST 1: Workflow CRUD Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowCRUDLifecycle:
    """Create workflow -> read -> update -> verify state at each step."""

    async def test_create_workflow_inserts_and_activates(self):
        """create_workflow persists via the repository and activates it."""
        request = _make_create_request(title="My New Workflow")

        with (
            patch(f"{_REPO}.create", new_callable=AsyncMock) as mock_create,
            patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock) as mock_activate,
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
        mock_create.assert_awaited_once()
        # Activation flips the pending workflow live via the repository.
        mock_activate.assert_awaited_once()

    async def test_get_workflow_returns_none_when_missing(self):
        """get_workflow returns None for a non-existent workflow."""
        with patch(f"{_REPO}.get_for_user", new_callable=AsyncMock, return_value=None):
            result = await WorkflowService.get_workflow("wf_missing", FAKE_USER_ID)

        assert result is None

    async def test_get_workflow_returns_transformed_document(self):
        """get_workflow returns a Workflow model from a stored document."""
        doc = _make_workflow_doc()

        with patch(f"{_REPO}.get_for_user", new_callable=AsyncMock, return_value=doc):
            result = await WorkflowService.get_workflow(FAKE_WORKFLOW_ID, FAKE_USER_ID)

        assert result is not None
        assert result.title == "Test Workflow"
        assert result.id == FAKE_WORKFLOW_ID

    async def test_update_workflow_applies_changes(self):
        """update_workflow persists field changes and returns updated workflow."""
        current = _make_workflow()
        updated = _make_workflow(title="Updated Title")

        update_request = UpdateWorkflowRequest(title="Updated Title")

        with (
            # get_workflow is called twice: once for current state, once to
            # return the re-read after the persisted update.
            patch(
                _GET_WORKFLOW,
                new_callable=AsyncMock,
                side_effect=[current, updated],
            ),
            patch(
                f"{_REPO}.update_for_user",
                new_callable=AsyncMock,
                return_value=_make_workflow_doc(title="Updated Title"),
            ) as mock_update,
            patch("app.services.workflow.service.workflow_scheduler"),
        ):
            result = await WorkflowService.update_workflow(
                FAKE_WORKFLOW_ID, update_request, FAKE_USER_ID
            )

        assert result is not None
        assert result.title == "Updated Title"
        mock_update.assert_awaited_once()

    async def test_delete_workflow_removes_document(self):
        """delete_workflow removes the document and returns True."""
        with (
            patch(
                _GET_WORKFLOW,
                new_callable=AsyncMock,
                return_value=_make_workflow(),
            ),
            patch(
                f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=True
            ) as mock_delete,
            patch("app.services.workflow.service.workflow_scheduler") as mock_scheduler,
        ):
            mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock()
            mock_scheduler.cancel_task = AsyncMock()
            result = await WorkflowService.delete_workflow(FAKE_WORKFLOW_ID, FAKE_USER_ID)

        assert result is True
        mock_delete.assert_awaited_once()

    async def test_delete_workflow_returns_false_when_not_found(self):
        """delete_workflow returns False when the document does not exist."""
        with (
            patch(_GET_WORKFLOW, new_callable=AsyncMock, return_value=None),
            patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=False),
            patch("app.services.workflow.service.workflow_scheduler") as mock_scheduler,
        ):
            mock_scheduler.cancel_scheduled_workflow_execution = AsyncMock()
            mock_scheduler.cancel_task = AsyncMock()
            result = await WorkflowService.delete_workflow("wf_nonexistent", FAKE_USER_ID)

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
        """create_execution persists a record with status 'running'."""
        # The repository echoes back the document it was handed, so the
        # service-built execution_id/started_at/status flow through unchanged.
        with patch(
            f"{_EXEC_REPO}.create",
            new_callable=AsyncMock,
            side_effect=lambda doc: doc,
        ) as mock_create:
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
        mock_create.assert_awaited_once()

    async def test_complete_execution_success(self):
        """complete_execution marks the record 'success' and returns True."""
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        completed = WorkflowExecutionDocument(
            execution_id="exec_abc123",
            workflow_id=FAKE_WORKFLOW_ID,
            user_id=FAKE_USER_ID,
            status="success",
            started_at=started_at,
            summary="Completed all steps",
            duration_seconds=1.5,
        )

        with patch(
            f"{_EXEC_REPO}.complete",
            new_callable=AsyncMock,
            return_value=completed,
        ) as mock_complete:
            result = await complete_execution(
                execution_id="exec_abc123",
                status="success",
                summary="Completed all steps",
            )

        assert result is True
        # Duration is computed inside the repository; the service just forwards
        # the completion fields.
        mock_complete.assert_awaited_once_with(
            "exec_abc123",
            status="success",
            summary="Completed all steps",
            error_message=None,
            conversation_id=None,
            trace=None,
        )

    async def test_complete_execution_failure_with_error_message(self):
        """complete_execution records 'failed' status with error message."""
        completed = WorkflowExecutionDocument(
            execution_id="exec_fail",
            workflow_id=FAKE_WORKFLOW_ID,
            user_id=FAKE_USER_ID,
            status="failed",
            started_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            error_message="Step 2 timed out",
            duration_seconds=2.0,
        )

        with patch(
            f"{_EXEC_REPO}.complete",
            new_callable=AsyncMock,
            return_value=completed,
        ) as mock_complete:
            result = await complete_execution(
                execution_id="exec_fail",
                status="failed",
                error_message="Step 2 timed out",
            )

        assert result is True
        mock_complete.assert_awaited_once_with(
            "exec_fail",
            status="failed",
            summary=None,
            error_message="Step 2 timed out",
            conversation_id=None,
            trace=None,
        )

    async def test_complete_execution_returns_false_for_missing(self):
        """complete_execution returns False when execution_id is not found."""
        with patch(f"{_EXEC_REPO}.complete", new_callable=AsyncMock, return_value=None):
            result = await complete_execution(
                execution_id="exec_nonexistent",
                status="success",
            )

        assert result is False

    async def test_get_workflow_executions_paginates(self):
        """get_workflow_executions returns paginated results with correct metadata."""
        exec_docs = [
            WorkflowExecutionDocument(
                execution_id=f"exec_{i}",
                workflow_id=FAKE_WORKFLOW_ID,
                user_id=FAKE_USER_ID,
                status="success",
                started_at=datetime(2026, 1, 1, 12, i, 0, tzinfo=UTC),
                trigger_type="manual",
            )
            for i in range(3)
        ]

        with patch(
            f"{_EXEC_REPO}.list_for_workflow",
            new_callable=AsyncMock,
            return_value=(exec_docs, 5),
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

        with (
            patch(
                "app.services.oauth.oauth_service.check_integration_status",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.services.workflow.service.TriggerService.register_triggers",
                new_callable=AsyncMock,
                return_value=["trigger_id_1", "trigger_id_2"],
            ) as mock_register,
        ):
            result = await WorkflowService._register_integration_triggers(
                workflow_id=FAKE_WORKFLOW_ID,
                user_id=FAKE_USER_ID,
                trigger_config=trigger_config,
            )

        # _register_integration_triggers now returns (trigger_ids, integration_connected)
        trigger_ids, connected = result
        assert trigger_ids == ["trigger_id_1", "trigger_id_2"]
        assert connected is True
        mock_register.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            # The parameter is `owner_id` now: registration serves tracked todos
            # as well as workflows, and naming it workflow_id made every handler's
            # logging and error text lie for half its callers.
            owner_id=FAKE_WORKFLOW_ID,
            trigger_name="calendar_event_created",
            trigger_config=trigger_config,
            raise_on_failure=True,
        )

    async def test_register_skips_non_integration_triggers(self):
        """_register_integration_triggers returns ([], True) for manual triggers."""
        trigger_config = _make_trigger_config(trigger_type="manual")

        result = await WorkflowService._register_integration_triggers(
            workflow_id=FAKE_WORKFLOW_ID,
            user_id=FAKE_USER_ID,
            trigger_config=trigger_config,
        )

        # Non-integration triggers return ([], True) — trigger_ids empty, integration_connected True
        assert result == ([], True)

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

        with (
            patch(f"{_REPO}.create", new_callable=AsyncMock),
            patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock) as mock_delete,
            patch("app.services.workflow.service.ChromaClient") as mock_chroma_cls,
            # check_integration_status is imported lazily inside the function;
            # patch it True so the code proceeds past the connectivity gate to
            # call register_triggers (which then raises TriggerRegistrationError).
            patch(
                "app.services.oauth.oauth_service.check_integration_status",
                new_callable=AsyncMock,
                return_value=True,
            ),
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

        # Verify rollback: the pending workflow was deleted via the repository.
        mock_delete.assert_awaited_once()


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

        with (
            patch(_GET_WORKFLOW, new_callable=AsyncMock, return_value=workflow),
            # touch() heartbeats last-execution; a non-None return means it matched.
            patch(
                f"{_REPO}.touch",
                new_callable=AsyncMock,
                return_value=_make_workflow_doc(),
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

        with patch(_GET_WORKFLOW, new_callable=AsyncMock, return_value=workflow):
            with pytest.raises(ValueError, match="deactivated"):
                await WorkflowService.execute_workflow(
                    FAKE_WORKFLOW_ID,
                    WorkflowExecutionRequest(),
                    FAKE_USER_ID,
                )

    async def test_execute_workflow_raises_for_missing_workflow(self):
        """execute_workflow raises ValueError when workflow not found."""
        with patch(_GET_WORKFLOW, new_callable=AsyncMock, return_value=None):
            with pytest.raises(ValueError, match="not found"):
                await WorkflowService.execute_workflow(
                    "wf_ghost",
                    WorkflowExecutionRequest(),
                    FAKE_USER_ID,
                )

    def test_enrich_steps_preserves_order_and_assigns_ids(self):
        """enrich_steps assigns sequential IDs and preserves step order."""

        generated = [
            GeneratedStep(title="Fetch data", category="api", description="Get the data"),
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
        assert enriched[0].id == "step_0"
        assert enriched[1].id == "step_1"
        assert enriched[2].id == "step_2"
        assert enriched[0].title == "Fetch data"
        assert enriched[1].title == "Process data"
        assert enriched[2].title == "Send report"
        assert enriched[2].category == "gmail"


# ---------------------------------------------------------------------------
# TEST 6: Execution Failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutionFailure:
    """Simulate failure mid-execution -> verify partial state is recorded."""

    async def test_execution_failure_records_error_state(self):
        """A failed execution stores error_message and status='failed'."""
        started_at = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        completed = WorkflowExecutionDocument(
            execution_id="exec_mid_fail",
            workflow_id=FAKE_WORKFLOW_ID,
            user_id=FAKE_USER_ID,
            status="failed",
            started_at=started_at,
            completed_at=datetime(2026, 3, 15, 10, 5, 0, tzinfo=UTC),
            duration_seconds=300.0,
            error_message="LLM API rate limit exceeded at step 3",
        )

        with patch(
            f"{_EXEC_REPO}.complete",
            new_callable=AsyncMock,
            return_value=completed,
        ) as mock_complete:
            result = await complete_execution(
                execution_id="exec_mid_fail",
                status="failed",
                error_message="LLM API rate limit exceeded at step 3",
            )

        assert result is True
        # completed_at/duration_seconds are computed by the repository; the service
        # forwards the failed status and error message.
        mock_complete.assert_awaited_once_with(
            "exec_mid_fail",
            status="failed",
            summary=None,
            error_message="LLM API rate limit exceeded at step 3",
            conversation_id=None,
            trace=None,
        )

    async def test_execution_count_incremented_on_failure(self):
        """increment_execution_count records a non-successful execution."""
        with patch(
            f"{_REPO}.record_execution", new_callable=AsyncMock, return_value=True
        ) as mock_record:
            result = await WorkflowService.increment_execution_count(
                FAKE_WORKFLOW_ID, FAKE_USER_ID, is_successful=False
            )

        assert result is True
        # The $inc counter split now lives in the repository; the service just
        # forwards the success flag.
        mock_record.assert_awaited_once_with(FAKE_WORKFLOW_ID, FAKE_USER_ID, successful=False)

    async def test_execution_count_incremented_on_success(self):
        """increment_execution_count records a successful execution."""
        with patch(
            f"{_REPO}.record_execution", new_callable=AsyncMock, return_value=True
        ) as mock_record:
            result = await WorkflowService.increment_execution_count(
                FAKE_WORKFLOW_ID, FAKE_USER_ID, is_successful=True
            )

        assert result is True
        mock_record.assert_awaited_once_with(FAKE_WORKFLOW_ID, FAKE_USER_ID, successful=True)


# ---------------------------------------------------------------------------
# TEST 7: Slug Generation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSlugGeneration:
    """Create workflows with similar names -> verify unique slugs."""

    async def test_generate_unique_slug_returns_base_when_available(self):
        """Slug for a title is '{base}-{6hex}' — always includes a random suffix."""
        with patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock, return_value=None):
            slug = await generate_unique_workflow_slug("My Awesome Workflow")

        # Format is always "{base}-{6_hex_chars}"
        assert slug.startswith("my-awesome-workflow-")
        suffix = slug.rsplit("-", 1)[1]
        assert len(suffix) == 6
        assert all(c in "0123456789abcdef" for c in suffix)

    async def test_generate_unique_slug_appends_suffix_on_collision(self):
        """When candidate slugs are taken, the function keeps retrying with fresh hex suffixes."""
        # First two probes hit an existing public workflow; the third is free.
        with patch(
            f"{_REPO}.find_public_slug_conflict",
            new_callable=AsyncMock,
            side_effect=[_make_workflow_doc(), _make_workflow_doc(), None],
        ) as mock_conflict:
            slug = await generate_unique_workflow_slug("Daily Report")

        # The function retried and returned a free candidate
        assert slug.startswith("daily-report-")
        suffix = slug.rsplit("-", 1)[1]
        assert len(suffix) == 6
        assert all(c in "0123456789abcdef" for c in suffix)
        # The conflict probe ran exactly 3 times (2 collisions + 1 free)
        assert mock_conflict.await_count == 3

    async def test_generate_unique_slug_handles_empty_title(self):
        """An empty/invalid title falls back to 'workflow-{hex}' base."""
        with patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock, return_value=None):
            slug = await generate_unique_workflow_slug("")

        assert slug.startswith("workflow-")
        suffix = slug.rsplit("-", 1)[1]
        assert len(suffix) == 6
        assert all(c in "0123456789abcdef" for c in suffix)

    async def test_generate_unique_slug_excludes_own_id(self):
        """When exclude_id is provided, the probe forwards it to exclude that workflow."""
        with patch(
            f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock, return_value=None
        ) as mock_conflict:
            await generate_unique_workflow_slug("Test Workflow", exclude_id="wf_self")

        assert mock_conflict.await_args.kwargs["exclude_id"] == "wf_self"


# ---------------------------------------------------------------------------
# TEST 8: Queue Service
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestQueueService:
    """Enqueue workflow -> verify it appears in queue with correct params."""

    async def test_queue_workflow_generation(self):
        """queue_workflow_generation enqueues with correct function name and args.

        Production always enqueues from inside a wide-event boundary, so the run
        happens in one here: enqueue_worker_job stamps the caller's trace id onto
        the payload only when a trace is in scope. Asserting the exact call
        outside a boundary would silently depend on whatever ran before it.
        """
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_gen_123"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.workflow.queue_service.RedisPoolManager.get_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            async with wide_task("test_queue_workflow_generation"):
                trace_id = get_trace_id()
                result = await WorkflowQueueService.queue_workflow_generation(
                    FAKE_WORKFLOW_ID, FAKE_USER_ID
                )

        assert result is True
        assert trace_id
        mock_pool.enqueue_job.assert_awaited_once_with(
            "generate_workflow_steps",
            FAKE_WORKFLOW_ID,
            FAKE_USER_ID,
            _gaia_trace_id=trace_id,
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
        args, kwargs = mock_pool.enqueue_job.call_args
        assert args == ("execute_workflow_by_id", FAKE_WORKFLOW_ID, {"source": "api"})
        # A deterministic _job_id dedupes accidental duplicate enqueues.
        assert kwargs["_job_id"].startswith("execute_workflow_by_id:")

    async def test_queue_workflow_execution_deduped_enqueue_returns_true(self):
        """A None from enqueue_job means the same _job_id is already queued — the
        duplicate was deduped, which is success, not failure."""
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

        assert result is True

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


# ---------------------------------------------------------------------------
# TEST 9: Generation Service (retries)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGenerationServiceRetries:
    """Test the generation service regeneration logic."""

    async def test_generate_steps_raises_after_retries(self):
        """generate_steps_with_llm raises RuntimeError after max retries."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})
        mock_registry.get_core_tools = MagicMock(return_value=[])

        with (
            # Schema-invalid output on every attempt exhausts the regeneration loop.
            patch(
                "app.services.workflow.generation_service.ainvoke_structured",
                new_callable=AsyncMock,
                side_effect=OutputParserException("bad json"),
            ),
            # Patch the local binding in generation_service (where it is imported),
            # not the source registry module. The `from ... import get_tool_registry`
            # at the top of generation_service.py creates an independent local name.
            patch(
                "app.services.workflow.generation_service.get_tool_registry",
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
                    user_id="test-user",
                )


# ---------------------------------------------------------------------------
# TEST 10: Activate / Deactivate Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestActivateDeactivateLifecycle:
    """Test workflow activation and deactivation flows."""

    async def test_activate_workflow_enables_and_registers_triggers(self):
        """activate_workflow sets activated=True and registers integration triggers."""
        pending = _make_workflow(activated=False, trigger_type="manual")
        activated = _make_workflow(activated=True, trigger_type="manual")

        with (
            # get_workflow: first the pending workflow, then the re-read after activation.
            patch(
                _GET_WORKFLOW,
                new_callable=AsyncMock,
                side_effect=[pending, activated],
            ),
            patch(
                f"{_REPO}.activate",
                new_callable=AsyncMock,
                return_value=_make_workflow_doc(activated=True),
            ) as mock_activate,
            patch("app.services.workflow.service.workflow_scheduler"),
        ):
            result = await WorkflowService.activate_workflow(FAKE_WORKFLOW_ID, FAKE_USER_ID)

        assert result is not None
        assert result.activated is True
        mock_activate.assert_awaited_once()

    async def test_deactivate_workflow_disables_and_cancels(self):
        """deactivate_workflow sets activated=False."""
        active = _make_workflow(activated=True)
        deactivated = _make_workflow(activated=False)

        with (
            patch(
                _GET_WORKFLOW,
                new_callable=AsyncMock,
                side_effect=[active, deactivated],
            ),
            patch(
                f"{_REPO}.deactivate",
                new_callable=AsyncMock,
                return_value=_make_workflow_doc(activated=False),
            ) as mock_deactivate,
            patch("app.services.workflow.service.workflow_scheduler"),
        ):
            result = await WorkflowService.deactivate_workflow(FAKE_WORKFLOW_ID, FAKE_USER_ID)

        assert result is not None
        assert result.activated is False
        # The repository deactivate() call persists activated=False.
        mock_deactivate.assert_awaited_once()
