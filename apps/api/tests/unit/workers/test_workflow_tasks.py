"""Unit tests for workflow_tasks ARQ worker."""

import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

from bson import ObjectId
import pytest

from app.api.v1.middleware.tiered_rate_limiter import (
    CostBudgetExceededException,
    RateLimitExceededException,
)
from app.config.rate_limits import RateLimitPeriod
from app.constants.log_tags import LogTag
from app.constants.vfs import SYSTEM_USER_ID
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import (
    Reply,
    ReplySettled,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
)
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelDeliveryStatus,
    NotificationAction,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    RedirectConfig,
    notification_id,
)
from app.models.playbook_models import PlaybookRunStatus
from app.models.scheduler_models import DeactivationReason
from app.models.user_models import AuthenticatedUser, UserDocument
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import TriggerType, WorkflowExecutionRequest, WorkflowStep
from app.services.conversation.outcome import EntryOutcome
from app.services.delivery.chat_channel import ChatChannel, InApp
from app.services.workflow.conversation_service import build_selected_workflow_data
from app.services.workflow.execution_service import WorkflowFireTimedOut, WorkflowTurnFailed
from app.services.workflow.notifications import notify_workflow_result
from app.services.workflow.queue_service import WorkflowQueueService
from app.services.workflow.service import WorkflowService
from app.services.workflow.validators import WorkflowValidator
from app.utils import auth_utils
from app.utils.errors import AppError
from app.utils.notification.orchestrator import Notified
from app.workers.config.worker_settings import WORKER_JOB_TIMEOUT_SECONDS
from app.workers.tasks.workflow_tasks import (
    AGENT_RUN_SUMMARY,
    _rate_limit_failure_content,
    execute_workflow_as_chat,
    execute_workflow_by_id,
    generate_workflow_steps,
    process_workflow_generation_task,
    regenerate_workflow_steps,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.workflows import (
    WorkflowCreated,
    WorkflowExecuted,
    WorkflowResultDelivered,
)
from shared.py.analytics.context import (
    AnalyticsContext,
    analytics_context,
    current_analytics_context,
)
from shared.py.conversation_wire import ReplyOutcome
from tests.helpers import UNKNOWN_USER_ID, users_get

USER_ID = "6812f0b3c9a14e2b7d5a91cc"


@pytest.fixture(autouse=True)
def _no_real_analytics():
    """Keep every test hermetic: WORKFLOW_CREATED events are asserted through this mock and never reach a real PostHog client."""
    with patch("app.workers.tasks.workflow_tasks.capture") as mock_capture:
        yield mock_capture


@pytest.fixture(autouse=True)
def _onboarded_user():
    """Default every test's user to a finished-onboarding one, so the system-initiated-run gate stays out of the way.

    The gate's own tests (test_workflow_tasks_onboarding_gate.py) override this.
    """
    user = UserDocument.model_validate({"onboarding": {"completed": True}})
    with patch(
        "app.workers.tasks.workflow_tasks.user_repository.get",
        AsyncMock(return_value=user),
    ):
        yield


def _make_workflow(
    workflow_id: str | None = None,
    user_id: str = USER_ID,
    title: str = "Daily Standup",
    steps: list | None = None,
    is_todo_workflow: bool = False,
    source_todo_id: str | None = None,
):
    wf = MagicMock()
    wf.id = workflow_id or str(uuid4())
    wf.user_id = user_id
    wf.title = title
    wf.description = "A test workflow"
    wf.prompt = "Run the standup"
    wf.steps = steps or [WorkflowStep(id="s1", title="Step 1", description="Do it")]
    wf.is_todo_workflow = is_todo_workflow
    wf.source_todo_id = source_todo_id
    wf.gate = None
    wf.model_dump = MagicMock(return_value={"id": wf.id, "title": wf.title})
    return wf


def _patch_scheduler(workflow=None):
    """Stand in for the process-wide workflow_scheduler singleton.

    Returns the mock plus its unstarted patcher, so callers can enter it in a
    with (...): block alongside their other patches.
    """
    scheduler = AsyncMock()
    scheduler.get_task = AsyncMock(return_value=workflow)
    return scheduler, patch(
        "app.workers.tasks.workflow_tasks.workflow_scheduler",
        scheduler,
    )


@pytest.fixture(autouse=True)
def _no_analytics():
    """Neutralize the analytics capture on workflow-conversation creation.

    The generation task creates the workflow's conversation via
    create_system_conversation, which captures chat:conversation_created
    through capture — the PostHog provider is not registered in this
    test module's import chain, so the call must be mocked.
    """
    with patch("app.services.conversation_service.capture"):
        yield


# ---------------------------------------------------------------------------
# execute_workflow_by_id
# ---------------------------------------------------------------------------


class TestExecuteWorkflowById:
    """Tests for execute_workflow_by_id."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    @pytest.fixture
    def workflow_id(self) -> str:
        return str(uuid4())

    async def test_workflow_not_found_returns_message(self, ctx, workflow_id):
        _, p_scheduler = _patch_scheduler()

        mock_create_execution = AsyncMock()
        mock_complete_execution = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                mock_create_execution,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_execution,
            ),
        ):
            result = await execute_workflow_by_id(ctx, workflow_id)

        assert f"Workflow {workflow_id} not found" in result

    async def test_successful_execution_returns_success_message(self, ctx):
        workflow = _make_workflow()

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()
        mock_execute_chat = AsyncMock(return_value=("conv_123", []))

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                mock_execute_chat,
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_exec,
            ),
        ):
            mock_wf_svc.increment_execution_count = mock_increment
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "executed successfully" in result
        assert workflow.id in result
        mock_complete_exec.assert_awaited_once()
        complete_kwargs = mock_complete_exec.call_args.kwargs
        assert complete_kwargs["conversation_id"] == "conv_123"
        assert complete_kwargs["status"] == "success"

    async def test_execution_count_incremented_on_success(self, ctx):
        workflow = _make_workflow()

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_exec,
            ),
        ):
            mock_wf_svc.increment_execution_count = mock_increment
            await execute_workflow_by_id(ctx, workflow.id)

        mock_increment.assert_awaited_once_with(workflow.id, workflow.user_id, is_successful=True)

    async def test_execution_count_incremented_as_failed_on_error(self, ctx):
        workflow = _make_workflow()

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(side_effect=RuntimeError("LLM timeout")),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_exec,
            ),
        ):
            mock_wf_svc.increment_execution_count = mock_increment
            result = await execute_workflow_by_id(ctx, workflow.id)

        mock_increment.assert_awaited_once_with(workflow.id, workflow.user_id, is_successful=False)
        assert "Error executing workflow" in result

    @pytest.mark.parametrize(
        "context,expected_trigger_type",
        [({"trigger_type": "scheduled"}, "scheduled"), (None, "manual")],
    )
    async def test_trigger_type_from_context(self, ctx, context, expected_trigger_type):
        workflow = _make_workflow()

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_exec,
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            await execute_workflow_by_id(ctx, workflow.id, context=context)

        mock_create_exec.assert_awaited_once_with(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            trigger_type=expected_trigger_type,
            execution_id=None,
        )

    async def test_shared_scheduler_survives_failed_execution(self, ctx):
        # The scheduler is a process-wide singleton owning an ARQ Redis pool.
        # Closing it per job churned thousands of pools an hour and OOM-killed
        # the worker, so a failing job must leave it open for the next one.
        workflow = _make_workflow()

        mock_scheduler, p_scheduler = _patch_scheduler(workflow)

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(side_effect=ValueError("boom")),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.notification_service"),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            await execute_workflow_by_id(ctx, workflow.id)

        mock_scheduler.close.assert_not_awaited()

    async def test_the_execution_id_a_manual_run_answers_with_is_the_one_stored(self, ctx):
        """Regression (live test): POST /execute returned exec_wf_<id>_<hex>, the run was stored as another id."""
        workflow = _make_workflow()
        queued = AsyncMock(return_value=True)
        with (
            patch.object(WorkflowService, "get_workflow", AsyncMock(return_value=workflow)),
            patch.object(WorkflowValidator, "validate_for_execution"),
            patch.object(workflow_repository, "touch", AsyncMock(return_value=True)),
            patch.object(WorkflowQueueService, "queue_workflow_execution", queued),
        ):
            answered = await WorkflowService.execute_workflow(
                workflow.id, WorkflowExecutionRequest(), workflow.user_id
            )
        _, _, job_context = queued.await_args.args
        stored = AsyncMock(side_effect=lambda document: document)

        _, p_scheduler = _patch_scheduler(workflow)
        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch.object(workflow_executions_repository, "create", stored),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks._rearm_quietly", AsyncMock()),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            await execute_workflow_by_id(ctx, workflow.id, context=job_context)

        assert [c.args[0].execution_id for c in stored.await_args_list] == [answered.execution_id]

    async def test_success_path_threads_the_exact_arguments_through(self, ctx):
        """The chat turn, the completion record and the re-arm each act on THIS run's workflow, execution id and context — a dropped, renamed or None'd value lands on the wrong conversation, the wrong execution row, or arms the wrong occurrence."""
        workflow = _make_workflow()
        execution_id = str(uuid4())
        mock_execution = MagicMock()
        mock_execution.execution_id = execution_id
        context = {"trigger_type": "manual"}

        scheduler, p_scheduler = _patch_scheduler(workflow)
        rearm = AsyncMock()
        execute_chat = AsyncMock(return_value=("conv_123", []))
        complete_exec = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                execute_chat,
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                complete_exec,
            ),
            patch("app.workers.tasks.workflow_tasks._rearm_quietly", rearm),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id, context=context)

        assert "executed successfully" in result
        assert execute_chat.await_args.args == (
            workflow,
            AuthenticatedUser(user_id=workflow.user_id),
            context,
        )
        complete_exec.assert_awaited_once_with(
            execution_id=execution_id,
            status="success",
            summary=AGENT_RUN_SUMMARY,
            conversation_id="conv_123",
            trace=[],
        )
        rearm.assert_awaited_once_with(scheduler, workflow, "manual", workflow.id)

    async def test_failure_path_records_and_rearms_with_the_exact_arguments(self, ctx):
        """A failed run must still close THIS execution row and arm the SAME occurrence the success path would have — a None'd id strands an open execution record or silently kills the recurrence."""
        workflow = _make_workflow()
        execution_id = str(uuid4())
        mock_execution = MagicMock()
        mock_execution.execution_id = execution_id
        context = {"trigger_type": "manual"}
        error = ValueError("boom")

        scheduler, p_scheduler = _patch_scheduler(workflow)
        rearm = AsyncMock()
        record_failure = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(side_effect=error),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks._record_execution_failure",
                record_failure,
            ),
            patch("app.workers.tasks.workflow_tasks._rearm_quietly", rearm),
        ):
            result = await execute_workflow_by_id(ctx, workflow.id, context=context)

        assert "Error executing workflow" in result
        record_failure.assert_awaited_once_with(
            error, workflow, workflow.id, execution_id, record=None
        )
        rearm.assert_awaited_once_with(scheduler, workflow, "manual", workflow.id)

    async def test_scheduled_execution_captures_workflow_executed(self, ctx, _no_real_analytics):
        workflow = _make_workflow()
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(
                ctx, workflow.id, context={"trigger_type": "schedule"}
            )

        assert "executed successfully" in result
        _no_real_analytics.assert_called_once_with(
            UserId(workflow.user_id),
            WorkflowExecuted(workflow_id=workflow.id, trigger_type="schedule"),
        )

    async def test_integration_execution_captures_workflow_executed(self, ctx, _no_real_analytics):
        # Integration triggers pass only ``trigger_data`` — no trigger_type —
        # so the event must derive its source instead of reading "manual".
        workflow = _make_workflow()
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(
                ctx, workflow.id, context={"trigger_data": {"message_id": "m1"}}
            )

        assert "executed successfully" in result
        _no_real_analytics.assert_called_once_with(
            UserId(workflow.user_id),
            WorkflowExecuted(workflow_id=workflow.id, trigger_type="integration"),
        )

    async def test_explicit_trigger_type_wins_over_trigger_data(self, ctx, _no_real_analytics):
        # Integration detection requires trigger_type to be ABSENT — a context
        # carrying both must stay on its explicit trigger, not flip to
        # "integration".
        workflow = _make_workflow()
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(
                ctx,
                workflow.id,
                context={
                    "trigger_type": "schedule",
                    "trigger_data": {"message_id": "m1"},
                },
            )

        assert "executed successfully" in result
        _no_real_analytics.assert_called_once_with(
            UserId(workflow.user_id),
            WorkflowExecuted(workflow_id=workflow.id, trigger_type="schedule"),
        )

    async def test_manual_execution_does_not_capture_workflow_executed(
        self, ctx, _no_real_analytics
    ):
        # Manual runs are captured by the run-now endpoint at queue time, so
        # the worker must not emit a duplicate event for them.
        workflow = _make_workflow()
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        _, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "executed successfully" in result
        _no_real_analytics.assert_not_called()


