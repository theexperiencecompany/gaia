"""Memory utilities for agent operations."""

from datetime import UTC, datetime

from app.services.memory_service import memory_service
from shared.py.wide_events import log


async def store_user_message_memory(user_id: str, message: str, conversation_id: str):
    """Store user message in memory and return formatted data if successful."""
    log.set(
        user_id=user_id,
        conversation_id=conversation_id,
        operation="store_user_message_memory",
    )
    try:
        result = await memory_service.store_memory(
            message=message,
            user_id=user_id,
            conversation_id=conversation_id,
            metadata={
                "timestamp": datetime.now(UTC).isoformat(),
                "conversation_id": conversation_id,
                "type": "user_message",
            },
            async_mode=True,
        )

        if result:
            return {
                "type": "memory_stored",
                "content": f"Stored message: {message}...",
                "timestamp": datetime.now(UTC).isoformat(),
                "conversation_id": conversation_id,
            }
    except Exception as e:
        log.error(f"Error storing memory: {e}")

    return None
