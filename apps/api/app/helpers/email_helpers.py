"""Helper functions for email processing."""

from datetime import UTC, datetime
import time
import unicodedata

from bson import ObjectId
import html2text

from app.agents.memory.profile_extractor import PLATFORM_CONFIG
from app.agents.prompts.email_filter_prompts import EMAIL_MEMORY_EXTRACTION_PROMPT
from app.constants.email import NO_SUBJECT, UNKNOWN_SENDER
from app.constants.memory import MemorySourceType
from app.db.mongodb.collections import users_collection
from app.memory.engine import memory_engine
from shared.py.wide_events import log

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


def process_email_content(emails: list[dict]) -> tuple[list[dict], int]:
    """
    Process email content converting HTML to clean text.
    Skips platform emails (they're only used for profile discovery).

    Args:
        emails: Raw email data from Gmail API

    Returns:
        Tuple of (processed_emails, failed_count)
    """
    processed = []
    failed_count = 0

    for email_data in emails:
        try:
            # Skip platform emails - only used for profile discovery
            sender = (email_data.get("sender") or email_data.get("from", "")).lower()

            # Check against all platform sender domains from config
            is_platform_email = False
            for platform_config in PLATFORM_CONFIG.values():
                sender_domains = platform_config.get("sender_domains", [])
                if any(domain in sender for domain in sender_domains):
                    is_platform_email = True
                    break

            if is_platform_email:
                continue

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
                        "message_id": email_data.get("messageId") or email_data.get("id"),
                        "sender": email_data.get("sender")
                        or email_data.get("from", UNKNOWN_SENDER),
                        "subject": email_data.get("subject", NO_SUBJECT),
                    },
                }
            )
        except Exception:
            failed_count += 1

    return processed, failed_count


async def store_emails_to_memory(
    user_id: str,
    processed_emails: list[dict],
    user_name: str | None = None,
    user_email: str | None = None,
) -> None:
    """
    Ingest an email batch into the memory engine.

    Args:
        user_id: User ID
        processed_emails: List of processed email dicts
        user_name: User's name (optional)
        user_email: User's email (optional)
    """
    if not processed_emails:
        return

    try:
        messages = [
            {
                "role": "user",
                "content": f"""The user RECEIVED this email (not sent by the user).

From: {email_data.get("metadata", {}).get("sender", UNKNOWN_SENDER)}
Subject: {email_data.get("metadata", {}).get("subject", NO_SUBJECT)}

{email_data.get("content", "")}""",
            }
            for email_data in processed_emails
            if email_data.get("content", "").strip()
        ]

        if not messages:
            return

        user_context = _build_user_context(user_name, user_email)

        t0_store = time.monotonic()
        result = await memory_engine.retain(
            user_id,
            messages,
            source_type=MemorySourceType.EMAIL,
            extraction_hints=f"{user_context}\n\n{EMAIL_MEMORY_EXTRACTION_PROMPT}",
            user_name=user_name,
            user_email=user_email,
        )
        store_elapsed = time.monotonic() - t0_store

        log.info(
            f"[timing] Memory retain ({len(messages)} emails): {store_elapsed:.1f}s — "
            f"{result.facts_extracted} facts extracted"
        )

    except Exception as e:
        log.error(f"Error storing email batch to memory: {e}")
        # Don't re-raise - we want to continue processing other batches


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
                "email_memory_processed_at": datetime.now(UTC),
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
    Store a single social profile to memory.

    Args:
        user_id: User ID
        platform: Platform name (twitter, github, etc.)
        profile_url: Profile URL
        content: Crawled profile content
        user_name: User's name (optional)
    """
    try:
        memory_content = f"User's {platform} profile: {profile_url} {content}"

        await memory_engine.retain(
            user_id,
            [{"role": "user", "content": memory_content}],
            source_type=MemorySourceType.EMAIL,
            source_id=profile_url,
            extraction_hints=(
                f"This is the user's own {platform} profile, discovered during email "
                "onboarding. Extract durable facts about the user: their handle, bio, "
                "role, projects, interests, and location."
            ),
            user_name=user_name,
        )
        log.info(f"Stored {platform} profile to memory: {profile_url}")
    except Exception as e:
        log.error(f"Failed to store {platform} profile: {e}")
