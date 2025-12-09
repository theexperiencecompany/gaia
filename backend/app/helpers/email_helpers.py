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


def remove_invisible_chars(s: str) -> str:
    """Remove invisible Unicode characters."""
    return "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))


def aggressive_clean_email(text: str) -> str:
    """
    Aggressively clean email content to minimize size while preserving meaning.
    Does NOT truncate - only removes noise.

    Args:
        text: Raw email text

    Returns:
        Cleaned text (no truncation)
    """
    import re

    # Remove email threading
    text = re.sub(r"On .* wrote:", "", text)
    text = re.sub(r"From:.*?Subject:", "", text, flags=re.DOTALL)

    # Remove URLs but keep domain for context
    text = re.sub(r"https?://([^/\s]+)[^\s]*", r"[\1]", text)

    # Remove common footer patterns
    footer_patterns = [
        r"unsubscribe.*$",
        r"manage (your )?preferences.*$",
        r"view (in|this) (browser|online).*$",
        r"click here.*$",
        r"this email was sent.*$",
        r"privacy policy.*$",
        r"terms of service.*$",
        r"copyright ©.*$",
        r"all rights reserved.*$",
    ]
    for pattern in footer_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Remove separators
    text = re.sub(r"[\r\n]+[-_=*]{3,}[\r\n]+", "\n", text)

    # Compress whitespace aggressively
    text = re.sub(r"[ \t]+", " ", text)  # Multiple spaces -> single space
    text = re.sub(r"\n\s*\n\s*\n+", "", text)
    text = text.strip()

    return text


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

            # Aggressively clean to reduce size
            clean_text = aggressive_clean_email(clean_text)

            if not clean_text or len(clean_text) < 20:  # Skip very short
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
    Store emails to Zep as text chunks of max 9500 characters.

    Approach:
    1. Convert emails to plain text with metadata
    2. Chunk by 9500 character limit (respects Zep's 10K limit)
    3. Send chunks in parallel

    Args:
        user_id: User ID
        processed_emails: List of processed email dicts
        user_name: User's name (not used, kept for compatibility)
        user_email: User's email (not used, kept for compatibility)
    """
    if not processed_emails:
        return

    try:
        import asyncio

        # Convert emails to text format
        email_texts = []
        for email_data in processed_emails:
            content = email_data.get("content", "").strip()
            if not content:
                continue

            metadata = email_data.get("metadata", {})

            # Format as simple text
            email_text = f"""From: {metadata.get("sender", UNKNOWN_SENDER)}
              Subject: {metadata.get("subject", NO_SUBJECT)}
              ID: {metadata.get("message_id", "unknown")}

              {content}
              ---
            """

            email_texts.append(email_text)

        if not email_texts:
            return

        # Chunk by 10K character limit
        MAX_CHUNK_SIZE = 9500
        chunks = []
        current_chunk = ""

        for email_text in email_texts:
            # If single email > 10K, split it into multiple chunks
            if len(email_text) > MAX_CHUNK_SIZE:
                # Save current chunk first
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""

                # Split large email into 10K pieces
                for i in range(0, len(email_text), MAX_CHUNK_SIZE):
                    chunk_piece = email_text[i : i + MAX_CHUNK_SIZE]
                    chunks.append(chunk_piece)

                continue

            # Check if adding this email exceeds limit (account for newline separator)
            separator_size = 10 if current_chunk else 0
            if len(current_chunk) + separator_size + len(email_text) > MAX_CHUNK_SIZE:
                # Save current chunk and start new one
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = email_text
            else:
                # Add to current chunk
                current_chunk += "\n" + email_text if current_chunk else email_text

        # Don't forget last chunk
        if current_chunk:
            chunks.append(current_chunk)

        logger.info(f"Split {len(email_texts)} emails into {len(chunks)} chunks")

        # Pack chunks into batches - measure actual JSON size for accuracy
        import json

        MAX_BATCH_SIZE = 9500
        batches = []
        current_batch = []

        for chunk in chunks:
            # Try adding chunk to current batch
            test_batch = current_batch + [chunk]
            # Measure actual size when serialized as JSON array
            batch_size = len(json.dumps(test_batch))

            if batch_size > MAX_BATCH_SIZE and current_batch:
                # Would exceed limit - save current batch and start new one
                batches.append(current_batch)
                current_batch = [chunk]
            else:
                # Fits - add it
                current_batch = test_batch

        # Don't forget last batch
        if current_batch:
            batches.append(current_batch)

        logger.info(f"Packed {len(chunks)} chunks into {len(batches)} batches for Zep")

        # Send all batches in parallel
        async def process_batch(batch: List[str], batch_num: int) -> None:
            await memory_service.add_business_data_batch(
                user_id=user_id,
                data_items=batch,
            )
            batch_size = len(json.dumps(batch))
            logger.info(
                f"Batch {batch_num}/{len(batches)}: {len(batch)} chunks ({batch_size} chars)"
            )

        tasks = [process_batch(batch, i + 1) for i, batch in enumerate(batches)]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(f"✓ Stored {len(email_texts)} emails in {len(batches)} batches")

    except Exception as e:
        logger.error(f"Error storing emails to Zep: {e}")


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
