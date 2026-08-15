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
  - WorkflowGenerationService.generate_steps_with_llm (structured output,
    regeneration, empty steps, max attempts, provider error propagation)
  - WorkflowGenerationService.generate_workflow_prompt (success, parse failure)
  - WorkflowScheduler (schedule, cancel, reschedule, get_task, get_pending_task,
    update_task_status, get_workflow_status)
  - WorkflowQueueService (queue_workflow_generation, queue_workflow_execution,
    queue_todo_workflow_generation,
    is_workflow_generating, clear_workflow_generating_flag)
  - TriggerService (get_all_workflow_triggers,
    register_triggers, unregister_triggers)
  - WorkflowValidator (validate_for_execution: pass, deactivated, no steps,
    no trigger config, multiple errors)
  - generation_service helpers (enrich_steps, _build_trigger_hint,
    _build_available_triggers)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.exceptions import OutputParserException
import pytest

from app.models.workflow_models import (
    CreateWorkflowRequest,
    GeneratedPromptOutput,
    GeneratedStep,
    GeneratedWorkflow,
    IntegrationRef,
    PromptTriggerHint,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowDocument,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
    WorkflowStep,
)
from app.services.workflow.generation_service import (
    WorkflowGenerationService,
    _build_available_triggers,
    _build_trigger_hint,
    enrich_steps,
)
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.service import (
    WorkflowService,
    generate_unique_workflow_slug,
)
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
    cron_expression: str | None = None,
    trigger_name: str | None = None,
    composio_trigger_ids: list[str] | None = None,
    next_run: datetime | None = None,
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
    workflow_id: str | None = WORKFLOW_ID,
    activated: bool = True,
    steps: list | None = None,
    trigger_config: TriggerConfig | None = None,
    description: str = "Test description",
    prompt: str = "Execute test workflow",
    user_id: str = USER_ID,
    is_todo_workflow: bool = False,
    error_message: str | None = None,
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
    description: str | None = "A test workflow",
    trigger_config: TriggerConfig | None = None,
    steps: list[WorkflowStep] | None = None,
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


def _make_workflow_doc(workflow: Workflow | None = None, **overrides) -> WorkflowDocument:
    """Build a typed WorkflowDocument (the repository's return shape) from a Workflow."""
    wf = workflow or _make_workflow()
    data = wf.model_dump()
    data.update(overrides)
    return WorkflowDocument(**data)


# ---------------------------------------------------------------------------
# Patch-target constants
# ---------------------------------------------------------------------------

