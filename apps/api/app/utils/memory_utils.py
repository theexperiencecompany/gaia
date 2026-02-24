"""Memory utilities for agent operations."""

from datetime import datetime, timezone

from app.config.loggers import llm_logger as logger
from app.services.memory_service import memory_service


async def store_user_message_memory(user_id: str, message: str, conversation_id: str):
    """Store user message in memory and return formatted data if successful."""
    try:
        result = await memory_service.store_memory(
            message=message,
            user_id=user_id,
            conversation_id=conversation_id,
            metadata={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
                "type": "user_message",
            },
            async_mode=True,
        )

        if result:
            return {
                "type": "memory_stored",
                "content": f"Stored message: {message}...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
            }
    except Exception as e:
        logger.error(f"Error storing memory: {e}")

    return None
