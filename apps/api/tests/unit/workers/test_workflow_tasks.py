"""Unit tests for workflow_tasks ARQ worker."""

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

from bson import ObjectId
import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.models.agent_models import SilentRunResult
from app.models.notification.notification_models import (
    ActionType,
    NotificationSourceEnum,
)
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import TriggerType
from app.services.analytics_service import AnalyticsEvents
from app.services.workflow.conversation_service import build_selected_workflow_data
from app.services.workflow.execution_service import WorkflowFireQueued
from app.services.workflow.notifications import (
    send_workflow_completion_notification,
    send_workflow_failure_notification,
)
from app.utils.errors import AppError
from app.workers.tasks.workflow_tasks import (
    AGENT_RUN_SUMMARY,
    execute_workflow_as_chat,
    execute_workflow_by_id,
    generate_workflow_steps,
    process_workflow_generation_task,
    regenerate_workflow_steps,
)


@pytest.fixture(autouse=True)
def _no_real_analytics():
    """Keep every test hermetic: WORKFLOW_CREATED events are asserted through
    this mock and never reach a real PostHog client."""
    with patch("app.workers.tasks.workflow_tasks.capture_event") as mock_capture:
        yield mock_capture


@pytest.fixture(autouse=True)
def _onboarded_user():
    """Default every test's user to a finished-onboarding one, so the
    system-initiated-run gate stays out of the way. The gate's own tests
    (test_workflow_tasks_onboarding_gate.py) override this."""
    user = MagicMock()
    user.onboarding = {"completed": True}
    with patch(
        "app.workers.tasks.workflow_tasks.user_repository.get",
        AsyncMock(return_value=user),
    ):
        yield


