"""ARQ worker tasks for storing memories in mem0."""

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
    Store a batch of emails in mem0 using a single API call.

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

            # Format clean content for mem0 (instructions handled via custom_instructions parameter)
            memory_content = f"""The user RECEIVED this email (not sent by the user).

From: {sender}
Subject: {subject}

{content}"""

            messages.append({"role": "user", "content": memory_content})

        if not messages:
            logger.warning(f"No valid emails to process for user {user_id}")
            return f"No valid emails to process for user {user_id}"

        logger.info(
            f"Storing {len(messages)} emails in a single mem0 API call (user {user_id})..."
        )

        # Build user context for consistent attribution
        user_context = ""
        if user_name:
            user_context = f"The user's name is {user_name}."
            if user_email:
                user_context += f" Their email is {user_email}."

        # Single API call to store all memories with custom instructions
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
            async_mode=False,
            custom_instructions=f"""{user_context}

Extract memories ABOUT THE USER from emails they received.

WHAT TO EXTRACT:
- Identity: Name, email, usernames, role, title
- Work: Job, company, projects, skills, industry
- Services: Apps/tools they use, accounts they have, subscriptions
- Interests: Hobbies, topics they follow, communities, newsletters
- Location: City, timezone, work setup (remote/hybrid)
- Relationships: Colleagues, collaborators, frequent contacts
- Preferences: Communication style, tool choices, work style
- Goals: What they're building, learning, or working toward

ONLY STORE IF:
- It's ABOUT THE USER (not about senders or general topics)
- Persistent/stable information (not one-off events)
- Actionable for an AI assistant
- Pattern-based behaviors

DON'T STORE:
- Marketing/promotional content
- Info about other people (unless their relationship to user)
- Trivial details or spam
- Sensitive data (passwords, financial info)
- Generic content that doesn't reveal anything about the user

FORMAT: Present tense, factual statements starting with "User"
Example: "User works as Software Engineer at Acme Corp", "User's email is john@example.com"
""",
        )

        if result:
            logger.info(
                f"✓ Batch completed for user {user_id}: stored {len(messages)} emails successfully"
            )
            return f"Stored {len(messages)} emails in mem0 successfully"
        else:
            # Note: result=False means Mem0 filtered all emails (returned 0 memories)
            # This is NOT an error - it's a valid outcome
            logger.warning(
                f"Mem0 filtered all {len(messages)} emails for user {user_id} (deemed non-memorable)"
            )
            return (
                f"Processed {len(messages)} emails - Mem0 filtered all as non-memorable"
            )

    except Exception as e:
        error_msg = f"Error in batch memory processing for user {user_id}: {str(e)}"
        logger.error(error_msg)
        return error_msg
