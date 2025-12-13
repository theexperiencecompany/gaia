"""ARQ worker task for Gmail email memory processing."""

from app.agents.memory.email_processor import process_gmail_to_memory


async def process_gmail_emails_to_memory(ctx, user_id: str) -> str:
    """
    ARQ background task to process Gmail emails into memories.

    Args:
        ctx: ARQ context (unused but required)
        user_id: User ID to process emails for

    Returns:
        Processing result message
    """
    try:
        result = await process_gmail_to_memory(user_id)

        if result.get("already_processed", False):
            return f"Gmail emails already processed for user {user_id}"

        total = result.get("total", 0)
        successful = result.get("successful", 0)
        failed = result.get("failed", 0)
        processing_complete = result.get("processing_complete", False)

        if processing_complete:
            return f"Gmail email processing completed for user {user_id}: {successful}/{total} emails processed successfully"
        else:
            return f"Gmail email processing failed for user {user_id}: {successful}/{total} emails processed, {failed} failed - not marking as complete"

    except Exception as e:
        return f"Fatal error in Gmail email processing for user {user_id}: {e}"
