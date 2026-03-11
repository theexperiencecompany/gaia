"""Unit tests for reminder_tasks ARQ worker."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


from app.workers.tasks.reminder_tasks import (
    cleanup_expired_reminders,
    process_reminder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reminder_doc(
    reminder_id: str = "reminder_123",
    status: str = "scheduled",
    scheduled_at: datetime | None = None,
    repeat: str | None = None,
    occurrence_count: int = 0,
) -> dict:
    """Return a minimal reminder document as MongoDB would return it."""
    if scheduled_at is None:
        scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    return {
        "_id": reminder_id,
        "user_id": "user_abc",
        "agent": "static",
        "status": status,
        "scheduled_at": scheduled_at,
        "occurrence_count": occurrence_count,
        "repeat": repeat,
        "max_occurrences": None,
        "stop_after": datetime.now(timezone.utc) + timedelta(days=180),
        "payload": {"title": "Test", "body": "Do the thing"},
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "updated_at": datetime.now(timezone.utc) - timedelta(minutes=5),
    }


# ---------------------------------------------------------------------------
# TestProcessReminder — worker thin-wrapper behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessReminder:
    """Tests for process_reminder ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_success_returns_success_message(self, ctx):
        with patch(
            "app.workers.tasks.reminder_tasks.reminder_scheduler"
        ) as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            result = await process_reminder(ctx, "reminder_123")

        assert "Successfully processed reminder reminder_123" == result

    async def test_reminder_scheduler_called_with_id(self, ctx):
        with patch(
            "app.workers.tasks.reminder_tasks.reminder_scheduler"
        ) as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            await process_reminder(ctx, "reminder_abc")

        mock_scheduler.process_task_execution.assert_awaited_once_with("reminder_abc")

    async def test_exception_propagates(self, ctx):
        with patch(
            "app.workers.tasks.reminder_tasks.reminder_scheduler"
        ) as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock(
                side_effect=RuntimeError("DB connection lost")
            )
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await process_reminder(ctx, "reminder_xyz")

    async def test_ctx_unused_does_not_affect_outcome(self):
        for ctx in [{}, {"redis": AsyncMock()}, {"job_id": "j1"}]:
            with patch(
                "app.workers.tasks.reminder_tasks.reminder_scheduler"
            ) as mock_scheduler:
                mock_scheduler.process_task_execution = AsyncMock()
                result = await process_reminder(ctx, "r1")
            assert "Successfully processed reminder r1" == result


