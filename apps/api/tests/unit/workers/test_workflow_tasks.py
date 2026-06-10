"""Unit tests for workflow_tasks ARQ worker."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.models.notification.notification_models import NotificationSourceEnum
from app.services.workflow.notifications import (
    send_workflow_completion_notification,
    send_workflow_failure_notification,
)
from app.workers.tasks.workflow_tasks import (
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


@pytest.mark.unit
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
                "app.services.workflow.execution_service.create_execution",
                mock_create_execution,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                mock_create_exec,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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


@pytest.mark.unit
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
            patch("app.workers.tasks.workflow_tasks.todos_collection") as mock_todos,
            patch("app.workers.tasks.workflow_tasks.TodoService") as mock_todo_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_todos.update_one = AsyncMock(return_value=mock_todo_result)
            mock_todo_svc._invalidate_cache = AsyncMock()

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

            with pytest.raises(ValueError, match="Workflow generation failed"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")

    async def test_todo_not_updated_raises(self, ctx):
        # Must be a valid 24-char hex ObjectId string because production code
        # calls ObjectId(todo_id) before the mocked update_one is invoked.
        todo_id = "507f1f77bcf86cd799439012"
        user_id = "user_abc"
        workflow = _make_workflow(user_id=user_id)

        mock_todo_result = MagicMock()
        mock_todo_result.modified_count = 0

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todos_collection") as mock_todos,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=workflow)
            mock_todos.update_one = AsyncMock(return_value=mock_todo_result)
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            with pytest.raises(ValueError, match="not found or not updated"):
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
            patch("app.workers.tasks.workflow_tasks.todos_collection") as mock_todos,
            patch("app.workers.tasks.workflow_tasks.TodoService") as mock_todo_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=capture_create)
            mock_todos.update_one = AsyncMock(return_value=mock_todo_result)
            mock_todo_svc._invalidate_cache = AsyncMock()
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
                return_value={"conversation_id": expected_conv_id},
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
                return_value={"conversation_id": "conv_123"},
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
                return_value={"conversation_id": "conv_ctx"},
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
                return_value={"conversation_id": "conv_1"},
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
                return_value={"conversation_id": "conv_fallback"},
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
                return_value={"conversation_id": "conv_steps"},
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
                return_value={"conversation_id": "conv_none"},
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
                return_value={"conversation_id": "conv_usermsg"},
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


@pytest.mark.unit
class TestWorkflowNotificationSenders:
    """Tests for the workflow completion/failure notification senders."""

    async def test_completion_notification_sent_with_split_messages(self):
        """send_workflow_completion_notification splits the result text on the
        message break and sends one notification."""
        with (
            patch(
                "app.services.workflow.notifications.notification_service",
            ) as mock_notif,
            patch(
                "app.services.workflow.notifications.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"timezone": "Asia/Kolkata"},
            ),
        ):
            mock_notif.create_notification = AsyncMock()
            await send_workflow_completion_notification(
                workflow_id="wf_1",
                workflow_title="Morning Briefing",
                conversation_id="conv_123",
                user_id="user_abc",
                result_text="got emails<NEW_MESSAGE_BREAK>and calendar",
            )

        mock_notif.create_notification.assert_awaited_once()
        notif_req = mock_notif.create_notification.call_args[0][0]
        # Human, WhatsApp-style copy: exact phrasing rotates, but the workflow
        # name is always woven into the title and there's a casual body.
        assert "Morning Briefing" in notif_req.content.title
        assert notif_req.content.body
        assert notif_req.content.rich_content["type"] == "workflow_execution"
        assert notif_req.content.rich_content["messages"] == ["got emails", "and calendar"]

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


@pytest.mark.unit
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
            "app.services.workflow.execution_service.create_execution",
            AsyncMock(return_value=mock_execution),
        )
        p_complete = patch(
            "app.services.workflow.execution_service.complete_execution",
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
        assert "PRO" in notif_req.content.body
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
        assert "PRO" in notif_req.content.body

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
                "app.services.workflow.execution_service.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                AsyncMock(side_effect=RuntimeError("DB unavailable")),
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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
                "app.services.workflow.execution_service.create_execution",
                AsyncMock(return_value=mock_execution),
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
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


@pytest.mark.unit
class TestProcessWorkflowGenerationTaskAdditional:
    """Additional edge-case tests for process_workflow_generation_task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_workflow_created_with_no_steps_raises_value_error(self, ctx):
        """If workflow is created but has zero steps, a ValueError is raised."""
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

            with pytest.raises(ValueError, match="has no steps"):
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

            with pytest.raises(ValueError, match="unknown error"):
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
            patch("app.workers.tasks.workflow_tasks.todos_collection") as mock_todos,
            patch("app.workers.tasks.workflow_tasks.TodoService") as mock_todo_svc,
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
            mock_todos.update_one = AsyncMock(return_value=mock_todo_result)
            mock_todo_svc._invalidate_cache = AsyncMock()

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
            patch("app.workers.tasks.workflow_tasks.todos_collection") as mock_todos,
            patch("app.workers.tasks.workflow_tasks.TodoService") as mock_todo_svc,
            patch("app.workers.tasks.workflow_tasks.get_websocket_manager") as mock_ws_mgr,
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.clear_workflow_generating_flag",
                AsyncMock(),
            ),
        ):
            mock_wf_svc.create_workflow = AsyncMock(side_effect=capture_create)
            mock_todos.update_one = AsyncMock(return_value=mock_todo_result)
            mock_todo_svc._invalidate_cache = AsyncMock()
            mock_ws = AsyncMock()
            mock_ws.broadcast_to_user = AsyncMock()
            mock_ws_mgr.return_value = mock_ws

            await process_workflow_generation_task(
                ctx, todo_id, user_id, "Buy groceries", description="Milk, eggs, bread"
            )

        assert len(captured_requests) == 1
        assert "**Details:** Milk, eggs, bread" in captured_requests[0].prompt

    async def test_workflow_with_no_id_raises(self, ctx):
        """If workflow.id is falsy after creation, it raises ValueError."""
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

            with pytest.raises(ValueError, match="Workflow generation failed"):
                await process_workflow_generation_task(ctx, todo_id, user_id, "Todo title")


# ---------------------------------------------------------------------------
# generate_workflow_steps — additional coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
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
