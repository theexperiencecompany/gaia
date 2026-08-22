"""ARQ worker task for Gmail email memory processing."""

from typing import Any

from app.agents.memory.email_processor import process_gmail_to_memory
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def process_gmail_emails_to_memory(ctx: dict[str, Any], user_id: str) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """
    ARQ background task to process Gmail emails into memories.

    Args:
        ctx: ARQ context (unused but required)
        user_id: User ID to process emails for

    Returns:
        Processing result message
    """
    log.set(user_id=user_id)
    result = await process_gmail_to_memory(user_id)

    if result.get("already_processed", False):
        log.info(f"{LogTag.WORKER} Gmail emails already processed", user_id=user_id)
        return f"Gmail emails already processed for user {user_id}"

    total = result.get("total", 0)
    successful = result.get("successful", 0)
    failed = result.get("failed", 0)
    processing_complete = result.get("processing_complete", False)
    log.set(total=total, successful=successful, failed=failed)

    if processing_complete:
        log.info(
            f"{LogTag.WORKER} Gmail email processing completed",
            user_id=user_id,
            successful=successful,
            total=total,
        )
        return f"Gmail email processing completed for user {user_id}: {successful}/{total} emails processed successfully"
    log.warning(
        f"{LogTag.WORKER} Gmail email processing incomplete",
        user_id=user_id,
        failed_count=failed,
    )
    return f"Gmail email processing failed for user {user_id}: {successful}/{total} emails processed, {failed} failed - not marking as complete"
