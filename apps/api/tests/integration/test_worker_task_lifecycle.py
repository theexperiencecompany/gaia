"""
Integration tests for Background Worker Task Lifecycle (ARQ).

Tests the real ARQ task functions with mocked I/O boundaries (MongoDB,
Redis, external services). Verifies that each task function:
- Calls the correct service/DB methods
- Handles success and error paths
- Returns meaningful result messages
- Processes data correctly before delegating to services
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from freezegun import freeze_time as _freeze_time
import pytest

from app.models.user_models import OnboardingPhase
from app.workers.lifecycle.startup import startup
from app.workers.tasks.cleanup_tasks import cleanup_stuck_personalization
from app.workers.tasks.memory_email_tasks import process_gmail_emails_to_memory
from app.workers.tasks.onboarding_tasks import process_onboarding_intelligence_task
from app.workers.tasks.reminder_tasks import (
    cleanup_expired_reminders,
    process_reminder,
)
from app.workers.tasks.user_tasks import check_inactive_users
from app.workers.tasks.workflow_tasks import (
    execute_workflow_by_id,
    process_workflow_generation_task,
)

# freezegun's module-restore logic collides with the transformers library
# (references to torch at class-definition scope). Ignoring transformers
# avoids NameError: name 'torch' is not defined during freeze_time teardown.
_FREEZEGUN_IGNORE = ["transformers"]


def freeze_time(*args, **kwargs):
    """Wrapper that always passes ignore=['transformers']."""
    kwargs.setdefault("ignore", _FREEZEGUN_IGNORE)
    return _freeze_time(*args, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_REMINDER_ID = str(ObjectId())
ARQ_CTX: dict = {}

# ---------------------------------------------------------------------------
# TEST 1: Reminder task execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReminderTaskExecution:
    """Verify process_reminder delegates to the scheduler and returns a result."""

    async def test_process_reminder_success(self):
        """Import the real task, call it, verify it invokes process_task_execution."""

        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()

            result = await process_reminder(ARQ_CTX, FAKE_REMINDER_ID)

            mock_scheduler.process_task_execution.assert_awaited_once_with(FAKE_REMINDER_ID)
            assert FAKE_REMINDER_ID in result
            assert "Successfully" in result

    async def test_process_reminder_propagates_scheduler_error(self):
        """If the scheduler raises, the error should propagate (not be swallowed)."""

        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock(
                side_effect=RuntimeError("DB connection lost")
            )

            with pytest.raises(RuntimeError, match="DB connection lost"):
                await process_reminder(ARQ_CTX, FAKE_REMINDER_ID)

    @freeze_time("2026-04-01T12:00:00Z")
    async def test_cleanup_expired_reminders_deletes_old_completed(self):
        """cleanup_expired_reminders should delete completed/cancelled reminders older than 30 days."""

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 5

        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_delete_result)

            result = await cleanup_expired_reminders(ARQ_CTX)

            mock_col.delete_many.assert_awaited_once()
            call_filter = mock_col.delete_many.call_args[0][0]

            # Verify the query targets completed/cancelled statuses
            assert call_filter["status"]["$in"] == ["completed", "cancelled"]

            # Verify the cutoff date is 30 days ago from the frozen time
            expected_cutoff = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
            actual_cutoff = call_filter["updated_at"]["$lt"]
            assert abs((actual_cutoff - expected_cutoff).total_seconds()) < 2

            assert "5" in result
            assert "Cleaned up" in result

    @freeze_time("2026-04-01T12:00:00Z")
    async def test_cleanup_expired_reminders_zero_deleted(self):
        """When no expired reminders exist, report zero deleted."""

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0

        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_delete_result)

            result = await cleanup_expired_reminders(ARQ_CTX)
            assert "0" in result


# ---------------------------------------------------------------------------
# TEST 2: Email memory extraction (process_gmail_emails_to_memory)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEmailMemoryExtraction:
    """Verify the email memory task delegates to process_gmail_to_memory."""

    async def test_already_processed_short_circuits(self):
        """If emails are already processed, return early."""

        with patch("app.workers.tasks.memory_email_tasks.process_gmail_to_memory") as mock_proc:
            mock_proc.return_value = {
                "already_processed": True,
                "total": 0,
                "successful": 0,
            }

            result = await process_gmail_emails_to_memory(ARQ_CTX, FAKE_USER_ID)

            mock_proc.assert_awaited_once_with(FAKE_USER_ID)
            assert "already processed" in result

    async def test_successful_processing(self):
        """Successful run should report total and successful counts."""

        with patch("app.workers.tasks.memory_email_tasks.process_gmail_to_memory") as mock_proc:
            mock_proc.return_value = {
                "already_processed": False,
                "total": 50,
                "successful": 48,
                "failed": 2,
                "processing_complete": True,
            }

            result = await process_gmail_emails_to_memory(ARQ_CTX, FAKE_USER_ID)

            assert "48/50" in result
            assert "completed" in result.lower()

    async def test_incomplete_processing_reports_failure(self):
        """When processing is incomplete, the message should reflect failure."""

        with patch("app.workers.tasks.memory_email_tasks.process_gmail_to_memory") as mock_proc:
            mock_proc.return_value = {
                "already_processed": False,
                "total": 50,
                "successful": 20,
                "failed": 30,
                "processing_complete": False,
            }

            result = await process_gmail_emails_to_memory(ARQ_CTX, FAKE_USER_ID)

            assert "failed" in result.lower()
            assert "30" in result


# ---------------------------------------------------------------------------
# TEST 3: Cleanup task safety (cleanup_stuck_personalization)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCleanupTaskSafety:
    """Verify cleanup only touches stuck users, not active/completed ones."""

    async def test_cleanup_requeues_stuck_users(self):
        """Stuck users at PERSONALIZATION_PENDING phase should be re-queued."""

        stuck_user_id = ObjectId()
        stuck_user = {
            "_id": stuck_user_id,
            "onboarding": {
                "phase": OnboardingPhase.PERSONALIZATION_PENDING.value,
            },
            "updated_at": datetime(2026, 3, 31, 10, 0, 0, tzinfo=UTC),
        }

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[stuck_user])

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_users,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="job-123",
            ) as mock_enqueue,
        ):
            mock_users.find.return_value = mock_cursor

            result = await cleanup_stuck_personalization(ARQ_CTX, max_age_minutes=30)

            # Verify the query filters for the personalization-pending phase
            find_call = mock_users.find.call_args[0][0]
            assert find_call["onboarding.phase"] == OnboardingPhase.PERSONALIZATION_PENDING.value

            # Verify re-queue was called with the correct user id
            mock_enqueue.assert_awaited_once_with(str(stuck_user_id))

            assert "1 re-queued" in result
            assert "0 errors" in result

    async def test_cleanup_no_stuck_users(self):
        """When no stuck users exist, return a clean message."""

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_users:
            mock_users.find.return_value = mock_cursor

            result = await cleanup_stuck_personalization(ARQ_CTX, max_age_minutes=30)

            assert "No stuck users found" in result

    async def test_cleanup_handles_enqueue_failure_gracefully(self):
        """If enqueue_intelligence_job returns None for a user, count it as an error."""

        stuck_user = {
            "_id": ObjectId(),
            "onboarding": {"phase": OnboardingPhase.PERSONALIZATION_PENDING.value},
            "updated_at": datetime(2026, 3, 30, tzinfo=UTC),
        }

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[stuck_user])

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_users,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value=None,  # None means enqueue failed
            ),
        ):
            mock_users.find.return_value = mock_cursor

            result = await cleanup_stuck_personalization(ARQ_CTX, max_age_minutes=30)

            assert "0 re-queued" in result
            assert "1 errors" in result

    async def test_cleanup_handles_db_error(self):
        """If the DB query itself fails, return an error message rather than crashing."""

        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_users:
            mock_users.find.side_effect = RuntimeError("MongoDB down")

            result = await cleanup_stuck_personalization(ARQ_CTX, max_age_minutes=30)

            assert "Error" in result
            assert "MongoDB down" in result


# ---------------------------------------------------------------------------
# TEST 4: Task error handling (various tasks with invalid input)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTaskErrorHandling:
    """Verify tasks do not silently swallow errors on invalid input."""

    async def test_process_reminder_with_none_id_propagates(self):
        """Passing None as reminder_id should propagate through to the scheduler."""

        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock(
                side_effect=TypeError("expected str, got NoneType")
            )

            with pytest.raises(TypeError):
                await process_reminder(ARQ_CTX, None)

    async def test_email_task_propagates_processor_error(self):
        """If process_gmail_to_memory raises, it should propagate."""

        with patch("app.workers.tasks.memory_email_tasks.process_gmail_to_memory") as mock_proc:
            mock_proc.side_effect = ValueError("Invalid user ID format")

            with pytest.raises(ValueError, match="Invalid user ID format"):
                await process_gmail_emails_to_memory(ARQ_CTX, "bad-id")

    async def test_onboarding_task_reports_service_error(self):
        """If the intelligence service raises, the task catches it and returns a failure message."""

        with (
            patch(
                "app.services.onboarding.intelligence_service.process_onboarding_intelligence",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM timeout"),
            ),
            patch("app.workers.tasks.onboarding_tasks.users_collection") as mock_users,
        ):
            mock_users.update_one = AsyncMock()

            result = await process_onboarding_intelligence_task(ARQ_CTX, FAKE_USER_ID)

            assert "failed" in result.lower()
            assert "LLM timeout" in result
            assert FAKE_USER_ID in result


# ---------------------------------------------------------------------------
# TEST 5: Workflow task execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowTaskExecution:
    """Verify workflow execution tracks success/failure and sends notifications."""

    async def test_execute_workflow_not_found(self):
        """When workflow ID does not exist, return a not-found message."""

        mock_scheduler = AsyncMock()
        mock_scheduler.initialize = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=None)
        mock_scheduler.close = AsyncMock()

        with patch(
            "app.workers.tasks.workflow_tasks.WorkflowScheduler",
            return_value=mock_scheduler,
        ):
            result = await execute_workflow_by_id(ARQ_CTX, "nonexistent-wf-id")

            assert "not found" in result

    async def test_execute_workflow_success_increments_count(self):
        """Successful execution should increment execution count and create execution record."""

        mock_workflow = MagicMock()
        mock_workflow.id = "wf-123"
        mock_workflow.user_id = FAKE_USER_ID
        mock_workflow.title = "Test Workflow"
        mock_workflow.steps = [MagicMock(), MagicMock()]

        mock_scheduler = AsyncMock()
        mock_scheduler.initialize = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=mock_workflow)
        mock_scheduler.close = AsyncMock()

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-456"

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                return_value=mock_scheduler,
            ),
            patch(
                "app.services.workflow.execution_service.create_execution",
                new_callable=AsyncMock,
                return_value=mock_execution,
            ) as mock_create_exec,
            patch(
                "app.services.workflow.execution_service.complete_execution",
                new_callable=AsyncMock,
            ) as mock_complete_exec,
            # execute_workflow_as_chat now returns a conversation_id str (not a list of messages)
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                new_callable=AsyncMock,
                return_value="conv-789",
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_service,
        ):
            mock_wf_service.increment_execution_count = AsyncMock()

            result = await execute_workflow_by_id(ARQ_CTX, "wf-123")

            # Verify execution record created
            mock_create_exec.assert_awaited_once()
            create_kwargs = mock_create_exec.call_args[1]
            assert create_kwargs["workflow_id"] == "wf-123"
            assert create_kwargs["user_id"] == FAKE_USER_ID

            # Verify execution count incremented with success=True
            mock_wf_service.increment_execution_count.assert_awaited_once_with(
                "wf-123", FAKE_USER_ID, is_successful=True
            )

            # Verify execution completed with the conversation_id returned by execute_workflow_as_chat
            mock_complete_exec.assert_awaited_once()
            complete_kwargs = mock_complete_exec.call_args[1]
            assert complete_kwargs["status"] == "success"
            assert complete_kwargs["execution_id"] == "exec-456"
            assert complete_kwargs["conversation_id"] == "conv-789"

            assert "successfully" in result

    async def test_execute_workflow_failure_records_error(self):
        """Failed execution should record failure and send error notification."""

        mock_workflow = MagicMock()
        mock_workflow.id = "wf-fail"
        mock_workflow.user_id = FAKE_USER_ID
        mock_workflow.title = "Failing Workflow"
        mock_workflow.steps = [MagicMock()]

        mock_scheduler = AsyncMock()
        mock_scheduler.initialize = AsyncMock()
        mock_scheduler.get_task = AsyncMock(return_value=mock_workflow)
        mock_scheduler.close = AsyncMock()

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-err"

        with (
            patch(
                "app.workers.tasks.workflow_tasks.WorkflowScheduler",
                return_value=mock_scheduler,
            ),
            patch(
                "app.services.workflow.execution_service.create_execution",
                new_callable=AsyncMock,
                return_value=mock_execution,
            ),
            patch(
                "app.services.workflow.execution_service.complete_execution",
                new_callable=AsyncMock,
            ) as mock_complete_exec,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Agent crashed"),
            ),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_service,
            patch("app.workers.tasks.workflow_tasks.notification_service") as mock_notif,
        ):
            mock_wf_service.increment_execution_count = AsyncMock()
            mock_notif.create_notification = AsyncMock()

            result = await execute_workflow_by_id(ARQ_CTX, "wf-fail")

            # Verify execution completed with failure
            mock_complete_exec.assert_awaited_once()
            complete_kwargs = mock_complete_exec.call_args[1]
            assert complete_kwargs["status"] == "failed"
            assert "Agent crashed" in complete_kwargs["error_message"]

            # Verify failure count incremented
            mock_wf_service.increment_execution_count.assert_awaited_once_with(
                "wf-fail", FAKE_USER_ID, is_successful=False
            )

            # Verify failure notification sent
            mock_notif.create_notification.assert_awaited_once()

            assert "Error" in result


# ---------------------------------------------------------------------------
# TEST 6: Worker startup hooks
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkerStartupHooks:
    """Verify the ARQ startup function initializes required services."""

    async def test_startup_calls_unified_startup(self):
        """The startup hook should invoke unified_startup with 'arq_worker'."""

        with patch(
            "app.workers.lifecycle.startup.unified_startup",
            new_callable=AsyncMock,
        ) as mock_unified:
            ctx: dict = {}
            await startup(ctx)

            mock_unified.assert_awaited_once_with("arq_worker")
            assert "startup_time" in ctx

    async def test_startup_stores_startup_time_in_context(self):
        """The startup hook should record a startup_time in the ARQ context dict."""

        with patch(
            "app.workers.lifecycle.startup.unified_startup",
            new_callable=AsyncMock,
        ):
            ctx: dict = {}
            await startup(ctx)

            assert "startup_time" in ctx
            assert isinstance(ctx["startup_time"], float)
            assert ctx["startup_time"] > 0


# ---------------------------------------------------------------------------
# TEST 7: User task (check_inactive_users)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUserTasks:
    """Verify inactive user detection and email sending."""

    @freeze_time("2026-04-01T12:00:00Z")
    async def test_check_inactive_users_sends_emails(self):
        """Inactive users older than 7 days should receive an email."""

        inactive_user = {
            "_id": ObjectId(),
            "email": "inactive@example.com",
            "name": "Inactive User",
            "last_active_at": datetime(2026, 3, 20, tzinfo=UTC).replace(tzinfo=None),
            "is_active": True,
        }

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[inactive_user])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_users,
            patch("app.utils.email_utils.send_inactive_user_email") as mock_send,
        ):
            mock_users.find.return_value = mock_cursor
            mock_send.return_value = True

            result = await check_inactive_users(ARQ_CTX)

            mock_send.assert_awaited_once_with(
                user_email="inactive@example.com",
                user_name="Inactive User",
                user_id=str(inactive_user["_id"]),
            )
            assert "1 inactive users" in result
            assert "sent 1 emails" in result

    @freeze_time("2026-04-01T12:00:00Z")
    async def test_check_inactive_users_no_inactive(self):
        """When no inactive users are found, report zero."""

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch("app.db.mongodb.collections.users_collection") as mock_users:
            mock_users.find.return_value = mock_cursor

            result = await check_inactive_users(ARQ_CTX)

            assert "0 inactive users" in result
            assert "sent 0 emails" in result

    @freeze_time("2026-04-01T12:00:00Z")
    async def test_check_inactive_users_email_failure_counted(self):
        """When sending an email fails, count it as a failure but continue."""

        users = [
            {
                "_id": ObjectId(),
                "email": "fail@example.com",
                "name": "Fail User",
                "last_active_at": datetime(2026, 3, 15).replace(tzinfo=None),
            },
            {
                "_id": ObjectId(),
                "email": "ok@example.com",
                "name": "OK User",
                "last_active_at": datetime(2026, 3, 15).replace(tzinfo=None),
            },
        ]

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_users,
            patch("app.utils.email_utils.send_inactive_user_email") as mock_send,
        ):
            mock_users.find.return_value = mock_cursor
            # First call raises, second succeeds
            mock_send.side_effect = [
                ConnectionError("SMTP down"),
                True,
            ]

            result = await check_inactive_users(ARQ_CTX)

            assert mock_send.await_count == 2
            # Only 1 email sent successfully
            assert "sent 1 emails" in result


# ---------------------------------------------------------------------------
# TEST 8: Onboarding task
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOnboardingTask:
    """Verify onboarding task delegates correctly."""

    async def test_onboarding_intelligence_task_success(self):
        """Successful run should call the intelligence service and return a message."""

        with patch(
            "app.services.onboarding.intelligence_service.process_onboarding_intelligence",
            new_callable=AsyncMock,
        ) as mock_service:
            result = await process_onboarding_intelligence_task(ARQ_CTX, FAKE_USER_ID)

            mock_service.assert_awaited_once_with(FAKE_USER_ID)
            assert "onboarding intelligence completed" in result.lower()
            assert FAKE_USER_ID in result


# ---------------------------------------------------------------------------
# TEST 9: Workflow generation task
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowGenerationTask:
    """Verify workflow generation creates workflow and links to todo."""

    async def test_generation_success_links_workflow_to_todo(self):
        """Successful generation should create a workflow, update the todo, and broadcast."""

        mock_workflow = MagicMock()
        mock_workflow.id = "wf-gen-1"
        mock_workflow.steps = [MagicMock(), MagicMock(), MagicMock()]
        mock_workflow.model_dump = MagicMock(return_value={"id": "wf-gen-1"})

        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1

        mock_ws_manager = AsyncMock()
        mock_ws_manager.broadcast_to_user = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.todos_collection") as mock_todos,
            patch("app.workers.tasks.workflow_tasks.TodoService") as mock_todo_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws_manager,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService",
            ) as mock_queue_svc,
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=mock_workflow)
            mock_todos.update_one = AsyncMock(return_value=mock_update_result)
            mock_todo_svc._invalidate_cache = AsyncMock()
            mock_queue_svc.clear_workflow_generating_flag = AsyncMock()

            result = await process_workflow_generation_task(
                ARQ_CTX,
                todo_id="aaaaaaaaaaaaaaaaaaaaaaaa",
                user_id=FAKE_USER_ID,
                title="Write report",
                description="Quarterly report",
            )

            # Verify workflow was created
            mock_wf_svc.create_workflow.assert_awaited_once()

            # Verify todo was updated with workflow_id
            mock_todos.update_one.assert_awaited_once()
            update_filter = mock_todos.update_one.call_args[0][0]
            assert update_filter["_id"] == ObjectId("aaaaaaaaaaaaaaaaaaaaaaaa")
            update_set = mock_todos.update_one.call_args[0][1]["$set"]
            assert update_set["workflow_id"] == "wf-gen-1"

            # Verify WebSocket broadcast
            mock_ws_manager.broadcast_to_user.assert_awaited_once()
            ws_data = mock_ws_manager.broadcast_to_user.call_args[0][1]
            assert ws_data["type"] == "workflow.generated"
            assert ws_data["todo_id"] == "aaaaaaaaaaaaaaaaaaaaaaaa"

            # Verify generating flag cleared
            mock_queue_svc.clear_workflow_generating_flag.assert_awaited_once_with(
                "aaaaaaaaaaaaaaaaaaaaaaaa"
            )

            assert "Successfully" in result

    async def test_generation_failure_clears_flag_and_broadcasts_error(self):
        """When workflow generation fails, clear the flag and broadcast failure."""

        mock_ws_manager = AsyncMock()
        mock_ws_manager.broadcast_to_user = AsyncMock()

        with (
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.get_websocket_manager",
                return_value=mock_ws_manager,
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService",
            ) as mock_queue_svc,
        ):
            mock_wf_svc.create_workflow = AsyncMock(return_value=None)
            mock_queue_svc.clear_workflow_generating_flag = AsyncMock()

            with pytest.raises(ValueError, match="No workflow created"):
                await process_workflow_generation_task(
                    ARQ_CTX,
                    todo_id="bbbbbbbbbbbbbbbbbbbbbbbb",
                    user_id=FAKE_USER_ID,
                    title="Fail task",
                )

            # Verify flag cleared even on failure
            mock_queue_svc.clear_workflow_generating_flag.assert_awaited_once_with(
                "bbbbbbbbbbbbbbbbbbbbbbbb"
            )

            # Verify failure WebSocket broadcast
            mock_ws_manager.broadcast_to_user.assert_awaited_once()
            ws_data = mock_ws_manager.broadcast_to_user.call_args[0][1]
            assert ws_data["type"] == "workflow.generation_failed"
            assert ws_data["todo_id"] == "bbbbbbbbbbbbbbbbbbbbbbbb"
