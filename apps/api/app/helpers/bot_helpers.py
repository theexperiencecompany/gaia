"""
Bot platform helper functions.

Provides utilities for bot authentication, user lookup, session management,
and message processing across Discord, Slack, Telegram platforms.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.agents.core.agent import call_agent_silent
from app.config.loggers import chat_logger as logger
from app.db.mongodb.collections import users_collection
from app.models.message_models import MessageRequestWithHistory
from app.services.model_service import get_user_selected_model

# Supported platforms for bot integration
SUPPORTED_PLATFORMS = {"discord", "slack", "telegram"}


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
        User document if found, None otherwise
    """
    return await users_collection.find_one(
        {f"platform_links.{platform}.{platform}_id": platform_user_id}
    )


async def get_or_create_session(
    platform: str, platform_user_id: str, channel_id: Optional[str]
) -> str:
    """
    Get or create a conversation session.

    Note: Currently stateless - returns new conversation ID each time.
    TODO: Implement persistent session storage (Redis/MongoDB) to maintain
    conversation history across multiple messages.

    Args:
        platform: Platform name
        platform_user_id: User's platform ID
        channel_id: Optional channel/thread ID for scoping

    Returns:
        Conversation ID (currently always new UUID)
    """
    return str(uuid4())


async def get_user_context(user: dict) -> tuple[Optional[object], datetime]:
    """
    Get user's model config and timezone-aware datetime.

    Args:
        user: User document from database

    Returns:
        Tuple of (model_config, user_time)
    """
    # Get user's selected model preference
    user_model_config = None
    user_id = user.get("_id")
    if user_id:
        try:
            user_model_config = await get_user_selected_model(str(user_id))
        except Exception as e:
            logger.warning(f"Failed to get user model config: {e}")

    # Get user's timezone for accurate datetime
    user_timezone_str = user.get("timezone", "UTC")
    try:
        user_tz = ZoneInfo(user_timezone_str)
        user_time = datetime.now(user_tz)
    except Exception as e:
        logger.warning(f"Invalid timezone '{user_timezone_str}', using UTC: {e}")
        user_time = datetime.now(timezone.utc)

    return user_model_config, user_time


async def process_chat_message(
    message: str,
    conversation_id: str,
    user: dict,
    user_model_config: Optional[object],
    user_time: datetime,
) -> str:
    """
    Process chat message through GAIA agent.

    Args:
        message: User's message
        conversation_id: Conversation ID
        user: User document
        user_model_config: User's selected model config
        user_time: Timezone-aware current time

    Returns:
        Agent's response text

    Raises:
        Exception: If agent processing fails
    """
    message_request = MessageRequestWithHistory(
        message=message,
        conversation_id=conversation_id,
        messages=[{"role": "user", "content": message}],
    )

    response_text, _ = await call_agent_silent(
        request=message_request,
        conversation_id=conversation_id,
        user=user,
        user_time=user_time,
        user_model_config=user_model_config,
    )

    return response_text
