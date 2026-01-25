from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.agents.core.agent import call_agent_silent
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import chat_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.models.message_models import MessageRequestWithHistory

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
    """Find user by platform ID using structured format."""
    return await users_collection.find_one(
        {f"platform_links.{platform}.{platform}_id": platform_user_id}
    )


async def get_or_create_session(
    platform: str, platform_user_id: str, channel_id: Optional[str]
) -> str:
    # TODO: Replace with persistent session storage (e.g., Redis, MongoDB)
    # Temporary workaround: always return a new conversation ID (stateless)
    # session_key = f"{platform}:{platform_user_id}:{channel_id or 'dm'}"
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
        response_text, _ = await call_agent_silent(
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
        response_text, _ = await call_agent_silent(
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


# ============================================================================
# Bot Authentication Endpoints
# ============================================================================


@router.post("/auth/link/{platform}")
async def link_platform_account_authenticated(
    platform: str,
    platform_user_id: str = Query(...),
    user: dict = Depends(get_current_user),
) -> dict:
    """Link a platform account to the authenticated user's GAIA account."""
    if platform not in ["discord", "slack", "telegram"]:
        raise HTTPException(status_code=400, detail="Invalid platform")

    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    result = await users_collection.update_one(
        {"user_id": user_id}, {"$set": {f"platform_links.{platform}": platform_user_id}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "success": True,
        "message": f"Your {platform.title()} account has been linked to GAIA.",
        "platform": platform,
    }


@router.get("/auth/status/{platform}/{platform_user_id}")
async def check_auth_status(platform: str, platform_user_id: str) -> dict:
    """Check if a platform user is linked to a GAIA account."""
    user = await users_collection.find_one(
        {f"platform_links.{platform}.{platform}_id": platform_user_id}
    )
    return {
        "authenticated": user is not None,
        "platform": platform,
        "platform_user_id": platform_user_id,
    }