# The service now performs every DB operation through this module-level repository
# singleton; tests patch its methods instead of a raw collection handle.
_REPO = "app.services.workflow.service.workflow_repository"


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

    @patch("app.services.workflow.service._slug_suffix", return_value="aabbcc")
    @patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock, return_value=None)
    async def test_unique_slug_first_try(self, _mock_conflict, _mock_suffix):
        # No conflicting public workflow → the first candidate is free.
        slug = await generate_unique_workflow_slug("My Test Workflow")
        assert slug == "my-test-workflow-aabbcc"

    @patch("app.services.workflow.service._slug_suffix", side_effect=["hex001", "hex002"])
    @patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock)
    async def test_slug_collision_appends_suffix(self, mock_conflict, _mock_suffix):
        # First candidate collides (a conflict doc), second is free (None).
        mock_conflict.side_effect = [_make_workflow_doc(), None]
        slug = await generate_unique_workflow_slug("My Workflow")
        assert slug == "my-workflow-hex002"

    @patch(
        "app.services.workflow.service._slug_suffix",
        side_effect=["hex001", "hex002", "hex003"],
    )
    @patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock)
    async def test_slug_multiple_collisions(self, mock_conflict, _mock_suffix):
        mock_conflict.side_effect = [_make_workflow_doc(), _make_workflow_doc(), None]
        slug = await generate_unique_workflow_slug("My Workflow")
        assert slug == "my-workflow-hex003"

    @patch("app.services.workflow.service._slug_suffix", return_value="aabbcc")
    @patch("app.services.workflow.service.slugify", return_value="")
    @patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock, return_value=None)
    async def test_empty_title_falls_back_to_workflow(
        self, _mock_conflict, _mock_slugify, _mock_suffix
    ):
        slug = await generate_unique_workflow_slug("")
        assert slug == "workflow-aabbcc"

    @patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock, return_value=None)
    async def test_exclude_id_passed_to_query(self, mock_conflict):
        await generate_unique_workflow_slug("Test", exclude_id="wf_existing")
        assert mock_conflict.await_args.kwargs["exclude_id"] == "wf_existing"

    @patch("app.services.workflow.service._slug_suffix", return_value="aabbcc")
    @patch(f"{_REPO}.find_public_slug_conflict", new_callable=AsyncMock)
    async def test_slug_gives_up_after_max_retries(self, mock_conflict, _mock_suffix):
        # Every candidate collides — the generator exhausts its retries and raises.
        mock_conflict.return_value = _make_workflow_doc()
        with pytest.raises(RuntimeError, match="unique slug"):
            await generate_unique_workflow_slug("My Workflow")


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
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_manual_workflow_success(
        self, mock_create, _mock_activate, mock_chroma, mock_scheduler, mock_queue
    ):
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request()
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert isinstance(result, Workflow)
        assert result.title == "New Workflow"
        assert result.activated is True
        mock_create.assert_awaited_once()
        mock_queue.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowQueueService.queue_workflow_generation",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_with_pre_existing_steps_skips_generation(
        self, _mock_create, _mock_activate, mock_chroma, mock_scheduler, mock_queue
    ):
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        steps = [WorkflowStep(id="s1", title="Pre-existing", description="Already defined")]
        request = _make_create_request(steps=steps)
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert isinstance(result, Workflow)
        # Should NOT queue generation when steps are provided
        mock_queue.assert_not_awaited()

    @patch(
        "app.services.workflow.service.compute_missing_integrations",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.find_system_workflow", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_returns_existing_system_workflow_instead_of_duplicate(
        self, mock_create, mock_find_system, mock_chroma, _mock_scheduler, _mock_missing
    ):
        """A system workflow is one-per-user: reaching the same definition from the
        explore card after the provisioner already made it must hand back that
        workflow, not create a second copy."""
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())
        already_provisioned = _make_workflow()
        mock_find_system.return_value = already_provisioned

        request = _make_create_request(
            steps=[WorkflowStep(id="s1", title="Triage", description="d")]
        )
        request.system_workflow_key = "gmail:email_intelligence"

        result = await WorkflowService.create_workflow(request, USER_ID)

        assert result is already_provisioned
        mock_find_system.assert_awaited_once_with(USER_ID, "gmail:email_intelligence")
        mock_create.assert_not_awaited()

    @patch(
        "app.services.workflow.service.compute_missing_integrations",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_stays_inactive_when_steps_need_unconnected_integrations(
        self, _mock_create, mock_activate, mock_chroma, _mock_scheduler, mock_missing
    ):
        """Supplied steps skip generation, so the generation-time gate never runs on
        them. A workflow needing an app the user hasn't connected must still be
        created switched off rather than firing and failing on its first run."""
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())
        mock_missing.return_value = [IntegrationRef(id="gmail", name="Gmail")]

        request = _make_create_request(
            steps=[WorkflowStep(id="s1", title="Read inbox", description="d")]
        )
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert result.activated is False
        mock_activate.assert_not_awaited()

    @patch(
        "app.services.workflow.service.compute_missing_integrations",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_activates_when_no_integrations_missing(
        self, _mock_create, mock_activate, mock_chroma, _mock_scheduler, _mock_missing
    ):
        """The counterpart to the above: nothing missing means it still switches on."""
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request(
            steps=[WorkflowStep(id="s1", title="Remind me", description="d")]
        )
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert result.activated is True
        mock_activate.assert_awaited_once()

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
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_with_generate_immediately(
        self, _mock_create, _mock_activate, mock_chroma, mock_scheduler, mock_get, mock_gen
    ):
        generated_wf = _make_workflow()
        mock_get.return_value = generated_wf
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request(generate_immediately=True)
        result = await WorkflowService.create_workflow(request, USER_ID)

        mock_gen.assert_awaited_once()
        assert result == generated_wf

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_schedule_workflow_schedules_execution(
        self, _mock_create, _mock_activate, mock_chroma, mock_scheduler
    ):
        next_run = datetime.now(UTC) + timedelta(hours=1)
        trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            next_run=next_run,
        )
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        request = _make_create_request(
            trigger_config=trigger,
            steps=[WorkflowStep(id="s1", title="s", description="d")],
        )
        await WorkflowService.create_workflow(request, USER_ID, user_timezone="America/New_York")

        mock_scheduler.schedule_workflow_execution.assert_awaited_once()

    @patch(
        "app.services.oauth.oauth_service.check_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
        return_value=["trigger_1"],
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_integration_workflow_registers_triggers(
        self,
        _mock_create,
        _mock_activate,
        mock_chroma,
        mock_scheduler,
        mock_register,
        _mock_check_status,
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="calendar_event_created",
        )
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
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_rollback_on_trigger_registration_error(
        self, _mock_create, mock_delete, mock_chroma, mock_scheduler, mock_register
    ):
        mock_register.side_effect = TriggerRegistrationError(
            "Registration failed", trigger_name="test_trigger"
        )
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="test_trigger",
        )
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request(trigger_config=trigger)
        with pytest.raises(TriggerRegistrationError):
            await WorkflowService.create_workflow(request, USER_ID)

        # Verify rollback occurred (the pending workflow is deleted)
        mock_delete.assert_awaited_once()

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_fails_on_db_insert(self, mock_create, mock_chroma, mock_scheduler):
        # The repository raises if the insert can't be read back; the failure
        # propagates out of create_workflow.
        mock_create.side_effect = ValueError("Failed to create workflow")
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
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_chroma_failure_non_critical(
        self, _mock_create, _mock_activate, mock_chroma, mock_scheduler, mock_queue
    ):
        """ChromaDB failure should not prevent workflow creation."""
        mock_chroma.get_langchain_client = AsyncMock(side_effect=Exception("ChromaDB down"))

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
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_queue_generation_failure_still_returns_workflow(
        self, _mock_create, _mock_activate, mock_chroma, mock_scheduler, mock_queue
    ):
        """If queueing generation fails, the workflow is still returned."""
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        request = _make_create_request()
        result = await WorkflowService.create_workflow(request, USER_ID)

        assert isinstance(result, Workflow)

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch("app.services.workflow.service.ChromaClient")
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock)
    @patch(f"{_REPO}.mark_activated_with_triggers", new_callable=AsyncMock)
    @patch(f"{_REPO}.create", new_callable=AsyncMock)
    async def test_create_cleanup_on_generic_error_after_trigger_registration(
        self, _mock_create, mock_activate, mock_delete, mock_chroma, mock_scheduler
    ):
        """A generic error after the workflow row exists rolls the workflow back."""
        # The activation write raises after the pending row is created.
        mock_activate.side_effect = Exception("Unexpected error")
        mock_chroma.get_langchain_client = AsyncMock(return_value=MagicMock())

        trigger = _make_trigger_config(
            trigger_type=TriggerType.MANUAL,
        )
        request = _make_create_request(trigger_config=trigger)

        with pytest.raises(Exception, match="Unexpected error"):
            await WorkflowService.create_workflow(request, USER_ID)

        mock_delete.assert_awaited()


# ===========================================================================
# WorkflowService.get_workflow tests
# ===========================================================================


class TestGetWorkflow:
    """Tests for WorkflowService.get_workflow."""

    @patch(f"{_REPO}.get_for_user", new_callable=AsyncMock)
    async def test_get_workflow_found(self, mock_get_for_user):
        wf = _make_workflow()
        mock_get_for_user.return_value = _make_workflow_doc(wf)

        result = await WorkflowService.get_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        assert result.title == "Test Workflow"
        mock_get_for_user.assert_awaited_once_with(WORKFLOW_ID, USER_ID)

    @patch(f"{_REPO}.get_for_user", new_callable=AsyncMock, return_value=None)
    async def test_get_workflow_not_found(self, _mock_get_for_user):
        result = await WorkflowService.get_workflow("nonexistent", USER_ID)
        assert result is None

    @patch(f"{_REPO}.get_for_user", new_callable=AsyncMock)
    async def test_get_workflow_db_error_raises(self, mock_get_for_user):
        mock_get_for_user.side_effect = Exception("DB connection lost")

        with pytest.raises(Exception, match="DB connection lost"):
            await WorkflowService.get_workflow(WORKFLOW_ID, USER_ID)


# ===========================================================================
# WorkflowService.list_workflows tests
# ===========================================================================


