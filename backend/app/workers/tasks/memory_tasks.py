"""ARQ worker tasks for storing memories in Zep."""

from datetime import datetime, timezone
from typing import Dict, List

from app.config.loggers import arq_worker_logger as logger
from app.services.memory_service import memory_service


async def store_memories_batch(
    ctx: dict,
    user_id: str,
    emails_batch: List[Dict],
    user_name: str | None = None,
    user_email: str | None = None,
) -> str:
    """
    Store a batch of emails in Zep using a single API call.

    Args:
        ctx: ARQ context
        user_id: User ID to store memories for
        emails_batch: List of email data with content and metadata
        user_name: User's full name for consistent memory attribution
        user_email: User's email address

    Returns:
        Processing result message
    """
    try:
        if not emails_batch:
            return f"No emails to process for user {user_id}"

        logger.info(
            f"Processing batch of {len(emails_batch)} emails for user {user_id} ({user_name})"
        )

        # Build messages array for single API call
        messages = []
        for email_data in emails_batch:
            content = email_data.get("content", "")
            metadata = email_data.get("metadata", {})

            if not content.strip():
                continue

            subject = metadata.get("subject", "[No Subject]")
            sender = metadata.get("sender", "[Unknown Sender]")

            # Format clean content for Zep
            memory_content = f"""The user RECEIVED this email (not sent by the user).

From: {sender}
Subject: {subject}

{content}"""

            messages.append({"role": "user", "content": memory_content})

        if not messages:
            logger.warning(f"No valid emails to process for user {user_id}")
            return f"No valid emails to process for user {user_id}"

        logger.info(
            f"Storing {len(messages)} emails in a single Zep API call (user {user_id})..."
        )

        # Single API call to store all memories
        result = await memory_service.store_memory_batch(
            messages=messages,
            user_id=user_id,
            metadata={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "gmail_background_batch",
                "batch_size": len(messages),
                "user_name": user_name,
                "user_email": user_email,
            },
        )

        if result:
            logger.info(
                f"✓ Batch completed for user {user_id}: stored {len(messages)} emails successfully"
            )
            return f"Stored {len(messages)} emails in Zep successfully"
        else:
            # Note: result=False means Zep filtered all emails (returned 0 memories)
            # This is NOT an error - it's a valid outcome
            logger.warning(
                f"Zep filtered all {len(messages)} emails for user {user_id} (deemed non-memorable)"
            )
            return (
                f"Processed {len(messages)} emails - Zep filtered all as non-memorable"
            )

    except Exception as e:
        error_msg = f"Error in batch memory processing for user {user_id}: {str(e)}"
        logger.error(error_msg)
        return error_msg
