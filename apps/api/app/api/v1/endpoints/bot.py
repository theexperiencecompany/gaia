import asyncio
import json
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from app.config.loggers import chat_logger as logger
from app.config.settings import settings
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX, PLATFORM_LINK_TOKEN_TTL
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.models.bot_models import (
    BotAuthStatusResponse,
    BotChatRequest,
    BotSettingsResponse,
    CreateLinkTokenRequest,
    CreateLinkTokenResponse,
    IntegrationInfo,
    ResetSessionRequest,
)
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.services.bot_service import BotService
from app.services.bot_token_service import create_bot_session_token
from app.services.chat_service import run_chat_stream_background
from app.services.integrations.marketplace import get_integration_details
from app.services.integrations.user_integrations import get_user_connected_integrations
from app.services.model_service import get_user_selected_model
from app.services.platform_link_service import Platform, PlatformLinkService
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

_background_tasks: set[asyncio.Task] = set()


async def require_bot_api_key(request: Request) -> None:
    """Verify that the request has a valid bot API key (set by BotAuthMiddleware)."""
    if not getattr(request.state, "bot_api_key_valid", False):
        raise HTTPException(status_code=401, detail="Invalid or missing bot API key")


@router.post(
    "/create-link-token",
    response_model=CreateLinkTokenResponse,
    status_code=200,
    summary="Create Platform Link Token",
    description="Generate a secure, time-limited token for platform account linking.",
)
async def create_link_token(
    request: Request, body: CreateLinkTokenRequest
) -> CreateLinkTokenResponse:
    """Create a secure token that bots include in auth URLs.

    This prevents CSRF attacks where an attacker crafts a link with someone
    else's platform user ID to hijack their account linking.
    """
    await require_bot_api_key(request)

    # Validate body matches the authenticated platform headers to prevent any
    # API key holder from generating tokens for arbitrary platform users.
    state_platform = getattr(request.state, "bot_platform", None)
    state_user_id = getattr(request.state, "bot_platform_user_id", None)

    if state_platform and state_platform != body.platform:
        raise HTTPException(
            status_code=403,
            detail="Platform in body does not match X-Bot-Platform header",
        )
    if state_user_id and state_user_id != body.platform_user_id:
        raise HTTPException(
            status_code=403,
            detail="platform_user_id in body does not match X-Bot-Platform-User-Id header",
        )

    token = secrets.token_urlsafe(32)
    redis_client = redis_cache.client
    token_key = f"{PLATFORM_LINK_TOKEN_PREFIX}:{token}"

    mapping: dict = {
        "platform": body.platform,
        "platform_user_id": body.platform_user_id,
    }
    if body.username:
        mapping["username"] = body.username
    if body.display_name:
        mapping["display_name"] = body.display_name

    await redis_client.hset(token_key, mapping=mapping)
    await redis_client.expire(token_key, PLATFORM_LINK_TOKEN_TTL)

    auth_url = f"{settings.FRONTEND_URL}/auth/link-platform?platform={body.platform}&token={token}"

    return CreateLinkTokenResponse(token=token, auth_url=auth_url)


@router.get(
    "/link-token-info/{token}",
    status_code=200,
    summary="Get Link Token Display Info",
    description="Return non-sensitive display metadata for a pending link token.",
)
async def get_link_token_info(token: str) -> dict:
    """Return display metadata from a link token for the confirmation page.

    The token itself is the credential — no additional auth required.
    Only returns non-sensitive display fields (platform, username, display_name).
    Does NOT consume the token.
    """
    redis_client = redis_cache.client
    token_key = f"{PLATFORM_LINK_TOKEN_PREFIX}:{token}"
    data = await redis_client.hgetall(token_key)
    if not data:
        raise HTTPException(status_code=404, detail="Token not found or expired")
    return {
        "platform": data.get("platform"),
        "username": data.get("username"),
        "display_name": data.get("display_name"),
    }


