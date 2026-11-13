"""Periodic recovery scan for scheduled tasks (workflows + reminders)."""

from typing import Any

from app.services.reminder_service import reminder_scheduler
from app.services.workflow.scheduler import workflow_scheduler
from shared.py.wide_events import log


async def rescan_pending_scheduled_tasks(_ctx: dict[str, Any]) -> str:
    """Re-enqueue any SCHEDULED task that is due but whose ARQ job was lost.

    Safety net for the once-per-boot startup scan; re-enqueueing is idempotent
    via the deterministic _job_id. Also reaps workflows AND reminders wedged in
    EXECUTING back to SCHEDULED — without the reminder half, a SIGKILLed one
    stayed EXECUTING forever and never fired again.
    """
    reaped = await workflow_scheduler.reap_stale_executing()
    reaped += await reminder_scheduler.reap_stale_executing()
    await workflow_scheduler.scan_and_schedule_pending_tasks()
    await reminder_scheduler.scan_and_schedule_pending_tasks()
    log.set(reaped_stale_executing=reaped)
    return f"rescan_pending_scheduled_tasks complete (reaped {reaped} stale executing)"
