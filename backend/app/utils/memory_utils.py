"""Memory utilities for agent operations."""

import asyncio
from datetime import datetime, timezone

from app.config.loggers import llm_logger as logger
from app.services.memory_service import memory_service
from app.agents.templates.mail_templates import GmailMessageParser


async def store_user_message_memory(user_id: str, message: str, conversation_id: str):
    """Store user message in memory and return formatted data if successful."""
    try:
        result = await memory_service.store_memory(
            content=message,
            user_id=user_id,
            conversation_id=conversation_id,
            metadata={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
                "type": "user_message",
            },
        )

        if result:
            return {
                "type": "memory_stored",
                "content": f"Stored message: {message[:50]}...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
            }
    except Exception as e:
        logger.error(f"Error storing memory: {e}")

    return None


def start_memory_task(user_id: str, message: str, conversation_id: str):
    """Start memory storage task if conditions are met."""
    if user_id and message:
        return asyncio.create_task(
            store_user_message_memory(user_id, message, conversation_id)
        )
    return None


def check_memory_task_yield(memory_task, memory_yielded: bool):
    """Check if memory task is done and return data to yield."""
    if memory_task and memory_task.done() and not memory_yielded:
        try:
            memory_stored = memory_task.result()
            if memory_stored:
                return memory_stored, True
        except Exception as e:
            logger.error(f"Error getting memory task result: {e}")
            return None, True
    return None, memory_yielded


async def await_remaining_memory_task(memory_task, memory_yielded: bool):
    """Await remaining memory task if not yet yielded."""
    if memory_task and not memory_yielded:
        try:
            memory_stored = await memory_task
            if memory_stored:
                return memory_stored
        except Exception as e:
            logger.error(f"Error awaiting memory task: {e}")
    return None


def format_email_for_memory(parser: GmailMessageParser) -> str:
    """Format email content for Mem0 storage."""
    sender = parser.sender or "Unknown Sender"
    subject = parser.subject or "No Subject"
    content = parser.text_content or "No content available"

    return f"""User received email from {sender} with subject "{subject}".

{content}"""
