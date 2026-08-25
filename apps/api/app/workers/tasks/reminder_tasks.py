"""
Reminder-related ARQ tasks.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.constants.log_tags import LogTag
from app.db.repositories.reminders import reminder_repository
from app.services.reminder_service import reminder_scheduler
from shared.py.wide_events import log


async def process_reminder(ctx: dict[str, Any], reminder_id: str) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """
    Process a reminder task.

    Args:
        ctx: ARQ context
        reminder_id: ID of the reminder to process

    Returns:
        Processing result message
    """
    log.set(reminder_id=reminder_id)
    log.info(f"{LogTag.WORKER} Processing reminder task", reminder_id=reminder_id)
    await reminder_scheduler.process_task_execution(reminder_id)
    log.info(f"{LogTag.WORKER} Successfully processed reminder", reminder_id=reminder_id)
    return f"Successfully processed reminder {reminder_id}"


async def cleanup_expired_reminders(ctx: dict[str, Any]) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """
    Cleanup expired or completed reminders (scheduled task).

    Args:
        ctx: ARQ context

    Returns:
        Cleanup result message
    """
    log.info(f"{LogTag.WORKER} Running cleanup of expired reminders")
    cutoff_date = datetime.now(UTC) - timedelta(days=30)

    deleted = await reminder_repository.delete_finished_before(cutoff_date)
    log.set(reminders_deleted=deleted)
    log.info(f"{LogTag.WORKER} Cleaned up expired reminders", deleted_count=deleted)
    return f"Cleaned up {deleted} expired reminders"
