"""Unit tests for reminder_tasks ARQ worker."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


from app.workers.tasks.reminder_tasks import (
    cleanup_expired_reminders,
    process_reminder,
)


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


@pytest.mark.unit
class TestCleanupExpiredReminders:
    """Tests for cleanup_expired_reminders ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_cleanup_returns_deleted_count_in_message(self, ctx):
        mock_result = MagicMock()
        mock_result.deleted_count = 7

        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            result = await cleanup_expired_reminders(ctx)

        assert mock_col.delete_many.called
        assert "Cleaned up 7 expired reminders" == result

    async def test_cleanup_zero_deletions_message(self, ctx):
        mock_result = MagicMock()
        mock_result.deleted_count = 0

        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            result = await cleanup_expired_reminders(ctx)

        assert mock_col.delete_many.called
        assert "Cleaned up 0 expired reminders" == result

    async def test_cleanup_query_filters_completed_and_cancelled(self, ctx):
        mock_result = MagicMock()
        mock_result.deleted_count = 3

        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            await cleanup_expired_reminders(ctx)

        call_args = mock_col.delete_many.call_args
        query = call_args[0][0]
        assert "$in" in query["status"]
        assert "completed" in query["status"]["$in"]
        assert "cancelled" in query["status"]["$in"]

    async def test_cleanup_query_uses_thirty_day_cutoff(self, ctx):
        """The cutoff date in the query must be approx 30 days in the past."""
        from datetime import datetime, timedelta, timezone

        mock_result = MagicMock()
        mock_result.deleted_count = 0

        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(return_value=mock_result)
            before_call = datetime.now(timezone.utc)
            await cleanup_expired_reminders(ctx)
            after_call = datetime.now(timezone.utc)

        query = mock_col.delete_many.call_args[0][0]
        cutoff = query["updated_at"]["$lt"]

        expected_lower = before_call - timedelta(days=30)
        expected_upper = after_call - timedelta(days=30)

        # Allow a 5 second window for the cutoff to account for test execution time
        assert (
            expected_lower - timedelta(seconds=5)
            <= cutoff
            <= expected_upper + timedelta(seconds=5)
        )

    async def test_cleanup_exception_propagates(self, ctx):
        with patch("app.db.mongodb.collections.reminders_collection") as mock_col:
            mock_col.delete_many = AsyncMock(
                side_effect=Exception("MongoDB unavailable")
            )
            with pytest.raises(Exception, match="MongoDB unavailable"):
                await cleanup_expired_reminders(ctx)