class TestListWorkflows:
    """Tests for WorkflowService.list_workflows."""

    @pytest.fixture(autouse=True)
    def mock_integrations_status(self):
        with patch(
            "app.services.oauth.oauth_service.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={},
        ):
            yield

    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock)
    async def test_list_workflows_returns_workflows(self, mock_list):
        mock_list.return_value = [_make_workflow_doc(_make_workflow())]

        result, total = await WorkflowService.list_workflows(USER_ID)
        assert len(result) == 1
        assert isinstance(result[0], Workflow)
        # Unpaginated: total is derived from the rows, no separate count query.
        assert total == 1

    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock, return_value=[])
    async def test_list_workflows_empty(self, _mock_list):
        result, total = await WorkflowService.list_workflows(USER_ID)
        assert result == []
        assert total == 0

    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock, return_value=[])
    async def test_list_workflows_excludes_todo_workflows_by_default(self, mock_list):
        await WorkflowService.list_workflows(USER_ID, exclude_todo_workflows=True)

        # The todo-exclusion filter is the repository's contract; the service just
        # forwards the flag (and the unpaginated limit/offset).
        mock_list.assert_awaited_once_with(
            USER_ID, exclude_todo_workflows=True, limit=None, offset=0
        )

    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock, return_value=[])
    async def test_list_workflows_includes_todo_workflows_when_false(self, mock_list):
        await WorkflowService.list_workflows(USER_ID, exclude_todo_workflows=False)

        mock_list.assert_awaited_once_with(
            USER_ID, exclude_todo_workflows=False, limit=None, offset=0
        )

    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock)
    async def test_list_workflows_returns_all_repo_rows(self, mock_list):
        # Malformed-row skipping now lives in the repository (each row is validated
        # into a typed WorkflowDocument there); the service faithfully returns every
        # row the repository yields.
        mock_list.return_value = [
            _make_workflow_doc(_make_workflow(workflow_id="wf_a")),
            _make_workflow_doc(_make_workflow(workflow_id="wf_b")),
        ]

        result, total = await WorkflowService.list_workflows(USER_ID)
        assert len(result) == 2
        assert total == 2

    @patch(f"{_REPO}.count_for_user", new_callable=AsyncMock, return_value=42)
    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock, return_value=[])
    async def test_list_workflows_paginated_forwards_and_counts(self, mock_list, mock_count):
        # A paginated caller: limit/offset are forwarded to the repo and the repo's
        # full match count (not len(result)) is reported as total.
        _result, total = await WorkflowService.list_workflows(USER_ID, limit=10, offset=20)

        mock_list.assert_awaited_once_with(
            USER_ID, exclude_todo_workflows=True, limit=10, offset=20
        )
        mock_count.assert_awaited_once_with(USER_ID, exclude_todo_workflows=True)
        assert total == 42

    @patch(f"{_REPO}.count_for_user", new_callable=AsyncMock)
    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock)
    async def test_list_workflows_skips_count_when_unpaginated(self, mock_list, mock_count):
        # An unpaginated fetch already holds every match, so total is derived from
        # the rows and the second count round-trip is skipped.
        mock_list.return_value = [_make_workflow_doc(_make_workflow())]

        _result, total = await WorkflowService.list_workflows(USER_ID)

        mock_count.assert_not_awaited()
        assert total == 1

    @patch(f"{_REPO}.list_for_user", new_callable=AsyncMock)
    async def test_list_workflows_db_error_raises(self, mock_list):
        mock_list.side_effect = Exception("DB error")

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
    @patch(f"{_REPO}.update_for_user", new_callable=AsyncMock)
    async def test_update_title_success(self, mock_update, mock_get):
        wf = _make_workflow()
        updated_wf = _make_workflow()
        updated_wf.title = "Updated Title"
        mock_get.side_effect = [wf, updated_wf]
        mock_update.return_value = _make_workflow_doc(updated_wf)

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
    @patch(f"{_REPO}.update_for_user", new_callable=AsyncMock, return_value=None)
    async def test_update_matched_count_zero_returns_none(self, _mock_update, mock_get):
        mock_get.return_value = _make_workflow()

        request = _make_update_request(title="Updated")
        result = await WorkflowService.update_workflow(WORKFLOW_ID, request, USER_ID)

        assert result is None

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.update_for_user", new_callable=AsyncMock)
    async def test_update_trigger_config_reschedules(self, mock_update, mock_get, mock_scheduler):
        next_run = datetime.now(UTC) + timedelta(hours=2)
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
        mock_update.return_value = _make_workflow_doc(updated_wf)
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
    @patch(f"{_REPO}.update_for_user", new_callable=AsyncMock)
    async def test_update_disable_schedule_cancels(self, mock_update, mock_get, mock_scheduler):
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
        mock_update.return_value = _make_workflow_doc(updated_wf)

        request = _make_update_request(trigger_config=new_trigger)
        result = await WorkflowService.update_workflow(WORKFLOW_ID, request, USER_ID)

        # Disabling a schedule no longer explicitly cancels ARQ jobs — the claim
        # gate rejects any in-flight job once activated=False is persisted.
        assert result is not None

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
        return_value=(["new_trigger_id"], True),
    )
    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.update_for_user", new_callable=AsyncMock)
    async def test_update_integration_trigger_re_registers(
        self,
        mock_update,
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
        mock_update.return_value = _make_workflow_doc(updated_wf)

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

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=True)
    async def test_delete_success(self, mock_delete, mock_get):
        mock_get.return_value = _make_workflow()

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True
        mock_delete.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=False)
    async def test_delete_not_found(self, _mock_delete, mock_get):
        mock_get.return_value = None

        result = await WorkflowService.delete_workflow("nonexistent", USER_ID)
        assert result is False

    @patch(
        "app.services.workflow.service.TriggerService.unregister_triggers",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=True)
    async def test_delete_with_integration_triggers_unregisters(
        self, _mock_delete, mock_get, mock_unregister
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="calendar_event",
            composio_trigger_ids=["tid_1", "tid_2"],
        )
        wf = _make_workflow(trigger_config=trigger)
        mock_get.return_value = wf

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True
        mock_unregister.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=True)
    async def test_delete_scheduled_workflow_no_scheduler_teardown(self, mock_delete, mock_get):
        """A scheduled workflow deletes cleanly: liveness is governed by the claim
        gate, so delete performs no scheduler teardown — just the row removal."""
        trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
        )
        mock_get.return_value = _make_workflow(trigger_config=trigger)

        result = await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)
        assert result is True
        mock_delete.assert_awaited_once()

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock)
    async def test_delete_db_error_raises(self, mock_delete, mock_get):
        mock_get.return_value = _make_workflow()
        mock_delete.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            await WorkflowService.delete_workflow(WORKFLOW_ID, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.delete_for_user", new_callable=AsyncMock, return_value=True)
    async def test_delete_with_triggers_but_no_trigger_name_skips_unregister(
        self, _mock_delete, mock_get
    ):
        """If trigger_ids exist but trigger_name is None, unregister is skipped."""
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name=None,
            composio_trigger_ids=["tid_1"],
        )
        wf = _make_workflow(trigger_config=trigger)
        mock_get.return_value = wf

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
    @patch(f"{_REPO}.touch", new_callable=AsyncMock)
    async def test_execute_success(self, mock_touch, mock_get, mock_queue):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf
        mock_touch.return_value = _make_workflow_doc(wf)

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
    @patch(f"{_REPO}.touch", new_callable=AsyncMock)
    async def test_execute_queue_failure(self, mock_touch, mock_get, mock_queue):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf
        mock_touch.return_value = _make_workflow_doc(wf)

        request = WorkflowExecutionRequest()
        with pytest.raises(ValueError, match="Failed to queue"):
            await WorkflowService.execute_workflow(WORKFLOW_ID, request, USER_ID)

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.touch", new_callable=AsyncMock, return_value=None)
    async def test_execute_update_timestamp_failure(self, _mock_touch, mock_get):
        wf = _make_workflow(activated=True)
        mock_get.return_value = wf

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
    @patch(f"{_REPO}.activate", new_callable=AsyncMock)
    async def test_activate_manual_workflow(self, mock_activate, mock_get, mock_scheduler):
        wf = _make_workflow(activated=False)
        activated_wf = _make_workflow(activated=True)
        mock_get.side_effect = [wf, activated_wf]
        mock_activate.return_value = _make_workflow_doc(activated_wf)

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
    @patch(f"{_REPO}.activate", new_callable=AsyncMock, return_value=None)
    async def test_activate_db_update_no_match_returns_none(self, _mock_activate, mock_get):
        wf = _make_workflow(activated=False)
        mock_get.return_value = wf

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
    async def test_activate_trigger_registration_failure_raises(self, mock_get, mock_register):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="test_trigger",
        )
        wf = _make_workflow(activated=False, trigger_config=trigger)
        mock_get.return_value = wf
        mock_register.side_effect = TriggerRegistrationError("Failed", trigger_name="test_trigger")

        with pytest.raises(TriggerRegistrationError):
            await WorkflowService.activate_workflow(WORKFLOW_ID, USER_ID)

    @patch("app.services.workflow.service.workflow_scheduler")
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.activate", new_callable=AsyncMock)
    async def test_activate_schedule_workflow_schedules_execution(
        self, mock_activate, mock_get, mock_scheduler
    ):
        next_run = datetime.now(UTC) + timedelta(hours=1)
        trigger = _make_trigger_config(
            trigger_type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            next_run=next_run,
        )
        wf = _make_workflow(activated=False, trigger_config=trigger)
        activated_wf = _make_workflow(activated=True, trigger_config=trigger)
        mock_get.side_effect = [wf, activated_wf]
        mock_activate.return_value = _make_workflow_doc(activated_wf)
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        result = await WorkflowService.activate_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None
        mock_scheduler.schedule_workflow_execution.assert_awaited_once()