def _make_workflow(
    workflow_id: str | None = None,
    user_id: str = "user_abc",
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
    wf.steps = steps or [
        MagicMock(id="s1", title="Step 1", description="Do it", category="general")
    ]
    wf.is_todo_workflow = is_todo_workflow
    wf.source_todo_id = source_todo_id
    wf.model_dump = MagicMock(return_value={"id": wf.id, "title": wf.title})
    return wf


def _patch_scheduler(workflow=None):
    """Stand in for the process-wide workflow_scheduler singleton.

    Returns the mock plus its unstarted patcher, so callers can enter it in a
    `with (...):` block alongside their other patches.
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
    ``create_system_conversation``, which captures ``CONVERSATION_CREATED``
    through ``capture_event`` — the PostHog provider is not registered in this
    test module's import chain, so the call must be mocked.
    """
    with patch("app.services.conversation_service.capture_event"):
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

    async def test_success_path_threads_the_exact_arguments_through(self, ctx):
        """The chat turn, the completion record and the re-arm each act on THIS
        run's workflow, execution id and context — a dropped, renamed or None'd
        value lands on the wrong conversation, the wrong execution row, or arms
        the wrong occurrence."""
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
        execute_chat.assert_awaited_once_with(workflow, {"user_id": workflow.user_id}, context)
        complete_exec.assert_awaited_once_with(
            execution_id=execution_id,
            status="success",
            summary=AGENT_RUN_SUMMARY,
            conversation_id="conv_123",
            trace=[],
        )
        rearm.assert_awaited_once_with(scheduler, workflow, context, workflow.id)

    async def test_failure_path_records_and_rearms_with_the_exact_arguments(self, ctx):
        """A failed run must still close THIS execution row and arm the SAME
        occurrence the success path would have — a None'd id strands an open
        execution record or silently kills the recurrence."""
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
        record_failure.assert_awaited_once_with(error, workflow, workflow.id, execution_id)
        rearm.assert_awaited_once_with(scheduler, workflow, context, workflow.id)

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
            workflow.user_id,
            AnalyticsEvents.WORKFLOW_EXECUTED,
            {"workflow_id": workflow.id, "trigger_type": "schedule"},
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
            workflow.user_id,
            AnalyticsEvents.WORKFLOW_EXECUTED,
            {"workflow_id": workflow.id, "trigger_type": "integration"},
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
            workflow.user_id,
            AnalyticsEvents.WORKFLOW_EXECUTED,
            {"workflow_id": workflow.id, "trigger_type": "schedule"},
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
        user_id = "user_abc"
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
            mock_repo.update = AsyncMock(return_value=mock_todo_result)

            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            result = await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", "Get milk and eggs"
            )

        assert "Successfully generated standalone workflow" in result
        assert workflow.id in result
        assert todo_id in result

        _no_real_analytics.assert_called_once()
        assert _no_real_analytics.call_args.args[0] == user_id
        assert _no_real_analytics.call_args.args[1] == AnalyticsEvents.WORKFLOW_CREATED
        assert _no_real_analytics.call_args.args[2] == {
            "workflow_id": workflow.id,
            "steps_count": len(workflow.steps),
            "is_todo_workflow": True,
        }

    async def test_workflow_creation_returns_none_raises(self, ctx):
        todo_id = str(uuid4())
        user_id = "user_abc"

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
        user_id = "user_abc"
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
            mock_repo.update = AsyncMock(return_value=None)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="not found or not updated"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

    async def test_websocket_failure_event_sent_on_exception(self, ctx):
        todo_id = str(ObjectId())
        user_id = "user_abc"

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
        """When description is empty the prompt template omits the details section.

        The argument is omitted entirely so the function's default value is what's
        under test, not an explicitly-passed empty string.
        """
        # Must be a valid 24-char hex ObjectId string because production code
        # calls ObjectId(todo_id) before the mocked update_one is invoked.
        todo_id = "507f1f77bcf86cd799439013"
        user_id = "user_abc"
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
            mock_repo.update = AsyncMock(return_value=mock_todo_result)
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
        user_id = "user_abc"

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            result = await regenerate_workflow_steps(ctx, workflow_id, user_id, "Steps were wrong")

        assert "Successfully regenerated steps" in result
        assert workflow_id in result

    async def test_exception_propagates(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock(
                side_effect=RuntimeError("Service down")
            )
            with pytest.raises(RuntimeError, match="Service down"):
                await regenerate_workflow_steps(ctx, workflow_id, user_id, "reason")

    async def test_force_different_tools_default_is_true(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"

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
        user_id = "user_abc"
        workflow = _make_workflow(workflow_id=workflow_id, is_todo_workflow=False)

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            result = await generate_workflow_steps(ctx, workflow_id, user_id)

        assert "Successfully generated steps" in result
        assert workflow_id in result

    async def test_todo_workflow_sends_websocket_event(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"
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
        user_id = "user_abc"
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
        user_id = "user_abc"

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc._generate_workflow_steps = AsyncMock(side_effect=RuntimeError("LLM error"))

            with pytest.raises(RuntimeError, match="LLM error"):
                await generate_workflow_steps(ctx, workflow_id, user_id)


# ---------------------------------------------------------------------------
# execute_workflow_as_chat
# ---------------------------------------------------------------------------


class TestExecuteWorkflowAsChat:
    """Dedicated tests for execute_workflow_as_chat.

    The function is decorated with @tiered_rate_limit which is globally
    patched to a no-op in conftest.py, so rate-limit enforcement is not
    exercised here; we test the function body directly.

    I/O boundaries mocked:
      - get_user_by_id
      - get_or_create_workflow_conversation
      - call_agent_silent  (the core agent invocation)
      - reset_workflow_threads  (Postgres; proven in test_thread_reset.py)
    """

    @pytest.fixture(autouse=True)
    def reset_threads(self):
        with patch(
            "app.workers.tasks.workflow_tasks.reset_workflow_threads",
            new_callable=AsyncMock,
        ) as reset:
            yield reset

    def _make_workflow(self, workflow_id: str | None = None, user_id: str = "user_abc"):
        wf = MagicMock()
        wf.id = workflow_id or str(ObjectId())
        wf.user_id = user_id
        wf.title = "Morning Briefing"
        wf.description = "Daily morning workflow"
        wf.prompt = "Run the morning briefing"
        wf.steps = [
            MagicMock(id="s1", title="Step 1", description="Check mail", category="comms"),
            MagicMock(id="s2", title="Step 2", description="Weather", category="info"),
        ]
        return wf

    async def test_chat_dispatch_called_with_correct_conversation_id(self):
        """call_agent_silent receives the conversation_id from get_or_create_workflow_conversation."""
        workflow = self._make_workflow()
        expected_conv_id = "conv_expected_123"

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value=expected_conv_id,
            ) as mock_get_conv,
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Result text", tool_data={}),
            ) as mock_call_agent,
        ):
            conversation_id, _trace = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        # Conversation was fetched for this workflow and user
        mock_get_conv.assert_awaited_once_with(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            workflow_title=workflow.title,
        )

        # Agent was invoked once with the correct conversation_id
        mock_call_agent.assert_awaited_once()
        assert mock_call_agent.call_args.kwargs["conversation_id"] == expected_conv_id

        # Returns the conversation id string
        assert conversation_id == expected_conv_id

    async def test_successful_execution_returns_conversation_id(self):
        """On success the function returns the conversation id string."""
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_123",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Step 1 done. Step 2 done.", tool_data={}),
            ) as mock_call_agent,
        ):
            conversation_id, _trace = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        assert conversation_id == "conv_123"
        mock_call_agent.assert_awaited_once()

    async def test_trigger_context_carries_workflow_id(self):
        """The trigger_context forwarded to the agent carries the workflow id."""
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_ctx",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Done", tool_data={}),
            ) as mock_call_agent,
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        trigger_context = mock_call_agent.call_args.kwargs["options"].trigger_context
        assert trigger_context["workflow_id"] == workflow.id

    async def test_exception_in_agent_returns_error_message_not_reraise(self):
        """When call_agent_silent raises, the function re-raises so the caller
        marks the execution as failed.
        """
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_1",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Agent crashed"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Agent crashed"):
                await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

    async def test_get_user_by_id_failure_falls_back_to_utc(self):
        """When get_user_by_id raises, the function falls back gracefully and still
        calls the agent with a minimal user_data dict.
        """
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                side_effect=ConnectionError("DB unreachable"),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_fallback",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Fallback result", tool_data={}),
            ) as mock_call_agent,
        ):
            conversation_id, _trace = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        # Execution completes successfully despite user fetch failing
        assert conversation_id == "conv_fallback"

        # Agent was called with a minimal user dict that still includes user_id
        call_user = mock_call_agent.call_args.kwargs["user"]
        assert call_user["user_id"] == workflow.user_id

    async def test_workflow_steps_passed_to_agent_as_selected_workflow(self):
        """All workflow steps are serialised and forwarded inside the request's
        selectedWorkflow field so the agent knows what to execute.
        """
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_steps",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Done", tool_data={}),
            ) as mock_call_agent,
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        request_arg = mock_call_agent.call_args.kwargs["request"]
        assert request_arg.selectedWorkflow is not None
        assert request_arg.selectedWorkflow.id == workflow.id
        assert request_arg.message == f"Execute workflow: {workflow.title}"
        # Both steps must be present
        step_ids = [s["id"] for s in request_arg.selectedWorkflow.steps]
        assert "s1" in step_ids
        assert "s2" in step_ids

    async def test_user_data_none_falls_back_to_utc(self):
        """When get_user_by_id returns None, the function uses a minimal
        user_data dict and UTC timezone."""
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_none",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="None user result", tool_data={}),
            ) as mock_call_agent,
        ):
            conversation_id, _trace = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        assert conversation_id == "conv_none"
        call_user = mock_call_agent.call_args.kwargs["user"]
        assert call_user["user_id"] == workflow.user_id

    async def test_user_message_has_selected_workflow(self):
        """The persisted trigger user message carries the selectedWorkflow data."""
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_usermsg",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ) as mock_store,
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="OK", tool_data={}),
            ),
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        stored_messages = mock_store.call_args.kwargs["workflow_execution_messages"]
        user_msg = stored_messages[0]
        assert user_msg.type == "user"
        assert user_msg.selectedWorkflow is not None
        assert user_msg.selectedWorkflow.id == workflow.id

    async def test_it_resets_the_conversations_checkpoint_threads_before_running(
        self, reset_threads
    ):
        """Without this the run replays every previous run out of Postgres."""
        workflow = self._make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_reset",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Done", tool_data={}),
            ),
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        reset_threads.assert_awaited_once_with("conv_reset")

    async def test_it_returns_the_runs_tool_calls_as_the_trace(self):
        """The trace is what the next run reads instead of the checkpoints."""
        workflow = self._make_workflow()
        tool_data = {
            "tool_data": [
                {
                    "tool_name": "tool_calls_data",
                    "data": {
                        "tool_name": "GMAIL_FETCH",
                        "inputs": {"query": "is:unread"},
                        "output": "12 messages",
                    },
                }
            ]
        }

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_trace",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=SilentRunResult(message="Done", tool_data=tool_data),
            ),
        ):
            _conversation_id, trace = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        assert [c.tool_name for c in trace] == ["GMAIL_FETCH"]
        assert trace[0].args == {"query": "is:unread"}
        assert trace[0].result_digest == "12 messages"


