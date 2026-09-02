"""Unit tests for app.workers.tasks.scheduler_recovery_tasks.

``rescan_pending_scheduled_tasks`` is the periodic safety net for deferred
work lost mid-run: it reaps BOTH workflows and reminders wedged in EXECUTING,
then re-scans both schedulers. If any pass fails the whole task must fail
loudly — a swallowed scheduler error would silently break the recovery
guarantee.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.scheduler_recovery_tasks import rescan_pending_scheduled_tasks

MODULE = "app.workers.tasks.scheduler_recovery_tasks"


class TestRescanPendingScheduledTasks:
    async def test_reaps_and_rescans_both_schedulers(self):
        """Reminders are reaped too, not just workflows.

        A reminder wedged in EXECUTING is otherwise invisible forever: the
        due-scan filters on status="scheduled", so nothing can see it again and
        it simply never fires.
        """
        workflow_reap = AsyncMock(return_value=2)
        reminder_reap = AsyncMock(return_value=1)
        workflow_scan = AsyncMock()
        reminder_scan = AsyncMock()
        with (
            patch(f"{MODULE}.workflow_scheduler.reap_stale_executing", workflow_reap),
            patch(f"{MODULE}.reminder_scheduler.reap_stale_executing", reminder_reap),
            patch(f"{MODULE}.workflow_scheduler.scan_and_schedule_pending_tasks", workflow_scan),
            patch(f"{MODULE}.reminder_scheduler.scan_and_schedule_pending_tasks", reminder_scan),
        ):
            result = await rescan_pending_scheduled_tasks({})

        assert result == "rescan_pending_scheduled_tasks complete (reaped 3 stale executing)"
        workflow_reap.assert_awaited_once()
        reminder_reap.assert_awaited_once()
        workflow_scan.assert_awaited_once()
        reminder_scan.assert_awaited_once()

    async def test_zero_reaped_is_still_reported(self):
        with (
            patch(f"{MODULE}.workflow_scheduler.reap_stale_executing", AsyncMock(return_value=0)),
            patch(f"{MODULE}.reminder_scheduler.reap_stale_executing", AsyncMock(return_value=0)),
            patch(f"{MODULE}.workflow_scheduler.scan_and_schedule_pending_tasks", AsyncMock()),
            patch(f"{MODULE}.reminder_scheduler.scan_and_schedule_pending_tasks", AsyncMock()),
        ):
            result = await rescan_pending_scheduled_tasks({})

        assert result == "rescan_pending_scheduled_tasks complete (reaped 0 stale executing)"

    async def test_a_reap_failure_propagates(self):
        with (
            patch(
                f"{MODULE}.workflow_scheduler.reap_stale_executing",
                AsyncMock(side_effect=RuntimeError("postgres down")),
            ),
            pytest.raises(RuntimeError, match="postgres down"),
        ):
            await rescan_pending_scheduled_tasks({})

    async def test_a_rescan_failure_propagates(self):
        with (
            patch(f"{MODULE}.workflow_scheduler.reap_stale_executing", AsyncMock(return_value=0)),
            patch(f"{MODULE}.reminder_scheduler.reap_stale_executing", AsyncMock(return_value=0)),
            patch(
                f"{MODULE}.workflow_scheduler.scan_and_schedule_pending_tasks",
                AsyncMock(side_effect=RuntimeError("redis evicted the queue")),
            ),
            pytest.raises(RuntimeError, match="redis evicted"),
        ):
            await rescan_pending_scheduled_tasks({})
