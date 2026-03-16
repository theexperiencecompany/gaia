"""Unit tests for workflow_tasks ARQ worker."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId

from app.workers.tasks.workflow_tasks import (
    execute_workflow_by_id,
    execute_workflow_as_chat,
    process_workflow_generation_task,
    regenerate_workflow_steps,
    generate_workflow_steps,
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

    def _patch_dependencies(self, workflow, execution_messages=None):
        """Return a context manager that patches all external collaborators."""
        if execution_messages is None:
            bot_msg = MagicMock()
            bot_msg.type = "bot"
            bot_msg.response = "Done!"
            user_msg = MagicMock()
            user_msg.type = "user"
            execution_messages = [user_msg, bot_msg]

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        patches = [
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                autospec=True,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                new_callable=AsyncMock,
                return_value=execution_messages,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowService",
                autospec=True,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.create_workflow_completion_notification",
                new_callable=AsyncMock,
                return_value={"conversation_id": str(uuid4())},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.notification_service",
            ),
        ]
        return patches

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
        bot_msg = MagicMock()
        bot_msg.type = "bot"
        bot_msg.response = "All steps done"
        user_msg = MagicMock()
        user_msg.type = "user"
        execution_messages = [user_msg, bot_msg]

        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid4())

        mock_scheduler_cls = MagicMock()
        mock_scheduler = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=workflow)
        mock_scheduler_cls.return_value = mock_scheduler

        mock_create_exec = AsyncMock(return_value=mock_execution)
        mock_complete_exec = AsyncMock()
        mock_increment = AsyncMock()
        mock_completion_notif = AsyncMock(return_value={"conversation_id": "conv_1"})
        mock_execute_chat = AsyncMock(return_value=execution_messages)

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
                "app.workers.tasks.workflow_tasks.create_workflow_completion_notification",
                mock_completion_notif,
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
        assert "executed successfully" in result
        assert workflow.id in result

    async def test_execution_count_incremented_on_success(self, ctx):
        workflow = _make_workflow()
        bot_msg = MagicMock()
        bot_msg.type = "bot"
        bot_msg.response = "Done"
        execution_messages = [bot_msg]

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
                AsyncMock(return_value=execution_messages),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_workflow_completion_notification",
                AsyncMock(return_value={"conversation_id": "conv_1"}),
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
            await execute_workflow_by_id(ctx, workflow.id)

        mock_scheduler.initialize.assert_awaited_once()
        mock_increment.assert_awaited_once_with(
            workflow.id, workflow.user_id, is_successful=True
        )

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
        mock_increment.assert_awaited_once_with(
            workflow.id, workflow.user_id, is_successful=False
        )
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

        bot_msg = MagicMock()
        bot_msg.type = "bot"
        bot_msg.response = "Done"

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=[bot_msg]),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_workflow_completion_notification",
                AsyncMock(return_value={"conversation_id": "conv_1"}),
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
        bot_msg = MagicMock()
        bot_msg.type = "bot"
        bot_msg.response = "OK"

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                mock_scheduler_cls,
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value=[bot_msg]),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.create_workflow_completion_notification",
                AsyncMock(return_value={"conversation_id": "c1"}),
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
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager"
            ) as mock_ws_mgr,
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
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager"
            ) as mock_ws_mgr,
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
                await process_workflow_generation_task(
                    ctx, todo_id, user_id, "Todo title"
                )

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
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager"
            ) as mock_ws_mgr,
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
                await process_workflow_generation_task(
                    ctx, todo_id, user_id, "Todo title"
                )

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
            mock_wf_svc.create_workflow = AsyncMock(
                side_effect=RuntimeError("DB error")
            )

            with pytest.raises(RuntimeError):
                await process_workflow_generation_task(
                    ctx, todo_id, user_id, "Todo title"
                )

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
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager"
            ) as mock_ws_mgr,
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
            result = await regenerate_workflow_steps(
                ctx, workflow_id, user_id, "Steps were wrong"
            )

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
            mock_wf_svc._generate_workflow_steps = AsyncMock(
                side_effect=RuntimeError("LLM error")
            )

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
            MagicMock(
                id="s1", title="Step 1", description="Check mail", category="comms"
            ),
            MagicMock(id="s2", title="Step 2", description="Weather", category="info"),
        ]
        return wf

    def _patch_io(
        self,
        user_data=None,
        conversation_id="conv_abc",
        agent_response=("All done.", {}),
    ):
        """Return a list of context-manager patches covering every I/O boundary."""
        return [
            patch(
                "app.workers.tasks.workflow_tasks.get_user_by_id",
                new_callable=AsyncMock,
                return_value=user_data or {"user_id": "user_abc", "timezone": "UTC"},
            ),
            patch(
                "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
                new_callable=AsyncMock,
                return_value={"conversation_id": conversation_id},
            ),
            patch(
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=agent_response,
            ),
        ]

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
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=("Result text", {}),
            ) as mock_call_agent,
        ):
            messages = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        # Conversation was fetched for this workflow and user
        mock_get_conv.assert_awaited_once_with(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            workflow_title=workflow.title,
        )

        # Agent was invoked with the correct conversation_id
        call_kwargs = mock_call_agent.call_args
        assert call_kwargs.kwargs["conversation_id"] == expected_conv_id

        # Returns a user message followed by a bot message
        assert len(messages) == 2
        assert messages[0].type == "user"
        assert messages[1].type == "bot"
        assert messages[1].response == "Result text"

    async def test_successful_execution_returns_user_then_bot_message(self):
        """On success the function returns exactly [user_message, bot_message]."""
        workflow = self._make_workflow()
        agent_text = "Step 1 done. Step 2 done."

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
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=(agent_text, {}),
            ),
        ):
            messages = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        assert len(messages) == 2
        user_msg, bot_msg = messages
        assert user_msg.type == "user"
        assert bot_msg.type == "bot"
        assert bot_msg.response == agent_text

    async def test_exception_in_agent_returns_error_message_not_reraise(self):
        """When call_agent_silent raises, the function catches and returns a single
        error MessageModel rather than propagating the exception.
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
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Agent crashed"),
            ),
        ):
            # Must NOT raise — internal exception handling returns an error message
            messages = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        assert len(messages) == 1
        error_msg = messages[0]
        assert error_msg.type == "bot"
        assert "Workflow Execution Failed" in error_msg.response
        assert workflow.title in error_msg.response

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
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=("Fallback result", {}),
            ) as mock_call_agent,
        ):
            messages = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

        # Execution completes successfully despite user fetch failing
        assert len(messages) == 2
        assert messages[1].response == "Fallback result"

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
                "app.agents.core.agent.call_agent_silent",
                new_callable=AsyncMock,
                return_value=("Done", {}),
            ) as mock_call_agent,
        ):
            await execute_workflow_as_chat(workflow, {"user_id": workflow.user_id}, {})

        request_arg = mock_call_agent.call_args.kwargs["request"]
        assert request_arg.selectedWorkflow is not None
        assert request_arg.selectedWorkflow.id == workflow.id
        # Both steps must be present
        step_ids = [s["id"] for s in request_arg.selectedWorkflow.steps]
        assert "s1" in step_ids
        assert "s2" in step_ids
