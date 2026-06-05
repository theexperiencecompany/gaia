"""Periodic recovery scan for scheduled tasks (workflows + reminders)."""

from app.services.reminder_service import reminder_scheduler
from app.services.workflow.scheduler import workflow_scheduler
from shared.py.wide_events import wide_task


async def rescan_pending_scheduled_tasks(_ctx: dict) -> str:
    """Re-enqueue any SCHEDULED task that is due but whose ARQ job was lost.

    The startup scan (``scan_and_schedule_pending_tasks``) only runs once per boot,
    so a deferred job lost mid-run (Redis eviction/flush) would otherwise sit until
    the next restart. This periodic pass is the safety net. The deterministic ARQ
    ``_job_id`` makes re-enqueueing idempotent, so it overlaps harmlessly with jobs
    that are already queued.

    It also reaps workflows wedged in EXECUTING (a fire claimed the row but its worker
    died before re-arming) back to SCHEDULED so they resume.
    """
    async with wide_task("rescan_pending_scheduled_tasks"):
        reaped = await workflow_scheduler.reap_stale_executing()
        await workflow_scheduler.scan_and_schedule_pending_tasks()
        await reminder_scheduler.scan_and_schedule_pending_tasks()
        return f"rescan_pending_scheduled_tasks complete (reaped {reaped} stale executing)"
