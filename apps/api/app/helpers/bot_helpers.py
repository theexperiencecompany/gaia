"""
Bot platform helper functions.

Provides utilities for bot authentication, user lookup, and conversation management
across Discord, Slack, Telegram platforms.
"""

from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status

from app.config.loggers import chat_logger as logger
from app.db.mongodb.collections import conversations_collection, users_collection
from app.models.chat_models import ConversationModel
from app.services.conversation_service import create_conversation_service

# Supported platforms for bot integration
SUPPORTED_PLATFORMS = {"discord", "slack", "telegram", "whatsapp", "cli"}


def validate_platform(platform: str) -> None:
    """
    Validate that platform is supported.

    Args:
        platform: Platform name to validate

    Raises:
        HTTPException: If platform is not supported
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform. Must be one of: {', '.join(SUPPORTED_PLATFORMS)}",
        )


async def get_user_by_platform_id(
    platform: str, platform_user_id: str
) -> Optional[dict]:
    """
    Find GAIA user by platform ID using structured platform_links format.

    Args:
        platform: Platform name (discord, slack, telegram)
        platform_user_id: User's ID on that platform

    Returns:
        User dict with user_id field (same format as web auth), or None
    """
    user_data = await users_collection.find_one(
        {f"platform_links.{platform}.{platform}_id": platform_user_id}
    )
    if not user_data:
        return None

    # Convert to same format as web auth (user_id string instead of _id ObjectId)
    user_info = {
        "user_id": str(user_data.get("_id")),
        **user_data,
    }
    user_info.pop("_id", None)
    return user_info


async def get_or_create_bot_conversation(
    platform: str,
    platform_user_id: str,
    channel_id: Optional[str],
    user_doc: dict,
) -> tuple[str, list]:
    """
    Get existing bot conversation or create new one with full message history.

    Conversations are scoped per platform/user/channel using session_key.

    Args:
        platform: Platform name (discord, slack, telegram)
        platform_user_id: User's ID on the platform
        channel_id: Optional channel/thread ID for scoping
        user_doc: GAIA user document from database

    Returns:
        Tuple of (conversation_id, messages_history)
        - conversation_id: Unique conversation identifier
        - messages_history: List of {"role": str, "content": str} messages
    """
    session_key = f"bot_{platform}_{platform_user_id}_{channel_id or 'dm'}"

    conversation = await conversations_collection.find_one(
        {"user_id": user_doc["user_id"], "session_key": session_key}
    )

    if conversation:
        messages = conversation.get("messages", [])
        # Map stored "bot" type to "assistant" role for LangChain compatibility
        formatted_messages = [
            {
                "role": "assistant" if msg["type"] == "bot" else msg["type"],
                "content": msg["response"],
            }
            for msg in messages
        ]
        logger.info(
            f"Found existing bot conversation {conversation['conversation_id']} "
            f"with {len(formatted_messages)} messages"
        )
        return conversation["conversation_id"], formatted_messages

    # Create new conversation (same as web flow)
    conversation_id = str(uuid4())
    await create_conversation_service(
        ConversationModel(
            conversation_id=conversation_id,
            description=f"{platform.title()} Chat",
        ),
        user_doc,
    )

    # Add bot-specific metadata
    await conversations_collection.update_one(
        {"user_id": user_doc["user_id"], "conversation_id": conversation_id},
        {
            "$set": {
                "session_key": session_key,
                "platform": platform,
                "channel_id": channel_id,
            }
        },
    )

    logger.info(
        f"Created new bot conversation {conversation_id} for {platform}/{platform_user_id}"
    )
    return conversation_id, []
