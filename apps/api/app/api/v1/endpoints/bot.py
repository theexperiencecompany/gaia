"""
Bot platform endpoints for Discord, Slack, Telegram, etc.
"""

from fastapi import APIRouter, Depends

from app.config.loggers import chat_logger as logger
from app.helpers.bot_helpers import (
    get_or_create_session,
    get_user_by_platform_id,
    get_user_context,
    process_chat_message,
    validate_platform,
)
from app.schemas.bot.request import BotChatRequest
from app.schemas.bot.response import AuthStatusResponse, BotChatResponse
from app.api.v1.dependencies.bot_dependencies import verify_bot_api_key

router = APIRouter()


@router.post(
    "/chat",
    response_model=BotChatResponse,
    summary="Authenticated Bot Chat",
    description="Process chat from authenticated bot user with full GAIA context",
)
async def bot_chat(
    request: BotChatRequest,
    _: None = Depends(verify_bot_api_key),
) -> BotChatResponse:
    """
    Handle authenticated chat from bot platforms.
    Returns unauthenticated response if user not linked.
    """
    validate_platform(request.platform)

    # Check if user is linked
    user = await get_user_by_platform_id(request.platform, request.platform_user_id)
    if not user:
        return BotChatResponse(
            response="Please link your account first",
            conversation_id="",
            authenticated=False,
        )

    conversation_id = await get_or_create_session(
        request.platform, request.platform_user_id, request.channel_id
    )

    # Get user context (model config, timezone)
    user_model_config, user_time = await get_user_context(user)

    # Process message through agent
    try:
        response_text = await process_chat_message(
            message=request.message,
            conversation_id=conversation_id,
            user=user,
            user_model_config=user_model_config,
            user_time=user_time,
        )
    except Exception as e:
        logger.error(
            f"Bot chat error for {request.platform}/{request.platform_user_id}: {e}",
            exc_info=True,
        )
        response_text = (
            "Sorry, something went wrong processing your message. Please try again."
        )

    return BotChatResponse(
        response=response_text,
        conversation_id=conversation_id,
        authenticated=True,
    )


# TODO: Temporarily disabled - require authentication for all bot interactions
# @router.post(
#     "/chat/public",
#     response_model=BotChatResponse,
#     summary="Public Bot Chat",
#     description="Process unauthenticated chat with limited capabilities",
# )
# async def bot_chat_public(
#     request: BotChatRequest,
#     _: None = Depends(verify_bot_api_key),
# ) -> BotChatResponse:
#     """
#     Handle public (unauthenticated) chat from bot platforms.
#
#     Creates temporary session with no user context. Limited capabilities:
#     - No access to integrations
#     - No personalization
#     - No memory retention
#     - Uses default model
#
#     Used for public mentions or before user links account.
#     """
#     validate_platform(request.platform)
#
#     conversation_id = str(uuid4())
#
#     # Create temporary bot user context
#     bot_user = {
#         "user_id": f"bot_{request.platform}",
#         "email": f"bot@{request.platform}.gaia",
#         "name": "GAIA Bot",
#         "timezone": "UTC",
#     }
#
#     # Process message with minimal context
#     try:
#         response_text = await process_chat_message(
#             message=request.message,
#             conversation_id=conversation_id,
#             user=bot_user,
#             user_model_config=None,
#             user_time=datetime.now(timezone.utc),
#         )
#     except Exception as e:
#         logger.error(
#             f"Bot public chat error for {request.platform}: {e}", exc_info=True
#         )
#         response_text = "Sorry, something went wrong. Please try again."
#
#     return BotChatResponse(
#         response=response_text,
#         conversation_id=conversation_id,
#         authenticated=False,
#     )


@router.get(
    "/auth/status/{platform}/{platform_user_id}",
    response_model=AuthStatusResponse,
    summary="Check Auth Status",
    description="Check if platform user is linked to GAIA account",
)
async def check_auth_status(
    platform: str,
    platform_user_id: str,
    _: None = Depends(verify_bot_api_key),
) -> AuthStatusResponse:
    """
    Check if a platform user has linked their GAIA account.

    Used by bots to determine whether to show auth prompt or process chat.
    """
    validate_platform(platform)

    user = await get_user_by_platform_id(platform, platform_user_id)

    return AuthStatusResponse(
        authenticated=user is not None,
        platform=platform,
        platform_user_id=platform_user_id,
    )