class TestAWorkflowWhoseOwnerIsNotAUser:
    """Regression: a workflow owned by "system" fired as a user fabricated from the bare id."""

    @pytest.mark.regression
    @pytest.mark.parametrize("owner", [SYSTEM_USER_ID, UNKNOWN_USER_ID])
    async def test_it_is_deactivated_and_never_run(
        self, owner: str, _no_real_analytics: MagicMock
    ) -> None:
        workflow = _make_workflow(user_id=owner)
        _, p_scheduler = _patch_scheduler(workflow)
        execute_chat = AsyncMock(return_value=("conv_1", []))
        create_exec = AsyncMock()
        paid = AsyncMock(return_value=True)

        with (
            p_scheduler,
            patch("app.workers.tasks.workflow_tasks.require_owner", auth_utils.require_owner),
            patch("app.workers.tasks.workflow_tasks.user_repository.get", users_get),
            patch("app.workers.tasks.workflow_tasks.is_paid", paid),
            patch("app.workers.tasks.workflow_tasks.execute_workflow_as_chat", execute_chat),
            patch("app.workers.tasks.workflow_tasks.create_execution", create_exec),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as service,
        ):
            service.deactivate_workflow = AsyncMock()
            with patch("app.workers.tasks.workflow_tasks.log") as log_mock:
                result = await execute_workflow_by_id({}, workflow.id)

        assert result == f"Workflow {workflow.id} retired: its owner is not a user"
        log_mock.error.assert_called_once_with(
            f"{LogTag.WORKER} Workflow owner is not a user; deactivating it",
            workflow_id=workflow.id,
            user_id=owner,
            error="The owner is not a GAIA user",
        )
        execute_chat.assert_not_awaited()
        create_exec.assert_not_awaited()
        paid.assert_not_awaited()
        _no_real_analytics.assert_not_called()
        service.deactivate_workflow.assert_awaited_once_with(
            workflow.id, owner, reason=DeactivationReason.OWNER_NOT_FOUND
        )

    async def test_a_real_owner_still_runs(self) -> None:
        workflow = _make_workflow(user_id="64abc123def4567890abcdef")
        _, p_scheduler = _patch_scheduler(workflow)
        execute_chat = AsyncMock(return_value=("conv_1", []))

        with (
            p_scheduler,
            patch("app.workers.tasks.workflow_tasks.require_owner", auth_utils.require_owner),
            patch("app.workers.tasks.workflow_tasks.user_repository.get", users_get),
            patch("app.workers.tasks.workflow_tasks.execute_workflow_as_chat", execute_chat),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=MagicMock(execution_id="exec_1")),
            ),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as service,
        ):
            service.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id({}, workflow.id)

        assert "executed successfully" in result
        execute_chat.assert_awaited_once()
        assert execute_chat.await_args.args[1].user_id == workflow.user_id


