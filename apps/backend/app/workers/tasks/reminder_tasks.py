"""
Reminder-related ARQ tasks.
"""

from datetime import datetime, timedelta, timezone

from app.config.loggers import arq_worker_logger as logger
from app.services.reminder_service import reminder_scheduler


async def process_reminder(ctx: dict, reminder_id: str) -> str:
    """
    Process a reminder task.

    Args:
        ctx: ARQ context
        reminder_id: ID of the reminder to process

    Returns:
        Processing result message
    """
    logger.info(f"Processing reminder task: {reminder_id}")

    try:
        await reminder_scheduler.process_task_execution(reminder_id)

        result = f"Successfully processed reminder {reminder_id}"
        logger.info(result)
        return result

    except Exception as e:
        error_msg = f"Failed to process reminder {reminder_id}: {str(e)}"
        logger.error(error_msg)
        raise


async def cleanup_expired_reminders(ctx: dict) -> str:
    """
    Cleanup expired or completed reminders (scheduled task).

    Args:
        ctx: ARQ context

    Returns:
        Cleanup result message
    """
    from app.db.mongodb.collections import reminders_collection

    logger.info("Running cleanup of expired reminders")

    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

        result = await reminders_collection.delete_many(
            {
                "status": {"$in": ["completed", "cancelled"]},
                "updated_at": {"$lt": cutoff_date},
            }
        )

        message = f"Cleaned up {result.deleted_count} expired reminders"
        logger.info(message)
        return message

    except Exception as e:
        error_msg = f"Failed to cleanup expired reminders: {str(e)}"
        logger.error(error_msg)
        raise
