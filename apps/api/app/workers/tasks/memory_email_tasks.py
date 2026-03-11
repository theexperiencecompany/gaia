"""ARQ worker task for Gmail email memory processing."""

from app.agents.memory.email_processor import process_gmail_to_memory
from shared.py.wide_events import log, wide_task


async def process_gmail_emails_to_memory(ctx, user_id: str) -> str:
    """
    ARQ background task to process Gmail emails into memories.

    Args:
        ctx: ARQ context (unused but required)
        user_id: User ID to process emails for

    Returns:
        Processing result message
    """
    async with wide_task("process_gmail_emails_to_memory", user_id=user_id):
        result = await process_gmail_to_memory(user_id)

        if result.get("already_processed", False):
            message = f"Gmail emails already processed for user {user_id}"
            log.info(message)
            return message

        total = result.get("total", 0)
        successful = result.get("successful", 0)
        failed = result.get("failed", 0)
        processing_complete = result.get("processing_complete", False)
        log.set(total=total, successful=successful, failed=failed)

        if processing_complete:
            message = f"Gmail email processing completed for user {user_id}: {successful}/{total} emails processed successfully"
            log.info(message)
            return message
        else:
            log.warning(
                f"Gmail email processing incomplete for user {user_id}: {failed} failed",
            )
            return f"Gmail email processing failed for user {user_id}: {successful}/{total} emails processed, {failed} failed - not marking as complete"
