from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.agents.core.agent import call_agent_silent
from app.config.loggers import chat_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.models.message_models import MessageRequestWithHistory
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()


class BotChatRequest(BaseModel):
    message: str
    platform: str
    platform_user_id: str
    channel_id: Optional[str] = None


class BotChatResponse(BaseModel):
    response: str
    conversation_id: str
    authenticated: bool


class SessionResponse(BaseModel):
    conversation_id: str
    platform: str
    platform_user_id: str


async def verify_bot_api_key(x_bot_api_key: str = Header(..., alias="X-Bot-API-Key")):
    bot_api_key = getattr(settings, "GAIA_BOT_API_KEY", None)
    if not bot_api_key or x_bot_api_key != bot_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def get_user_by_platform_id(
    platform: str, platform_user_id: str
) -> Optional[dict]:
    return await users_collection.find_one(
        {f"platform_links.{platform}": platform_user_id}
    )


async def get_or_create_session(
    platform: str, platform_user_id: str, channel_id: Optional[str]
) -> str:
    return str(uuid4())


@router.post(
    "/chat",
    response_model=BotChatResponse,
    status_code=200,
    summary="Authenticated Bot Chat",
    description="Process a chat message from an authenticated bot user.",
)
async def bot_chat(
    request: BotChatRequest, _: None = Depends(verify_bot_api_key)
) -> BotChatResponse:
    """
    Handle an authenticated chat request from a bot platform.

    Args:
        request (BotChatRequest): The chat request containing message and user details.

    Returns:
        BotChatResponse: The agent's response and session info.
    """
    user = await get_user_by_platform_id(request.platform, request.platform_user_id)

    if not user:
        return BotChatResponse(
            response="Please authenticate first using /auth",
            conversation_id="",
            authenticated=False,
        )

    conversation_id = await get_or_create_session(
        request.platform, request.platform_user_id, request.channel_id
    )

    message_request = MessageRequestWithHistory(
        message=request.message,
        conversation_id=conversation_id,
        messages=[{"role": "user", "content": request.message}],
    )

    try:
        response_text, _meta = await call_agent_silent(
            request=message_request,
            conversation_id=conversation_id,
            user=user,
            user_time=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error(f"Bot chat error: {e}")
        response_text = "An error occurred while processing your request."

    return BotChatResponse(
        response=response_text, conversation_id=conversation_id, authenticated=True
    )


@router.post(
    "/chat/public",
    response_model=BotChatResponse,
    status_code=200,
    summary="Public Bot Chat",
    description="Process a public (unauthenticated) chat message.",
)
async def bot_chat_public(
    request: BotChatRequest, _: None = Depends(verify_bot_api_key)
) -> BotChatResponse:
    """
    Handle an unauthenticated public chat request.

    This endpoint creates a temporary session and bot user context.

    Args:
        request (BotChatRequest): The chat request.

    Returns:
        BotChatResponse: The agent's response.
    """
    conversation_id = str(uuid4())

    bot_user = {
        "user_id": f"bot_{request.platform}",
        "email": f"bot@{request.platform}.gaia",
        "name": "GAIA Bot",
    }

    message_request = MessageRequestWithHistory(
        message=request.message,
        conversation_id=conversation_id,
        messages=[{"role": "user", "content": request.message}],
    )

    try:
        response_text, _meta = await call_agent_silent(
            request=message_request,
            conversation_id=conversation_id,
            user=bot_user,
            user_time=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error(f"Bot public chat error: {e}")
        response_text = "An error occurred while processing your request."

    return BotChatResponse(
        response=response_text, conversation_id=conversation_id, authenticated=False
    )


@router.get(
    "/session/{platform}/{platform_user_id}",
    response_model=SessionResponse,
    status_code=200,
    summary="Get Session",
    description="Retrieve or create a session for a platform user.",
)
async def get_session(
    platform: str,
    platform_user_id: str,
    channel_id: Optional[str] = None,
    _: None = Depends(verify_bot_api_key),
) -> SessionResponse:
    """
    Get the active conversation ID for a user.

    Args:
        platform (str): The platform name.
        platform_user_id (str): The user's ID on the platform.
        channel_id (Optional[str]): The channel ID.

    Returns:
        SessionResponse: The session details.
    """
    conversation_id = await get_or_create_session(
        platform, platform_user_id, channel_id
    )
    return SessionResponse(
        conversation_id=conversation_id,
        platform=platform,
        platform_user_id=platform_user_id,
    )
