"""
Reminder-related ARQ tasks.
"""

from datetime import datetime, timedelta, timezone

from app.services.reminder_service import reminder_scheduler
from shared.py.wide_events import log, wide_task


async def process_reminder(ctx: dict, reminder_id: str) -> str:
    """
    Process a reminder task.

    Args:
        ctx: ARQ context
        reminder_id: ID of the reminder to process

    Returns:
        Processing result message
    """
    async with wide_task("process_reminder", reminder_id=reminder_id):
        log.info(f"Processing reminder task: {reminder_id}")
        await reminder_scheduler.process_task_execution(reminder_id)
        result = f"Successfully processed reminder {reminder_id}"
        log.info(result)
        return result


async def cleanup_expired_reminders(ctx: dict) -> str:
    """
    Cleanup expired or completed reminders (scheduled task).

    Args:
        ctx: ARQ context

    Returns:
        Cleanup result message
    """
    async with wide_task("cleanup_expired_reminders"):
        from app.db.mongodb.collections import reminders_collection

        log.info("Running cleanup of expired reminders")
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

        result = await reminders_collection.delete_many(
            {
                "status": {"$in": ["completed", "cancelled"]},
                "updated_at": {"$lt": cutoff_date},
            }
        )
        log.set(reminders_deleted=result.deleted_count)
        message = f"Cleaned up {result.deleted_count} expired reminders"
        log.info(message)
        return message