# ===========================================================================
# WorkflowService.deactivate_workflow tests
# ===========================================================================


class TestDeactivateWorkflow:
    """Tests for WorkflowService.deactivate_workflow."""

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.deactivate", new_callable=AsyncMock)
    async def test_deactivate_success(self, mock_deactivate, mock_get):
        wf = _make_workflow(activated=True)
        deactivated_wf = _make_workflow(activated=False)
        mock_get.side_effect = [wf, deactivated_wf]
        mock_deactivate.return_value = _make_workflow_doc(deactivated_wf)

        result = await WorkflowService.deactivate_workflow(WORKFLOW_ID, USER_ID)
        assert result is not None

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    async def test_deactivate_not_found(self, mock_get):
        mock_get.return_value = None

        result = await WorkflowService.deactivate_workflow("nonexistent", USER_ID)
        assert result is None

    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.deactivate", new_callable=AsyncMock, return_value=None)
    async def test_deactivate_db_update_no_match(self, _mock_deactivate, mock_get):
        wf = _make_workflow(activated=True)
        mock_get.side_effect = [wf]

        result = await WorkflowService.deactivate_workflow(WORKFLOW_ID, USER_ID)
        assert result is None

    @patch(
        "app.services.workflow.service.TriggerService.unregister_triggers",
        new_callable=AsyncMock,
        return_value=True,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.deactivate", new_callable=AsyncMock)
    async def test_deactivate_with_integration_triggers_unregisters(
        self, mock_deactivate, mock_get, mock_unregister
    ):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="calendar_event",
            composio_trigger_ids=["tid_1"],
        )
        wf = _make_workflow(activated=True, trigger_config=trigger)
        deactivated_wf = _make_workflow(activated=False, trigger_config=trigger)
        mock_get.side_effect = [wf, deactivated_wf]
        mock_deactivate.return_value = _make_workflow_doc(deactivated_wf)

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
    @patch(f"{_REPO}.set_steps", new_callable=AsyncMock)
    async def test_regenerate_success(self, mock_set_steps, mock_get, mock_gen):
        wf = _make_workflow()
        mock_get.return_value = wf
        new_steps = [
            WorkflowStep(id="step_0", title="New Step", category="gaia", description="New")
        ]
        mock_gen.return_value = new_steps
        mock_set_steps.return_value = _make_workflow_doc(wf, steps=new_steps)

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
    @patch(f"{_REPO}.set_steps", new_callable=AsyncMock, return_value=None)
    async def test_regenerate_db_returns_none(self, _mock_set_steps, mock_get, mock_gen):
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_gen.return_value = [
            WorkflowStep(id="step_0", title="T", category="c", description="d")
        ]

        result = await WorkflowService.regenerate_workflow_steps(WORKFLOW_ID, USER_ID)
        assert result is None


# ===========================================================================
# WorkflowService.increment_execution_count tests
# ===========================================================================


