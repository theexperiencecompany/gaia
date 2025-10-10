"""ARQ worker tasks for storing memories in mem0."""

import asyncio
from typing import Dict, List
from datetime import datetime, timezone

from app.config.loggers import arq_worker_logger as logger
from app.services.memory_service import memory_service


async def store_memories_batch(
    ctx: dict, user_id: str, emails_batch: List[Dict]
) -> str:
    """
    Store a batch of emails in mem0 using asyncio.gather.

    Args:
        ctx: ARQ context
        user_id: User ID to store memories for
        emails_batch: List of email data with content and metadata

    Returns:
        Processing result message
    """
    try:
        if not emails_batch:
            return f"No emails to process for user {user_id}"

        logger.info(
            f"Processing batch of {len(emails_batch)} emails for user {user_id}"
        )

        # Create memory storage tasks
        memory_tasks = []
        for email_data in emails_batch:
            content = email_data.get("content", "")
            metadata = email_data.get("metadata", {})

            if not content.strip():
                continue

            subject = metadata.get("subject", "[No Subject]")
            sender = metadata.get("sender", "[Unknown Sender]")

            # Format prompt for mem0
            memory_content = f"""The user has received this email with subject "{subject}" from {sender}.

            Email content: {content}

            You are storing long-term memories about the user. Only store memories that reflect the user's:
            - persistent interests, hobbies, and preferences
            - app/service usage or subscriptions
            - location, role, or recurring behavior
            - patterns that may help anticipate user needs

            Do NOT store:
            - one-off promotions, offers, discounts, or marketing emails
            - ephemeral events that are not part of a pattern
            - minor details that do not affect the user’s behavior

            Summarize information in a general and actionable way. You may choose not to store any memory if the email is trivial.
            """

            enhanced_metadata = {
                **metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "gmail_background_batch",
            }

            task = memory_service.store_memory(
                content=memory_content, user_id=user_id, metadata=enhanced_metadata
            )
            memory_tasks.append(task)

        if not memory_tasks:
            return f"No valid emails to process for user {user_id}"

        # Execute all tasks concurrently with asyncio.gather
        results = await asyncio.gather(*memory_tasks, return_exceptions=True)

        # Count results
        successful = sum(
            1 for r in results if not isinstance(r, Exception) and r is not None
        )
        failed = len(results) - successful

        logger.info(
            f"Batch completed for user {user_id}: {successful}/{len(results)} stored successfully"
        )
        return f"Stored {successful}/{len(results)} emails in mem0, {failed} failed"

    except Exception as e:
        error_msg = f"Error in batch memory processing for user {user_id}: {str(e)}"
        logger.error(error_msg)
        return error_msg
