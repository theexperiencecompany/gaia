import asyncio
from datetime import UTC, datetime
import json
import secrets
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX, PLATFORM_LINK_TOKEN_TTL
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.decorators import tiered_rate_limit
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
from app.services.audio_transcription_service import (
    MAX_AUDIO_BYTES,
    AudioTooLargeError,
    UnsupportedAudioFormatError,
    transcribe_audio,
    validate_audio_payload,
)
from app.services.bot_service import BotService
from app.services.bot_token_service import create_bot_session_token
from app.services.chat.stream import run_chat_stream_background
from app.services.integrations.marketplace import get_integration_details
from app.services.integrations.user_integrations import get_user_connected_integrations
from app.services.platform_link_service import Platform, PlatformLinkService
from shared.py.wide_events import log

router = APIRouter()

_background_tasks: set[asyncio.Task] = set()


async def require_bot_api_key(request: Request) -> None:
    """Verify that the request has a valid bot API key (set by BotAuthMiddleware)."""
    if not getattr(request.state, "bot_api_key_valid", False):
        raise HTTPException(status_code=401, detail="Invalid or missing bot API key")


def _bot_rate_limit_notice(chunk: dict) -> str | None:
    """Render a web-only rate-limit card as a plain-text notice for bots.

    Rate limits are streamed as a ``tool_data`` card for the web UI to render.
    Bots drop ``tool_data``, so without this they'd silently swallow the limit.
    Returns the user-facing notice, or ``None`` if ``chunk`` isn't such a card.

    The upgrade link is emitted as CommonMark ``[label](url)``; each bot adapter
    localises it to its platform's link syntax (WhatsApp ``label (url)``, Slack
    ``<url|label>``, Telegram keeps ``[label](url)``).
    """
    tool_data = chunk.get("tool_data")
    if not isinstance(tool_data, dict) or tool_data.get("tool_name") != "rate_limit_data":
        return None

    card = tool_data.get("data") or {}
    feature = str(card.get("feature") or "this feature").replace("_", " ")
    notice = f"⏳ You've reached your {feature} limit. Please try again later."

    # Nudge an upgrade only for non-Pro users (Pro is the top tier).
    if card.get("current_plan") != "pro":
        pricing_url = f"{settings.FRONTEND_URL}/pricing"
        notice += f" [Upgrade to Pro]({pricing_url}) for higher limits."
    return notice


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
    log.set(operation="create_link_token", platform=body.platform)

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

    log.set(outcome="success")
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
    log.set(operation="get_link_token_info")
    redis_client = redis_cache.client
    token_key = f"{PLATFORM_LINK_TOKEN_PREFIX}:{token}"
    data = await redis_client.hgetall(token_key)
    if not data:
        raise HTTPException(status_code=404, detail="Token not found or expired")
    log.set(platform=data.get("platform"))
    log.set(outcome="success")
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
    """Stream a bot chat reply as SSE, resolving the linked user and replaying history."""
    await require_bot_api_key(request)
    log.set(operation="bot_chat_stream", platform=body.platform)
    await BotService.enforce_rate_limit(body.platform, body.platform_user_id)

    # Use middleware-resolved user if available
    user = getattr(request.state, "user", None)
    if not user or not getattr(request.state, "authenticated", False):
        user = await PlatformLinkService.get_user_by_platform_id(
            body.platform, body.platform_user_id
        )

    if not user:

        async def auth_required():
            """Emit a single `not_authenticated` SSE event for unlinked users."""
            yield f"data: {json.dumps({'error': 'not_authenticated'})}\n\n"

        return StreamingResponse(auth_required(), media_type="text/event-stream")

    user_id = user.get("user_id") or str(user.get("_id", ""))
    user["user_id"] = user_id  # Ensure user_id is always set in the dict
    log.set(user={"id": user_id}, platform=body.platform, outcome="success")

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
        fileIds=body.file_ids or [],
        fileData=body.file_data or [],
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
            user_time=datetime.now(UTC),
            conversation_id=conversation_id,
            source=body.platform,
        )
    )

    def task_done_callback(t: asyncio.Task):
        """Drop the finished background task from the registry and log failures."""
        _background_tasks.discard(t)
        if t.exception():
            log.error(f"Background stream task failed: {t.exception()}")

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

                    # Surface rate-limit cards (web-only UI) to bots as a short
                    # text notice, before the web-only fields are dropped below.
                    # Non-terminal: the agent's partial reply still streams, so
                    # pad with blank lines on both sides to keep the notice on its
                    # own paragraph rather than running into adjacent agent text.
                    rate_limit_notice = _bot_rate_limit_notice(data)
                    if rate_limit_notice is not None:
                        payload = json.dumps({"text": f"\n\n{rate_limit_notice}\n\n"})
                        yield f"data: {payload}\n\n"
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
            log.error(f"Bot stream subscription error: {e}")
            yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

    return StreamingResponse(stream_from_redis(), media_type="text/event-stream")