@router.post(
    "/chat-stream",
    status_code=200,
    summary="Streaming Bot Chat",
    description="Stream a chat response as Server-Sent Events.",
)
async def bot_chat_stream(request: Request, body: BotChatRequest) -> StreamingResponse:
    await require_bot_api_key(request)
    await BotService.enforce_rate_limit(body.platform, body.platform_user_id)

    # Use middleware-resolved user if available
    user = getattr(request.state, "user", None)
    if not user or not getattr(request.state, "authenticated", False):
        user = await PlatformLinkService.get_user_by_platform_id(
            body.platform, body.platform_user_id
        )

    if not user:

        async def auth_required():
            yield f"data: {json.dumps({'error': 'not_authenticated'})}\n\n"

        return StreamingResponse(auth_required(), media_type="text/event-stream")

    user_id = user.get("user_id") or str(user.get("_id", ""))
    user["user_id"] = user_id  # Ensure user_id is always set in the dict

    conversation_id = await BotService.get_or_create_session(
        body.platform, body.platform_user_id, body.channel_id, user
    )

    raw_history = await BotService.load_conversation_history(conversation_id, user_id)
    raw_history.append({"role": "user", "content": body.message})
    history: list[MessageDict] = [
        MessageDict(role=m["role"], content=m["content"]) for m in raw_history
    ]

    message_request = MessageRequestWithHistory(
        message=body.message,
        conversation_id=conversation_id,
        messages=history,
    )

    # Generate session token upfront so it can be sent in the stream
    session_token = create_bot_session_token(
        user_id=user_id,
        platform=body.platform,
        platform_user_id=body.platform_user_id,
        expires_minutes=15,
    )

    # Generate stream ID and start background streaming
    stream_id = str(uuid4())
    await stream_manager.start_stream(stream_id, conversation_id, user_id)

    # Launch background task
    task = asyncio.create_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=message_request,
            user=user,
            user_time=datetime.now(timezone.utc),
            conversation_id=conversation_id,
        )
    )

    def task_done_callback(t: asyncio.Task):
        _background_tasks.discard(t)
        if t.exception():
            logger.error(f"Background stream task failed: {t.exception()}")

    task.add_done_callback(task_done_callback)
    _background_tasks.add(task)

    async def stream_from_redis():
        """Subscribe to Redis stream and translate chunks for bot clients."""
        # Send session token as first event
        yield f"data: {json.dumps({'session_token': session_token})}\n\n"

        # Send initial keepalive to establish connection
        yield ": keepalive\n\n"

        try:
            async for chunk in stream_manager.subscribe_stream(stream_id):
                # Forward keepalive comments directly
                if chunk.startswith(":"):
                    yield chunk
                    continue

                if not chunk.startswith("data: "):
                    continue

                raw = chunk[len("data: ") :].strip()
                if raw == "[DONE]":
                    yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id})}\n\n"
                    return

                try:
                    data = json.loads(raw)

                    # Forward keepalives so bot clients reset inactivity timers
                    if data.get("keepalive"):
                        yield f"data: {json.dumps({'keepalive': True})}\n\n"
                        continue

                    # Skip web-only fields
                    if any(
                        key in data
                        for key in [
                            "conversation_description",
                            "user_message_id",
                            "bot_message_id",
                            "stream_id",
                            "tool_data",
                            "tool_output",
                            "follow_up_actions",
                        ]
                    ):
                        continue

                    # Translate {"response": "..."} → {"text": "..."}
                    if "response" in data:
                        yield f"data: {json.dumps({'text': data['response']})}\n\n"
                    elif "error" in data:
                        yield f"data: {json.dumps({'error': data['error']})}\n\n"
                        break
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.error(f"Bot stream subscription error: {e}")
            yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

    return StreamingResponse(stream_from_redis(), media_type="text/event-stream")


