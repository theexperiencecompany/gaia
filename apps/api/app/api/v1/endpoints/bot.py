from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.agents.core.agent import call_agent_silent
from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
)
from app.config.loggers import chat_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import conversations_collection, users_collection
from app.models.chat_models import MessageModel, SystemPurpose, UpdateMessagesRequest
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.services.conversation_service import create_system_conversation, update_messages
from app.services.payments.payment_service import payment_service

router = APIRouter()

VALID_PLATFORMS = {"discord", "slack", "telegram"}
PUBLIC_CONTEXT_PREFIX = (
    "[SYSTEM: This message is from a public group channel. "
    "Do NOT access personal data. Do not use tools for "
    "email, calendar, files, todos, notes, reminders, "
    "goals, or workflows. Only respond with general "
    "knowledge and conversation.]\n\n"
)

tiered_limiter = TieredRateLimiter()


def validate_platform(platform: str) -> None:
    if platform not in VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")


class BotChatRequest(BaseModel):
    message: str
    platform: str
    platform_user_id: str
    channel_id: Optional[str] = None
    public_context: bool = False


class BotChatResponse(BaseModel):
    response: str
    conversation_id: str
    authenticated: bool


class SessionResponse(BaseModel):
    conversation_id: str
    platform: str
    platform_user_id: str


class NewSessionRequest(BaseModel):
    platform: str
    platform_user_id: str
    channel_id: Optional[str] = None


class NewSessionResponse(BaseModel):
    message: str
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


async def get_or_create_bot_session(
    user_id: str,
    platform: str,
    channel_id: Optional[str],
) -> str:
    query: dict = {
        "user_id": user_id,
        "is_system_generated": True,
        "system_purpose": SystemPurpose.BOT_CHAT.value,
        "metadata.bot_platform": platform,
        "metadata.bot_active": True,
    }
    if channel_id:
        query["metadata.bot_channel_id"] = channel_id

    # Sort by _id ascending to always pick the oldest session deterministically
    # (avoids non-determinism when multiple sessions exist due to concurrent creation)
    existing = await conversations_collection.find_one(query, sort=[("_id", 1)])

    if existing:
        return str(existing["conversation_id"])

    result = await create_system_conversation(
        user_id=user_id,
        description=f"Bot Chat ({platform})",
        system_purpose=SystemPurpose.BOT_CHAT,
    )
    conversation_id = result["conversation_id"]

    metadata = {
        "bot_platform": platform,
        "bot_channel_id": channel_id,
        "bot_active": True,
    }
    await conversations_collection.update_one(
        {"conversation_id": conversation_id},
        {"$set": {"metadata": metadata}},
    )

    return conversation_id


async def save_bot_messages(
    conversation_id: str, user_id: str, user_message: str, assistant_message: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    messages = [
        MessageModel(type="user", response=user_message, date=now),
        MessageModel(type="ai", response=assistant_message, date=now),
    ]
    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id, messages=messages
            ),
            {"user_id": user_id},
        )
    except Exception as e:
        logger.error(f"Failed to save bot messages: {e}")


@router.post(
    "/chat",
    response_model=BotChatResponse,
    status_code=200,
    summary="Bot Chat",
    description="Process a chat message from a bot platform user.",
)
async def bot_chat(
    request: BotChatRequest, _: None = Depends(verify_bot_api_key)
) -> BotChatResponse:
    validate_platform(request.platform)

    user = await get_user_by_platform_id(request.platform, request.platform_user_id)

    if not user:
        return BotChatResponse(
            response="Please authenticate first using /auth",
            conversation_id="",
            authenticated=False,
        )

    user_id = user.get("user_id", "")

    subscription = await payment_service.get_user_subscription_status(user_id)
    user_plan: PlanType = subscription.plan_type or PlanType.FREE
    try:
        await tiered_limiter.check_and_increment(user_id, "bot_chat", user_plan)
    except RateLimitExceededException:
        return BotChatResponse(
            response="You've reached your usage limit. Please try again later or upgrade your plan.",
            conversation_id="",
            authenticated=True,
        )

    conversation_id = await get_or_create_bot_session(
        user_id, request.platform, request.channel_id
    )

    # Prepend public context instruction into the message content so it reaches
    # the LLM via construct_langchain_messages (which reads messages[-1]["content"])
    message_content = request.message
    if request.public_context:
        message_content = PUBLIC_CONTEXT_PREFIX + request.message

    current_msg = MessageDict(role="user", content=message_content)
    message_request = MessageRequestWithHistory(
        message=message_content,
        conversation_id=conversation_id,
        messages=[current_msg],
    )

    agent_succeeded = False
    response_text = "An error occurred while processing your request."
    try:
        response_text, _meta = await call_agent_silent(
            request=message_request,
            conversation_id=conversation_id,
            user=user,
            user_time=datetime.now(timezone.utc),
        )
        agent_succeeded = True
    except Exception as e:
        logger.error(f"Bot chat error: {e}")

    if agent_succeeded:
        await save_bot_messages(conversation_id, user_id, request.message, response_text)

    return BotChatResponse(
        response=response_text, conversation_id=conversation_id, authenticated=True
    )


@router.post(
    "/chat/public",
    response_model=BotChatResponse,
    status_code=200,
    summary="Public Bot Chat (Deprecated)",
    description="Deprecated. Use /chat with public_context=true instead.",
    deprecated=True,
)
async def bot_chat_public(
    request: BotChatRequest, _: None = Depends(verify_bot_api_key)
) -> BotChatResponse:
    return BotChatResponse(
        response="This endpoint is deprecated. Please use /auth to link your account, then use the regular chat.",
        conversation_id="",
        authenticated=False,
    )


@router.post(
    "/session/new",
    response_model=NewSessionResponse,
    status_code=200,
    summary="Start New Session",
    description="Deactivate existing bot sessions and start fresh.",
)
async def new_session(
    request: NewSessionRequest, _: None = Depends(verify_bot_api_key)
) -> NewSessionResponse:
    validate_platform(request.platform)

    user = await get_user_by_platform_id(request.platform, request.platform_user_id)
    if not user:
        return NewSessionResponse(
            message="Please authenticate first using /auth",
            platform=request.platform,
            platform_user_id=request.platform_user_id,
        )

    user_id = user.get("user_id", "")

    query: dict = {
        "user_id": user_id,
        "is_system_generated": True,
        "system_purpose": SystemPurpose.BOT_CHAT.value,
        "metadata.bot_platform": request.platform,
        "metadata.bot_active": True,
    }
    if request.channel_id:
        query["metadata.bot_channel_id"] = request.channel_id

    await conversations_collection.update_many(
        query,
        {"$set": {"metadata.bot_active": False}},
    )

    return NewSessionResponse(
        message="New session started. Your next message will begin a fresh conversation.",
        platform=request.platform,
        platform_user_id=request.platform_user_id,
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
    validate_platform(platform)

    user = await get_user_by_platform_id(platform, platform_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user.get("user_id", "")
    conversation_id = await get_or_create_bot_session(
        user_id, platform, channel_id
    )

    return SessionResponse(
        conversation_id=conversation_id,
        platform=platform,
        platform_user_id=platform_user_id,
    )