@router.post(
    "/reset-session",
    status_code=200,
    summary="Reset Bot Session",
    description="Start a new conversation, archiving the current one.",
)
async def reset_session(request: Request, body: ResetSessionRequest) -> dict:
    """Archive the current conversation and start a fresh bot session."""
    await require_bot_api_key(request)
    log.set(operation="reset_session", platform=body.platform)

    user = getattr(request.state, "user", None)
    if not user or not getattr(request.state, "authenticated", False):
        user = await PlatformLinkService.get_user_by_platform_id(
            body.platform, body.platform_user_id
        )

    if not user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    user_id = user.get("user_id") or str(user.get("_id", ""))
    user["user_id"] = user_id  # Ensure user_id is always set in the dict
    log.set(user={"id": user_id}, platform=body.platform)

    new_conversation_id = await BotService.reset_session(
        body.platform, body.platform_user_id, body.channel_id, user
    )
    log.set(outcome="success")
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
    """Report whether a platform user is linked to a GAIA account."""
    await require_bot_api_key(request)
    log.set(operation="check_auth_status", platform=platform)
    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")
    user = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)
    log.set(outcome="success")
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
    """Return the platform user's settings, connected integrations, and model."""
    await require_bot_api_key(request)
    log.set(operation="get_bot_settings", platform=platform)
    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")
    user = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)

    if not user:
        return BotSettingsResponse(
            authenticated=False,
            user_name=None,
            account_created_at=None,
            profile_image_url=None,
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
        log.error(f"Error fetching integrations for settings: {e}")

    user_name = user.get("name") or user.get("username")
    profile_image_url = user.get("profile_image_url") or user.get("avatar_url")
    account_created_at = None
    if user.get("created_at"):
        account_created_at = user["created_at"].isoformat()

    log.set(outcome="success")
    return BotSettingsResponse(
        authenticated=True,
        user_name=user_name,
        account_created_at=account_created_at,
        profile_image_url=profile_image_url,
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
    log.set(operation="unlink_account")

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

    log.set(platform=platform, outcome="success")
    return {"success": True}


@router.post(
    "/transcribe",
    status_code=200,
    summary="Transcribe Bot Audio",
    description=(
        "Transcribe a short audio clip (e.g. WhatsApp voice note) to text. "
        "Requires the bot to be authenticated as a linked platform user."
    ),
    responses={
        401: {"description": "Account not linked."},
        413: {"description": "Audio exceeds the maximum allowed size."},
        415: {"description": "Unsupported audio format."},
        502: {"description": "Transcription provider failed."},
    },
)
@tiered_rate_limit("audio_transcription")
async def transcribe_bot_audio(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    user: Annotated[dict, Depends(get_current_user)],
    content_length: Annotated[int | None, Header(alias="content-length")] = None,
) -> dict:
    """Convert audio bytes into a transcript for bot adapters."""
    await require_bot_api_key(request)
    log.set(operation="bot_transcribe_audio", user={"id": user.get("user_id")})

    if content_length is not None and content_length > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit.",
        )

    audio_bytes = await file.read(MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit.",
        )

    try:
        normalized = validate_audio_payload(content_type=file.content_type, size=len(audio_bytes))
    except AudioTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except UnsupportedAudioFormatError as e:
        raise HTTPException(status_code=415, detail=str(e))

    filename = file.filename or "voice-note"
    try:
        text = await transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=normalized,
        )
    except Exception as e:
        log.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Transcription failed")

    return {"text": text}
