"""Simple email processing with Gemini for background tasks."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.llm.client import init_llm
from app.agents.prompts.mail_prompts import (
    EMAIL_COMPREHENSIVE_ANALYSIS,
    SMART_REPLY_GENERATION,
)
from app.config.loggers import common_logger as logger
from app.db.mongodb.collections import mail_collection
from app.models.mail_models import EmailComprehensiveAnalysis, SmartRepliesResponse
from langchain_core.output_parsers import PydanticOutputParser

email_comprehensive_parser = PydanticOutputParser(
    pydantic_object=EmailComprehensiveAnalysis
)

smart_reply_parser = PydanticOutputParser(pydantic_object=SmartRepliesResponse)


async def get_email_importance_summaries(
    user_id: str, limit: int = 50, important_only: bool = False
) -> Dict[str, Any]:
    """
    Get email importance summaries for a user.

    Args:
        user_id: User ID
        limit: Maximum number of emails to return
        important_only: If True, only return important emails

    Returns:
        Dictionary containing email summaries and metadata
    """
    try:
        # Build query filter
        query_filter: Dict[str, Any] = {"user_id": user_id}
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
        logger.error(f"Error retrieving email summaries for user {user_id}: {e}")
        raise


async def get_single_email_importance_summary(
    user_id: str, message_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get importance summary for a specific email.

    Args:
        user_id: User ID
        message_id: Gmail message ID

    Returns:
        Dictionary containing email summary
    """
    try:
        # Find the email in database
        email = await mail_collection.find_one(
            {"user_id": user_id, "message_id": message_id}
        )

        if not email:
            return None

        # Convert ObjectId to string for JSON serialization
        email["_id"] = str(email["_id"])
        # Convert datetime to ISO string
        if "analyzed_at" in email:
            email["analyzed_at"] = email["analyzed_at"].isoformat()

        return {"status": "success", "email": email}
    except Exception as e:
        logger.error(
            f"Error retrieving email summary for user {user_id}, message {message_id}: {e}"
        )
        raise


async def process_email_comprehensive_analysis(
    subject: str, sender: str, date: str, content: str
) -> Optional[EmailComprehensiveAnalysis]:
    """
    Process email to determine importance, generate summary, and create semantic labels in one go.
    This is more efficient than separate API calls for importance and semantic analysis.

    Args:
        subject: Email subject
        sender: Email sender
        date: Email date
        content: Email content

    Returns:
        EmailComprehensiveAnalysis or None if processing fails
    """
    try:
        # Initialize Gemini LLM
        llm = init_llm(preferred_provider="gemini")

        # Format prompt with email data and format instructions
        prompt = EMAIL_COMPREHENSIVE_ANALYSIS.format(
            subject=subject,
            sender=sender,
            date=date,
            content=content,
            format_instructions=email_comprehensive_parser.get_format_instructions(),
        )

        # Get response from llm
        response = await llm.ainvoke(prompt)

        if isinstance(response, str):
            response_text = response.strip()
        else:
            response_text = response.text

        # Parse response following agent.py pattern
        try:
            # Parse using the parser directly
            result = email_comprehensive_parser.parse(response_text)
            logger.info(f"Successfully parsed comprehensive email analysis: {result}")
            return result

        except Exception as parse_error:
            logger.error(f"Failed to parse AI response with parser: {parse_error}")

            raise ValueError(
                "Failed to parse AI response. Please check the response format."
            )

    except Exception as e:
        logger.error(f"Error processing email comprehensive analysis with Gemini: {e}")
        return None


async def get_bulk_email_importance_summaries(
    user_id: str, message_ids: List[str]
) -> Dict[str, Any]:
    """
    Get importance summaries for multiple emails in bulk.

    Args:
        user_id: User ID
        message_ids: List of Gmail message IDs

    Returns:
        Dictionary containing email summaries indexed by message_id
    """
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
        logger.error(f"Error retrieving bulk email summaries for user {user_id}: {e}")
        raise


async def generate_smart_replies(
    subject: str, sender: str, date: str, content: str
) -> Optional[SmartRepliesResponse]:
    """Generate 3 smart reply suggestions using Gemini LLM."""
    try:
        llm = init_llm(preferred_provider="gemini")
        prompt = SMART_REPLY_GENERATION.format(
            subject=subject,
            sender=sender,
            date=date,
            content=content,
            format_instructions=smart_reply_parser.get_format_instructions(),
        )
        response = await llm.ainvoke(prompt)
        response_text = response.text if hasattr(response, "text") else str(response)
        result = smart_reply_parser.parse(response_text.strip())
        logger.info(f"Successfully generated smart replies for: {subject}")
        return result
    except Exception as e:
        logger.error(f"Error generating smart replies: {e}")
        return None


async def analyze_email_on_demand(
    user_id: str, message_id: str, email_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Run comprehensive analysis on an email and store in MongoDB. Returns cached if exists."""
    try:
        existing = await mail_collection.find_one(
            {"user_id": user_id, "message_id": message_id}
        )
        if existing:
            existing["_id"] = str(existing["_id"])
            if "analyzed_at" in existing:
                existing["analyzed_at"] = existing["analyzed_at"].isoformat()
            return existing

        analysis = await process_email_comprehensive_analysis(
            subject=email_data["subject"],
            sender=email_data["sender"],
            date=email_data["date"],
            content=email_data["content"],
        )

        if not analysis:
            return None

        doc: Dict[str, Any] = {
            "user_id": user_id,
            "message_id": message_id,
            "thread_id": email_data.get("thread_id"),
            "subject": email_data["subject"],
            "sender": email_data["sender"],
            "is_important": analysis.is_important,
            "importance_level": analysis.importance_level.value,
            "summary": analysis.summary,
            "semantic_labels": analysis.semantic_labels,
            "analyzed_at": datetime.now(timezone.utc),
        }

        await mail_collection.insert_one(doc)
        doc["_id"] = str(doc["_id"])
        doc["analyzed_at"] = doc["analyzed_at"].isoformat()
        return doc
    except Exception as e:
        logger.error(f"Error analyzing email on demand for {message_id}: {e}")
        return None


async def get_or_generate_smart_replies(
    user_id: str, message_id: str, email_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Get cached smart replies or generate new ones."""
    try:
        existing = await mail_collection.find_one(
            {
                "user_id": user_id,
                "message_id": message_id,
                "smart_replies": {"$exists": True},
            }
        )
        if existing and existing.get("smart_replies"):
            return {"smart_replies": existing["smart_replies"], "cached": True}

        result = await generate_smart_replies(
            subject=email_data["subject"],
            sender=email_data["sender"],
            date=email_data["date"],
            content=email_data["content"],
        )

        if not result:
            return None

        replies_data = [reply.model_dump() for reply in result.replies]

        await mail_collection.update_one(
            {"user_id": user_id, "message_id": message_id},
            {
                "$set": {
                    "smart_replies": replies_data,
                    "smart_replies_generated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "message_id": message_id,
                    "thread_id": email_data.get("thread_id"),
                    "subject": email_data["subject"],
                    "sender": email_data["sender"],
                },
            },
            upsert=True,
        )

        return {"smart_replies": replies_data, "cached": False}
    except Exception as e:
        logger.error(f"Error generating smart replies for {message_id}: {e}")
        return None
