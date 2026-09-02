"""Unit tests for reminder_tasks ARQ worker."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.reminder_tasks import (
    cleanup_expired_reminders,
    process_reminder,
)
from tests.helpers import captured_wide_event


class TestProcessReminder:
    """Tests for process_reminder ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_success_returns_success_message(self, ctx):
        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            result = await process_reminder(ctx, "reminder_123")

        assert result == "Successfully processed reminder reminder_123"

    async def test_reminder_scheduler_called_with_id(self, ctx):
        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            await process_reminder(ctx, "reminder_abc")

        # Unstamped (a job enqueued before the stamp existed) claims on status alone.
        mock_scheduler.process_task_execution.assert_awaited_once_with("reminder_abc", None)

    async def test_occurrence_stamp_is_passed_through_to_the_claim(self, ctx):
        """The armed occurrence pins the claim, so a stale sibling job is rejected."""
        armed = datetime(2099, 1, 15, 12, 0, tzinfo=UTC)
        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            await process_reminder(ctx, "reminder_abc", int(armed.timestamp()))

        mock_scheduler.process_task_execution.assert_awaited_once_with("reminder_abc", armed)

    async def test_garbage_stamp_is_ignored_not_crashed(self, ctx):
        """A non-numeric stamp degrades to an unstamped claim instead of raising."""
        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            await process_reminder(ctx, "reminder_abc", "not-a-number")  # type: ignore[arg-type]  # deliberately bad-typed stamp: proves a non-numeric stamp degrades to an unstamped claim

        mock_scheduler.process_task_execution.assert_awaited_once_with("reminder_abc", None)

    async def test_parses_the_stamp_scoped_to_this_reminder(self, ctx):
        # The reminder id is passed to the parser (for its diagnostics) and the
        # parsed occurrence is what pins the claim.
        with (
            patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler,
            patch(
                "app.workers.tasks.reminder_tasks.parse_occurrence_stamp", return_value="OCC"
            ) as parse,
        ):
            mock_scheduler.process_task_execution = AsyncMock()
            await process_reminder(ctx, "reminder_abc", 777)

        parse.assert_called_once_with(777, "reminder_abc")
        mock_scheduler.process_task_execution.assert_awaited_once_with("reminder_abc", "OCC")

    async def test_stamps_the_wide_event_with_the_reminder_and_schedule(self, ctx):
        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock()
            async with captured_wide_event() as event:
                await process_reminder(ctx, "reminder_abc", 777)

        assert event["reminder_id"] == "reminder_abc"
        assert event["scheduled_for"] == 777

    async def test_exception_propagates(self, ctx):
        with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
            mock_scheduler.process_task_execution = AsyncMock(
                side_effect=RuntimeError("DB connection lost")
            )
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await process_reminder(ctx, "reminder_xyz")

    async def test_ctx_unused_does_not_affect_outcome(self):
        for ctx in [{}, {"redis": AsyncMock()}, {"job_id": "j1"}]:
            with patch("app.workers.tasks.reminder_tasks.reminder_scheduler") as mock_scheduler:
                mock_scheduler.process_task_execution = AsyncMock()
                result = await process_reminder(ctx, "r1")
            assert result == "Successfully processed reminder r1"


class TestCleanupExpiredReminders:
    """Tests for cleanup_expired_reminders ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    # The status/date filter is the repository's contract (proven in
    # tests/contracts/test_reminders_repository.py::test_delete_finished_before);
    # here we assert delegation and that the worker owns the 30-day cutoff.

    async def test_cleanup_returns_deleted_count_in_message(self, ctx):
        with patch(
            "app.workers.tasks.reminder_tasks.reminder_repository.delete_finished_before",
            new_callable=AsyncMock,
            return_value=7,
        ) as mock_delete:
            result = await cleanup_expired_reminders(ctx)

        assert mock_delete.await_count == 1
        assert result == "Cleaned up 7 expired reminders"

    async def test_cleanup_zero_deletions_message(self, ctx):
        with patch(
            "app.workers.tasks.reminder_tasks.reminder_repository.delete_finished_before",
            new_callable=AsyncMock,
            return_value=0,
        ):
            result = await cleanup_expired_reminders(ctx)

        assert result == "Cleaned up 0 expired reminders"

    async def test_cleanup_uses_thirty_day_cutoff(self, ctx):
        """The cutoff handed to the repository must be approx 30 days in the past."""
        from datetime import datetime, timedelta

        with patch(
            "app.workers.tasks.reminder_tasks.reminder_repository.delete_finished_before",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_delete:
            before_call = datetime.now(UTC)
            await cleanup_expired_reminders(ctx)
            after_call = datetime.now(UTC)

        cutoff = mock_delete.call_args.args[0]
        expected_lower = before_call - timedelta(days=30)
        expected_upper = after_call - timedelta(days=30)
        assert (
            expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)
        )

    async def test_cleanup_exception_propagates(self, ctx):
        with patch(
            "app.workers.tasks.reminder_tasks.reminder_repository.delete_finished_before",
            new_callable=AsyncMock,
            side_effect=Exception("MongoDB unavailable"),
        ):
            with pytest.raises(Exception, match="MongoDB unavailable"):
                await cleanup_expired_reminders(ctx)
