import json
import os
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List

import html2text
from app.config.loggers import memory_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.services.mail.mail_service import search_messages
from arq import create_pool
from arq.connections import RedisSettings
from bson import ObjectId

# Constants
EMAIL_QUERY = "newer_than:90d"
MAX_RESULTS = 100
BATCH_SIZE = 50
UNKNOWN_SENDER = "[Unknown]"
NO_SUBJECT = "[No Subject]"

h = html2text.HTML2Text()
h.ignore_links = True
h.body_width = 0
h.ignore_images = True
h.skip_internal_links = True


async def process_gmail_to_memory(user_id: str) -> Dict:
    """Process user's Gmail emails into Mem0 memories.

    Returns dict with total, successful, failed counts and processing status.
    """
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if user and user.get("email_memory_processed", False):
        logger.info(f"User {user_id} emails already processed, skipping")
        return {
            "total": 0,
            "successful": 0,
            "already_processed": True,
            "processing_complete": True,
        }

    # Fetch emails in batches
    try:
        all_emails: List[Dict[str, Any]] = []
        page_token = None
        batch_count = 0

        while len(all_emails) < MAX_RESULTS:
            remaining = MAX_RESULTS - len(all_emails)
            batch_size = min(BATCH_SIZE, remaining)
            batch_count += 1

            logger.info(
                f"Fetching batch {batch_count}, requesting {batch_size} emails, page_token: {page_token}"
            )

            result = await search_messages(
                user_id=user_id,
                query=EMAIL_QUERY,
                max_results=batch_size,
                page_token=page_token,
            )

            batch_emails = result.get("messages", [])
            logger.info(f"Batch {batch_count} returned {len(batch_emails)} emails")

            if not batch_emails:
                logger.info("No more emails returned, breaking")
                break

            all_emails.extend(batch_emails)
            page_token = result.get("nextPageToken")

            logger.info(
                f"Total emails so far: {len(all_emails)}, next page token: {page_token}"
            )

            if not page_token:
                logger.info("No next page token, breaking")
                break

        emails = all_emails
        logger.info(f"Final email count: {len(emails)}")
    except Exception as e:
        logger.error(f"Failed to fetch emails: {e}")
        emails = []

    if not emails:
        await _mark_processed(user_id, 0)
        return {"total": 0, "successful": 0, "processing_complete": True}

    # Process and store emails
    processed_emails, failed_count = _process_email_content(emails)

    # Write emails to test file for inspection
    await _write_emails_to_test_file(user_id, processed_emails)

    successful_count = await _store_memories_batch(user_id, processed_emails)

    processing_complete = successful_count > 0
    if processing_complete:
        await _mark_processed(user_id, successful_count)
        logger.info(
            f"Processed {successful_count}/{len(emails)} emails for user {user_id}"
        )

    return {
        "total": len(emails),
        "successful": successful_count,
        "failed": failed_count + (len(processed_emails) - successful_count),
        "processing_complete": processing_complete,
    }


def remove_invisible_chars(s):
    """Remove invisible Unicode characters."""
    return "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))


def _process_email_content(emails: List[Dict]) -> tuple[List[Dict], int]:
    """Process email content converting HTML to clean text."""
    processed = []
    failed_count = 0

    for email_data in emails:
        try:
            message_text = email_data.get("messageText", "")
            if not message_text.strip():
                failed_count += 1
                continue

            # Convert HTML to clean text
            clean_text = h.handle(message_text).strip()
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


async def _store_memories_batch(user_id: str, processed_emails: List[Dict]) -> int:
    """Store memories in batches using ARQ background task."""
    if not processed_emails:
        return 0

    try:
        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        pool = await create_pool(redis_settings)

        # Enqueue the batch memory storage task
        job = await pool.enqueue_job(
            "store_memories_batch",
            user_id,
            processed_emails,
        )

        await pool.close()

        if job:
            logger.info(
                f"Successfully queued memory storage task for {len(processed_emails)} emails, job ID: {job.job_id}"
            )
            # Return count as if successful since we queued the task
            return len(processed_emails)
        else:
            logger.error("Failed to queue memory storage task")
            return 0

    except Exception as e:
        logger.error(f"Error queuing memory storage task: {e}")
        return 0


async def _mark_processed(user_id: str, memory_count: int) -> None:
    """Mark user's email processing as complete."""
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


async def _write_emails_to_test_file(user_id: str, emails: List[Dict]) -> None:
    """Write emails to test file for inspection."""
    test_data = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "emails": emails,
    }

    filename = "email_test_output.json"
    filepath = os.path.join(os.path.dirname(__file__), filename)

    try:
        with open(filepath, "w") as f:
            json.dump(test_data, f, indent=2, default=str)
        logger.info(f"Emails written to test file: {filepath}")
    except Exception as e:
        logger.error(f"Failed to write emails to test file: {e}")