# ---------------------------------------------------------------------------
# workflow notification senders (app.services.workflow.notifications)
# ---------------------------------------------------------------------------


class TestWorkflowNotificationSenders:
    """Tests for the workflow completion/failure notification senders."""

    async def test_completion_notification_is_inapp_with_view_results_link(
        self,
    ) -> None:
        """send_workflow_completion_notification fires a human, in-app-only badge.

        The result itself is delivered to the user's chat as real messages, so the
        notification carries no result payload and no external push — just a single
        "View Results" link so a web user reaches the run's conversation in one tap.
        """
        with patch(
            "app.services.workflow.notifications.notification_service",
        ) as mock_notif:
            mock_notif.create_notification = AsyncMock()
            await send_workflow_completion_notification(
                workflow_id="wf_1",
                workflow_title="Morning Briefing",
                conversation_id="conv_xyz",
                user_id="user_abc",
            )

        mock_notif.create_notification.assert_awaited_once()
        notif_req = mock_notif.create_notification.call_args[0][0]
        # Human copy: phrasing rotates, but the workflow name is woven into the
        # title and there is a casual body.
        assert "Morning Briefing" in notif_req.content.title
        assert notif_req.content.body
        # Scoped to in-app only (no external chrome push) and no result payload.
        assert [c.channel_type for c in notif_req.channels] == [CHANNEL_TYPE_INAPP]
        assert notif_req.content.rich_content is None
        # Exactly one "View Results" redirect to the run's conversation.
        actions = notif_req.content.actions
        assert len(actions) == 1
        assert actions[0].type == ActionType.REDIRECT
        assert actions[0].config.redirect.url == "/c/conv_xyz"
        assert notif_req.metadata == {
            "workflow_id": "wf_1",
            "conversation_id": "conv_xyz",
        }

    async def test_failure_notification_sent_with_workflow_failed_source(self):
        """send_workflow_failure_notification sends a WORKFLOW_FAILED notification."""
        with patch(
            "app.services.workflow.notifications.notification_service",
        ) as mock_notif:
            mock_notif.create_notification = AsyncMock()
            await send_workflow_failure_notification(
                workflow_id="wf_1",
                workflow_title="Morning Briefing",
                user_id="user_abc",
            )

        mock_notif.create_notification.assert_awaited_once()
        notif_req = mock_notif.create_notification.call_args[0][0]
        assert notif_req.source == NotificationSourceEnum.WORKFLOW_FAILED


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

        Returns individual patch objects so they can be used in a `with (...):`
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
        """RateLimitExceededException with reset_time sends a notification
        mentioning when the limit resets and prompting upgrade."""
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
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        mock_notif.create_notification.assert_awaited_once()
        notif_req = mock_notif.create_notification.call_args[0][0]
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
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        notif_req = mock_notif.create_notification.call_args[0][0]
        assert "not available on your current plan" in notif_req.content.body
        assert "Upgrade to Pro" in notif_req.content.body

    async def test_rate_limit_with_invalid_reset_time_format_falls_back(self, ctx):
        """When reset_time string in the detail dict is unparseable,
        the fallback body is used (no Resets line)."""
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
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        notif_req = mock_notif.create_notification.call_args[0][0]
        # Falls back to the version without the reset time formatting
        assert "you've used all your workflow executions" in notif_req.content.body

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
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        notif_req = mock_notif.create_notification.call_args[0][0]
        assert "encountered an error" in notif_req.content.body
        # No upgrade action for generic errors
        assert notif_req.content.actions is None

    async def test_notification_failure_during_error_is_swallowed(self, ctx):
        """If notification_service.create_notification fails during error handling,
        the exception is swallowed and the error result is still returned."""
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
            mock_notif.create_notification = AsyncMock(
                side_effect=RuntimeError("Notification service down")
            )
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
            mock_notif.create_notification = AsyncMock()
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
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result

    async def test_no_execution_id_skips_complete_execution_on_error(self, ctx):
        """When create_execution itself fails, execution_id is None
        and complete_execution is not called."""
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
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(ctx, workflow.id)

        assert "Error executing workflow" in result
        # complete_execution should NOT have been called since execution_id is None
        mock_complete_exec.assert_not_awaited()

    async def test_conversation_id_and_trace_passed_to_complete_execution(self, ctx):
        """The conversation id and recorded trace from execute_workflow_as_chat are
        forwarded to complete_execution — the trace is what the next run reads."""
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
        user_id = "user_abc"
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
        user_id = "user_abc"
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
        """When the websocket broadcast fails during the success path,
        the function still returns success."""
        todo_id = "507f1f77bcf86cd799439014"
        user_id = "user_abc"
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
            mock_repo.update = AsyncMock(return_value=mock_todo_result)

            result = await process_workflow_generation_task(ctx, todo_id, user_id, "Test Todo")

        assert "Successfully generated" in result

    async def test_clear_flag_failure_on_exception_does_not_mask_error(self, ctx):
        """When clear_workflow_generating_flag fails during exception handling,
        the original exception is still raised."""
        todo_id = str(ObjectId())
        user_id = "user_abc"

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
        """When the failure websocket broadcast itself fails, the original
        exception is still raised."""
        todo_id = str(ObjectId())
        user_id = "user_abc"

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
        user_id = "user_abc"
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
            mock_repo.update = AsyncMock(return_value=mock_todo_result)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", description="Milk, eggs, bread"
            )

        assert len(captured_requests) == 1
        assert "**Details:** Milk, eggs, bread" in captured_requests[0].prompt

    async def test_workflow_with_no_id_raises(self, ctx):
        """If workflow.id is falsy after creation, it raises AppError."""
        todo_id = str(ObjectId())
        user_id = "user_abc"
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
        user_id = "user_abc"

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
        user_id = "user_abc"
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
        """When the WebSocket broadcast fails for a todo workflow,
        the function still returns success."""
        workflow_id = str(uuid4())
        user_id = "user_abc"
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
        user_id = "user_abc"

        with patch("app.services.workflow.service.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            await regenerate_workflow_steps(
                ctx, workflow_id, user_id, "reason", force_different_tools=False
            )

        mock_wf_svc.regenerate_workflow_steps.assert_awaited_once_with(
            workflow_id, user_id, "reason", False
        )