class TestIncrementExecutionCount:
    """Tests for WorkflowService.increment_execution_count."""

    @patch(f"{_REPO}.record_execution", new_callable=AsyncMock, return_value=True)
    async def test_increment_success(self, mock_record):
        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=True
        )
        assert result is True

        # A successful run records against both counters (the repo owns the $inc).
        mock_record.assert_awaited_once_with(WORKFLOW_ID, USER_ID, successful=True)

    @patch(f"{_REPO}.record_execution", new_callable=AsyncMock, return_value=True)
    async def test_increment_failure_only_total(self, mock_record):
        result = await WorkflowService.increment_execution_count(
            WORKFLOW_ID, USER_ID, is_successful=False
        )
        assert result is True

        mock_record.assert_awaited_once_with(WORKFLOW_ID, USER_ID, successful=False)

    @patch(f"{_REPO}.record_execution", new_callable=AsyncMock, return_value=False)
    async def test_increment_workflow_not_found(self, _mock_record):
        result = await WorkflowService.increment_execution_count("nonexistent", USER_ID)
        assert result is False

    @patch(f"{_REPO}.record_execution", new_callable=AsyncMock)
    async def test_increment_db_error_returns_false(self, mock_record):
        mock_record.side_effect = Exception("DB error")

        result = await WorkflowService.increment_execution_count(WORKFLOW_ID, USER_ID)
        assert result is False


# ===========================================================================
# WorkflowService._generate_workflow_steps tests
# ===========================================================================


class TestGenerateWorkflowSteps:
    """Tests for WorkflowService._generate_workflow_steps (internal)."""

    @patch("app.services.workflow.service.handle_workflow_error", new_callable=AsyncMock)
    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.set_steps", new_callable=AsyncMock)
    @patch(f"{_REPO}.touch", new_callable=AsyncMock)
    async def test_generate_steps_success(
        self, mock_touch, mock_set_steps, mock_get, mock_gen, mock_error_handler
    ):
        wf = _make_workflow()
        mock_get.return_value = wf
        steps_data = [WorkflowStep(id="step_0", title="S", category="gaia", description="D")]
        mock_gen.return_value = steps_data
        mock_touch.return_value = _make_workflow_doc(wf)

        await WorkflowService._generate_workflow_steps(WORKFLOW_ID, USER_ID)

        mock_gen.assert_awaited_once()
        # Heartbeat at start, then persist the generated steps.
        mock_touch.assert_awaited_once()
        mock_set_steps.assert_awaited_once()

    @patch("app.services.workflow.service.handle_workflow_error", new_callable=AsyncMock)
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.touch", new_callable=AsyncMock, return_value=None)
    async def test_generate_steps_workflow_not_found_returns_early(
        self, _mock_touch, mock_get, mock_error_handler
    ):
        mock_get.return_value = None

        # Should not raise, just return
        await WorkflowService._generate_workflow_steps(WORKFLOW_ID, USER_ID)
        mock_error_handler.assert_not_awaited()

    @patch("app.services.workflow.service.handle_workflow_error", new_callable=AsyncMock)
    @patch(
        "app.services.workflow.service.WorkflowGenerationService.generate_steps_with_llm",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.service.WorkflowService.get_workflow",
        new_callable=AsyncMock,
    )
    @patch(f"{_REPO}.set_error_message", new_callable=AsyncMock)
    @patch(f"{_REPO}.touch", new_callable=AsyncMock)
    async def test_generate_steps_llm_failure_persists_error(
        self, mock_touch, mock_set_error, mock_get, mock_gen, mock_error_handler
    ):
        wf = _make_workflow()
        mock_get.return_value = wf
        mock_gen.side_effect = RuntimeError("LLM quota exceeded")
        mock_touch.return_value = _make_workflow_doc(wf)

        await WorkflowService._generate_workflow_steps(WORKFLOW_ID, USER_ID)

        # The failure message is persisted via the repository, then the shared
        # error handler runs.
        mock_set_error.assert_awaited_once()
        assert mock_set_error.await_args.args[2] == "LLM quota exceeded"
        mock_error_handler.assert_awaited_once()


# ===========================================================================
# WorkflowService._register_integration_triggers tests
# ===========================================================================


class TestRegisterIntegrationTriggers:
    """Tests for WorkflowService._register_integration_triggers."""

    async def test_non_integration_trigger_returns_empty(self):
        trigger = _make_trigger_config(trigger_type=TriggerType.MANUAL)
        result = await WorkflowService._register_integration_triggers(WORKFLOW_ID, USER_ID, trigger)
        # Non-INTEGRATION triggers return ([], True): empty ids, integration_connected=True
        assert result == ([], True)

    async def test_integration_trigger_without_name_raises(self):
        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION, trigger_name=None)
        with pytest.raises(TriggerRegistrationError, match="trigger_name"):
            await WorkflowService._register_integration_triggers(WORKFLOW_ID, USER_ID, trigger)

    @patch(
        "app.services.workflow.service.TriggerService.register_triggers",
        new_callable=AsyncMock,
        return_value=["tid_1"],
    )
    async def test_integration_trigger_success(self, mock_register):
        trigger = _make_trigger_config(
            trigger_type=TriggerType.INTEGRATION, trigger_name="calendar_event"
        )
        result = await WorkflowService._register_integration_triggers(WORKFLOW_ID, USER_ID, trigger)
        # Returns (trigger_ids, integration_connected)
        assert result == (["tid_1"], True)
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
        assert result[0].id == "step_0"
        assert result[1].id == "step_1"
        assert result[0].title == "Step A"
        assert result[0].category == "gmail"

    def test_enrich_empty_list(self):
        result = enrich_steps([])
        assert result == []


