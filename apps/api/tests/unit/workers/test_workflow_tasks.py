"""Unit tests for workflow_tasks ARQ worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
import pytest

from app.api.v1.middleware.tiered_rate_limiter import (
    CostBudgetExceededException,
    RateLimitExceededException,
)
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.models.notification.notification_models import (
    ActionStyle,
    ActionType,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.payment_models import PlanType
from app.models.todo_models import TodoUpdate
from app.models.workflow_models import TriggerType
from app.services.workflow.notifications import (
    send_workflow_completion_notification,
    send_workflow_failure_notification,
)
from app.utils.errors import AppError
from app.workers.tasks.workflow_tasks import (
    _log_schedule_drift,
    _notify_workflow_failed,
    _quota_exhausted_body,
    _rate_limit_failure_content,
    _rearm_if_scheduled,
    _rearm_quietly,
    _record_execution_failure,
    execute_workflow_as_chat,
    execute_workflow_by_id,
    generate_workflow_steps,
    process_workflow_generation_task,
    regenerate_workflow_steps,
)


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
        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=None)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_execution = AsyncMock()
        mock_complete_execution = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()
        mock_execute_chat = AsyncMock(return_value="conv_123")

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

        mock_scheduler.initialize.assert_awaited_once()
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

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_123"),
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

        mock_scheduler.initialize.assert_awaited_once()
        mock_increment.assert_awaited_once_with(workflow.id, workflow.user_id, is_successful=True)

    async def test_execution_count_incremented_as_failed_on_error(self, ctx):
        workflow = _make_workflow()

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

        mock_scheduler.initialize.assert_awaited_once()
        mock_increment.assert_awaited_once_with(workflow.id, workflow.user_id, is_successful=False)
        assert "Error executing workflow" in result

    async def test_trigger_type_from_context(self, ctx):
        workflow = _make_workflow()
        context = {"trigger_type": "scheduled"}

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_123"),
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

        mock_scheduler.initialize.assert_awaited_once()
        mock_create_exec.assert_awaited_once_with(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            trigger_type="scheduled",
        )

    async def test_default_trigger_type_is_manual_when_no_context(self, ctx):
        workflow = _make_workflow()
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_123"),
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
            await execute_workflow_by_id(ctx, workflow.id, context=None)

        mock_scheduler.initialize.assert_awaited_once()
        mock_create_exec.assert_awaited_once_with(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            trigger_type="manual",
        )

    async def test_scheduler_always_closed_in_finally(self, ctx):
        workflow = _make_workflow()

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

        mock_scheduler.initialize.assert_awaited_once()
        mock_scheduler.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# process_workflow_generation_task
# ---------------------------------------------------------------------------


class TestProcessWorkflowGenerationTask:
    """Tests for process_workflow_generation_task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_successful_generation_returns_success_message(self, ctx):
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
        """When description is empty the prompt template omits the details section."""
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

            await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", description=""
            )

        assert len(captured_requests) == 1
        # The **Details:** section should be absent when description is empty
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

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            result = await regenerate_workflow_steps(ctx, workflow_id, user_id, "Steps were wrong")

        assert "Successfully regenerated steps" in result
        assert workflow_id in result

    async def test_exception_propagates(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock(
                side_effect=RuntimeError("Service down")
            )
            with pytest.raises(RuntimeError, match="Service down"):
                await regenerate_workflow_steps(ctx, workflow_id, user_id, "reason")

    async def test_force_different_tools_default_is_true(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
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

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
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
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
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
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
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

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
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
    """

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
                return_value=("Result text", {}),
            ) as mock_call_agent,
        ):
            conversation_id = await execute_workflow_as_chat(
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
                return_value=("Step 1 done. Step 2 done.", {}),
            ) as mock_call_agent,
        ):
            conversation_id = await execute_workflow_as_chat(
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
                return_value=("Done", {}),
            ) as mock_call_agent,
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        trigger_context = mock_call_agent.call_args.kwargs["trigger_context"]
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
                return_value=("Fallback result", {}),
            ) as mock_call_agent,
        ):
            conversation_id = await execute_workflow_as_chat(
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
                return_value=("Done", {}),
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
                return_value=("None user result", {}),
            ) as mock_call_agent,
        ):
            conversation_id = await execute_workflow_as_chat(
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
                return_value=("OK", {}),
            ),
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        stored_messages = mock_store.call_args.kwargs["workflow_execution_messages"]
        user_msg = stored_messages[0]
        assert user_msg.type == "user"
        assert user_msg.selectedWorkflow is not None
        assert user_msg.selectedWorkflow.id == workflow.id


# ---------------------------------------------------------------------------
# workflow notification senders (app.services.workflow.notifications)
# ---------------------------------------------------------------------------


class TestWorkflowNotificationSenders:
    """Tests for the workflow completion/failure notification senders."""

    async def test_completion_notification_is_inapp_with_view_results_link(self) -> None:
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
        assert notif_req.metadata == {"workflow_id": "wf_1", "conversation_id": "conv_xyz"}

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
        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        p_scheduler = patch(
            "app.workers.tasks.workflow_tasks.WorkflowScheduler",
            mock_scheduler_cls,
        )
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

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_complete_exec = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
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

    async def test_conversation_id_passed_to_complete_execution(self, ctx):
        """The conversation id returned by execute_workflow_as_chat is forwarded
        to complete_execution."""
        workflow = _make_workflow()

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        mock_complete_exec = AsyncMock()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_123"),
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
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
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
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
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
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
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

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            await regenerate_workflow_steps(
                ctx, workflow_id, user_id, "reason", force_different_tools=False
            )

        mock_wf_svc.regenerate_workflow_steps.assert_awaited_once_with(
            workflow_id, user_id, "reason", False
        )


# ---------------------------------------------------------------------------
# _log_schedule_drift
# ---------------------------------------------------------------------------


class TestLogScheduleDrift:
    """Direct tests for _log_schedule_drift."""

    def test_no_scheduled_at_returns_without_logging(self):
        workflow = _make_workflow()
        workflow.scheduled_at = None

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", datetime.now(UTC))

        mock_log.set.assert_not_called()
        mock_log.warning.assert_not_called()

    def test_non_datetime_scheduled_at_returns_without_logging(self):
        workflow = _make_workflow()
        workflow.scheduled_at = "2026-01-01T00:00:00+00:00"

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", datetime.now(UTC))

        mock_log.set.assert_not_called()
        mock_log.warning.assert_not_called()

    def test_large_drift_warns_with_exact_values(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        actual_fire_utc = datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC)

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", actual_fire_utc)

        mock_log.set.assert_called_once_with(
            scheduled_at_utc="2026-01-01T00:00:00+00:00",
            drift_from_scheduled_seconds=600,
        )
        mock_log.warning.assert_called_once_with(
            "[WORKER] Workflow fired off schedule (positive = late, negative = early)",
            workflow_id="wf_1",
            drift=600,
        )

    def test_early_fire_also_warns_with_negative_drift(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC)
        actual_fire_utc = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", actual_fire_utc)

        assert mock_log.warning.call_args.kwargs["drift"] == -600

    def test_drift_within_threshold_logs_set_but_no_warning(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime.now(UTC) - timedelta(seconds=60)
        actual_fire_utc = datetime.now(UTC)

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", actual_fire_utc)

        drift = mock_log.set.call_args.kwargs["drift_from_scheduled_seconds"]
        assert drift <= 300
        assert (
            mock_log.set.call_args.kwargs["scheduled_at_utc"] == workflow.scheduled_at.isoformat()
        )
        mock_log.warning.assert_not_called()

    def test_naive_scheduled_at_is_treated_as_utc(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime(2026, 1, 1, 0, 0, 0).replace(tzinfo=None)
        actual_fire_utc = datetime(2026, 1, 1, 0, 10, 0, tzinfo=UTC)

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", actual_fire_utc)

        assert mock_log.set.call_args.kwargs["scheduled_at_utc"] == "2026-01-01T00:00:00+00:00"
        assert mock_log.warning.call_args.kwargs["drift"] == 600

    def test_exact_threshold_drift_does_not_warn(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        actual_fire_utc = datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC)

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", actual_fire_utc)

        assert mock_log.set.call_args.kwargs["drift_from_scheduled_seconds"] == 300
        mock_log.warning.assert_not_called()

    def test_just_over_threshold_drift_warns(self):
        workflow = _make_workflow()
        workflow.scheduled_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        actual_fire_utc = datetime(2026, 1, 1, 0, 5, 1, tzinfo=UTC)

        with patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            _log_schedule_drift(workflow, "wf_1", actual_fire_utc)

        assert mock_log.set.call_args.kwargs["drift_from_scheduled_seconds"] == 301
        assert mock_log.warning.call_args.kwargs["drift"] == 301


# ---------------------------------------------------------------------------
# _rearm_if_scheduled
# ---------------------------------------------------------------------------


class TestRearmIfScheduled:
    """Direct tests for _rearm_if_scheduled."""

    async def test_no_workflow_does_not_rearm(self):
        scheduler = AsyncMock()
        await _rearm_if_scheduled(scheduler, None, {"trigger_type": TriggerType.SCHEDULE.value})
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_non_repeating_workflow_does_not_rearm(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = None
        workflow.activated = True
        await _rearm_if_scheduled(scheduler, workflow, {"trigger_type": TriggerType.SCHEDULE.value})
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_deactivated_workflow_does_not_rearm(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = False
        await _rearm_if_scheduled(scheduler, workflow, {"trigger_type": TriggerType.SCHEDULE.value})
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_no_context_does_not_rearm(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        await _rearm_if_scheduled(scheduler, workflow, None)
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_context_without_trigger_type_does_not_rearm(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        await _rearm_if_scheduled(scheduler, workflow, {})
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_non_schedule_trigger_does_not_rearm(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        await _rearm_if_scheduled(scheduler, workflow, {"trigger_type": "manual"})
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_schedule_trigger_rearms_with_next_occurrence(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        workflow.occurrence_count = 2
        await _rearm_if_scheduled(scheduler, workflow, {"trigger_type": TriggerType.SCHEDULE.value})
        scheduler.handle_recurring_task.assert_awaited_once_with(workflow, 3)

    async def test_missing_occurrence_count_rearms_with_one(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        workflow.occurrence_count = None
        await _rearm_if_scheduled(scheduler, workflow, {"trigger_type": TriggerType.SCHEDULE.value})
        scheduler.handle_recurring_task.assert_awaited_once_with(workflow, 1)


# ---------------------------------------------------------------------------
# _rearm_quietly
# ---------------------------------------------------------------------------


class TestRearmQuietly:
    """Direct tests for _rearm_quietly."""

    async def test_delegates_to_rearm_if_scheduled(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()
        context = {"trigger_type": "manual"}

        with patch(
            "app.workers.tasks.workflow_tasks._rearm_if_scheduled",
            new_callable=AsyncMock,
        ) as mock_rearm:
            await _rearm_quietly(scheduler, workflow, context, "wf_1")

        mock_rearm.assert_awaited_once_with(scheduler, workflow, context)

    async def test_rearm_failure_is_logged_not_raised(self):
        scheduler = AsyncMock()
        workflow = _make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks._rearm_if_scheduled",
                AsyncMock(side_effect=RuntimeError("scheduler down")),
            ),
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            await _rearm_quietly(scheduler, workflow, {"trigger_type": "schedule"}, "wf_1")

        mock_log.error.assert_called_once()
        message = mock_log.error.call_args.args[0]
        assert "Failed to re-arm workflow" in message
        assert "wf_1" in message


# ---------------------------------------------------------------------------
# _quota_exhausted_body
# ---------------------------------------------------------------------------


class TestQuotaExhaustedBody:
    """Direct tests for _quota_exhausted_body."""

    async def test_formats_reset_in_user_timezone(self):
        workflow = _make_workflow(title="Standup")

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"user_id": workflow.user_id, "timezone": "America/New_York"},
            ) as mock_get_user,
            patch(
                "app.workers.tasks.workflow_tasks.format_local_time",
                return_value="Mar 21 at 08:00 AM EDT",
            ) as mock_format,
        ):
            body = await _quota_exhausted_body(workflow, "2026-03-21T12:00:00+00:00")

        mock_get_user.assert_awaited_once_with(workflow.user_id)
        mock_format.assert_called_once_with(
            datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC),
            "America/New_York",
            fmt="%b %d at %I:%M %p %Z",
        )
        assert body == (
            "'Standup' couldn't run — you've used all your workflow executions for today. "
            "Resets Mar 21 at 08:00 AM EDT."
        )

    async def test_naive_reset_time_is_treated_as_utc(self):
        workflow = _make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.format_local_time",
                return_value="Mar 21 at 12:00 PM UTC",
            ) as mock_format,
        ):
            body = await _quota_exhausted_body(workflow, "2026-03-21T12:00:00")

        assert mock_format.call_args.args[0] == datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC)
        assert mock_format.call_args.args[1] is None
        assert body.endswith("Resets Mar 21 at 12:00 PM UTC.")

    async def test_user_lookup_failure_still_formats_reset(self):
        workflow = _make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                side_effect=ConnectionError("db down"),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.format_local_time",
                return_value="Mar 21 at 12:00 PM UTC",
            ) as mock_format,
        ):
            body = await _quota_exhausted_body(workflow, "2026-03-21T12:00:00+00:00")

        assert mock_format.call_args.args[1] is None
        assert body.endswith("Resets Mar 21 at 12:00 PM UTC.")

    async def test_invalid_reset_time_returns_plain_body(self):
        workflow = _make_workflow(title="Standup")

        with (
            patch("app.workers.tasks.workflow_tasks.get_user_by_id") as mock_get_user,
            patch("app.workers.tasks.workflow_tasks.format_local_time") as mock_format,
        ):
            body = await _quota_exhausted_body(workflow, "not-a-date")

        assert body == (
            "'Standup' couldn't run — you've used all your workflow executions for today."
        )
        mock_get_user.assert_not_awaited()
        mock_format.assert_not_called()


# ---------------------------------------------------------------------------
# _rate_limit_failure_content
# ---------------------------------------------------------------------------


class TestRateLimitFailureContent:
    """Direct tests for _rate_limit_failure_content."""

    async def test_cost_budget_copy_with_upgrade_for_free_user(self):
        workflow = _make_workflow(title="Standup")
        error = CostBudgetExceededException(
            feature="trigger_workflow_executions", current_plan="free"
        )

        body, upgrade_action = await _rate_limit_failure_content(error, workflow)

        assert body == (
            "'Standup' couldn't run — you're out of AI usage for today. "
            "It will run again after your usage resets. Upgrade to Pro for much higher limits."
        )
        assert upgrade_action is not None
        assert upgrade_action.type == ActionType.REDIRECT
        assert upgrade_action.label == "Upgrade to Pro"
        assert upgrade_action.style == ActionStyle.PRIMARY
        assert upgrade_action.config.redirect.url == "/settings?section=subscription"
        assert upgrade_action.config.redirect.open_in_new_tab is False
        assert upgrade_action.config.redirect.close_notification is True

    async def test_cost_budget_no_upgrade_for_pro_user(self):
        workflow = _make_workflow(title="Standup")
        error = CostBudgetExceededException(
            feature="trigger_workflow_executions", current_plan=PlanType.PRO.value
        )

        body, upgrade_action = await _rate_limit_failure_content(error, workflow)

        assert body == (
            "'Standup' couldn't run — you're out of AI usage for today. "
            "It will run again after your usage resets."
        )
        assert upgrade_action is None

    async def test_quota_copy_with_reset_time_and_upgrade(self):
        workflow = _make_workflow(title="Standup")
        error = RateLimitExceededException(
            feature="trigger_workflow_executions",
            reset_time=datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC),
            current_plan="free",
        )

        with (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.format_local_time",
                return_value="Mar 21 at 12:00 PM UTC",
            ),
        ):
            body, upgrade_action = await _rate_limit_failure_content(error, workflow)

        assert body == (
            "'Standup' couldn't run — you've used all your workflow executions for today. "
            "Resets Mar 21 at 12:00 PM UTC. Upgrade to Pro for higher daily limits."
        )
        assert upgrade_action is not None

    async def test_quota_copy_no_upgrade_for_pro_user(self):
        workflow = _make_workflow(title="Standup")
        error = RateLimitExceededException(
            feature="trigger_workflow_executions",
            reset_time=datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC),
            current_plan=PlanType.PRO.value,
        )

        with (
            patch("app.workers.tasks.workflow_tasks.get_user_by_id", new_callable=AsyncMock),
            patch(
                "app.workers.tasks.workflow_tasks.format_local_time",
                return_value="Mar 21 at 12:00 PM UTC",
            ),
        ):
            body, upgrade_action = await _rate_limit_failure_content(error, workflow)

        assert "Upgrade to Pro for higher daily limits" not in body
        assert upgrade_action is None

    async def test_plan_gated_copy_without_reset_time(self):
        workflow = _make_workflow(title="Standup")
        error = RateLimitExceededException(feature="trigger_workflow_executions")

        body, upgrade_action = await _rate_limit_failure_content(error, workflow)

        assert body == (
            "'Standup' couldn't run — automated workflow execution is not available "
            "on your current plan. Upgrade to Pro to unlock this feature."
        )
        assert upgrade_action is not None
        assert upgrade_action.label == "Upgrade to Pro"

    async def test_non_dict_detail_is_treated_as_empty(self):
        workflow = _make_workflow(title="Standup")
        error = RateLimitExceededException(feature="trigger_workflow_executions")
        error.detail = "oops"

        body, upgrade_action = await _rate_limit_failure_content(error, workflow)

        assert "not available on your current plan" in body
        assert upgrade_action is not None

    async def test_error_without_detail_attr_falls_back_to_plan_gated(self):
        workflow = _make_workflow(title="Standup")

        body, upgrade_action = await _rate_limit_failure_content(ValueError("boom"), workflow)

        assert body == (
            "'Standup' couldn't run — automated workflow execution is not available "
            "on your current plan. Upgrade to Pro to unlock this feature."
        )
        assert upgrade_action is not None


# ---------------------------------------------------------------------------
# _notify_workflow_failed
# ---------------------------------------------------------------------------


class TestNotifyWorkflowFailed:
    """Direct tests for _notify_workflow_failed."""

    async def test_generic_error_sends_failed_notification(self):
        workflow = _make_workflow(title="Standup")
        error = ValueError("boom")

        with (
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_notif.create_notification = AsyncMock()
            await _notify_workflow_failed(error, workflow)

        mock_notif.create_notification.assert_awaited_once()
        req = mock_notif.create_notification.call_args.args[0]
        assert req.user_id == workflow.user_id
        assert req.source == NotificationSourceEnum.WORKFLOW_FAILED
        assert req.type == NotificationType.ERROR
        assert req.content.title == "Workflow Failed: Standup"
        assert (
            req.content.body
            == "Your workflow 'Standup' encountered an error and could not complete."
        )
        assert req.content.actions is None
        assert req.metadata == {"workflow_id": workflow.id, "error_type": "ValueError"}

    async def test_cost_budget_sends_paused_notification(self):
        workflow = _make_workflow(title="Standup")
        error = CostBudgetExceededException(feature="trigger_workflow_executions")

        with (
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_notif.create_notification = AsyncMock()
            await _notify_workflow_failed(error, workflow)

        req = mock_notif.create_notification.call_args.args[0]
        assert req.content.title == "Workflow Paused: Standup"
        assert "It will run again after your usage resets" in req.content.body
        assert req.content.actions is not None

    async def test_rate_limit_sends_quota_copy_with_upgrade_action(self):
        workflow = _make_workflow(title="Standup")
        error = RateLimitExceededException(
            feature="trigger_workflow_executions",
            reset_time=datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC),
            current_plan="free",
        )

        with (
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
            patch("app.workers.tasks.workflow_tasks.log"),
            patch("app.workers.tasks.workflow_tasks.get_user_by_id", new_callable=AsyncMock),
            patch(
                "app.workers.tasks.workflow_tasks.format_local_time",
                return_value="Mar 21 at 12:00 PM UTC",
            ),
        ):
            mock_notif.create_notification = AsyncMock()
            await _notify_workflow_failed(error, workflow)

        req = mock_notif.create_notification.call_args.args[0]
        assert req.content.title == "Workflow Failed: Standup"
        assert "Resets Mar 21 at 12:00 PM UTC" in req.content.body
        assert req.metadata["error_type"] == "RateLimitExceededException"
        assert req.content.actions is not None

    async def test_notification_failure_is_swallowed(self):
        workflow = _make_workflow(title="Standup")

        with (
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_notif.create_notification = AsyncMock(
                side_effect=RuntimeError("notification service down")
            )
            await _notify_workflow_failed(ValueError("boom"), workflow)

        mock_log.debug.assert_called_once()
        message = mock_log.debug.call_args.args[0]
        assert "Failed to send failure notification" in message
        assert message.endswith("notification service down")


# ---------------------------------------------------------------------------
# _record_execution_failure
# ---------------------------------------------------------------------------


class TestRecordExecutionFailure:
    """Direct tests for _record_execution_failure."""

    async def test_completes_execution_and_updates_stats_with_exact_args(self):
        workflow = _make_workflow()
        error = ValueError("boom")

        with (
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_svc,
            patch(
                "app.workers.tasks.workflow_tasks._notify_workflow_failed",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_svc.increment_execution_count = AsyncMock()
            await _record_execution_failure(error, workflow, workflow.id, "exec_1")

        mock_complete.assert_awaited_once_with(
            execution_id="exec_1", status="failed", error_message="boom"
        )
        mock_svc.increment_execution_count.assert_awaited_once_with(
            workflow.id, workflow.user_id, is_successful=False
        )
        mock_notify.assert_awaited_once_with(error, workflow)

    async def test_no_execution_id_skips_complete(self):
        workflow = _make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_svc,
            patch(
                "app.workers.tasks.workflow_tasks._notify_workflow_failed",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_svc.increment_execution_count = AsyncMock()
            await _record_execution_failure(ValueError("boom"), workflow, workflow.id, None)

        mock_complete.assert_not_awaited()
        mock_svc.increment_execution_count.assert_awaited_once()
        mock_notify.assert_awaited_once()

    async def test_workflow_none_skips_stats_and_notify(self):
        with (
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_svc,
            patch(
                "app.workers.tasks.workflow_tasks._notify_workflow_failed",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_svc.increment_execution_count = AsyncMock()
            await _record_execution_failure(ValueError("boom"), None, "wf_1", "exec_1")

        mock_complete.assert_awaited_once()
        mock_svc.increment_execution_count.assert_not_awaited()
        mock_notify.assert_not_awaited()

    async def test_cost_budget_exceeded_does_not_count_failure(self):
        workflow = _make_workflow()
        error = CostBudgetExceededException(feature="trigger_workflow_executions")

        with (
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                new_callable=AsyncMock,
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_svc,
            patch(
                "app.workers.tasks.workflow_tasks._notify_workflow_failed",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_svc.increment_execution_count = AsyncMock()
            await _record_execution_failure(error, workflow, workflow.id, None)

        mock_svc.increment_execution_count.assert_not_awaited()
        mock_notify.assert_awaited_once_with(error, workflow)

    async def test_complete_failure_does_not_mask_stats_and_notify(self):
        workflow = _make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db write failed"),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_svc,
            patch(
                "app.workers.tasks.workflow_tasks._notify_workflow_failed",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_svc.increment_execution_count = AsyncMock()
            await _record_execution_failure(ValueError("boom"), workflow, workflow.id, "exec_1")

        mock_svc.increment_execution_count.assert_awaited_once()
        mock_notify.assert_awaited_once()
        message = mock_log.debug.call_args.args[0]
        assert "Failed to complete execution record" in message
        assert message.endswith("db write failed")

    async def test_stats_failure_does_not_mask_notify(self):
        workflow = _make_workflow()

        with (
            patch(
                "app.workers.tasks.workflow_tasks.complete_execution",
                new_callable=AsyncMock,
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_svc,
            patch(
                "app.workers.tasks.workflow_tasks._notify_workflow_failed",
                new_callable=AsyncMock,
            ) as mock_notify,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_svc.increment_execution_count = AsyncMock(
                side_effect=RuntimeError("stats db down")
            )
            await _record_execution_failure(ValueError("boom"), workflow, workflow.id, "exec_1")

        mock_notify.assert_awaited_once()
        message = mock_log.debug.call_args.args[0]
        assert "Failed to update workflow stats" in message
        assert message.endswith("stats db down")


# ---------------------------------------------------------------------------
# execute_workflow_by_id — exact args, claim, budget, drift, re-arm
# ---------------------------------------------------------------------------


class TestExecuteWorkflowByIdExactArgs:
    """Exact-arg and boundary coverage for execute_workflow_by_id."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    @pytest.fixture
    def workflow_id(self) -> str:
        return str(uuid4())

    async def test_workflow_not_found_exact_return_and_cleanup(self, ctx, workflow_id):
        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=None)
        mock_scheduler_cls.return_value = mock_scheduler

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowScheduler", mock_scheduler_cls),
            patch("app.workers.tasks.workflow_tasks.create_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            result = await execute_workflow_by_id(ctx, workflow_id)

        assert result == f"Workflow {workflow_id} not found"
        mock_scheduler.initialize.assert_awaited_once()
        mock_scheduler.get_task.assert_awaited_once_with(workflow_id)
        mock_scheduler.close.assert_awaited_once()

    async def test_scheduled_fire_already_claimed_skips_execution(self, ctx):
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler.claim_scheduled_for_execution = AsyncMock(return_value=False)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create = AsyncMock()
        mock_chat = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowScheduler", mock_scheduler_cls),
            patch("app.workers.tasks.workflow_tasks.create_execution", mock_create),
            patch("app.workers.tasks.workflow_tasks.execute_workflow_as_chat", mock_chat),
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            result = await execute_workflow_by_id(
                ctx, workflow.id, context={"trigger_type": TriggerType.SCHEDULE.value}
            )

        assert result == f"Workflow {workflow.id} already claimed; skipped duplicate scheduled fire"
        mock_scheduler.claim_scheduled_for_execution.assert_awaited_once_with(workflow.id)
        mock_create.assert_not_awaited()
        mock_chat.assert_not_awaited()
        mock_scheduler.handle_recurring_task.assert_not_awaited()
        mock_scheduler.close.assert_awaited_once()

    async def test_scheduled_fire_claims_and_rearms_next_occurrence(self, ctx):
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        workflow.occurrence_count = 2
        workflow.scheduled_at = None

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler.claim_scheduled_for_execution = AsyncMock(return_value=True)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec_1"
        mock_create = AsyncMock(return_value=mock_execution)
        mock_complete = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowScheduler", mock_scheduler_cls),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_1"),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.create_execution", mock_create),
            patch("app.workers.tasks.workflow_tasks.complete_execution", mock_complete),
            patch(
                "app.workers.tasks.workflow_tasks.enforce_daily_cost_budget",
                AsyncMock(),
            ) as mock_budget,
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id(
                ctx, workflow.id, context={"trigger_type": TriggerType.SCHEDULE.value}
            )

        assert result == f"Workflow {workflow.id} executed successfully"
        mock_scheduler.claim_scheduled_for_execution.assert_awaited_once_with(workflow.id)
        mock_budget.assert_awaited_once_with(
            workflow.user_id, feature_key="trigger_workflow_executions"
        )
        mock_create.assert_awaited_once_with(
            workflow_id=workflow.id, user_id=workflow.user_id, trigger_type="schedule"
        )
        mock_scheduler.handle_recurring_task.assert_awaited_once_with(workflow, 3)

    async def test_cost_budget_exceeded_pauses_not_fails(self, ctx):
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        workflow.occurrence_count = 0
        workflow.scheduled_at = None

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler.claim_scheduled_for_execution = AsyncMock(return_value=True)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create = AsyncMock()
        budget_error = CostBudgetExceededException(
            feature="trigger_workflow_executions", current_plan="free"
        )

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowScheduler", mock_scheduler_cls),
            patch("app.workers.tasks.workflow_tasks.create_execution", mock_create),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
            patch(
                "app.workers.tasks.workflow_tasks.enforce_daily_cost_budget",
                AsyncMock(side_effect=budget_error),
            ),
            patch("app.workers.tasks.workflow_tasks.log"),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            mock_notif.create_notification = AsyncMock()
            result = await execute_workflow_by_id(
                ctx, workflow.id, context={"trigger_type": TriggerType.SCHEDULE.value}
            )

        assert result == f"Error executing workflow {workflow.id}: {budget_error}"
        mock_create.assert_not_awaited()
        mock_wf_svc.increment_execution_count.assert_not_awaited()
        req = mock_notif.create_notification.call_args.args[0]
        assert req.content.title == f"Workflow Paused: {workflow.title}"
        mock_scheduler.handle_recurring_task.assert_awaited_once_with(workflow, 1)

    async def test_schedule_drift_recorded_on_fire(self, ctx):
        workflow = _make_workflow()
        workflow.repeat = "0 9 * * *"
        workflow.activated = True
        workflow.scheduled_at = datetime.now(UTC) - timedelta(minutes=10)

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler.claim_scheduled_for_execution = AsyncMock(return_value=True)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec_1"

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowScheduler", mock_scheduler_cls),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_1"),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.enforce_daily_cost_budget", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            await execute_workflow_by_id(ctx, workflow.id)

        drift_calls = [
            call
            for call in mock_log.set.call_args_list
            if "drift_from_scheduled_seconds" in call.kwargs
        ]
        assert len(drift_calls) == 1
        assert drift_calls[0].kwargs["drift_from_scheduled_seconds"] > 300
        assert mock_log.warning.call_args.kwargs["drift"] > 300
        assert mock_log.warning.call_args.kwargs["workflow_id"] == workflow.id


