"""Unit tests for app.workers.tasks.scheduler_recovery_tasks.

``rescan_pending_scheduled_tasks`` is the periodic safety net for deferred
work lost mid-run: it reaps workflows wedged in EXECUTING, then re-scans both
the workflow and reminder schedulers. If any of the three passes fails the
whole task must fail loudly — a swallowed scheduler error would silently
break the recovery guarantee.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.scheduler_recovery_tasks import rescan_pending_scheduled_tasks

MODULE = "app.workers.tasks.scheduler_recovery_tasks"


class TestRescanPendingScheduledTasks:
    async def test_reaps_and_rescans_both_schedulers(self):
        reap = AsyncMock(return_value=2)
        workflow_scan = AsyncMock()
        reminder_scan = AsyncMock()
        with (
            patch(f"{MODULE}.workflow_scheduler.reap_stale_executing", reap),
            patch(f"{MODULE}.workflow_scheduler.scan_and_schedule_pending_tasks", workflow_scan),
            patch(f"{MODULE}.reminder_scheduler.scan_and_schedule_pending_tasks", reminder_scan),
        ):
            result = await rescan_pending_scheduled_tasks({})

        assert result == "rescan_pending_scheduled_tasks complete (reaped 2 stale executing)"
        reap.assert_awaited_once()
        workflow_scan.assert_awaited_once()
        reminder_scan.assert_awaited_once()

    async def test_zero_reaped_is_still_reported(self):
        with (
            patch(f"{MODULE}.workflow_scheduler.reap_stale_executing", AsyncMock(return_value=0)),
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
            patch(
                f"{MODULE}.workflow_scheduler.scan_and_schedule_pending_tasks",
                AsyncMock(side_effect=RuntimeError("redis evicted the queue")),
            ),
            pytest.raises(RuntimeError, match="redis evicted"),
        ):
            await rescan_pending_scheduled_tasks({})