class TestBuildTriggerHint:
    """Tests for _build_trigger_hint."""

    def test_no_config_returns_default(self):
        result = _build_trigger_hint(None)
        assert "No trigger selected" in result

    def test_schedule_with_cron(self):
        config = PromptTriggerHint(type="schedule", cron_expression="0 9 * * *")
        result = _build_trigger_hint(config)
        assert "scheduled trigger" in result
        assert "0 9 * * *" in result

    def test_schedule_without_cron(self):
        config = PromptTriggerHint(type="schedule")
        result = _build_trigger_hint(config)
        assert "scheduled trigger" in result

    def test_manual(self):
        result = _build_trigger_hint(PromptTriggerHint(type="manual"))
        assert "manual trigger" in result

    def test_integration_with_name(self):
        config = PromptTriggerHint(type="integration", trigger_name="gmail_new_message")
        result = _build_trigger_hint(config)
        assert "gmail_new_message" in result

    def test_unknown_type(self):
        result = _build_trigger_hint(PromptTriggerHint(type="webhook"))
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
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.generation_service.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_generate_success(
        self, mock_registry_fn: AsyncMock, mock_structured: AsyncMock
    ) -> None:
        # Setup tool registry mock
        mock_registry = MagicMock()
        mock_category = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_category.get_tool_objects.return_value = [mock_tool]
        mock_registry.get_all_category_objects.return_value = {"test_cat": mock_category}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_structured.return_value = GeneratedWorkflow(
            steps=[GeneratedStep(title="Step 1", category="gaia", description="Do something")]
        )

        result = await WorkflowGenerationService.generate_steps_with_llm(
            "Test prompt", "Test Title", user_id="test-user"
        )

        assert len(result) == 1
        assert result[0].id == "step_0"
        assert result[0].title == "Step 1"
        assert mock_structured.await_args[0][0] is GeneratedWorkflow

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.generation_service.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_generate_invalid_output_regenerates_then_succeeds(
        self, mock_registry_fn: AsyncMock, mock_structured: AsyncMock
    ) -> None:
        """A schema-invalid first attempt triggers one regeneration, which succeeds."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        generated = GeneratedWorkflow(
            steps=[GeneratedStep(title="Parsed", category="gaia", description="Second try")]
        )
        mock_structured.side_effect = [OutputParserException("bad output"), generated]

        result = await WorkflowGenerationService.generate_steps_with_llm(
            "Test prompt", "Test Title", user_id="test-user"
        )

        assert len(result) == 1
        assert result[0].title == "Parsed"
        assert mock_structured.await_count == 2

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.generation_service.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_generate_empty_steps_retries_then_fails(
        self, mock_registry_fn: AsyncMock, mock_structured: AsyncMock
    ) -> None:
        """If LLM returns empty steps, retry and ultimately raise RuntimeError."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_structured.return_value = GeneratedWorkflow(steps=[])

        with pytest.raises(RuntimeError, match="failed"):
            await WorkflowGenerationService.generate_steps_with_llm(
                "Test prompt", "Test Title", user_id="test-user"
            )

        assert mock_structured.await_count == 2

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.generation_service.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_generate_llm_error_propagates(
        self, mock_registry_fn: AsyncMock, mock_structured: AsyncMock
    ) -> None:
        """Provider errors propagate — transient retry lives in ainvoke_structured, not
        the generation loop, so the loop does not re-issue the request on an LLM failure."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_structured.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError, match="provider down"):
            await WorkflowGenerationService.generate_steps_with_llm(
                "Test prompt", "Test Title", user_id="test-user"
            )

        # Called exactly once — the loop does not retry provider errors.
        assert mock_structured.await_count == 1

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.generation_service.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_generate_with_description(
        self, mock_registry_fn: AsyncMock, mock_structured: AsyncMock
    ) -> None:
        """Description should be appended to the prompt context."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_structured.return_value = GeneratedWorkflow(
            steps=[GeneratedStep(title="S1", category="gaia", description="D")]
        )

        await WorkflowGenerationService.generate_steps_with_llm(
            "Prompt text", "Title", description="Short description", user_id="test-user"
        )

        # Verify description was included in the formatted prompt
        formatted_prompt = mock_structured.await_args[0][1]
        assert "Short description" in formatted_prompt

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.workflow.generation_service.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_generate_invalid_output_exhausts_attempts(
        self, mock_registry_fn: AsyncMock, mock_structured: AsyncMock
    ) -> None:
        """Schema-invalid output on every attempt raises RuntimeError after retries."""
        mock_registry = MagicMock()
        mock_registry.get_all_category_objects.return_value = {}
        mock_registry.get_core_tools.return_value = []
        mock_registry_fn.return_value = mock_registry

        mock_structured.side_effect = OutputParserException("bad output")

        with pytest.raises(RuntimeError, match="failed"):
            await WorkflowGenerationService.generate_steps_with_llm(
                "Prompt", "Title", user_id="test-user"
            )

        assert mock_structured.await_count == 2


# ===========================================================================
# WorkflowGenerationService.generate_workflow_prompt tests
# ===========================================================================


class TestGenerateWorkflowPrompt:
    """Tests for WorkflowGenerationService.generate_workflow_prompt."""

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_generate_prompt_success(self, mock_structured: AsyncMock) -> None:
        mock_structured.return_value = GeneratedPromptOutput(
            instructions="Step-by-step instructions here",
            trigger_type="schedule",
            cron_expression="0 9 * * 1-5",
        )

        result = await WorkflowGenerationService.generate_workflow_prompt(
            title="Morning Briefing",
            description="Daily summary",
            user_id="test-user",
        )

        assert result["prompt"] == "Step-by-step instructions here"
        assert result["suggested_trigger"] is not None
        assert result["suggested_trigger"].type == "schedule"
        assert result["suggested_trigger"].cron_expression == "0 9 * * 1-5"

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_generate_prompt_manual_suggested_trigger(
        self, mock_structured: AsyncMock
    ) -> None:
        mock_structured.return_value = GeneratedPromptOutput(
            instructions="Manual instructions",
            trigger_type="manual",
        )

        result = await WorkflowGenerationService.generate_workflow_prompt(
            title="Task", user_id="test-user"
        )

        assert result["prompt"] == "Manual instructions"
        assert result["suggested_trigger"] is not None
        assert result["suggested_trigger"].type == "manual"

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_generate_prompt_invalid_trigger_type_no_suggestion(
        self, mock_structured: AsyncMock
    ) -> None:
        mock_structured.return_value = GeneratedPromptOutput(
            instructions="Instructions",
            trigger_type="webhook",  # Not in the valid set
        )

        result = await WorkflowGenerationService.generate_workflow_prompt(
            title="Task", user_id="test-user"
        )

        assert result["prompt"] == "Instructions"
        assert result["suggested_trigger"] is None

    @patch("app.services.workflow.generation_service.OAUTH_INTEGRATIONS", [])
    @patch(
        "app.services.workflow.generation_service.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_generate_prompt_parse_failure_propagates(
        self, mock_structured: AsyncMock
    ) -> None:
        """OutputParserException from ainvoke_structured propagates — no fallback."""
        mock_structured.side_effect = OutputParserException("LLM unavailable")

        with pytest.raises(OutputParserException, match="LLM unavailable"):
            await WorkflowGenerationService.generate_workflow_prompt(
                title="Test", user_id="test-user"
            )


# ===========================================================================
# WorkflowScheduler tests
# ===========================================================================