MODULE = "app.workers.tasks.workflow_tasks"


class _FirePatches:
    """Every I/O edge one ``execute_workflow_by_id`` fire touches, mocked.

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
        self.increment = AsyncMock()
        self.chat = AsyncMock(return_value=("conv_1", []))
        self.cost_budget = AsyncMock()
        self.drain = AsyncMock(return_value=[{"event": "one"}])
        self.reschedule = AsyncMock()
        self.coalesce = MagicMock(return_value=30)
        self.distrust = AsyncMock()
        self.log = MagicMock()

    def enter(self, stack) -> None:
        for patcher in (
            patch(f"{MODULE}.workflow_scheduler", self.scheduler),
            patch(f"{MODULE}.create_execution", AsyncMock(return_value=self.execution)),
            patch(f"{MODULE}.complete_execution", self.complete_execution),
            patch(
                f"{MODULE}.WorkflowService",
                MagicMock(increment_execution_count=self.increment),
            ),
            patch(f"{MODULE}.execute_workflow_as_chat", self.chat),
            patch(f"{MODULE}.enforce_daily_cost_budget", self.cost_budget),
            patch(f"{MODULE}.drain_trigger_batch", self.drain),
            patch(f"{MODULE}.reschedule_if_refilled", self.reschedule),
            patch(f"{MODULE}.coalesce_window_seconds", self.coalesce),
            patch(f"{MODULE}.distrust_fresh_playbook", self.distrust),
            patch(f"{MODULE}.log", self.log),
        ):
            stack.enter_context(patcher)


class TestTheByIdTaskThreadsItsIdsThrough:
    """One fire touches five collaborators, each keyed on an id it was handed.
    A blanked or swapped id books this run against the wrong thing, which is
    worse than not booking it: nothing goes looking for wrong data."""

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
        """The distrust check is what stops a playbook frozen on an empty result
        from being replayed forever. Keyed on the wrong id it reads a playbook
        that is not this run's — so the bad body is never marked, and every later
        fire replays it."""
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
        """A manual fire is captured by the run-now endpoint at queue time, so
        capturing it again here would double-count every hand-run workflow."""
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id)

        captured = [
            entry.args[1] for entry in _no_real_analytics.call_args_list if len(entry.args) > 1
        ]
        assert AnalyticsEvents.WORKFLOW_EXECUTED not in captured

    async def test_a_webhook_payload_without_a_stamp_reads_as_an_integration_fire(
        self, _no_real_analytics
    ):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)

        with ExitStack() as stack:
            seams.enter(stack)
            await execute_workflow_by_id({}, workflow.id, {"trigger_data": {"events": []}})

        _no_real_analytics.assert_any_call(
            workflow.user_id,
            AnalyticsEvents.WORKFLOW_EXECUTED,
            {"workflow_id": workflow.id, "trigger_type": TriggerType.INTEGRATION.value},
        )


class TestTheCoalescedBatchIsTakenUnderItsOwnKey:
    """Trigger events live in Redis under ``trigger_batch_key``, not in the job
    payload. Reading the wrong key drains nothing and the events are stranded
    until something else happens to fire the workflow."""

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
    """The except blocks are where a fire explains itself; a blanked message
    or a dropped id there is a silent fire nobody can find in the logs."""

    async def test_a_queued_fire_is_logged_and_booked_with_its_own_signal(self):
        workflow = _make_workflow()
        seams = _FirePatches(workflow)
        queued = WorkflowFireQueued(
            task_id=workflow.id, user_id=workflow.user_id, conversation_id="conv_q", trace=[]
        )
        seams.chat.side_effect = queued
        never_ran = AsyncMock(return_value="queued instead")

        with ExitStack() as stack:
            seams.enter(stack)
            stack.enter_context(patch(f"{MODULE}._record_fire_that_never_ran", never_ran))
            result = await execute_workflow_by_id({}, workflow.id)

        assert result == "queued instead"
        seams.log.warning.assert_any_call(
            "[WORKER] Workflow fire did not run",
            workflow_id=workflow.id,
            reason=str(queued),
            error_type="WorkflowFireQueued",
        )
        assert never_ran.await_args.args == (
            queued,
            workflow,
            workflow.id,
            seams.execution.execution_id,
            None,
        )

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
        """The quota refusal is WARNING, not exception, so this line is the only
        record of it — a blanked message or type leaves an unexplained skipped
        run and no way to tell a quota stop from a crash."""
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


class TestTheWorkflowCardBothRunPathsAttach:
    """``build_selected_workflow_data`` is the one builder behind the agent turn
    and the playbook replay. The card is read by the UI by key, so the whole
    payload is pinned: a renamed step key renders an empty row, and a dropped
    prompt loses what the run was asked to do."""

    def _workflow(self):
        wf = MagicMock()
        wf.id = "wf_card_1"
        wf.title = "Morning Briefing"
        wf.description = "Daily morning workflow"
        wf.prompt = "Run the morning briefing"
        wf.steps = [
            MagicMock(id="s1", title="Step 1", description="Check mail", category="comms"),
            MagicMock(id="s2", title="Step 2", description="Draft the digest", category="general"),
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


class TestTheChatRunsTriggerTurnIsBuiltExactly:
    """The trigger turn is the only thing this function persists; the result is
    saved by the delivery path. Its shape is what the UI renders as the
    workflow card, so every field is asserted rather than its presence."""

    def _workflow(self):
        wf = MagicMock()
        wf.id = str(ObjectId())
        wf.user_id = "user_abc"
        wf.title = "Morning Briefing"
        wf.description = "Daily morning workflow"
        wf.prompt = "Run the morning briefing"
        wf.notify_on_completion = True
        wf.steps = [MagicMock(id="s1", title="Step 1", description="Check mail", category="comms")]
        return wf

    async def _run(self, workflow, add_messages, reset_threads, log_seam):
        with (
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(return_value={"user_id": workflow.user_id, "timezone": "UTC"}),
            ),
            patch(
                f"{MODULE}.get_or_create_workflow_conversation",
                AsyncMock(return_value="conv_expected_123"),
            ) as conversation,
            patch(f"{MODULE}.add_workflow_execution_messages", add_messages),
            patch(f"{MODULE}.reset_workflow_threads", reset_threads),
            patch(f"{MODULE}.log", log_seam),
            patch(
                "app.agents.core.agent.call_agent_silent",
                AsyncMock(return_value=SilentRunResult(message="Result text", tool_data={})),
            ) as agent,
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})
        return conversation, agent

    async def test_the_conversation_is_opened_for_this_workflow_user_and_title(self):
        workflow = self._workflow()
        log_seam = MagicMock()

        conversation, _ = await self._run(workflow, AsyncMock(), AsyncMock(), log_seam)

        conversation.assert_awaited_once_with(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            workflow_title=workflow.title,
        )
        log_seam.info.assert_any_call(
            "[WORKER] Executing workflow as chat session",
            workflow_id=workflow.id,
            user_id=workflow.user_id,
        )
        log_seam.set.assert_any_call(conversation_context_found=True)

    async def test_the_conversations_checkpoint_threads_are_reset_by_id(self):
        """Without the reset the run replays every previous run out of the
        checkpoints instead of reading this fire's recorded trace."""
        workflow = self._workflow()
        reset_threads = AsyncMock()

        await self._run(workflow, AsyncMock(), reset_threads, MagicMock())

        reset_threads.assert_awaited_once_with("conv_expected_123")

    async def test_the_turn_is_an_empty_user_message_carrying_the_workflow_card(self):
        workflow = self._workflow()
        add_messages = AsyncMock()

        _, agent = await self._run(workflow, add_messages, AsyncMock(), MagicMock())

        assert add_messages.await_args.kwargs["conversation_id"] == "conv_expected_123"
        assert add_messages.await_args.kwargs["user_id"] == workflow.user_id
        (message,) = add_messages.await_args.kwargs["workflow_execution_messages"]
        assert message.type == "user"
        # Empty on purpose: the UI renders the card, not a "Run workflow: ..." bubble.
        assert message.response == ""
        assert message.selectedWorkflow == build_selected_workflow_data(workflow)
        assert UUID(message.message_id).version == 4
        # The same card goes to the agent, so both surfaces render one workflow.
        assert agent.await_args.kwargs["request"].selectedWorkflow == message.selectedWorkflow

    async def test_the_trigger_context_carries_the_fires_context_and_mode(self):
        """The splatted fire context and the execution_mode key both route the
        silent run; a dropped or renamed key strands the result delivery."""
        workflow = self._workflow()
        with (
            patch(
                f"{MODULE}.get_user_by_id",
                AsyncMock(return_value={"user_id": workflow.user_id, "timezone": "UTC"}),
            ),
            patch(
                f"{MODULE}.get_or_create_workflow_conversation",
                AsyncMock(return_value="conv_expected_123"),
            ),
            patch(f"{MODULE}.add_workflow_execution_messages", AsyncMock()),
            patch(f"{MODULE}.reset_workflow_threads", AsyncMock()),
            patch(
                "app.agents.core.agent.call_agent_silent",
                AsyncMock(return_value=SilentRunResult(message="Result text", tool_data={})),
            ) as agent,
        ):
            await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {"trigger_batch": "b1"}
            )

        options = agent.await_args.kwargs["options"]
        assert options.trigger_context == {
            "trigger_batch": "b1",
            "workflow_id": workflow.id,
            "workflow_title": workflow.title,
            "workflow_notify_on_completion": True,
            "execution_mode": "background",
        }