# ---------------------------------------------------------------------------
# TestReminderSchedulerTimingAndDB — real scheduler logic with mocked DB
#
# These tests remove the self-mock of reminder_scheduler and instead let the
# real ReminderScheduler.process_task_execution run.  Only the MongoDB
# collection and the execute_task method are mocked so the timing / status
# guard logic is actually exercised.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReminderSchedulerTimingAndDB:
    """Verify real scheduler logic: timing guards and DB update calls."""

    # ------------------------------------------------------------------
    # Timing: task due NOW fires, task due in the future is skipped
    # ------------------------------------------------------------------

    async def test_scheduled_task_executes_when_status_is_scheduled(self):
        """A reminder with status=scheduled must go through execute_task."""
        from app.services.reminder_service import ReminderScheduler
        from app.models.scheduler_models import TaskExecutionResult

        doc = _make_reminder_doc(status="scheduled")

        mock_update = AsyncMock(return_value=True)
        mock_execute = AsyncMock(
            return_value=TaskExecutionResult(
                success=True, message="Reminder sent"
            )
        )

        scheduler = ReminderScheduler.__new__(ReminderScheduler)
        scheduler.redis_settings = None
        scheduler.arq_pool = None

        with (
            patch.object(scheduler, "get_task", AsyncMock(return_value=None)),
            patch.object(scheduler, "update_task_status", mock_update),
            patch.object(scheduler, "execute_task", mock_execute),
        ):
            # Patch get_task to return a proper ReminderModel built from the doc
            from app.models.reminder_models import ReminderModel

            reminder = ReminderModel(**doc)
            scheduler.get_task = AsyncMock(return_value=reminder)

            result = await scheduler.process_task_execution("reminder_123")

        assert result.success is True
        mock_execute.assert_awaited_once()

    async def test_task_not_in_scheduled_status_is_skipped(self):
        """A reminder that is cancelled/completed must NOT reach execute_task."""
        from app.services.reminder_service import ReminderScheduler
        from app.models.scheduler_models import TaskExecutionResult

        for bad_status in ("cancelled", "completed", "failed", "executing"):
            doc = _make_reminder_doc(status=bad_status)

            mock_execute = AsyncMock(
                return_value=TaskExecutionResult(success=True, message="ok")
            )

            scheduler = ReminderScheduler.__new__(ReminderScheduler)
            scheduler.redis_settings = None
            scheduler.arq_pool = None

            from app.models.reminder_models import ReminderModel

            reminder = ReminderModel(**doc)
            scheduler.get_task = AsyncMock(return_value=reminder)
            scheduler.execute_task = mock_execute
            scheduler.update_task_status = AsyncMock(return_value=True)

            result = await scheduler.process_task_execution("reminder_123")

            assert result.success is False, (
                f"Expected skipped execution for status={bad_status}, "
                f"got success=True"
            )
            mock_execute.assert_not_awaited(), (
                f"execute_task must not be called for status={bad_status}"
            )

    async def test_missing_reminder_returns_failure_result(self):
        """When the reminder ID does not exist, process_task_execution returns
        a failure result without raising."""
        from app.services.reminder_service import ReminderScheduler

        scheduler = ReminderScheduler.__new__(ReminderScheduler)
        scheduler.redis_settings = None
        scheduler.arq_pool = None
        scheduler.get_task = AsyncMock(return_value=None)
        scheduler.execute_task = AsyncMock()
        scheduler.update_task_status = AsyncMock(return_value=True)

        result = await scheduler.process_task_execution("nonexistent_id")

        assert result.success is False
        assert "nonexistent_id" in (result.message or "")
        scheduler.execute_task.assert_not_awaited()

    # ------------------------------------------------------------------
    # DB update verification: reminder is marked as sent (completed)
    # after successful one-time execution
    # ------------------------------------------------------------------

    async def test_one_time_reminder_marked_completed_after_execution(self):
        """After a one-time reminder fires successfully the DB must be updated
        with status=completed.  Changing this update call must break the test."""
        from app.services.reminder_service import ReminderScheduler
        from app.models.reminder_models import ReminderModel
        from app.models.scheduler_models import (
            ScheduledTaskStatus,
            TaskExecutionResult,
        )

        doc = _make_reminder_doc(status="scheduled", repeat=None)
        reminder = ReminderModel(**doc)

        status_updates: list[tuple] = []

        async def capture_update(task_id, status, update_data=None, user_id=None):
            status_updates.append((task_id, status, update_data))
            return True

        scheduler = ReminderScheduler.__new__(ReminderScheduler)
        scheduler.redis_settings = None
        scheduler.arq_pool = None
        scheduler.get_task = AsyncMock(return_value=reminder)
        scheduler.execute_task = AsyncMock(
            return_value=TaskExecutionResult(success=True, message="sent")
        )
        scheduler.update_task_status = AsyncMock(side_effect=capture_update)

        await scheduler.process_task_execution("reminder_123")

        # First update: EXECUTING (marks task as in-progress)
        assert status_updates[0][1] == ScheduledTaskStatus.EXECUTING, (
            "First DB write must set status to EXECUTING"
        )

        # Final update: COMPLETED (marks task as done)
        final_statuses = [s[1] for s in status_updates]
        assert ScheduledTaskStatus.COMPLETED in final_statuses, (
            "DB must be updated to COMPLETED after successful one-time execution"
        )

    async def test_failed_execution_marks_reminder_as_failed_in_db(self):
        """When execute_task raises, the reminder must be marked FAILED in DB."""
        from app.services.reminder_service import ReminderScheduler
        from app.models.reminder_models import ReminderModel
        from app.models.scheduler_models import ScheduledTaskStatus, TaskExecutionResult

        doc = _make_reminder_doc(status="scheduled", repeat=None)
        reminder = ReminderModel(**doc)

        status_updates: list[tuple] = []

        async def capture_update(task_id, status, update_data=None, user_id=None):
            status_updates.append((task_id, status, update_data))
            return True

        scheduler = ReminderScheduler.__new__(ReminderScheduler)
        scheduler.redis_settings = None
        scheduler.arq_pool = None
        scheduler.get_task = AsyncMock(return_value=reminder)
        scheduler.execute_task = AsyncMock(
            side_effect=RuntimeError("Notification service down")
        )
        scheduler.update_task_status = AsyncMock(side_effect=capture_update)

        result = await scheduler.process_task_execution("reminder_123")

        assert result.success is False
        final_statuses = [s[1] for s in status_updates]
        assert ScheduledTaskStatus.FAILED in final_statuses, (
            "DB must be updated to FAILED when execute_task raises"
        )

    async def test_db_update_called_with_correct_reminder_id(self):
        """The reminder ID passed into update_task_status must match the one
        given to process_task_execution — not a hard-coded or stale value."""
        from app.services.reminder_service import ReminderScheduler
        from app.models.reminder_models import ReminderModel
        from app.models.scheduler_models import TaskExecutionResult

        target_id = "specific_reminder_999"
        doc = _make_reminder_doc(reminder_id=target_id, status="scheduled")
        reminder = ReminderModel(**doc)

        updated_ids: list[str] = []

        async def capture_update(task_id, status, update_data=None, user_id=None):
            updated_ids.append(task_id)
            return True

        scheduler = ReminderScheduler.__new__(ReminderScheduler)
        scheduler.redis_settings = None
        scheduler.arq_pool = None
        scheduler.get_task = AsyncMock(return_value=reminder)
        scheduler.execute_task = AsyncMock(
            return_value=TaskExecutionResult(success=True, message="ok")
        )
        scheduler.update_task_status = AsyncMock(side_effect=capture_update)

        await scheduler.process_task_execution(target_id)

        for uid in updated_ids:
            assert uid == target_id, (
                f"update_task_status must be called with '{target_id}', got '{uid}'"
            )