# ---------------------------------------------------------------------------
# process_workflow_generation_task — exact args
# ---------------------------------------------------------------------------


class TestProcessWorkflowGenerationTaskExactArgs:
    """Exact-arg coverage for process_workflow_generation_task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_create_workflow_receives_exact_request(self, ctx):
        todo_id = "507f1f77bcf86cd799439016"
        user_id = "user_abc"
        workflow = _make_workflow(user_id=user_id)
        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        captured = {}

        async def capture_create(request, uid, **kwargs):
            captured["request"] = request
            captured["kwargs"] = kwargs
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
            mock_ws_mgr.return_value = mock_ws

            result = await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", "Get milk and eggs"
            )

        request = captured["request"]
        assert captured["kwargs"] == {"is_todo_workflow": True, "source_todo_id": todo_id}
        assert request.title == "Todo: Buy groceries"
        assert request.description == "Automated workflow to complete: Buy groceries"
        assert "**Details:** Get milk and eggs" in request.prompt
        assert "Buy groceries" in request.prompt
        assert request.trigger_config.type == TriggerType.MANUAL
        assert request.trigger_config.enabled is True
        assert request.generate_immediately is True
        assert (
            result == f"Successfully generated standalone workflow {workflow.id} for todo {todo_id}"
        )

    async def test_todo_update_receives_exact_args(self, ctx):
        todo_id = "507f1f77bcf86cd799439017"
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
            mock_ws_mgr.return_value = mock_ws

            await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

        call = mock_repo.update.await_args
        assert call.args == (todo_id,)
        assert call.kwargs["user_id"] == user_id
        update = call.kwargs["update"]
        assert isinstance(update, TodoUpdate)
        assert update.workflow_id == workflow.id

    async def test_websocket_success_payload_and_clear_flag(self, ctx):
        todo_id = "507f1f77bcf86cd799439018"
        user_id = "user_abc"
        workflow = _make_workflow(user_id=user_id)
        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        mock_ws = AsyncMock()
        mock_clear = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager", return_value=mock_ws),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                mock_clear,
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_repo.update = AsyncMock(return_value=mock_todo_result)

            await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

        mock_ws.broadcast_to_user.assert_awaited_once()
        call = mock_ws.broadcast_to_user.await_args
        assert call.args[0] == user_id
        payload = call.args[1]
        assert payload["type"] == "workflow.generated"
        assert payload["todo_id"] == todo_id
        workflow.model_dump.assert_called_once_with(mode="json")
        assert payload["workflow"] == workflow.model_dump()
        mock_clear.assert_awaited_once_with(todo_id)

    async def test_failure_path_clears_flag_and_broadcasts_error(self, ctx):
        todo_id = str(ObjectId())
        user_id = "user_abc"
        mock_ws = AsyncMock()
        mock_clear = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager", return_value=mock_ws),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                mock_clear,
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=RuntimeError("LLM exploded"))

            with pytest.raises(RuntimeError, match="LLM exploded"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

        mock_clear.assert_awaited_once_with(todo_id)
        call = mock_ws.broadcast_to_user.await_args
        assert call.args[0] == user_id
        payload = call.args[1]
        assert payload["type"] == "workflow.generation_failed"
        assert payload["todo_id"] == todo_id
        assert payload["error"] == "LLM exploded"

    async def test_success_path_logs_exact_context(self, ctx):
        todo_id = "507f1f77bcf86cd799439019"
        user_id = "user_abc"
        workflow = _make_workflow(user_id=user_id)
        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 1

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todo_repository") as mock_repo,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_repo.update = AsyncMock(return_value=mock_todo_result)
            mock_ws = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", "Get milk and eggs"
            )

        assert mock_log.set.call_args_list[0].kwargs == {
            "todo_id": todo_id,
            "user_id": user_id,
            "user": {"id": user_id},
        }
        info_calls = [c for c in mock_log.info.call_args_list if "standalone" in c.args[0]]
        assert len(info_calls) == 1
        assert (
            info_calls[0].args[0]
            == "[WORKER] Successfully generated and linked standalone workflow"
        )
        assert info_calls[0].kwargs == {
            "workflow_id": workflow.id,
            "todo_id": todo_id,
            "steps_count": 1,
        }
        workflow_sets = [c for c in mock_log.set.call_args_list if "workflow" in c.kwargs]
        assert len(workflow_sets) == 1
        assert workflow_sets[0].kwargs["workflow"] == {
            "id": workflow.id,
            "steps_count": 1,
            "trigger_type": "manual",
        }
        assert mock_log.set.call_args_list[-1].kwargs == {"websocket_broadcast_success": True}

    async def test_no_workflow_created_logs_error_with_exact_args(self, ctx):
        todo_id = str(ObjectId())
        user_id = "user_abc"

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=None)
            mock_ws = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(AppError, match="Workflow generation failed"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

        error_call = [
            c for c in mock_log.error.call_args_list if "no workflow created" in c.args[0]
        ]
        assert len(error_call) == 1
        assert error_call[0].args[0] == (
            "[WORKER] Failed to generate workflow for todo: no workflow created"
        )
        assert error_call[0].kwargs == {"todo_id": todo_id, "user_id": user_id}


# ---------------------------------------------------------------------------
# execute_workflow_as_chat — exact trigger context, request, timezone
# ---------------------------------------------------------------------------


class TestExecuteWorkflowAsChatExactArgs:
    """Exact trigger-context, request-shape and timezone coverage for
    execute_workflow_as_chat."""

    def _make_workflow(self, **overrides):
        wf = MagicMock()
        wf.id = str(ObjectId())
        wf.user_id = "user_abc"
        wf.title = "Morning Briefing"
        wf.description = "Daily morning workflow"
        wf.prompt = "Run the morning briefing"
        wf.steps = [MagicMock(id="s1", title="Step 1", description="Check mail", category="comms")]
        wf.notify_on_completion = True
        wf.trigger_config = MagicMock()
        wf.trigger_config.timezone = None
        for key, value in overrides.items():
            setattr(wf, key, value)
        return wf

    def _patches(self, user_data=None):
        return (
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value=(
                    {"user_id": "user_abc", "timezone": "UTC"} if user_data is None else user_data
                ),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value="conv_x",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=("Done", {}),
            ),
        )

    async def test_trigger_context_exact_fields(self):
        workflow = self._make_workflow()
        p1, p2, p3, p4 = self._patches()

        with p1, p2, p3, p4 as mock_call_agent:
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {"foo": "bar"})

        trigger_context = mock_call_agent.call_args.kwargs["trigger_context"]
        assert trigger_context == {
            "foo": "bar",
            "workflow_id": workflow.id,
            "workflow_title": workflow.title,
            "workflow_notify_on_completion": True,
            "execution_mode": "background",
        }

    async def test_trigger_context_notify_on_completion_false(self):
        workflow = self._make_workflow(notify_on_completion=False)
        p1, p2, p3, p4 = self._patches()

        with p1, p2, p3, p4 as mock_call_agent:
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        trigger_context = mock_call_agent.call_args.kwargs["trigger_context"]
        assert trigger_context["workflow_notify_on_completion"] is False

    async def test_request_exact_shape(self):
        workflow = self._make_workflow()
        p1, p2, p3, p4 = self._patches()

        with p1, p2, p3, p4 as mock_call_agent:
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        request = mock_call_agent.call_args.kwargs["request"]
        assert request.message == "Execute workflow: Morning Briefing"
        assert request.messages == []
        assert request.fileIds == []
        assert request.fileData == []
        assert request.selectedTool is None
        assert request.selectedWorkflow.id == workflow.id
        assert request.selectedWorkflow.title == workflow.title
        assert request.selectedWorkflow.description == workflow.description
        assert request.selectedWorkflow.prompt == workflow.prompt
        assert request.selectedWorkflow.steps == [
            {"id": "s1", "title": "Step 1", "description": "Check mail", "category": "comms"}
        ]

    async def test_trigger_message_persisted_exactly(self):
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
                return_value="conv_x",
            ),
            patch(
                "app.workers.tasks.workflow_tasks.add_workflow_execution_messages",
                new_callable=AsyncMock,
            ) as mock_store,
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=("Done", {}),
            ),
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        mock_store.assert_awaited_once()
        call = mock_store.await_args
        assert call.kwargs["conversation_id"] == "conv_x"
        assert call.kwargs["user_id"] == workflow.user_id
        messages = call.kwargs["workflow_execution_messages"]
        assert len(messages) == 1
        user_msg = messages[0]
        assert user_msg.type == "user"
        assert user_msg.response == ""
        assert user_msg.selectedWorkflow.id == workflow.id
        assert user_msg.selectedWorkflow.steps == [
            {"id": "s1", "title": "Step 1", "description": "Check mail", "category": "comms"}
        ]

    async def test_profile_timezone_wins(self):
        workflow = self._make_workflow()
        p1, p2, p3, p4 = self._patches(
            user_data={"user_id": workflow.user_id, "timezone": "America/New_York"}
        )

        with p1, p2, p3, p4 as mock_call_agent:
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        assert mock_call_agent.call_args.kwargs["user"]["timezone"] == "America/New_York"

    async def test_profile_utc_falls_back_to_schedule_timezone(self):
        workflow = self._make_workflow()
        workflow.trigger_config.timezone = "Asia/Kolkata"
        p1, p2, p3, p4 = self._patches(user_data={"user_id": workflow.user_id, "timezone": "UTC"})

        with p1, p2, p3, p4 as mock_call_agent:
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        assert mock_call_agent.call_args.kwargs["user"]["timezone"] == "Asia/Kolkata"

    async def test_no_timezones_falls_back_to_utc_with_warning(self):
        workflow = self._make_workflow()
        p1, p2, p3, p4 = self._patches(user_data={"user_id": workflow.user_id})

        with (
            p1,
            p2,
            p3,
            p4 as mock_call_agent,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        assert mock_call_agent.call_args.kwargs["user"]["timezone"] == "UTC"
        assert mock_log.warning.called

    async def test_success_path_logs_exact_context(self):
        workflow = self._make_workflow()
        p1, p2, p3, p4 = self._patches()

        with p1, p2, p3, p4, patch("app.workers.tasks.workflow_tasks.log") as mock_log:
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        info_calls = [c for c in mock_log.info.call_args_list]
        assert len(info_calls) == 1
        assert info_calls[0].args[0] == "[WORKER] Executing workflow as chat session"
        assert info_calls[0].kwargs == {
            "workflow_id": workflow.id,
            "user_id": workflow.user_id,
        }
        set_kwargs = [c.kwargs for c in mock_log.set.call_args_list]
        assert {"conversation_context_found": True} in set_kwargs
        assert {"workflow_agent_timezone": "UTC"} in set_kwargs

    async def test_agent_failure_logs_exact_error(self):
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
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            with pytest.raises(RuntimeError, match="Agent crashed"):
                await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        error_call = mock_log.error.call_args
        assert error_call.args[0] == "workflow_chat_execution_failed"
        assert error_call.kwargs == {
            "workflow_id": workflow.id,
            "workflow_title": workflow.title,
            "user_id": workflow.user_id,
            "error_type": "RuntimeError",
            "error": "Agent crashed",
            "outcome": "agent_error",
            "exc_info": True,
        }


# ---------------------------------------------------------------------------
# generate_workflow_steps — exact args and payload
# ---------------------------------------------------------------------------


class TestGenerateWorkflowStepsExactArgs:
    """Exact-arg coverage for generate_workflow_steps."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_service_calls_payload_and_exact_return(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"
        todo_id = "todo_1"
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=True,
            source_todo_id=todo_id,
        )

        mock_ws = AsyncMock()

        with (
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            result = await generate_workflow_steps(ctx, workflow_id, user_id)

        assert result == f"Successfully generated steps for workflow {workflow_id}"
        mock_wf_svc._generate_workflow_steps.assert_awaited_once_with(workflow_id, user_id)
        mock_wf_svc.get_workflow.assert_awaited_once_with(workflow_id, user_id)
        mock_ws.broadcast_to_user.assert_awaited_once()
        call = mock_ws.broadcast_to_user.await_args
        assert call.args[0] == user_id
        payload = call.args[1]
        assert payload["type"] == "workflow.generated"
        assert payload["todo_id"] == todo_id
        workflow.model_dump.assert_called_once_with(mode="json")
        assert payload["workflow"] == workflow.model_dump()

    async def test_logs_exact_context(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=True,
            source_todo_id="todo_1",
        )

        with (
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)
            mock_ws = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            await generate_workflow_steps(ctx, workflow_id, user_id)

        assert mock_log.set.call_args_list[0].kwargs == {
            "workflow_id": workflow_id,
            "user_id": user_id,
        }
        workflow_sets = [c for c in mock_log.set.call_args_list if "workflow" in c.kwargs]
        assert len(workflow_sets) == 1
        assert workflow_sets[0].kwargs["workflow"]["id"] == workflow_id
        assert workflow_sets[0].kwargs["workflow"]["steps_count"] == 1
        info_calls = mock_log.info.call_args_list
        assert len(info_calls) == 1
        assert info_calls[0].args[0] == "[WORKER] Successfully generated workflow steps"
        assert info_calls[0].kwargs == {"workflow_id": workflow_id}
        assert mock_log.set.call_args_list[-1].kwargs == {"websocket_broadcast_success": True}

    async def test_websocket_failure_logs_exact_warning(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"
        workflow = _make_workflow(
            workflow_id=workflow_id,
            is_todo_workflow=True,
            source_todo_id="todo_1",
        )

        mock_ws = MagicMock()
        mock_ws.broadcast_to_user = AsyncMock(side_effect=RuntimeError("WS error"))

        with (
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws,
            ),
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_wf_svc._generate_workflow_steps = AsyncMock()
            mock_wf_svc.get_workflow = AsyncMock(return_value=workflow)

            await generate_workflow_steps(ctx, workflow_id, user_id)

        assert mock_log.set.call_args_list[-1].kwargs == {"websocket_broadcast_success": False}
        warning = mock_log.warning.call_args
        assert warning.args[0] == "[WORKER] Failed to send WebSocket event"
        assert warning.kwargs == {
            "error_type": "RuntimeError",
            "error": "WS error",
            "workflow_id": workflow_id,
            "user_id": user_id,
        }


# ---------------------------------------------------------------------------
# regenerate_workflow_steps — exact return
# ---------------------------------------------------------------------------


class TestRegenerateWorkflowStepsExactReturn:
    """Exact return-value coverage for regenerate_workflow_steps."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_exact_return_value(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"

        with patch("app.services.workflow.WorkflowService") as mock_wf_svc:
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            result = await regenerate_workflow_steps(ctx, workflow_id, user_id, "reason", True)

        assert result == f"Successfully regenerated steps for workflow {workflow_id}"

    async def test_logs_exact_context(self, ctx):
        workflow_id = str(uuid4())
        user_id = "user_abc"

        with (
            patch("app.services.workflow.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            mock_wf_svc.regenerate_workflow_steps = AsyncMock()
            await regenerate_workflow_steps(ctx, workflow_id, user_id, "Steps were wrong")

        mock_log.set.assert_called_once_with(
            workflow_id=workflow_id, user_id=user_id, user={"id": user_id}
        )
        info_calls = mock_log.info.call_args_list
        assert len(info_calls) == 2
        assert info_calls[0].args[0] == "[WORKER] Regenerating workflow steps"
        assert info_calls[0].kwargs == {
            "workflow_id": workflow_id,
            "user_id": user_id,
            "reason": "Steps were wrong",
        }
        assert info_calls[1].args[0] == "[WORKER] Successfully regenerated workflow steps"
        assert info_calls[1].kwargs == {"workflow_id": workflow_id}