# ---------------------------------------------------------------------------
# process_workflow_generation_task
# ---------------------------------------------------------------------------


class TestProcessWorkflowGenerationTask:
    """Tests for process_workflow_generation_task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_successful_generation_returns_success_message(self, ctx, _no_real_analytics):
        # Must be a valid 24-char hex ObjectId string because production code
        # calls ObjectId(todo_id) before the mocked update_one is invoked.
        todo_id = "507f1f77bcf86cd799439011"
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)

        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_repo.link_workflow = AsyncMock(return_value=mock_todo_result)

            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            result = await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", "Get milk and eggs"
            )

        assert "Successfully generated standalone workflow" in result
        assert workflow.id in result
        assert todo_id in result
        mock_repo.link_workflow.assert_awaited_once_with(
            todo_id, user_id=user_id, workflow_id=workflow.id
        )

        _no_real_analytics.assert_called_once()
        assert _no_real_analytics.call_args.args == (
            UserId(user_id),
            WorkflowCreated(
                origin="todo_requested",
                workflow_id=workflow.id,
                steps_count=len(workflow.steps),
                is_todo_workflow=True,
            ),
        )

    async def test_workflow_creation_returns_none_raises(self, ctx):
        todo_id = str(uuid4())
        user_id = USER_ID

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=None)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="Workflow generation failed"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

    async def test_todo_not_updated_raises(self, ctx):
        # Must be a valid 24-char hex ObjectId string because production code
        # calls ObjectId(todo_id) before the mocked update_one is invoked.
        todo_id = "507f1f77bcf86cd799439012"
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_wf_svc.delete_workflow = AsyncMock(return_value=True)
            mock_repo.link_workflow = AsyncMock(return_value=None)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="not found or not updated") as refused:
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

        assert refused.value.why == "the todo was deleted, or is tracked and never links a workflow"
        # A refused link (deleted or tracked todo) must not leave an orphan "Todo:" workflow.
        mock_wf_svc.delete_workflow.assert_awaited_once_with(workflow.id, user_id)

    async def test_websocket_failure_event_sent_on_exception(self, ctx):
        todo_id = str(ObjectId())
        user_id = USER_ID

        mock_ws = AsyncMock()
        mock_ws.broadcast_to_user = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=RuntimeError("DB error"))

            with pytest.raises(RuntimeError):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

        mock_ws.broadcast_to_user.assert_awaited()
        call_args = mock_ws.broadcast_to_user.call_args
        payload = call_args[0][1]
        assert payload["type"] == "workflow.generation_failed"
        assert payload["todo_id"] == todo_id

    async def test_empty_description_uses_no_details_section(self, ctx):
        """When description is empty the prompt template omits the details section."""
        # Must be a valid 24-char hex ObjectId string because production code
        # calls ObjectId(todo_id) before the mocked update_one is invoked.
        todo_id = "507f1f77bcf86cd799439013"
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)
        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        captured_requests = []

        async def capture_create(request, uid, **kwargs):
            captured_requests.append(request)
            return workflow

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=capture_create)
            mock_repo.link_workflow = AsyncMock(return_value=mock_todo_result)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            await process_workflow_generation_task(ctx, todo_id, user_id, "Buy groceries")

        assert len(captured_requests) == 1
        # The **Details:** section should be absent when the (default) description is empty
        assert "**Details:**" not in captured_requests[0].prompt


# ---------------------------------------------------------------------------
# regenerate_workflow_steps
# ---------------------------------------------------------------------------


class TestRegenerateWorkflowSteps:
    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_successful_regeneration_returns_success(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            result = await regenerate_workflow_steps(ctx, workflow_id, user_id, "Steps were wrong")

        assert "Successfully regenerated steps" in result
        assert workflow_id in result

    async def test_exception_propagates(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock(
                side_effect=RuntimeError("Service down")
            )
            with pytest.raises(RuntimeError, match="Service down"):
                await regenerate_workflow_steps(ctx, workflow_id, user_id, "reason")

    async def test_force_different_tools_default_is_true(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            await regenerate_workflow_steps(ctx, workflow_id, user_id, "reason")

        mock_wf_svc.regenerate_workflow_steps.assert_awaited_once_with(
            workflow_id, user_id, "reason", True
        )


# ---------------------------------------------------------------------------
# generate_workflow_steps
# ---------------------------------------------------------------------------


class TestGenerateWorkflowSteps:
    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_successful_generation_returns_success(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID
        workflow = _make_workflow(workflow_id=workflow_id, is_todo_workflow=False)

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            result = await generate_workflow_steps(ctx, workflow_id, user_id)

        assert "Successfully generated steps" in result
        assert workflow_id in result

    async def test_todo_workflow_sends_websocket_event(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID
        todo_id = str(uuid4())
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=True,
            source_todo_id=todo_id,
        )

        mock_ws = AsyncMock()
        mock_ws.broadcast_to_user = AsyncMock()

        with (
            patch("app.services.workflow.service.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            await generate_workflow_steps(ctx, workflow_id, user_id)

        mock_ws.broadcast_to_user.assert_awaited_once()
        payload = mock_ws.broadcast_to_user.call_args[0][1]
        assert payload["type"] == "workflow.generated"
        assert payload["todo_id"] == todo_id

    async def test_non_todo_workflow_does_not_send_websocket(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=False,
            source_todo_id=None,
        )

        mock_ws = AsyncMock()
        mock_ws.broadcast_to_user = AsyncMock()

        with (
            patch("app.services.workflow.service.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            await generate_workflow_steps(ctx, workflow_id, user_id)

        mock_ws.broadcast_to_user.assert_not_awaited()

    async def test_exception_propagates(self, ctx):
        workflow_id = str(uuid4())
        user_id = USER_ID

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc._generate_workflow_steps = AsyncMock(side_effect=RuntimeError("LLM error"))

            with pytest.raises(RuntimeError, match="LLM error"):
                await generate_workflow_steps(ctx, workflow_id, user_id)


# ---------------------------------------------------------------------------
# execute_workflow_as_chat
# ---------------------------------------------------------------------------


class TestExecuteWorkflowAsChat:
    """execute_workflow_as_chat appends the fire, waits for its outcome off the log, and delivers it.

    Boundaries replaced: the conversation lookup, the thread reset (proven in
    test_thread_reset.py), the log append and the outcome wait (the real ones run in
    test_conversation_runtime_real.py), the run record and the chat-app delivery.
    """

    @pytest.fixture(autouse=True)
    def boundaries(self):
        with ExitStack() as stack:
            mocks = {
                name: stack.enter_context(
                    patch(f"app.workers.tasks.workflow_tasks.{name}", new_callable=AsyncMock)
                )
                for name in (
                    "get_or_create_workflow_conversation",
                    "accept",
                    "await_outcome",
                    "seed_run_record",
                    "read_run_record",
                    "_notify_run_finished",
                )
            }
            stack.enter_context(patch("app.workers.tasks.workflow_tasks.runtime_ports"))
            mocks["get_or_create_workflow_conversation"].return_value = "conv_wf"
            mocks["read_run_record"].return_value = [RecordedCall(tool_name="GMAIL_FETCH")]
            mocks["await_outcome"].return_value = EntryOutcome(
                settled=_answered("workflow:exec_1"), reply=_shown("Your brief"), work=()
            )
            yield mocks

    def _make_workflow(self) -> MagicMock:
        wf = MagicMock()
        wf.id = "wf_morning"
        wf.user_id = USER_ID
        wf.title = "Morning Briefing"
        wf.description = "Daily morning workflow"
        wf.prompt = "Run the morning briefing"
        wf.notify_on_completion = True
        wf.steps = [WorkflowStep(id="s1", title="Step 1", description="Check mail")]
        wf.trigger_config.timezone = None
        return wf

    async def _run(self, context: dict[str, object] | None = None) -> tuple[str, list]:
        return await execute_workflow_as_chat(
            self._make_workflow(),
            AuthenticatedUser(user_id=USER_ID, timezone="Europe/Paris"),
            context or {},
            execution_id="exec_1",
        )

    async def test_the_fire_is_logged_with_everything_its_turn_needs(self, boundaries) -> None:
        await self._run({"type": "gmail", "workflow_notify_on_completion": False})
        boundaries["get_or_create_workflow_conversation"].assert_awaited_once_with(
            workflow_id="wf_morning", user_id=USER_ID, workflow_title="Morning Briefing"
        )
        assert boundaries["accept"].await_args.args[1:3] == ("conv_wf", USER_ID)
        fired: WorkflowFired = boundaries["accept"].await_args.args[3]
        assert fired.id == "workflow:exec_1"
        assert fired.run.workflow == build_selected_workflow_data(self._make_workflow())
        assert (fired.run.execution_id, fired.run.timezone) == ("exec_1", "Europe/Paris")
        assert (fired.run.trigger.type, fired.run.trigger.workflow_id) == ("gmail", "wf_morning")
        # A caller that fires quietly lowers the workflow's own default.
        assert fired.run.trigger.workflow_notify_on_completion is False

    async def test_the_record_is_seeded_before_the_fire(self, boundaries) -> None:
        order = MagicMock()
        for name in ("seed_run_record", "accept"):
            order.attach_mock(boundaries[name], name)
        await execute_workflow_as_chat(
            self._make_workflow(),
            AuthenticatedUser(user_id=USER_ID),
            {},
            execution_id="exec_1",
            replayed=[RecordedCall(tool_name="REPLAYED")],
        )
        assert [c[0] for c in order.mock_calls] == ["seed_run_record", "accept"]
        boundaries["seed_run_record"].assert_awaited_once_with(
            "exec_1", [RecordedCall(tool_name="REPLAYED")]
        )

    async def test_a_finished_run_returns_its_record_and_delivers_its_answer(
        self, boundaries
    ) -> None:
        conversation_id, trace = await self._run()
        assert (conversation_id, trace) == ("conv_wf", [RecordedCall(tool_name="GMAIL_FETCH")])
        boundaries["read_run_record"].assert_awaited_once_with("exec_1")
        delivered = boundaries["_notify_run_finished"].await_args
        assert delivered.args[1:] == ("exec_1", "conv_wf", "Your brief")
        assert delivered.kwargs == {"notify_on_completion": True}

    async def test_a_silent_run_delivers_nothing(self, boundaries) -> None:
        boundaries["await_outcome"].return_value = EntryOutcome(
            settled=_answered("workflow:exec_1", ReplyOutcome.SILENT), reply=_shown(""), work=()
        )
        await self._run()
        boundaries["_notify_run_finished"].assert_not_awaited()

    async def test_a_run_whose_work_failed_raises_with_its_record_and_delivers_nothing(
        self, boundaries
    ) -> None:
        failed = WorkFinished(id="f", task_id="t1", outcome=WorkOutcome.FAILED, report="down")
        boundaries["await_outcome"].return_value = EntryOutcome(
            settled=_answered("workflow:exec_1"), reply=_shown("It failed"), work=(failed,)
        )
        with pytest.raises(WorkflowTurnFailed, match="work failed") as raised:
            await self._run()
        assert (raised.value.conversation_id, raised.value.trace) == (
            "conv_wf",
            [RecordedCall(tool_name="GMAIL_FETCH")],
        )
        boundaries["_notify_run_finished"].assert_not_awaited()

    async def test_a_record_that_cannot_be_read_leaves_the_finished_run_finished(
        self, boundaries
    ) -> None:
        boundaries["read_run_record"].side_effect = ConnectionError("redis down")
        with patch("app.workers.tasks.workflow_tasks.log") as log:
            conversation_id, trace = await self._run()
        assert (conversation_id, trace) == ("conv_wf", [])
        assert log.error.call_args.args == ("[WORKER] workflow run record could not be read",)


def _answered(entry_id: str, outcome: ReplyOutcome = ReplyOutcome.ANSWERED) -> ReplySettled:
    return ReplySettled(
        id="settled",
        reply_id="r1",
        outcome=outcome,
        answers=(entry_id,),
        through=1,
        quote_target=None,
    )


def _shown(text: str) -> Reply:
    return Reply(id="reply", reply_id="r1", attempt_id="a1", text=text)


# ---------------------------------------------------------------------------
# workflow notification senders (app.services.workflow.notifications)
# ---------------------------------------------------------------------------


class TestWorkflowNotificationSenders:
    """Tests for the workflow completion/failure notification senders."""

    async def test_a_run_result_is_one_notification_keyed_by_its_execution(self) -> None:
        """The inbox gets a short heads-up with a link; a chat app gets the result itself."""
        with (
            patch(
                "app.services.workflow.notifications.notification_service",
            ) as mock_notif,
            patch("app.services.workflow.notifications.capture"),
        ):
            mock_notif.notify = AsyncMock(
                return_value=Notified(record=MagicMock(channels=[]), target=None)
            )
            await notify_workflow_result(
                workflow_id="wf_1",
                workflow_title="Morning Briefing",
                execution_id="exec_9",
                conversation_id="conv_xyz",
                user_id=USER_ID,
                result_text="Three meetings today.",
            )

        (notif_req,) = mock_notif.notify.call_args.args
        assert notif_req.id == notification_id(USER_ID, "workflow_result", "exec_9")
        # Human copy: phrasing rotates, but the workflow name is woven into the title.
        assert "Morning Briefing" in notif_req.content.title
        assert notif_req.content.body
        assert notif_req.message == "Three meetings today."
        # Routed by the pipeline, not pinned to the inbox.
        assert notif_req.channels == []
        assert notif_req.type is NotificationType.SUCCESS
        (action,) = notif_req.content.actions
        expected_action = NotificationAction(
            type=ActionType.REDIRECT,
            label="View Results",
            style=ActionStyle.PRIMARY,
            config=ActionConfig(
                redirect=RedirectConfig(
                    url="/c/conv_xyz", open_in_new_tab=False, close_notification=True
                )
            ),
        )
        assert action.model_dump(exclude={"id"}) == expected_action.model_dump(exclude={"id"})
        assert notif_req.metadata == {
            "workflow_id": "wf_1",
            "conversation_id": "conv_xyz",
        }

    @pytest.mark.parametrize(
        ("status", "channels", "target", "expected"),
        [
            (
                NotificationStatus.DELIVERED,
                [
                    ChannelDeliveryStatus(
                        channel_type="telegram", status=NotificationStatus.DELIVERED
                    )
                ],
                ChatChannel(
                    source=ConversationSource.TELEGRAM,
                    platform_user_id="tg-1",
                    basis="recent_activity",
                ),
                WorkflowResultDelivered(
                    workflow_id="wf_1",
                    outcome="delivered",
                    platform="telegram",
                    destination="chat_app",
                    destination_basis="recent_activity",
                ),
            ),
            (
                NotificationStatus.PENDING,
                [],
                InApp(reason="no_chat_app"),
                WorkflowResultDelivered(
                    workflow_id="wf_1",
                    outcome="undelivered",
                    platform=None,
                    destination="in_app",
                    destination_basis="no_chat_app",
                ),
            ),
        ],
        ids=["chat-app", "inbox"],
    )
    async def test_the_delivery_is_counted_once_with_where_it_landed(
        self,
        status: NotificationStatus,
        channels: list[ChannelDeliveryStatus],
        target: ChatChannel | InApp,
        expected: WorkflowResultDelivered,
    ) -> None:
        record = MagicMock(status=status, channels=channels)
        with (
            patch("app.services.workflow.notifications.notification_service") as mock_notif,
            patch("app.services.workflow.notifications.capture") as capture,
        ):
            mock_notif.notify = AsyncMock(return_value=Notified(record=record, target=target))
            await notify_workflow_result(
                workflow_id="wf_1",
                workflow_title="Morning Briefing",
                execution_id="exec_9",
                conversation_id="conv_xyz",
                user_id=USER_ID,
                result_text="Three meetings today.",
            )

        capture.assert_called_once_with(UserId(USER_ID), expected)


# ---------------------------------------------------------------------------
# execute_workflow_by_id — additional coverage for error notification branches
# ---------------------------------------------------------------------------


class TestExecuteWorkflowByIdNotifications:
    """Additional tests covering the error notification branches in execute_workflow_by_id."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    def _make_error_patches(self, workflow, error):
        """Build the common with-block patches for an error scenario.

        Returns individual patch objects so they can be used in a with (...):
        block without needing iterable unpacking.
        """
        _, p_scheduler = _patch_scheduler(workflow)

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        p_chat = patch(
            "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
            AsyncMock(side_effect=error),
        )
        p_create = patch(
            "app.workers.tasks.workflow_tasks.create_execution",
            AsyncMock(return_value=mock_execution),
        )
        p_complete = patch(
            "app.workers.tasks.workflow_tasks.complete_execution",
            AsyncMock(),
        )
        return p_scheduler, p_chat, p_create, p_complete

    async def test_rate_limit_with_reset_time_sends_upgrade_notification(self, ctx):
        """RateLimitExceededException with reset_time sends a notification mentioning when the limit resets and prompting upgrade."""
        workflow = _make_workflow()
        reset_time = datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC)
        error = RateLimitExceededException(
            feature="trigger_workflow_executions",
            plan_required="pro",
            reset_time=reset_time,
        )

        p_sched, p_chat, p_create, p_complete = self._make_error_patches(workflow, error)

        with (
            p_sched,
            p_chat,
            p_create,
            p_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ) as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        mock_notif.notify.assert_awaited_once()
        notif_req = mock_notif.notify.call_args[0][0]
        assert "Resets" in notif_req.content.body
        assert "Upgrade to Pro" in notif_req.content.body
        # Should include an upgrade action
        assert notif_req.content.actions is not None
        assert len(notif_req.content.actions) == 1
        assert "Upgrade" in notif_req.content.actions[0].label

    async def test_rate_limit_without_reset_time_sends_plan_gated_notification(self, ctx):
        """RateLimitExceededException without reset_time sends a plan-gated message."""
        workflow = _make_workflow()
        error = RateLimitExceededException(
            feature="trigger_workflow_executions",
            plan_required="pro",
        )

        p_sched, p_chat, p_create, p_complete = self._make_error_patches(workflow, error)

        with (
            p_sched,
            p_chat,
            p_create,
            p_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ) as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        notif_req = mock_notif.notify.call_args[0][0]
        assert "not available on your current plan" in notif_req.content.body
        assert "Upgrade to Pro" in notif_req.content.body

    async def test_rate_limit_with_invalid_reset_time_format_falls_back(self, ctx):
        """When reset_time string in the detail dict is unparseable, the fallback body is used (no Resets line)."""
        workflow = _make_workflow()
        # Create a RateLimitExceededException and manually set an invalid reset_time
        error = RateLimitExceededException(
            feature="trigger_workflow_executions",
            plan_required="pro",
        )
        # Manually inject an invalid reset_time string into the detail dict
        error.detail["reset_time"] = "not-a-valid-date"

        p_sched, p_chat, p_create, p_complete = self._make_error_patches(workflow, error)

        with (
            p_sched,
            p_chat,
            p_create,
            p_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ) as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        notif_req = mock_notif.notify.call_args[0][0]
        # Falls back to the version without the reset time formatting
        assert "You've used all your workflow executions" in notif_req.content.body

    async def test_generic_error_sends_plain_failure_notification(self, ctx):
        """Non-rate-limit errors produce a plain failure notification."""
        workflow = _make_workflow()
        error = ValueError("Something broke")

        p_sched, p_chat, p_create, p_complete = self._make_error_patches(workflow, error)

        with (
            p_sched,
            p_chat,
            p_create,
            p_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ) as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        notif_req = mock_notif.notify.call_args[0][0]
        assert "encountered an error" in notif_req.content.body
        # No upgrade action for generic errors
        assert notif_req.content.actions is None

    async def test_a_run_that_did_not_complete_is_recorded_failed_and_notified_once(self, ctx):
        workflow = _make_workflow()
        error = WorkflowTurnFailed("work failed", conversation_id="conv_wf", trace=[])
        p_sched, p_chat, p_create, p_complete = self._make_error_patches(workflow, error)
        with (
            p_sched,
            p_chat,
            p_create,
            p_complete as complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            await execute_workflow_by_id(ctx, workflow.id)
        mock_notif.notify.assert_awaited_once()
        assert mock_notif.notify.call_args[0][0].source == (NotificationSourceEnum.WORKFLOW_FAILED)
        assert complete.await_args.kwargs["status"] == "failed"
        assert complete.await_args.kwargs["conversation_id"] == "conv_wf"
        mock_wf_svc.increment_execution_count.assert_awaited_once_with(
            workflow.id, workflow.user_id, is_successful=False
        )

    async def test_notification_failure_during_error_is_swallowed(self, ctx):
        """If notification_service.notify fails during error handling, the exception is swallowed and the error result is still returned."""
        workflow = _make_workflow()
        error = ValueError("Original error")

        p_sched, p_chat, p_create, p_complete = self._make_error_patches(workflow, error)

        with (
            p_sched,
            p_chat,
            p_create,
            p_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ) as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock(side_effect=RuntimeError("Notification service down"))
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result

    async def test_complete_execution_failure_during_error_is_swallowed(self, ctx):
        """If complete_execution fails during error handling, it doesn't crash."""
        workflow = _make_workflow()

        _, p_scheduler = _patch_scheduler(workflow)

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(side_effect=RuntimeError("LLM crash")),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(side_effect=RuntimeError("DB write failure")),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result

    async def test_increment_execution_count_failure_during_error_is_swallowed(self, ctx):
        """If increment_execution_count fails during error handling, it doesn't crash."""
        workflow = _make_workflow()

        _, p_scheduler = _patch_scheduler(workflow)

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(side_effect=RuntimeError("LLM crash")),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                AsyncMock(),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock(
                side_effect=RuntimeError("Stats DB down")
            )
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result

    async def test_no_execution_id_skips_complete_execution_on_error(self, ctx):
        """When create_execution itself fails, execution_id is None and complete_execution is not called."""
        workflow = _make_workflow()

        _, p_scheduler = _patch_scheduler(workflow)

        mock_complete_exec = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(side_effect=RuntimeError("DB unavailable")),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_exec,
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.notify = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        # complete_execution should NOT have been called since execution_id is None
        mock_complete_exec.assert_not_awaited()

    async def test_conversation_id_and_trace_passed_to_complete_execution(self, ctx):
        """The conversation id and recorded trace from execute_workflow_as_chat are forwarded to complete_execution — the trace is what the next run reads."""
        workflow = _make_workflow()

        _, p_scheduler = _patch_scheduler(workflow)

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())
        recorded_call = RecordedCall(tool_name="GMAIL_FETCH", args={"query": "is:unread"})

        mock_complete_exec = AsyncMock()

        with (
            p_scheduler,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=("conv_123", [recorded_call])),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                mock_complete_exec,
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "executed successfully" in result
        mock_complete_exec.assert_awaited_once()
        call_kwargs = mock_complete_exec.call_args.kwargs
        assert call_kwargs["conversation_id"] == "conv_123"
        assert call_kwargs["trace"] == [recorded_call]


