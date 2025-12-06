"""Helper functions for email processing."""

import unicodedata
from datetime import datetime, timezone
from typing import Dict, List

import html2text
from bson import ObjectId

from app.config.loggers import memory_logger as logger
from app.db.mongodb.collections import users_collection
from app.services.memory_service import memory_service

# Constants
UNKNOWN_SENDER = "[Unknown]"
NO_SUBJECT = "[No Subject]"

# HTML to text converter
_html_converter = html2text.HTML2Text()
_html_converter.ignore_links = True
_html_converter.body_width = 0
_html_converter.ignore_images = True
_html_converter.skip_internal_links = True


def _build_user_context(user_name: str | None, user_email: str | None) -> str:
    """
    Build user context string for memory extraction.

    Args:
        user_name: User's name (optional)
        user_email: User's email (optional)

    Returns:
        Formatted context string
    """
    if not user_name:
        return ""

    context = f"The user's name is {user_name}."
    if user_email:
        context += f" Their email is {user_email}."

    return context


def remove_invisible_chars(s: str) -> str:
    """Remove invisible Unicode characters."""
    return "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))


def process_email_content(emails: List[Dict]) -> tuple[List[Dict], int]:
    """
    Process email content converting HTML to clean text.

    Args:
        emails: Raw email data from Gmail API

    Returns:
        Tuple of (processed_emails, failed_count)
    """
    processed = []
    failed_count = 0

    for email_data in emails:
        try:
            message_text = email_data.get("messageText", "")
            if not message_text.strip():
                failed_count += 1
                continue

            # Convert HTML to clean text
            clean_text = _html_converter.handle(message_text).strip()
            clean_text = remove_invisible_chars(clean_text)

            if not clean_text:
                failed_count += 1
                continue

            processed.append(
                {
                    "content": clean_text,
                    "metadata": {
                        "type": "email",
                        "source": "gmail",
                        "message_id": email_data.get("messageId")
                        or email_data.get("id"),
                        "sender": email_data.get("sender")
                        or email_data.get("from", UNKNOWN_SENDER),
                        "subject": email_data.get("subject", NO_SUBJECT),
                    },
                }
            )
        except Exception:
            failed_count += 1

    return processed, failed_count


async def store_emails_to_zep(
    user_id: str,
    processed_emails: List[Dict],
    user_name: str | None = None,
    user_email: str | None = None,
) -> None:
    """
    Store email batch to Zep knowledge graph using batch API for faster processing.
    Processes up to 20 emails concurrently!

    Args:
        user_id: User ID
        processed_emails: List of processed email dicts
        user_name: User's name (not used, kept for compatibility)
        user_email: User's email (not used, kept for compatibility)
    """
    if not processed_emails:
        return

    try:
        # Prepare all email data for batch processing
        email_objects = []
        for email_data in processed_emails:
            content = email_data.get("content", "").strip()
            if not content:
                continue

            metadata = email_data.get("metadata", {})

            # Create structured email data for graph
            email_obj = {
                "type": "email",
                "source": "gmail",
                "direction": "received",
                "from": metadata.get("sender", UNKNOWN_SENDER),
                "subject": metadata.get("subject", NO_SUBJECT),
                "content": content,
                "message_id": metadata.get("message_id"),
            }
            email_objects.append(email_obj)

        # Use batch API for concurrent processing (up to 20 at a time)
        await memory_service.add_business_data_batch(
            user_id=user_id,
            data_items=email_objects,
        )

        logger.info(
            f"Added batch of {len(email_objects)} emails to Zep graph for user {user_id}"
        )

    except Exception as e:
        logger.error(f"Error storing batch to Zep: {e}")


async def mark_email_processing_complete(user_id: str, memory_count: int) -> None:
    """
    Mark user's email processing as complete in database.

    Args:
        user_id: User ID
        memory_count: Number of memories stored
    """
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "email_memory_processed": True,
                "email_memory_processed_at": datetime.now(timezone.utc),
                "email_memory_count": memory_count,
            }
        },
    )


async def store_single_profile(
    user_id: str,
    platform: str,
    profile_url: str,
    content: str,
    user_name: str | None = None,
) -> None:
    """
    Store a single social profile to Zep graph.

    Args:
        user_id: User ID
        platform: Platform name (twitter, github, etc.)
        profile_url: Profile URL
        content: Crawled profile content
        user_name: User's name (optional, not used - kept for compatibility)
    """
    try:
        # Create structured profile data for graph
        # Don't include user_name - causes entity confusion
        profile_obj = {
            "type": "social_profile",
            "platform": platform,
            "url": profile_url,
            "content": content,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }

        # Add to knowledge graph
        await memory_service.add_business_data(
            user_id=user_id,
            data=profile_obj,
        )
        logger.info(f"Stored {platform} profile to memory: {profile_url}")
    except Exception as e:
        logger.error(f"Failed to store {platform} profile: {e}")
