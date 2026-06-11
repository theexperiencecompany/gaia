"""ARQ worker task for ingesting email batches into the memory engine."""

from app.agents.prompts.email_filter_prompts import EMAIL_MEMORY_EXTRACTION_PROMPT
from app.constants.email import NO_SUBJECT, UNKNOWN_SENDER
from app.constants.memory import MemorySourceType
from app.memory.engine import memory_engine
from shared.py.wide_events import log, wide_task


async def store_memories_batch(
    ctx: dict,
    user_id: str,
    emails_batch: list[dict],
    user_name: str | None = None,
    user_email: str | None = None,
) -> str:
    """
    Ingest a batch of emails into memory in a single engine call.

    Args:
        ctx: ARQ context
        user_id: User ID to store memories for
        emails_batch: List of email data with content and metadata
        user_name: User's full name for consistent memory attribution
        user_email: User's email address

    Returns:
        Processing result message
    """
    async with wide_task("store_memories_batch", user_id=user_id):
        log.set(email_batch_size=len(emails_batch))

        if not emails_batch:
            return f"No emails to process for user {user_id}"

        log.info(f"Processing batch of {len(emails_batch)} emails for user {user_id} ({user_name})")

        messages = []
        for email_data in emails_batch:
            content = email_data.get("content", "")
            metadata = email_data.get("metadata", {})

            if not content.strip():
                continue

            subject = metadata.get("subject", NO_SUBJECT)
            sender = metadata.get("sender", UNKNOWN_SENDER)

            memory_content = f"""The user RECEIVED this email (not sent by the user).

From: {sender}
Subject: {subject}

{content}"""

            messages.append({"role": "user", "content": memory_content})

        if not messages:
            log.warning(f"No valid emails to process for user {user_id}")
            return f"No valid emails to process for user {user_id}"

        user_context = ""
        if user_name:
            user_context = f"The user's name is {user_name}."
            if user_email:
                user_context += f" Their email is {user_email}."

        try:
            result = await memory_engine.retain(
                user_id,
                messages,
                source_type=MemorySourceType.EMAIL,
                extraction_hints=f"{user_context}\n\n{EMAIL_MEMORY_EXTRACTION_PROMPT}",
                user_name=user_name,
            )
        except Exception as e:
            log.error(f"Error in batch memory processing for user {user_id}: {e}")
            return f"Error in batch memory processing for user {user_id}: {e}"

        if result.facts_extracted > 0:
            log.set(emails_stored=len(messages), emails_filtered=0)
            log.info(
                f"Batch completed for user {user_id}: {result.facts_extracted} facts "
                f"extracted from {len(messages)} emails"
            )
            return f"Extracted {result.facts_extracted} memories from {len(messages)} emails"
        # Zero facts means the extractor filtered everything — a valid outcome.
        log.set(emails_stored=0, emails_filtered=len(messages))
        log.warning(f"All {len(messages)} emails filtered as non-memorable for user {user_id}")
        return f"Processed {len(messages)} emails - all filtered as non-memorable"