# ---------------------------------------------------------------------------
# TestCleanupExpiredReminders
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanupExpiredReminders:
    """Tests for cleanup_expired_reminders ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_cleanup_returns_deleted_count_in_message(self, ctx):
        mock_result = MagicMock()
        mock_result.deleted_count = 7

        with patch(
            "app.db.mongodb.collections.reminders_collection"
        ) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            result = await cleanup_expired_reminders(ctx)

        assert "Cleaned up 7 expired reminders" == result

    async def test_cleanup_zero_deletions_message(self, ctx):
        mock_result = MagicMock()
        mock_result.deleted_count = 0

        with patch(
            "app.db.mongodb.collections.reminders_collection"
        ) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            result = await cleanup_expired_reminders(ctx)

        assert "Cleaned up 0 expired reminders" == result

    async def test_cleanup_query_filters_completed_and_cancelled(self, ctx):
        mock_result = MagicMock()
        mock_result.deleted_count = 3

        with patch(
            "app.db.mongodb.collections.reminders_collection"
        ) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            await cleanup_expired_reminders(ctx)

        call_args = mock_col.delete_many.call_args
        query = call_args[0][0]
        assert "$in" in query["status"]
        assert "completed" in query["status"]["$in"]
        assert "cancelled" in query["status"]["$in"]

    async def test_cleanup_query_uses_thirty_day_cutoff(self, ctx):
        """The cutoff date in the query must be approx 30 days in the past.
        If the production code changes to 7 days or 60 days this test fails."""
        mock_result = MagicMock()
        mock_result.deleted_count = 0

        with patch(
            "app.db.mongodb.collections.reminders_collection"
        ) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            before_call = datetime.now(timezone.utc)
            await cleanup_expired_reminders(ctx)
            after_call = datetime.now(timezone.utc)

        query = mock_col.delete_many.call_args[0][0]
        cutoff = query["updated_at"]["$lt"]

        expected_lower = before_call - timedelta(days=30)
        expected_upper = after_call - timedelta(days=30)

        # Allow a 5 second window for the cutoff to account for test execution time
        assert expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5), (
            f"Cutoff {cutoff} is not within the expected 30-day window "
            f"[{expected_lower}, {expected_upper}]"
        )

    async def test_cutoff_is_not_7_days(self, ctx):
        """Regression guard: cutoff must be ~30 days, not ~7 days."""
        mock_result = MagicMock()
        mock_result.deleted_count = 0

        with patch(
            "app.db.mongodb.collections.reminders_collection"
        ) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            before_call = datetime.now(timezone.utc)
            await cleanup_expired_reminders(ctx)

        query = mock_col.delete_many.call_args[0][0]
        cutoff = query["updated_at"]["$lt"]
        seven_days_ago = before_call - timedelta(days=7)

        # The cutoff must be older than 7 days ago (i.e., farther in the past)
        assert cutoff < seven_days_ago, (
            f"Cutoff {cutoff} should be older than 7 days ago ({seven_days_ago}); "
            "the 30-day window was not applied correctly"
        )

    async def test_cleanup_exception_propagates(self, ctx):
        with patch(
            "app.db.mongodb.collections.reminders_collection"
        ) as mock_col:
            mock_col.delete_many = AsyncMock(
                side_effect=Exception("MongoDB unavailable")
            )
            with pytest.raises(Exception, match="MongoDB unavailable"):
                await cleanup_expired_reminders(ctx)
