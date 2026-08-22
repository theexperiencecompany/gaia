import asyncio
from collections.abc import AsyncGenerator
import json
import secrets
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.constants.auth import AUDIT_ACTOR_BOT_API, AUDIT_ACTOR_UNAUTHENTICATED
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX, PLATFORM_LINK_TOKEN_TTL
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager, with_heartbeat
from app.db.redis import redis_cache
from app.decorators import enforce_daily_cost_budget, enforce_tiered_limit, tiered_rate_limit
from app.models.bot_models import (
    BotAuthStatusResponse,
    BotChatRequest,
    BotSettingsResponse,
    CreateLinkTokenRequest,
    CreateLinkTokenResponse,
    IntegrationInfo,
    LinkedUsersResponse,
    LinkTokenInfoResponse,
    LinkTokenRecord,
    ResetSessionRequest,
    ResetSessionResponse,
    TranscribeAudioResponse,
    UnlinkAccountResponse,
)
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_event
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
from app.services.integrations.user_integrations import get_user_integration_records
from app.services.platform_link_service import (
    Platform,
    PlatformLinkService,
    platform_requires_upgrade,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import get_trace_id, log, log_context

router = APIRouter()

BOT_STREAM_ERROR_NOT_AUTHENTICATED = "not_authenticated"
BOT_STREAM_ERROR_PLAN_REQUIRED = "plan_required"


def _refusal_stream(error_code: str) -> StreamingResponse:
    """A one-frame SSE reply refusing the turn before any work starts.

    Bots read this endpoint with a streaming body, so a refusal must travel as
    an SSE error frame — an HTTP error status would leave them an unreadable
    body. The code is the contract the bot adapters switch on.
    """

    async def frame() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'error': error_code})}\n\n"

    return StreamingResponse(frame(), media_type="text/event-stream")


def _capture_bot_turn_refused(user_id: str, platform: str, reason: str) -> None:
    """A bot turn stopped at a gate, with why — the counterpart to submitted."""
    capture_event(
        user_id,
        AnalyticsEvents.CHAT_MESSAGE_REFUSED,
        {"platform": platform, "reason": reason},
    )


def _resolve_user_id(user: dict[str, Any]) -> str:
    """The stable GAIA user id from a user document, or "" if it carries neither key.

    Both keys must be tried: ``PlatformLinkService`` returns a transitional
    shape (``_id``, no ``user_id``) while the auth middleware's
    ``build_user_context()`` returns the opposite. This is the id every bot
    capture and audit line attributes to, so a wrong answer here silently moves
    the record onto another profile.
    """
    return str(user.get("user_id") or user.get("_id") or "")


async def require_bot_api_key(request: Request) -> None:
    """Verify that the request has a valid bot API key (set by BotAuthMiddleware)."""
    if not getattr(request.state, "bot_api_key_valid", False):
        raise HTTPException(status_code=401, detail="Invalid or missing bot API key")


def _bot_rate_limit_notice(chunk: dict[str, Any]) -> str | None:
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