@router.post(
    "/reset-session",
    status_code=200,
    summary="Reset Bot Session",
    description="Start a new conversation, archiving the current one.",
)
async def reset_session(request: Request, body: ResetSessionRequest) -> dict:
    await require_bot_api_key(request)

    user = getattr(request.state, "user", None)
    if not user or not getattr(request.state, "authenticated", False):
        user = await PlatformLinkService.get_user_by_platform_id(
            body.platform, body.platform_user_id
        )

    if not user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    user_id = user.get("user_id") or str(user.get("_id", ""))
    user["user_id"] = user_id  # Ensure user_id is always set in the dict

    new_conversation_id = await BotService.reset_session(
        body.platform, body.platform_user_id, body.channel_id, user
    )
    return {"success": True, "conversation_id": new_conversation_id}


@router.get(
    "/auth-status/{platform}/{platform_user_id}",
    response_model=BotAuthStatusResponse,
    status_code=200,
    summary="Check Auth Status",
    description="Check if a platform user is linked to a GAIA account.",
)
async def check_auth_status(
    request: Request,
    platform: str,
    platform_user_id: str,
) -> BotAuthStatusResponse:
    await require_bot_api_key(request)
    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")
    user = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)
    return BotAuthStatusResponse(
        authenticated=user is not None,
        platform=platform,
        platform_user_id=platform_user_id,
    )


@router.get(
    "/settings/{platform}/{platform_user_id}",
    response_model=BotSettingsResponse,
    status_code=200,
    summary="Get User Settings",
    description="Get user account settings, connected integrations, and selected model.",
)
async def get_settings(
    request: Request,
    platform: str,
    platform_user_id: str,
) -> BotSettingsResponse:
    await require_bot_api_key(request)
    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")
    user = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)

    if not user:
        return BotSettingsResponse(
            authenticated=False,
            user_name=None,
            account_created_at=None,
            profile_image_url=None,
            selected_model_name=None,
            selected_model_icon_url=None,
            connected_integrations=[],
        )

    user_id = user.get("user_id") or str(user.get("_id", ""))
    user["user_id"] = user_id  # Ensure user_id is always set in the dict

    connected_integrations_list = []
    try:
        integrations = await get_user_connected_integrations(user_id)
        for integration_doc in integrations:
            integration_id = integration_doc.get("integration_id")
            status = integration_doc.get("status", "created")
            if integration_id:
                integration_details = await get_integration_details(integration_id)
                if integration_details:
                    connected_integrations_list.append(
                        IntegrationInfo(
                            name=integration_details.name,
                            logo_url=integration_details.icon_url,
                            status=status,
                        )
                    )
    except Exception as e:
        logger.error(f"Error fetching integrations for settings: {e}")

    selected_model_name = None
    selected_model_icon_url = None
    try:
        model = await get_user_selected_model(user_id)
        if model:
            selected_model_name = model.name
            selected_model_icon_url = model.logo_url
    except Exception as e:
        logger.error(f"Error fetching model for settings: {e}")

    user_name = user.get("name") or user.get("username")
    profile_image_url = user.get("profile_image_url") or user.get("avatar_url")
    account_created_at = None
    if user.get("created_at"):
        account_created_at = user["created_at"].isoformat()

    return BotSettingsResponse(
        authenticated=True,
        user_name=user_name,
        account_created_at=account_created_at,
        profile_image_url=profile_image_url,
        selected_model_name=selected_model_name,
        selected_model_icon_url=selected_model_icon_url,
        connected_integrations=connected_integrations_list,
    )


@router.post(
    "/unlink",
    status_code=200,
    summary="Unlink Platform Account",
    description="Disconnect a platform account from the linked GAIA user.",
)
async def unlink_account(request: Request) -> dict:
    """Unlink a platform user from their GAIA account."""
    await require_bot_api_key(request)

    platform = request.headers.get("X-Bot-Platform")
    platform_user_id = request.headers.get("X-Bot-Platform-User-Id")

    if not platform or not platform_user_id:
        raise HTTPException(status_code=400, detail="Missing platform headers")

    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")

    user = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Account not linked")

    user_id = str(user["_id"])
    await PlatformLinkService.unlink_account(user_id, platform)

    cache_key = f"bot_user:{platform}:{platform_user_id}"
    await redis_cache.client.delete(cache_key)

    return {"success": True}
