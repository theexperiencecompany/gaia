"""Simple email processing with Gemini for background tasks."""

from typing import Any

from langchain_core.output_parsers import PydanticOutputParser

from app.db.mongodb.collections import mail_collection
from app.models.mail_models import EmailComprehensiveAnalysis
from shared.py.wide_events import log

email_comprehensive_parser = PydanticOutputParser(pydantic_object=EmailComprehensiveAnalysis)


async def get_email_importance_summaries(
    user_id: str, limit: int = 50, important_only: bool = False
) -> dict[str, Any]:
    """Get email importance summaries for a user."""
    log.set(mail_user_id=user_id, mail_limit=limit, mail_important_only=important_only)
    try:
        # Build query filter
        query_filter: dict[str, Any] = {"user_id": user_id}
        if important_only:
            query_filter["is_important"] = True

        # Get email summaries from database
        cursor = mail_collection.find(query_filter).sort("analyzed_at", -1).limit(limit)
        emails = await cursor.to_list(length=limit)

        # Convert ObjectId to string for JSON serialization
        for email in emails:
            email["_id"] = str(email["_id"])
            # Convert datetime to ISO string
            if "analyzed_at" in email:
                email["analyzed_at"] = email["analyzed_at"].isoformat()

        return {
            "status": "success",
            "emails": emails,
            "count": len(emails),
            "filtered_by_importance": important_only,
        }
    except Exception as e:
        log.error(f"Error retrieving email summaries for user {user_id}: {e}")
        raise


async def get_single_email_importance_summary(
    user_id: str, message_id: str
) -> dict[str, Any] | None:
    """Get the importance summary for a specific email."""
    log.set(mail_user_id=user_id, mail_message_id=message_id)
    try:
        # Find the email in database
        email = await mail_collection.find_one({"user_id": user_id, "message_id": message_id})

        if not email:
            return None

        # Convert ObjectId to string for JSON serialization
        email["_id"] = str(email["_id"])
        # Convert datetime to ISO string
        if "analyzed_at" in email:
            email["analyzed_at"] = email["analyzed_at"].isoformat()

        return {"status": "success", "email": email}
    except Exception as e:
        log.error(f"Error retrieving email summary for user {user_id}, message {message_id}: {e}")
        raise


async def get_bulk_email_importance_summaries(
    user_id: str, message_ids: list[str]
) -> dict[str, Any]:
    """Get importance summaries for multiple emails in bulk, indexed by message_id."""
    log.set(
        mail_user_id=user_id,
        mail_bulk_message_count=len(message_ids),
    )
    try:
        # Query for all emails matching the message IDs
        query_filter = {"user_id": user_id, "message_id": {"$in": message_ids}}

        cursor = mail_collection.find(query_filter)
        emails = await cursor.to_list(length=len(message_ids))

        # Convert ObjectId to string and datetime to ISO string
        processed_emails = []
        for email in emails:
            email["_id"] = str(email["_id"])
            if "analyzed_at" in email:
                email["analyzed_at"] = email["analyzed_at"].isoformat()
            processed_emails.append(email)

        # Create a mapping of message_id to email summary
        email_summaries = {email["message_id"]: email for email in processed_emails}

        # Get the found and missing message IDs
        found_message_ids = set(email_summaries.keys())
        missing_message_ids = set(message_ids) - found_message_ids

        return {
            "status": "success",
            "emails": email_summaries,
            "found_count": len(found_message_ids),
            "missing_count": len(missing_message_ids),
            "found_message_ids": list(found_message_ids),
            "missing_message_ids": list(missing_message_ids),
        }
    except Exception as e:
        log.error(f"Error retrieving bulk email summaries for user {user_id}: {e}")
        raise