def _bot_approval_payload(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a HIL ``approval_request`` card as a bot ``approval`` payload.

    Bots drop ``tool_data``, but the approval prompt MUST reach the user — a bot
    has no buttons, so the user answers yes/no in chat and the conversational
    resolver relays it. The bot client renders this as an out-of-band message.
    Returns the approval data, or ``None`` if ``chunk`` isn't such a card.
    """
    tool_data = chunk.get("tool_data")
    if not isinstance(tool_data, dict) or tool_data.get("tool_name") != APPROVAL_REQUEST_TOOL_NAME:
        return None
    data = tool_data.get("data")
    return data if isinstance(data, dict) else None


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
        log.audit(
            "platform link token rejected",
            actor=AUDIT_ACTOR_BOT_API,
            resource=body.platform_user_id,
            provider=body.platform,
            reason="platform_header_mismatch",
        )
        raise HTTPException(
            status_code=403,
            detail="Platform in body does not match X-Bot-Platform header",
        )
    if state_user_id and state_user_id != body.platform_user_id:
        log.audit(
            "platform link token rejected",
            actor=AUDIT_ACTOR_BOT_API,
            resource=body.platform_user_id,
            provider=body.platform,
            reason="platform_user_id_header_mismatch",
        )
        raise HTTPException(
            status_code=403,
            detail="platform_user_id in body does not match X-Bot-Platform-User-Id header",
        )

    token = secrets.token_urlsafe(32)
    redis_client = redis_cache.client
    token_key = f"{PLATFORM_LINK_TOKEN_PREFIX}:{token}"

    mapping: dict[str, str] = {
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

    # `token` (and the auth_url embedding it) is the link credential — the record
    # names the platform account it was minted for, never the token.
    log.audit(
        "platform link token issued",
        actor=AUDIT_ACTOR_BOT_API,
        resource=body.platform_user_id,
        provider=body.platform,
    )
    log.set(outcome="success")
    return CreateLinkTokenResponse(token=token, auth_url=auth_url)


@router.get(
    "/link-token-info/{token}",
    response_model=LinkTokenInfoResponse,
    status_code=200,
    summary="Get Link Token Display Info",
    description="Return non-sensitive display metadata for a pending link token.",
)
async def get_link_token_info(token: str) -> LinkTokenInfoResponse:
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
        # The route is unauthenticated and the token in the path is the whole
        # credential, so a miss is a probe against the link flow — recorded with
        # the outcome, never with the token that was presented.
        log.audit(
            "platform link token lookup rejected",
            actor=AUDIT_ACTOR_UNAUTHENTICATED,
            reason="unknown_or_expired_token",
        )
        raise HTTPException(status_code=404, detail="Token not found or expired")
    record = LinkTokenRecord.model_validate(data)
    log.set(platform=record.platform)
    log.audit(
        "platform link token presented",
        actor=AUDIT_ACTOR_UNAUTHENTICATED,
        provider=record.platform,
    )
    log.set(outcome="success")
    return LinkTokenInfoResponse(
        platform=record.platform,
        username=record.username,
        display_name=record.display_name,
    )


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
        return _refusal_stream(BOT_STREAM_ERROR_NOT_AUTHENTICATED)

    user_id = _resolve_user_id(user)
    user["user_id"] = user_id  # Ensure user_id is always set in the dict
    log.set(user={"id": user_id}, outcome="success")
    # Linking is Pro-gated for premium platforms; re-check on every turn so a
    # user who downgrades after linking is refused here, not silently served.
    if await platform_requires_upgrade(user_id, body.platform):
        log.set(outcome="plan_required")  # pragma: no mutate
        _capture_bot_turn_refused(user_id, body.platform, "plan_required")
        return _refusal_stream(BOT_STREAM_ERROR_PLAN_REQUIRED)

    # Same quota the web chat endpoint charges via @tiered_rate_limit. It cannot
    # be a decorator here: the caller is resolved from a platform link above, so
    # there is no authenticated user when the decorator would run. Without this a
    # free user had no message limit through a bot, and bot turns never reached
    # `record_activity` — leaving them off the heatmap, streak and badge.
    # `BotService.enforce_rate_limit` above stays: it is flat per-platform
    # anti-spam (20/min, plan-blind), not the plan quota.
    await enforce_tiered_limit(user_id, "chat_messages")
    # The second half of what web chat charges: the tiered limit caps how MANY
    # messages, this caps how EXPENSIVE the day has been. `LLMAccountingMiddleware`
    # is an unbypassable mid-flight backstop, so cost was always bounded — but
    # without this a bot user over budget got a stream that opened and then died
    # partway instead of a clean refusal before any work.
    await enforce_daily_cost_budget(user_id, feature_key="chat_messages")

    # Captured HERE, past every gate, for the same reason the web endpoint
    # captures after its own: chat:message_submitted is the ground-truth volume
    # metric, and a turn refused for plan or quota never reached the agent.
    # Counting refusals as submissions inflates bot volume by exactly the
    # traffic of the users who hit walls most, and makes the two surfaces
    # incomparable. A refusal is its own event, with a reason.
    capture_event(
        user_id,
        AnalyticsEvents.CHAT_MESSAGE_SUBMITTED,
        {
            "platform": body.platform,
            "has_files": bool(body.file_ids or body.file_data),
        },
    )

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
    def _log_stream_failure(t: asyncio.Task) -> None:
        if not t.cancelled() and (exc := t.exception()):
            log.error(
                f"{LogTag.API} Background stream task failed",
                stream_id=stream_id,
                conversation_id=conversation_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    spawn_background_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=message_request,
            user=user,
            conversation_id=conversation_id,
            source=body.platform,
        ),
        on_done=_log_stream_failure,
    )

    async def stream_from_redis() -> AsyncGenerator[str, None]:
        """Subscribe to Redis stream and translate chunks for bot clients.

        The body runs while the response streams — after the request's
        ``http_request`` event has emitted — so it needs its own boundary or
        the delivery outcome is silently discarded. The generator body
        inherits the request's context, so ``get_trace_id()`` still returns
        the request's trace_id.
        """
        async with log_context(
            "sse_delivery",
            trace_id=get_trace_id() or None,
            stream_id=stream_id,
            platform=body.platform,
        ):
            # Send session token as first event
            yield f"data: {json.dumps({'session_token': session_token})}\n\n"

            # Send initial keepalive to establish connection
            yield ": keepalive\n\n"

            try:
                async for chunk in stream_manager.subscribe_stream(stream_id):
                    # Match the web stream path: stop forwarding if the bot client
                    # dropped the connection. The background task keeps running and
                    # persists the conversation.
                    if await request.is_disconnected():
                        log.set(client_disconnected=True)
                        log.info(
                            f"{LogTag.API} Bot client disconnected, stream continues in background",
                            stream_id=stream_id,
                        )
                        break
                    # Forward keepalive comments directly
                    if chunk.startswith(":"):
                        yield chunk
                        continue

                    # subscribe_stream id-tags every frame ("id: <redis-id>\ndata: ...")
                    # for Last-Event-ID resume — split the id line off before the data
                    # checks, or every content frame is silently dropped.
                    if chunk.startswith("id: "):
                        _, _, chunk = chunk.partition("\n")

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

                        # Surface HIL approval cards to bots as a dedicated frame the
                        # client renders as an out-of-band prompt (before tool_data
                        # is dropped below).
                        approval_payload = _bot_approval_payload(data)
                        if approval_payload is not None:
                            yield f"data: {json.dumps({'approval': approval_payload})}\n\n"
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
                    except json.JSONDecodeError as exc:
                        log.warning(
                            f"{LogTag.API} Bot stream: dropped a malformed SSE chunk",
                            error_type=type(exc).__name__,
                        )
                        continue
            except asyncio.CancelledError:
                # Client disconnected mid-stream — expected, not an error. The
                # background LangGraph task keeps running and persists the result.
                log.set(client_disconnected=True)
                log.info(f"{LogTag.API} Bot stream cancelled (client disconnected)")
                raise
            except Exception as e:
                log.error(
                    f"{LogTag.API} Bot stream subscription error",
                    stream_id=stream_id,
                    conversation_id=conversation_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                yield f"data: {json.dumps({'error': 'Stream error occurred'})}\n\n"

    # The translator above drops every web-only frame, so the socket can go
    # quiet for minutes while the turn is busy. with_heartbeat guarantees a
    # byte on the wire regardless, so no proxy in the path can mistake a
    # working stream for a dead one.
    return StreamingResponse(with_heartbeat(stream_from_redis()), media_type="text/event-stream")


@router.post(
    "/reset-session",
    response_model=ResetSessionResponse,
    status_code=200,
    summary="Reset Bot Session",
    description="Start a new conversation, archiving the current one.",
)
async def reset_session(request: Request, body: ResetSessionRequest) -> ResetSessionResponse:
    """Archive the current conversation and start a fresh bot session."""
    await require_bot_api_key(request)
    log.set(operation="reset_session", platform=body.platform)

    # `user` is one of two genuinely different untyped dict shapes here —
    # middleware's `build_user_context()` output (has "user_id", no "_id") or
    # PlatformLinkService's legacy dict (has "_id", no "user_id") — normalized
    # below and handed to BotService, which re-normalizes it the same way for
    # every other bot endpoint. Unifying the two shapes is a cross-file change
    # (platform_link_service.py, bot_auth_middleware.py, bot_service.py) out
    # of scope here; see API CLAUDE.md Type Safety §14.
    user = getattr(request.state, "user", None)
    if not user or not getattr(request.state, "authenticated", False):
        user = await PlatformLinkService.get_user_by_platform_id(
            body.platform, body.platform_user_id
        )

    if not user:
        raise HTTPException(status_code=401, detail="User not authenticated")

    user_id = _resolve_user_id(user)
    user["user_id"] = user_id  # Ensure user_id is always set in the dict
    log.set(user={"id": user_id}, platform=body.platform)

    new_conversation_id = await BotService.reset_session(
        body.platform, body.platform_user_id, body.channel_id, user
    )
    # Explicit id: bot routes are auth-excluded, so the request context has
    # nobody to attribute to (see apps/api/CLAUDE.md, Analytics).
    capture_event(
        user_id,
        AnalyticsEvents.BOT_SESSION_RESET,
        {"platform": body.platform},
    )
    log.set(outcome="success")
    return ResetSessionResponse(success=True, conversation_id=new_conversation_id)


@router.get(
    "/auth-status/{platform}/{platform_user_id}",
    response_model=BotAuthStatusResponse,
    status_code=200,
    summary="Check Auth Status",
    description="Check if a platform user is linked to a GAIA account.",
)
# evlog-map-disable-next-line audit -- read-only auth status probe, no state change to audit
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
    # The linked id is returned, not just the boolean: it is what the bot uses as
    # its PostHog distinct_id, so bot events land on the same profile as this
    # user's web and API events instead of a parallel `<platform>:<id>` ghost.
    user_id = _resolve_user_id(user) if user else None
    log.set(outcome="success")
    return BotAuthStatusResponse(
        authenticated=user is not None,
        platform=platform,
        platform_user_id=platform_user_id,
        user_id=user_id or None,
    )


@router.get(
    "/linked-users/{platform}",
    status_code=200,
    summary="List Linked Platform Users",
    description="List platform_user_ids of accounts linked to a platform (bots use this to pre-warm DM caches).",
)
async def list_linked_users(request: Request, platform: str) -> LinkedUsersResponse:
    """Return the platform_user_ids linked on the given platform."""
    await require_bot_api_key(request)
    log.set(operation="list_linked_users", platform=platform)
    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")
    ids = await PlatformLinkService.list_platform_user_ids(platform)
    log.set(outcome="success", linked_count=len(ids))
    return LinkedUsersResponse(platform_user_ids=ids)


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

    user_id = _resolve_user_id(user)
    user["user_id"] = user_id  # Ensure user_id is always set in the dict

    connected_integrations_list = []
    try:
        integrations = await get_user_integration_records(user_id)
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
        log.error(
            f"{LogTag.API} Error fetching integrations for settings",
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )

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
    response_model=UnlinkAccountResponse,
    status_code=200,
    summary="Unlink Platform Account",
    description="Disconnect a platform account from the linked GAIA user.",
)
async def unlink_account(request: Request) -> UnlinkAccountResponse:
    """Unlink a platform user from their GAIA account."""
    await require_bot_api_key(request)
    log.set(operation="unlink_account")

    platform = request.headers.get("X-Bot-Platform")
    platform_user_id = request.headers.get("X-Bot-Platform-User-Id")

    if not platform or not platform_user_id:
        raise HTTPException(status_code=400, detail="Missing platform headers")

    if not Platform.is_valid(platform):
        raise HTTPException(status_code=400, detail="Invalid platform")

    # PlatformLinkService.get_user_by_platform_id returns a transitional
    # legacy dict (see `user_to_legacy_dict`) shared by several bot endpoints;
    # only "_id" is read here, so it stays a dict rather than introducing a
    # one-off model for a single field (API CLAUDE.md Type Safety §14).
    user = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)
    if not user:
        log.audit(
            "platform account unlink rejected",
            actor=AUDIT_ACTOR_BOT_API,
            resource=platform_user_id,
            provider=platform,
            reason="account_not_linked",
        )
        raise HTTPException(status_code=404, detail="Account not linked")

    user_id = str(user["_id"])
    await PlatformLinkService.unlink_account(user_id, platform)
    log.audit(
        "platform account unlinked",
        actor=user_id,
        resource=platform_user_id,
        provider=platform,
    )

    cache_key = f"bot_user:{platform}:{platform_user_id}"
    await redis_cache.client.delete(cache_key)

    # Same event the web-side platform unlink emits — one user action, one name,
    # regardless of which surface triggered it.
    capture_event(
        user_id,
        AnalyticsEvents.INTEGRATION_DISCONNECTED,
        {"integration_id": platform},
    )
    log.set(platform=platform, outcome="success")
    return UnlinkAccountResponse(success=True)


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
    # `tiered_rate_limit` finds the caller by reading the `user` keyword argument
    # FastAPI injects and pulling "user_id" off it, so this stays the full auth
    # dict rather than a `get_user_id` string — narrowing it would silently skip
    # rate limiting for this route.
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    content_length: Annotated[int | None, Header(alias="content-length")] = None,
) -> TranscribeAudioResponse:
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
        raise HTTPException(status_code=413, detail=str(e)) from e
    except UnsupportedAudioFormatError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e

    filename = file.filename or "voice-note"
    try:
        text = await transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=normalized,
        )
    except Exception as e:
        log.error(
            f"{LogTag.API} Transcription failed",
            filename=filename,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail="Transcription failed") from e

    # After the transcription succeeds: an event on entry would count failures
    # as successes. Length, not content — the transcript is user speech.
    capture_event(
        str(user.get("user_id")),
        AnalyticsEvents.BOT_AUDIO_TRANSCRIBED,
        {"audio_bytes": len(audio_bytes), "transcript_length": len(text)},
    )
    return TranscribeAudioResponse(text=text)