class TestWorkflowScheduler:
    """Tests for WorkflowScheduler."""

    def test_get_job_name(self):
        scheduler = WorkflowScheduler()
        assert scheduler.get_job_name() == "execute_workflow_by_id"

    # get_task / update_task_status now delegate to workflow_repository — Mongo
    # shape/codec is the repository's contract (tests/contracts). Here we verify
    # delegation, the owner-scoped vs global get, and the fail-loud-swallow contract.
    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_get_task_found_uses_global_get(self, mock_repo):
        mock_repo.get = AsyncMock(return_value=_make_workflow())
        mock_repo.get_for_user = AsyncMock()

        result = await WorkflowScheduler().get_task(WORKFLOW_ID)

        assert isinstance(result, Workflow)
        mock_repo.get.assert_awaited_once_with(WORKFLOW_ID)
        mock_repo.get_for_user.assert_not_awaited()

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_get_task_not_found(self, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)

        result = await WorkflowScheduler().get_task("nonexistent")
        assert result is None

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_get_task_with_user_id_uses_owner_scoped_get(self, mock_repo):
        mock_repo.get_for_user = AsyncMock(return_value=_make_workflow())

        await WorkflowScheduler().get_task(WORKFLOW_ID, user_id=USER_ID)

        mock_repo.get_for_user.assert_awaited_once_with(WORKFLOW_ID, USER_ID)

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_get_task_db_error_returns_none(self, mock_repo):
        mock_repo.get = AsyncMock(side_effect=Exception("DB error"))

        result = await WorkflowScheduler().get_task(WORKFLOW_ID)
        assert result is None

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_update_task_status_success(self, mock_repo):
        mock_repo.set_status = AsyncMock(return_value=True)
        from app.models.scheduler_models import ScheduledTaskStatus

        result = await WorkflowScheduler().update_task_status(
            WORKFLOW_ID, ScheduledTaskStatus.EXECUTING
        )
        assert result is True

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_update_task_status_not_found(self, mock_repo):
        mock_repo.set_status = AsyncMock(return_value=False)
        from app.models.scheduler_models import ScheduledTaskStatus

        result = await WorkflowScheduler().update_task_status(
            "nonexistent", ScheduledTaskStatus.EXECUTING
        )
        assert result is False

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_update_task_status_with_user_id(self, mock_repo):
        mock_repo.set_status = AsyncMock(return_value=True)
        from app.models.scheduler_models import ScheduledTaskStatus

        await WorkflowScheduler().update_task_status(
            WORKFLOW_ID, ScheduledTaskStatus.SCHEDULED, user_id=USER_ID
        )

        assert mock_repo.set_status.call_args.kwargs["user_id"] == USER_ID

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_update_task_status_db_error_returns_false(self, mock_repo):
        mock_repo.set_status = AsyncMock(side_effect=Exception("DB error"))
        from app.models.scheduler_models import ScheduledTaskStatus

        result = await WorkflowScheduler().update_task_status(
            WORKFLOW_ID, ScheduledTaskStatus.EXECUTING
        )
        assert result is False

    @patch("app.services.workflow.scheduler.workflow_repository")
    async def test_update_task_status_with_extra_data(self, mock_repo):
        mock_repo.set_status = AsyncMock(return_value=True)
        from app.models.scheduler_models import ScheduledTaskStatus

        await WorkflowScheduler().update_task_status(
            WORKFLOW_ID,
            ScheduledTaskStatus.COMPLETED,
            update_data={"occurrence_count": 5},
        )

        assert mock_repo.set_status.call_args.kwargs["occurrence_count"] == 5

    async def test_schedule_workflow_execution_success(self):
        scheduler = WorkflowScheduler()
        scheduler.schedule_task = AsyncMock(return_value=True)

        scheduled_at = datetime.now(UTC) + timedelta(hours=1)
        result = await scheduler.schedule_workflow_execution(
            WORKFLOW_ID, scheduled_at, repeat="0 9 * * *"
        )
        assert result is True
        scheduler.schedule_task.assert_awaited_once()

    async def test_schedule_workflow_execution_failure(self):
        scheduler = WorkflowScheduler()
        scheduler.schedule_task = AsyncMock(return_value=False)

        scheduled_at = datetime.now(UTC) + timedelta(hours=1)
        result = await scheduler.schedule_workflow_execution(WORKFLOW_ID, scheduled_at)
        assert result is False

    async def test_schedule_workflow_execution_exception_returns_false(self):
        scheduler = WorkflowScheduler()
        scheduler.schedule_task = AsyncMock(side_effect=Exception("Redis down"))

        scheduled_at = datetime.now(UTC) + timedelta(hours=1)
        result = await scheduler.schedule_workflow_execution(WORKFLOW_ID, scheduled_at)
        assert result is False

    async def test_reschedule_workflow_success(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=True)
        scheduler.reschedule_task = AsyncMock(return_value=True)

        new_time = datetime.now(UTC) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time, repeat="0 10 * * *")
        assert result is True

    async def test_reschedule_workflow_db_failure(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=False)

        new_time = datetime.now(UTC) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time)
        assert result is False

    async def test_reschedule_workflow_arq_failure(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(return_value=True)
        scheduler.reschedule_task = AsyncMock(return_value=False)

        new_time = datetime.now(UTC) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time)
        assert result is False

    async def test_reschedule_workflow_exception_returns_false(self):
        scheduler = WorkflowScheduler()
        scheduler.update_task_status = AsyncMock(side_effect=Exception("Error"))

        new_time = datetime.now(UTC) + timedelta(hours=2)
        result = await scheduler.reschedule_workflow(WORKFLOW_ID, new_time)
        assert result is False

    # The recurring-due scan (status=scheduled, scheduled_at<=now, activated,
    # repeat) now lives on workflow_repository.find_pending_before — contract-tested
    # against real Mongo in tests/contracts/test_workflows_repository.py. Here we
    # verify the scheduler delegates to it and passes the scan time through.
    @patch("app.services.workflow.scheduler.workflow_repository.find_pending_before")
    async def test_get_pending_task_returns_workflows(self, mock_find_pending):
        mock_find_pending.return_value = [_make_workflow()]

        now = datetime.now(UTC)
        result = await WorkflowScheduler().get_pending_task(now)
        assert len(result) == 1
        mock_find_pending.assert_awaited_once_with(now)

    @patch("app.services.workflow.scheduler.workflow_repository.find_pending_before")
    async def test_get_pending_task_empty(self, mock_find_pending):
        mock_find_pending.return_value = []

        result = await WorkflowScheduler().get_pending_task(datetime.now(UTC))
        assert result == []

    @patch("app.services.workflow.scheduler.workflow_repository.find_pending_before")
    async def test_get_pending_task_propagates_db_error(self, mock_find_pending):
        # Fail-loud: the repository no longer swallows a scan failure into an empty
        # list (the old _query_pending_tasks did). A DB error propagates.
        mock_find_pending.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            await WorkflowScheduler().get_pending_task(datetime.now(UTC))

    async def test_execute_task_with_workflow(self):
        """execute_task with a valid Workflow should attempt execution."""
        scheduler = WorkflowScheduler()
        wf = _make_workflow()

        with patch(
            "app.workers.tasks.execute_workflow_as_chat", new_callable=AsyncMock
        ) as mock_exec:
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

    @pytest.fixture(autouse=True)
    def _route_enqueue_through_pool(self, route_enqueue_via_pool):
        """Shared conftest fixture routes the wide-event enqueue wrapper through
        pool.enqueue_job so the tests' pool mocks stay authoritative."""
        return

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_generation_success(self, mock_redis):
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_123"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_generation(WORKFLOW_ID, USER_ID)
        assert result is True
        mock_pool.enqueue_job.assert_awaited_once_with(
            "generate_workflow_steps", WORKFLOW_ID, USER_ID
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_generation_no_job(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_generation(WORKFLOW_ID, USER_ID)
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_generation_exception(self, mock_redis):
        mock_redis.get_pool = AsyncMock(side_effect=Exception("Redis down"))

        result = await WorkflowQueueService.queue_workflow_generation(WORKFLOW_ID, USER_ID)
        assert result is False

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_execution_success(self, mock_redis):
        import hashlib
        import json

        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_456"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_execution(
            WORKFLOW_ID, USER_ID, context={"key": "val"}
        )
        assert result is True
        dedup_payload = json.dumps(
            {"workflow_id": WORKFLOW_ID, "user_id": USER_ID, "context": {"key": "val"}},
            sort_keys=True,
            default=str,
        )
        expected_job_id = (
            "execute_workflow_by_id:" + hashlib.sha256(dedup_payload.encode()).hexdigest()[:32]
        )
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", WORKFLOW_ID, {"key": "val"}, _job_id=expected_job_id
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_execution_no_context(self, mock_redis):
        import hashlib
        import json

        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job_789"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID)
        assert result is True
        dedup_payload = json.dumps(
            {"workflow_id": WORKFLOW_ID, "user_id": USER_ID, "context": {}},
            sort_keys=True,
            default=str,
        )
        expected_job_id = (
            "execute_workflow_by_id:" + hashlib.sha256(dedup_payload.encode()).hexdigest()[:32]
        )
        # context defaults to empty dict
        mock_pool.enqueue_job.assert_awaited_once_with(
            "execute_workflow_by_id", WORKFLOW_ID, {}, _job_id=expected_job_id
        )

    @patch("app.services.workflow.queue_service.RedisPoolManager")
    async def test_queue_execution_failure(self, mock_redis):
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)
        mock_redis.get_pool = AsyncMock(return_value=mock_pool)

        result = await WorkflowQueueService.queue_workflow_execution(WORKFLOW_ID, USER_ID)
        # enqueue_job returning None means the job was deduped (already queued/running).
        # That is a success, not a failure.
        assert result is True

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

    # Reference counting (the Mongo $ne/trigger-id query) is the repository's
    # contract (tests/contracts/test_workflows_repository.py::test_count_trigger_references).
    # Here we verify the service's safe-to-delete filtering over that count.
    @patch("app.services.workflow.trigger_service.workflow_repository")
    async def test_get_triggers_safe_to_delete_all_safe(self, mock_repo):
        mock_repo.count_trigger_references = AsyncMock(return_value=0)

        safe = await TriggerService.get_triggers_safe_to_delete(["t1", "t2"])
        assert safe == ["t1", "t2"]

    @patch("app.services.workflow.trigger_service.workflow_repository")
    async def test_get_triggers_safe_to_delete_none_safe(self, mock_repo):
        mock_repo.count_trigger_references = AsyncMock(return_value=2)

        safe = await TriggerService.get_triggers_safe_to_delete(["t1"])
        assert safe == []

    @patch("app.services.workflow.trigger_service.workflow_repository")
    async def test_get_triggers_safe_to_delete_partial(self, mock_repo):
        # t1 has references, t2 does not
        mock_repo.count_trigger_references = AsyncMock(side_effect=[1, 0])

        safe = await TriggerService.get_triggers_safe_to_delete(["t1", "t2"])
        assert safe == ["t2"]

    @patch("app.services.workflow.trigger_service.workflow_repository")
    async def test_get_triggers_safe_to_delete_with_excluding_workflow_id(self, mock_repo):
        mock_repo.count_trigger_references = AsyncMock(return_value=0)

        await TriggerService.get_triggers_safe_to_delete(["t1"], excluding_workflow_id="wf_123")

        mock_repo.count_trigger_references.assert_awaited_once_with(
            "t1", excluding_workflow_id="wf_123"
        )

    @patch("app.services.workflow.trigger_service.workflow_repository")
    async def test_get_triggers_safe_to_delete_error_skips(self, mock_repo):
        """On error, trigger should not be included in safe-to-delete list."""
        mock_repo.count_trigger_references = AsyncMock(side_effect=Exception("DB error"))

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
    async def test_register_triggers_no_handler_raise_on_failure(self, mock_get_handler):
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
    async def test_register_triggers_empty_result_raise_on_failure(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(return_value=[])
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        # Empty result is valid (e.g. account-level Gmail trigger has no per-workflow IDs).
        # raise_on_failure only applies when the handler raises, not when it returns [].
        result = await TriggerService.register_triggers(
            USER_ID, WORKFLOW_ID, "calendar_event", trigger, raise_on_failure=True
        )
        assert result == []

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_type_error_re_raised(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.register = AsyncMock(side_effect=TypeError("Wrong type"))
        mock_get_handler.return_value = mock_handler

        trigger = _make_trigger_config(trigger_type=TriggerType.INTEGRATION)
        with pytest.raises(TypeError, match="Wrong type"):
            await TriggerService.register_triggers(USER_ID, WORKFLOW_ID, "trigger", trigger)

    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_register_triggers_generic_exception_raise_on_failure(self, mock_get_handler):
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
    async def test_unregister_triggers_none_safe_to_delete(self, mock_get_handler, mock_safe):
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        result = await TriggerService.unregister_triggers(USER_ID, "calendar_event", ["tid_1"])
        assert result is True
        # Handler.unregister should not be called
        mock_handler.unregister.assert_not_called()

    @patch(
        "app.services.workflow.trigger_service.TriggerService.get_triggers_safe_to_delete",
        new_callable=AsyncMock,
    )
    @patch("app.services.workflow.trigger_service.get_handler_by_name")
    async def test_unregister_triggers_exception_returns_false(self, mock_get_handler, mock_safe):
        mock_safe.side_effect = Exception("DB error")
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        result = await TriggerService.unregister_triggers(USER_ID, "trigger", ["tid_1"])
        assert result is False