# ---------------------------------------------------------------------------
# process_workflow_generation_task — additional coverage
# ---------------------------------------------------------------------------


class TestProcessWorkflowGenerationTaskAdditional:
    """Additional edge-case tests for process_workflow_generation_task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_workflow_created_with_no_steps_raises_app_error(self, ctx):
        """If workflow is created but has zero steps, an AppError is raised."""
        todo_id = str(ObjectId())
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)
        # Override steps to empty list directly (the helper uses `or` which
        # would replace [] with a default step)
        workflow.steps = []
        workflow.error_message = "LLM returned empty plan"

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="has no steps"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Empty Workflow")

    async def test_workflow_created_no_steps_error_message_none(self, ctx):
        """If workflow has no steps and error_message is None, 'unknown error' is used."""
        todo_id = str(ObjectId())
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)
        workflow.steps = []
        workflow.error_message = None

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="unknown error"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "No Steps")

    async def test_websocket_broadcast_failure_on_success_does_not_raise(self, ctx):
        """When the websocket broadcast fails during the success path, the function still returns success."""
        todo_id = "507f1f77bcf86cd799439014"
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)

        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        mock_ws = MagicMock()
        mock_ws.broadcast_to_user = AsyncMock(side_effect=RuntimeError("WebSocket error"))

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_repo.link_workflow = AsyncMock(return_value=mock_todo_result)

            result = await process_workflow_generation_task(ctx, todo_id, user_id, "Test Todo")

        assert "Successfully generated" in result

    async def test_clear_flag_failure_on_exception_does_not_mask_error(self, ctx):
        """When clear_workflow_generating_flag fails during exception handling, the original exception is still raised."""
        todo_id = str(ObjectId())
        user_id = USER_ID

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(side_effect=RuntimeError("Redis down")),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=ValueError("Original error"))
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(ValueError, match="Original error"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Failing Todo")

    async def test_websocket_failure_event_broadcast_fails_gracefully(self, ctx):
        """When the failure websocket broadcast itself fails, the original exception is still raised."""
        todo_id = str(ObjectId())
        user_id = USER_ID

        mock_ws = MagicMock()
        mock_ws.broadcast_to_user = AsyncMock(side_effect=RuntimeError("WS broadcast error"))

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=RuntimeError("DB error"))

            with pytest.raises(RuntimeError, match="DB error"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

    async def test_description_with_content_includes_details_section(self, ctx):
        """When description is provided, the prompt contains a **Details:** section."""
        todo_id = "507f1f77bcf86cd799439015"
        user_id = USER_ID
        workflow = _make_workflow(user_id=user_id)

        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        captured_requests = []

        async def capture_create(request, uid, **kwargs):
            captured_requests.append(request)
            return workflow

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=capture_create)
            mock_repo.link_workflow = AsyncMock(return_value=mock_todo_result)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            await process_workflow_generation_task(
                ctx,
                todo_id,
                user_id,
                "Buy groceries",
                description="Milk, eggs, bread",
            )

        assert len(captured_requests) == 1
        assert "**Details:** Milk, eggs, bread" in captured_requests[0].prompt

    async def test_workflow_with_no_id_raises(self, ctx):
        """If workflow.id is falsy after creation, it raises AppError."""
        todo_id = str(ObjectId())
        user_id = USER_ID
        workflow = MagicMock()
        workflow.id = None

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="Workflow generation failed"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")


# ---------------------------------------------------------------------------
# generate_workflow_steps — additional coverage
# ---------------------------------------------------------------------------


class TestGenerateWorkflowStepsAdditional:
    """Additional tests for generate_workflow_steps."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_get_workflow_returns_none_no_websocket_sent(self, ctx):
        """When get_workflow returns None, no websocket event is sent."""
        workflow_id = str(uuid4())
        user_id = USER_ID

        mock_ws = AsyncMock()
        mock_ws.broadcast_to_user = AsyncMock()

        with (
            patch("app.services.workflow.service.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=None)

            result = await generate_workflow_steps(ctx, workflow_id, user_id)

        assert "Successfully generated steps" in result
        mock_ws.broadcast_to_user.assert_not_awaited()

    async def test_todo_workflow_without_source_todo_id_no_websocket(self, ctx):
        """A todo workflow with source_todo_id=None does not trigger websocket."""
        workflow_id = str(uuid4())
        user_id = USER_ID
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=True,
            source_todo_id=None,
        )

        mock_ws = AsyncMock()
        mock_ws.broadcast_to_user = AsyncMock()

        with (
            patch("app.services.workflow.service.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            result = await generate_workflow_steps(ctx, workflow_id, user_id)

        assert "Successfully generated steps" in result
        mock_ws.broadcast_to_user.assert_not_awaited()

    async def test_websocket_failure_on_todo_workflow_does_not_raise(self, ctx):
        """When the WebSocket broadcast fails for a todo workflow, the function still returns success."""
        workflow_id = str(uuid4())
        user_id = USER_ID
        todo_id = str(uuid4())
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=True,
            source_todo_id=todo_id,
        )

        mock_ws = AsyncMock()
        mock_ws.broadcast_to_user = AsyncMock(side_effect=RuntimeError("WS error"))

        with (
            patch("app.services.workflow.service.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            result = await generate_workflow_steps(ctx, workflow_id, user_id)

        assert "Successfully generated steps" in result


# ---------------------------------------------------------------------------
# regenerate_workflow_steps — additional coverage
# ---------------------------------------------------------------------------


class TestRegenerateWorkflowStepsAdditional:
    """Additional tests for regenerate_workflow_steps."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_force_different_tools_false_passed_through(self, ctx):
        """When force_different_tools=False, the service gets False."""
        workflow_id = str(uuid4())
        user_id = USER_ID

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            await regenerate_workflow_steps(
                ctx, workflow_id, user_id, "reason", force_different_tools=False
            )

        mock_wf_svc.regenerate_workflow_steps.assert_awaited_once_with(
            workflow_id, user_id, "reason", False
        )


MODULE = "app.workers.tasks.workflow_tasks"
EXECUTION_SERVICE = "app.services.workflow.execution_service"

#: A fixed occurrence stamp, so the claim a scheduled fire makes is assertable.
SCHEDULED_FOR = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)

#: The trigger context of a fire the scheduler armed.
SCHEDULED_FIRE = {
    "trigger_type": TriggerType.SCHEDULE.value,
    "scheduled_for": SCHEDULED_FOR.timestamp(),
}


class _FirePatches:
    """Every I/O edge one execute_workflow_by_id fire touches, mocked.

    The by-id task is the only place several ids are threaded together (the
    batch key, the claim, the cost wall, the counters), so these tests assert
    the exact arguments each edge received rather than that it was called.
    """

    def __init__(self, workflow) -> None:
        self.workflow = workflow
        self.scheduler = AsyncMock()
        self.scheduler.get_task = AsyncMock(return_value=workflow)
        self.execution = MagicMock()
        self.execution.execution_id = "exec_1"
        self.complete_execution = AsyncMock()
        self.create_execution = AsyncMock(return_value=self.execution)
        self.increment = AsyncMock()
        self.chat = AsyncMock(return_value=("conv_1", []))
        self.cost_budget = AsyncMock()
        self.drain = AsyncMock(return_value=[{"event": "one"}])
        self.reschedule = AsyncMock()
        self.coalesce = MagicMock(return_value=30)
        self.distrust = AsyncMock()
        self.record_run_outcome = AsyncMock(return_value=None)
        self.notify = AsyncMock()
        self.log = MagicMock()

    def enter(self, stack) -> None:
        for patcher in (
            patch(f"{MODULE}.workflow_scheduler", self.scheduler),
            patch(f"{MODULE}.create_execution", self.create_execution),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            # A fire that never ran is recorded through execution_service's own helper.
            patch(f"{EXECUTION_SERVICE}.create_execution", self.create_execution),
            patch(f"{EXECUTION_SERVICE}.complete_execution", self.complete_execution),
            patch(
                f"{MODULE}.WorkflowService",
                MagicMock(increment_execution_count=self.increment),
            ),
            patch(f"{MODULE}.execute_workflow_as_chat", self.chat),
            patch(f"{MODULE}.enforce_cost_budget", self.cost_budget),
            patch(f"{MODULE}.drain_trigger_batch", self.drain),
            patch(f"{MODULE}.reschedule_if_refilled", self.reschedule),
            patch(f"{MODULE}.coalesce_window_seconds", self.coalesce),
            patch(f"{MODULE}.distrust_fresh_playbook", self.distrust),
            patch(f"{MODULE}.playbook_repository.record_run_outcome", self.record_run_outcome),
            patch(f"{MODULE}.notification_service.notify", self.notify),
            patch(f"{MODULE}.log", self.log),
        ):
            stack.enter_context(patcher)


class TestTheByIdTaskThreadsItsIdsThrough:
    """One fire touches five collaborators, each keyed on an id it was handed.

    A blanked or swapped id books this run against the wrong thing, which is worse than not booking
    it: nothing goes looking for wrong data.
    """

    async def test_the_workflow_is_fetched_by_the_id_the_task_was_given(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            result = await execute_workflow_by_id({}, workflow.id)

        seams.scheduler.get_task.assert_awaited_once_with(workflow.id)
        seams.log.info.assert_any_call(
            "[WORKER] Processing workflow execution", workflow_id=workflow.id
        )
        assert "executed successfully" in result

    async def test_a_workflow_that_is_gone_stops_the_fire_before_any_work(self):
        seams = _FirePatches(None)
        missing_id = str(uuid4())

        with ExitStack() as stack:
            seams.enter(stack)
            result = await execute_workflow_by_id({}, missing_id)

        assert result == f"Workflow {missing_id} not found"
        seams.complete_execution.assert_not_awaited()
        seams.chat.assert_not_awaited()

    async def test_the_daily_cost_wall_is_checked_for_this_user_and_feature(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id)

        assert seams.cost_budget.await_args_list == [
            call(workflow.user_id, feature_key="trigger_workflow_executions")
        ]

    async def test_the_success_is_counted_against_this_workflow_for_this_user(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id)

        assert seams.increment.await_args_list == [
            call(workflow.id, workflow.user_id, is_successful=True)
        ]

    async def test_the_fresh_playbook_is_distrust_checked_under_this_workflow_and_user(self):
        """The distrust check is what stops a playbook frozen on an empty result from being replayed forever."""
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        trace = [RecordedCall(tool_name="GMAIL_FETCH", args={"query": "is:unread"})]
        seams.chat = AsyncMock(return_value=("conv_1", trace))

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id)

        assert seams.distrust.await_args_list == [
            call(workflow.id, workflow.user_id, trace, healing=False)
        ]

    async def test_an_unstamped_context_reads_as_a_manual_fire_and_is_not_captured(
        self, _no_real_analytics
    ):
        """A manual fire is captured by the run-now endpoint at queue time, so capturing it again here would double-count every hand-run workflow."""
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id)

        captured = [type(entry.args[1]) for entry in _no_real_analytics.call_args_list]
        assert WorkflowExecuted not in captured

    async def test_a_scheduled_fire_claims_the_occurrence_it_was_armed_for(self):
        """ARQ cannot cancel a deferred job, so the claim is pinned to the occurrence — an unpinned claim runs a workflow at a time it was rescheduled away from."""
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id, SCHEDULED_FIRE)

        assert seams.scheduler.claim_task_for_execution.await_args_list == [
            call(workflow.id, expected_occurrence=SCHEDULED_FOR)
        ]

    async def test_a_fire_far_off_its_scheduled_time_is_warned_about_with_its_drift(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime.now(UTC) - timedelta(hours=1)
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id)

        drift = [
            entry
            for entry in seams.log.warning.call_args_list
            if entry.args and "fired off schedule" in str(entry.args[0])
        ]
        assert len(drift) == 1
        assert drift[0].kwargs["workflow_id"] == workflow.id
        assert drift[0].kwargs["drift"] >= 3600

    async def test_a_webhook_payload_without_a_stamp_reads_as_an_integration_fire(
        self, _no_real_analytics
    ):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id, {"trigger_data": {"events": []}})

        _no_real_analytics.assert_any_call(
            UserId(workflow.user_id),
            WorkflowExecuted(workflow_id=workflow.id, trigger_type=TriggerType.INTEGRATION.value),
        )


class TestTheCoalescedBatchIsTakenUnderItsOwnKey:
    """Trigger events live in Redis under trigger_batch_key, not in the job payload.

    Reading the wrong key drains nothing and the events are stranded until something else happens
    to fire the workflow.
    """

    async def test_the_batch_is_drained_and_refill_checked_under_the_context_key(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        context = {
            "trigger_batch_key": "batch_77",
            "trigger_type": TriggerType.INTEGRATION.value,
        }

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id, context)

        seams.drain.assert_awaited_once_with("batch_77")
        seams.reschedule.assert_awaited_once()
        assert seams.reschedule.await_args.args[1] == "batch_77"

    async def test_a_fire_with_no_batch_key_drains_nothing(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        seams.drain.assert_not_awaited()
        seams.reschedule.assert_not_awaited()

    async def test_the_drained_events_reach_the_run_as_its_trigger_data(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        seams.drain = AsyncMock(return_value=[{"event": "a"}, {"event": "b"}])
        context = {
            "trigger_batch_key": "batch_77",
            "trigger_type": TriggerType.INTEGRATION.value,
        }

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id, context)

        ran_with = seams.chat.await_args.args[2]
        assert ran_with["trigger_data"] == {
            "events": [{"event": "a"}, {"event": "b"}],
            "count": 2,
        }


class TestTheByIdExceptPathsNameTheirCause:
    """The except blocks are where a fire explains itself; a blanked message or a dropped id there is a silent fire nobody can find in the logs."""

    async def test_a_crashed_fire_is_logged_with_its_unwrapped_cause(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        seams.chat.side_effect = RuntimeError("gmail exploded")
        failure = AsyncMock(return_value="failed")

        with ExitStack() as stack:
            seams.enter(stack)
            stack.enter_context(patch(f"{MODULE}._record_run_failure", failure))
            result = await execute_workflow_by_id({}, workflow.id)

        assert result == "failed"
        seams.log.exception.assert_called_once_with(
            "[WORKER] Error executing workflow",
            workflow_id=workflow.id,
            error="gmail exploded",
            error_type="RuntimeError",
        )

    async def test_a_quota_capped_fire_is_warned_with_the_quota_it_hit(self):
        """The quota refusal is WARNING, not exception, so this line is the only record of it — a blanked message or type leaves an unexplained skipped run and no way to tell a quota stop from a crash."""
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        capped = RateLimitExceededException(
            feature="trigger_workflow_executions", plan_required="pro"
        )
        seams.chat.side_effect = capped
        failure = AsyncMock(return_value="skipped")

        with ExitStack() as stack:
            seams.enter(stack)
            stack.enter_context(patch(f"{MODULE}._record_run_failure", failure))
            result = await execute_workflow_by_id({}, workflow.id)

        assert result == "skipped"
        seams.log.exception.assert_not_called()
        seams.log.warning.assert_called_once_with(
            "[WORKER] Workflow skipped — rate limit exceeded",
            workflow_id=workflow.id,
            error=str(capped),
            error_type="RateLimitExceededException",
        )


class TestAFireCutOffByTheJobTimeoutIsBookedAgainstTheRightIds:
    """ARQ cancels the job rather than raising into it, so this is the only place the fire can be closed — and it has to close the right record.

    Fired on a schedule throughout: only a scheduler-originated fire advances the schedule, so that
    is the fire whose re-arm is worth asserting.
    """

    async def test_the_timeout_is_named_recorded_counted_and_rearmed(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        seams.chat.side_effect = asyncio.CancelledError()

        with ExitStack() as stack:
            seams.enter(stack)
            with pytest.raises(asyncio.CancelledError):
                await execute_workflow_by_id({}, workflow.id, SCHEDULED_FIRE)

        reason = str(WorkflowFireTimedOut(WORKER_JOB_TIMEOUT_SECONDS))
        seams.log.error.assert_any_call(
            "[WORKER] Workflow fire cut off by the job timeout",
            workflow_id=workflow.id,
            error=reason,
            error_type="WorkflowFireTimedOut",
        )
        assert seams.complete_execution.await_args_list == [
            call(
                execution_id="exec_1",
                status="failed",
                error_message=reason,
                conversation_id=None,
                trace=None,
            )
        ]
        assert seams.increment.await_args_list == [
            call(workflow.id, workflow.user_id, is_successful=False)
        ]
        seams.scheduler.handle_recurring_task.assert_awaited_once()

    async def test_the_shortcut_is_marked_failed_for_this_workflow_and_user(self):
        """Whatever the replay was doing may have run its side effects before the cut, so the next fire must heal rather than replay them again."""
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        seams.chat.side_effect = asyncio.CancelledError()

        with ExitStack() as stack:
            seams.enter(stack)
            with pytest.raises(asyncio.CancelledError):
                await execute_workflow_by_id({}, workflow.id, SCHEDULED_FIRE)

        seams.record_run_outcome.assert_awaited_once()
        recorded = seams.record_run_outcome.await_args
        assert recorded.args[0] == workflow.id
        assert recorded.args[1] == workflow.user_id
        assert recorded.args[2].status is PlaybookRunStatus.FAILED
        assert recorded.args[2].reason == str(WorkflowFireTimedOut(WORKER_JOB_TIMEOUT_SECONDS))

    async def test_a_rearm_failure_after_a_timeout_names_the_workflow(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        seams.chat.side_effect = asyncio.CancelledError()
        seams.scheduler.handle_recurring_task = AsyncMock(side_effect=RuntimeError("redis away"))

        with ExitStack() as stack:
            seams.enter(stack)
            with pytest.raises(asyncio.CancelledError):
                await execute_workflow_by_id({}, workflow.id, SCHEDULED_FIRE)

        logged = [str(entry.args[0]) for entry in seams.log.error.call_args_list if entry.args]
        assert any(workflow.id in line for line in logged), logged


class TestTheWorkflowCardBothRunPathsAttach:
    """build_selected_workflow_data is the one builder behind the agent turn and the playbook replay.

    The card is read by the UI by key, so the whole payload is pinned: a renamed step key renders
    an empty row, and a dropped prompt loses what the run was asked to do.
    """

    def _workflow(self):
        wf = MagicMock()
        wf.id = "wf_card_1"
        wf.title = "Morning Briefing"
        wf.description = "Daily morning workflow"
        wf.prompt = "Run the morning briefing"
        wf.steps = [
            WorkflowStep(id="s1", title="Step 1", description="Check mail", category="comms"),
            WorkflowStep(
                id="s2", title="Step 2", description="Draft the digest", category="general"
            ),
        ]
        return wf

    def test_the_card_carries_the_prompt_and_every_step_key_verbatim(self) -> None:
        card = build_selected_workflow_data(self._workflow())

        assert card.model_dump() == {
            "id": "wf_card_1",
            "title": "Morning Briefing",
            "description": "Daily morning workflow",
            "prompt": "Run the morning briefing",
            "steps": [
                {
                    "id": "s1",
                    "title": "Step 1",
                    "description": "Check mail",
                    "category": "comms",
                },
                {
                    "id": "s2",
                    "title": "Step 2",
                    "description": "Draft the digest",
                    "category": "general",
                },
            ],
        }

    def test_a_workflow_with_no_prompt_still_builds_a_card(self) -> None:
        workflow = self._workflow()
        workflow.prompt = None
        workflow.steps = []

        assert build_selected_workflow_data(workflow).model_dump() == {
            "id": "wf_card_1",
            "title": "Morning Briefing",
            "description": "Daily morning workflow",
            "prompt": None,
            "steps": [],
        }


class TestFireAttribution:
    """A workflow fire is the agent's work, attributed to what fired it."""

    @pytest.mark.parametrize(
        ("context", "expected"),
        [
            ({"trigger_type": TriggerType.SCHEDULE.value}, ("agent", "schedule", "worker")),
            (
                {"trigger_type": TriggerType.INTEGRATION.value},
                ("agent", "integration_trigger", "worker"),
            ),
            # A manual run keeps the user's carried request, acted on by the agent.
            ({"trigger_type": TriggerType.MANUAL.value}, ("agent", "interactive", "desktop")),
        ],
    )
    async def test_the_fire_runs_as_the_agent_in_its_triggers_context(
        self, context: dict[str, object], expected: tuple[str, str, str]
    ) -> None:
        seen: list[AnalyticsContext] = []

        async def _record(workflow_id: str, fire_context: object) -> str:
            seen.append(current_analytics_context())
            return "done"

        users_click = AnalyticsContext(
            attribution=Attribution(
                actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.DESKTOP
            )
        )
        with (
            analytics_context(users_click),
            patch("app.workers.tasks.workflow_tasks._execute_workflow_fire", _record),
        ):
            await execute_workflow_by_id({}, "wf-1", context)

        [attribution] = [ctx.attribution for ctx in seen]
        assert (attribution.actor, attribution.trigger, attribution.surface) == expected


class TestCostWallCopy:
    """A run the monthly allowance stopped names the day it resumes, not 'today'."""

    async def test_a_monthly_wall_names_the_reset_day(self) -> None:
        reset = datetime(2026, 12, 1, tzinfo=UTC)
        error = CostBudgetExceededException(
            feature="workflow_executions",
            reset_time=reset,
            current_plan="pro",
            message="You've used this month's AI usage allowance.",
            period=RateLimitPeriod.MONTH,
        )

        body, action = await _rate_limit_failure_content(error, _make_workflow())

        assert "December 1" in body
        assert "today" not in body
        assert action is None

    async def test_a_daily_wall_keeps_the_daily_copy(self) -> None:
        error = CostBudgetExceededException(
            feature="workflow_executions",
            reset_time=datetime(2026, 11, 4, tzinfo=UTC),
            current_plan="pro",
        )

        body, _ = await _rate_limit_failure_content(error, _make_workflow())

        assert "for today" in body
