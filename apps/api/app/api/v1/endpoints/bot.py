"""
Bot platform endpoints for Discord, Slack, Telegram, etc.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.agents.core.agent import call_agent
from app.api.v1.dependencies.bot_dependencies import verify_bot_api_key
from app.config.loggers import chat_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.general import NEW_MESSAGE_BREAKER
from app.helpers.bot_helpers import (
    get_or_create_bot_conversation,
    get_user_by_platform_id,
    validate_platform,
)
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import MessageRequestWithHistory
from app.schemas.bot.request import BotChatRequest
from app.schemas.bot.response import (
    AuthStatusResponse,
    BotChatResponse,
    BotSettingsResponse,
    ConnectedIntegration,
)
from app.services.conversation_service import update_messages
from app.services.model_service import get_user_context, get_user_selected_model
from app.services.oauth_service import get_all_integrations_status
from app.utils.stream_utils import (
    extract_complete_message,
    extract_response_text,
    is_done_marker,
)
from app.config import settings

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
            authenticated=False,
        )

    # Get or create conversation with full message history
    conversation_id, messages_history = await get_or_create_bot_conversation(
        platform=request.platform,
        platform_user_id=request.platform_user_id,
        channel_id=request.channel_id,
        user_doc=user,
    )

    # Get user context (model config, timezone)
    user_model_config, user_time = await get_user_context(user)

    # Process message through agent with conversation history
    try:
        # Build message list with history + current message
        messages = messages_history + [{"role": "user", "content": request.message}]

        message_request = MessageRequestWithHistory(
            message=request.message,
            conversation_id=conversation_id,
            messages=messages,
        )

        # Use streaming agent (same as web) but collect all chunks
        complete_message = ""
        async for chunk in await call_agent(
            request=message_request,
            conversation_id=conversation_id,
            user=user,
            user_time=user_time,
            user_model_config=user_model_config,
        ):
            nostream_msg = extract_complete_message(chunk)
            if nostream_msg is not None:
                complete_message = nostream_msg
                continue
            if is_done_marker(chunk):
                continue
            response_text = extract_response_text(chunk)
            if response_text:
                complete_message += response_text

        # Replace message breaks with newlines for bot platforms
        response_text = complete_message.replace(NEW_MESSAGE_BREAKER, "\n\n")

        # Save conversation (same as web flow in chat_service._save_conversation_async)
        user_message_id = str(uuid4())
        bot_message_id = str(uuid4())
        bot_timestamp = datetime.now(timezone.utc)
        user_timestamp = bot_timestamp - timedelta(milliseconds=100)

        user_message = MessageModel(
            type="user",
            response=request.message,
            date=user_timestamp.isoformat(),
            message_id=user_message_id,
        )
        bot_message = MessageModel(
            type="bot",
            response=response_text,
            date=bot_timestamp.isoformat(),
            message_id=bot_message_id,
        )

        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[user_message, bot_message],
            ),
            user=user,
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


# Integration icon paths matching toolIcons.tsx in web app
# These are relative paths that get prefixed with FRONTEND_URL
INTEGRATION_ICON_PATHS = {
    "google_calendar": "/images/icons/googlecalendar.webp",
    "gmail": "/images/icons/gmail.svg",
    "google_docs": "/images/icons/google_docs.webp",
    "googlesheets": "/images/icons/googlesheets.webp",
    "googletasks": "/images/icons/googletasks.svg",
    "googlemeet": "/images/icons/googlemeet.svg",
    "google_maps": "/images/icons/google_maps.svg",
    "notion": "/images/icons/notion.webp",
    "slack": "/images/icons/slack.svg",
    "twitter": "/images/icons/twitter.webp",
    "linkedin": "/images/icons/linkedin.svg",
    "github": "/images/icons/github.svg",
    "reddit": "/images/icons/reddit.svg",
    "instagram": "/images/icons/instagram.svg",
    "airtable": "/images/icons/airtable.svg",
    "linear": "/images/icons/linear.svg",
    "hubspot": "/images/icons/hubspot.svg",
    "todoist": "/images/icons/todoist.svg",
    "microsoft_teams": "/images/icons/microsoft_teams.svg",
    "zoom": "/images/icons/zoom.svg",
    "asana": "/images/icons/asana.svg",
    "trello": "/images/icons/trello.svg",
    "clickup": "/images/icons/clickup.svg",
}


def get_integration_icon_url(integration_id: str) -> str | None:
    """Get full icon URL for an integration."""
    path = INTEGRATION_ICON_PATHS.get(integration_id)
    if path:
        return f"{settings.FRONTEND_URL}{path}"
    return None


@router.get(
    "/settings/{platform}/{platform_user_id}",
    response_model=BotSettingsResponse,
    summary="Get User Settings",
    description="Get user profile, integrations, and model settings for bot display",
)
async def get_bot_settings(
    platform: str,
    platform_user_id: str,
    _: None = Depends(verify_bot_api_key),
) -> BotSettingsResponse:
    """
    Get user settings for bot display.

    Returns profile info, connected integrations, and selected model.
    Used by bots for /settings command display.
    """
    validate_platform(platform)

    user = await get_user_by_platform_id(platform, platform_user_id)
    if not user:
        return BotSettingsResponse(
            authenticated=False,
            user_name=None,
            profile_image_url=None,
            account_created_at=None,
            selected_model_name=None,
            selected_model_icon_url=None,
            connected_integrations=[],
        )

    user_id = user.get("user_id")

    # Get user's selected model
    model_name = None
    model_icon_url = None
    if user_id:
        try:
            model_config = await get_user_selected_model(user_id)
            if model_config:
                model_name = model_config.name
                model_icon_url = model_config.logo_url
        except Exception as e:
            logger.warning(f"Failed to get user model: {e}")

    # Get connected integrations
    connected_integrations: List[ConnectedIntegration] = []
    if user_id:
        try:
            integration_status = await get_all_integrations_status(user_id)
            for integration in OAUTH_INTEGRATIONS:
                if integration_status.get(integration.id, False):
                    connected_integrations.append(
                        ConnectedIntegration(
                            id=integration.id,
                            name=integration.name,
                            icon_url=get_integration_icon_url(integration.id),
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to get integration status: {e}")

    # Get account creation date from MongoDB _id or created_at field
    created_at: Union[str, datetime, None] = user.get("created_at")
    # Convert datetime to ISO string if needed
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    if not created_at and user.get("_id"):
        # Extract timestamp from ObjectId
        from bson import ObjectId

        try:
            created_at = ObjectId(user["_id"]).generation_time.isoformat()
        except Exception:
            logger.debug("Could not extract creation date from ObjectId")

    return BotSettingsResponse(
        authenticated=True,
        user_name=user.get("name") or user.get("email", "").split("@")[0],
        profile_image_url=user.get("profile_image_url") or user.get("picture"),
        account_created_at=created_at,
        selected_model_name=model_name,
        selected_model_icon_url=model_icon_url,
        connected_integrations=connected_integrations,
    )
