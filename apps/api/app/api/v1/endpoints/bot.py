from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import TypeAdapter

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.auth import get_current_user as get_request_user
from app.constants.auth import AUDIT_ACTOR_BOT_API
from app.constants.bot import BotRequestFailure
from app.constants.error_codes import BOT_ACCOUNT_NOT_LINKED, BOT_API_KEY_INVALID
from app.constants.log_tags import LogTag
from app.constants.platform_links import Platform
from app.db.redis import redis_cache
from app.decorators import (
    SubscriptionRequiredException,
    is_paid,
    require_active_subscription,
    tiered_rate_limit,
)
from app.models.bot_models import (
    BotAuthStatusResponse,
    BotChatRequest,
    BotSessionRequest,
    BotSettingsResponse,
    IntegrationInfo,
    LinkedUsersResponse,
    ResetSessionResponse,
    TranscribeAudioResponse,
    UnlinkAccountResponse,
)
from app.models.conversation_send_models import BotMessageAccepted
from app.models.integration_models import UserIntegrationDocument
from app.models.user_models import AuthenticatedUser
from app.models.work_cancel_models import ConversationStopResponse
from app.schemas.errors import error_responses
from app.services.analytics_service import capture
from app.services.audio_transcription_service import (
    MAX_AUDIO_BYTES,
    AudioTooLargeError,
    UnsupportedAudioFormatError,
    transcribe_audio,
    validate_audio_payload,
)
from app.services.bot_service import BotService
from app.services.bot_session_stop import reset_bot_session, stop_bot_session
from app.services.conversation.send import submit_bot_message
from app.services.integrations.marketplace import get_integration_details
from app.services.integrations.user_integrations import get_user_integration_records
from app.services.platform_link_service import (
    PlatformLinkService,
    platform_requires_upgrade,
)
from app.utils.auth_utils import resolve_bot_user
from shared.py.analytics import UserId
from shared.py.analytics.catalog.bots import BotAudioTranscribed, BotSessionReset
from shared.py.analytics.catalog.chat import ChatMessageRefused
from shared.py.analytics.catalog.integrations import IntegrationDisconnected
from shared.py.wide_events import log

router = APIRouter()


def _capture_bot_turn_refused(
    user_id: str, platform: str, reason: Literal["plan_required", "subscription_required"]
) -> None:
    """A bot turn stopped at a gate, with why — the counterpart to submitted."""
    capture(UserId(user_id), ChatMessageRefused(platform=platform, reason=reason))


def _bot_request_refused(
    status_code: int, reason: BotRequestFailure, message: str, code: str | None = None
) -> HTTPException:
    """Mark the wide event failed with its reason and build the refusal to raise."""
    log.fail(reason)
    detail: str | dict[str, str] = {"message": message, "code": code} if code else message
    return HTTPException(status_code=status_code, detail=detail)


async def _resolve_bot_caller(
    request: Request, platform: str, platform_user_id: str
) -> AuthenticatedUser | None:
    """Return the middleware-resolved user, else the platform account's linked user, else None."""
    user = get_request_user(request)
    if user is not None and getattr(request.state, "authenticated", False):
        return user
    return await resolve_bot_user(platform, platform_user_id)


async def _require_linked_bot_caller(
    request: Request, platform: str, platform_user_id: str
) -> AuthenticatedUser:
    """The caller's linked user; a 401 naming the unlinked account otherwise."""
    user = await _resolve_bot_caller(request, platform, platform_user_id)
    if user is None:
        raise _bot_request_refused(
            401,
            BotRequestFailure.ACCOUNT_NOT_LINKED,
            "This platform account is not linked to a GAIA account.",
            BOT_ACCOUNT_NOT_LINKED,
        )
    return user


def _require_valid_platform(platform: str) -> None:
    if not Platform.is_valid(platform):
        raise _bot_request_refused(400, BotRequestFailure.INVALID_PLATFORM, "Invalid platform")


async def require_bot_api_key(request: Request) -> None:
    """Verify that the request has a valid bot API key (set by BotAuthMiddleware)."""
    if not getattr(request.state, "bot_api_key_valid", False):
        raise _bot_request_refused(
            401,
            BotRequestFailure.BOT_API_KEY_INVALID,
            "Invalid or missing bot API key",
            BOT_API_KEY_INVALID,
        )


# ``get_user_integration_records`` returns dumped documents; the settings route
# validates them back into the document model where they enter the handler.
_USER_INTEGRATION_RECORDS = TypeAdapter(list[UserIntegrationDocument])


async def _bot_turn_refused(user_id: str, platform: str) -> bool:
    """Whether the linked user isn't entitled to send this bot chat turn, recording why.

    Re-checked every turn so a downgrade after linking is caught here.
    """
    # Two distinct gates: Pro-gated platform linking (premium platforms
    # only), then GAIA's paid-only gate, which blocks every platform
    # regardless of which ones require Pro to link at all.
    if await platform_requires_upgrade(user_id, platform):
        log.set(outcome="plan_required")  # pragma: no mutate
        _capture_bot_turn_refused(user_id, platform, "plan_required")
        return True

    if not await is_paid(user_id):
        log.set(outcome="subscription_required")  # pragma: no mutate
        _capture_bot_turn_refused(user_id, platform, "subscription_required")
        return True

    return False


@router.post(
    "/messages",
    status_code=202,
    summary="Send a Bot Message",
    description="Accept a message into the session's conversation; follow its events stream for the reply.",
)
async def bot_send_message(request: Request, body: BotChatRequest) -> BotMessageAccepted:
    """Accept a linked bot user's message on the conversation step and return its seq at once."""
    await require_bot_api_key(request)
    log.set(operation="bot_send_message", platform=body.platform)
    await BotService.enforce_rate_limit(body.platform, body.platform_user_id)
    user = await _require_linked_bot_caller(request, body.platform, body.platform_user_id)
    log.set(user={"id": user.user_id})
    if await _bot_turn_refused(user.user_id, body.platform):
        raise _bot_request_refused(
            402,
            BotRequestFailure.SUBSCRIPTION_REQUIRED,
            "This account's plan does not include messaging GAIA from this platform.",
        )
    accepted = await submit_bot_message(body, user)
    log.set(conversation={"id": accepted.conversation_id, "seq": accepted.seq})
    return accepted


@router.post(
    "/reset-session",
    response_model=ResetSessionResponse,
    status_code=200,
    summary="Reset Bot Session",
    description="Start a new conversation, archiving the current one.",
)
async def reset_session(request: Request, body: BotSessionRequest) -> ResetSessionResponse:
    """Archive the current conversation and start a fresh bot session."""
    await require_bot_api_key(request)
    log.set(operation="reset_session", platform=body.platform)

    user = await _require_linked_bot_caller(request, body.platform, body.platform_user_id)
    user_id = user.user_id
    log.set(user={"id": user_id})

    new_conversation_id = await reset_bot_session(
        body.platform, body.platform_user_id, body.channel_id, user, is_dm=body.is_dm
    )
    # Explicit id: bot routes are auth-excluded, so the request context has
    # nobody to attribute to (see apps/api/CLAUDE.md, Analytics).
    capture(UserId(user_id), BotSessionReset(platform=body.platform))
    log.set(outcome="success")
    return ResetSessionResponse(success=True, conversation_id=new_conversation_id)


@router.post(
    "/stop",
    summary="Stop Bot Conversation",
    description="Stop everything the session's conversation is running, keeping the session.",
)
async def stop_session(request: Request, body: BotSessionRequest) -> ConversationStopResponse:
    """Stop the bot session's conversation: its live turn and all its background work."""
    await require_bot_api_key(request)
    log.set(operation="stop_session", platform=body.platform)

    user = await _require_linked_bot_caller(request, body.platform, body.platform_user_id)
    log.set(user={"id": user.user_id})

    result = await stop_bot_session(
        body.platform, body.platform_user_id, body.channel_id, user, is_dm=body.is_dm
    )
    log.set(
        bot={"conversation_id": result.conversation_id},
        outcome="success",
        stopped_work=result.work.stopped_anything,
    )
    return result


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
    _require_valid_platform(platform)
    user = await resolve_bot_user(platform, platform_user_id)
    # The linked id is returned, not just the boolean: it is what the bot uses as
    # its PostHog distinct_id, so bot events land on the same profile as this
    # user's web and API events instead of a parallel `<platform>:<id>` ghost.
    log.set(outcome="success")
    return BotAuthStatusResponse(
        authenticated=user is not None,
        platform=platform,
        platform_user_id=platform_user_id,
        user_id=user.user_id if user is not None and user.user_id else None,
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
    _require_valid_platform(platform)
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
    _require_valid_platform(platform)
    user = await resolve_bot_user(platform, platform_user_id)

    if user is None:
        return BotSettingsResponse(
            authenticated=False,
            user_name=None,
            account_created_at=None,
            profile_image_url=None,
            connected_integrations=[],
        )

    user_id = user.user_id

    connected_integrations_list = []
    try:
        integrations = _USER_INTEGRATION_RECORDS.validate_python(
            await get_user_integration_records(user_id)
        )
        for integration_doc in integrations:
            integration_id = integration_doc.integration_id
            status = integration_doc.status
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
            user_id=user.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )

    user_name = user.name
    # ``picture`` is the profile image the user document actually carries; the
    # keys read here before (``profile_image_url``/``avatar_url``) never
    # existed on it, so bot settings always answered with no image.
    profile_image_url = user.picture
    account_created_at = user.created_at.isoformat() if user.created_at else None

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
        raise _bot_request_refused(
            400, BotRequestFailure.MISSING_PLATFORM_HEADERS, "Missing platform headers"
        )

    _require_valid_platform(platform)

    user = await resolve_bot_user(platform, platform_user_id)
    if user is None:
        log.audit(
            "platform account unlink rejected",
            actor=AUDIT_ACTOR_BOT_API,
            resource=platform_user_id,
            provider=platform,
            reason=BotRequestFailure.ACCOUNT_NOT_LINKED,
        )
        raise _bot_request_refused(
            404,
            BotRequestFailure.ACCOUNT_NOT_LINKED,
            "Account not linked",
            BOT_ACCOUNT_NOT_LINKED,
        )

    user_id = user.user_id
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
    capture(UserId(user_id), IntegrationDisconnected(integration_id=platform))
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
    responses=error_responses(
        {
            401: "Account not linked.",
            402: "Subscription required.",
            413: "Audio exceeds the maximum allowed size.",
            415: "Unsupported audio format.",
            502: "Transcription provider failed.",
        }
    ),
)
@tiered_rate_limit("audio_transcription")
async def transcribe_bot_audio(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    # `tiered_rate_limit` reads "user_id" off the `user` kwarg FastAPI injects,
    # so this stays the full auth dict — narrowing it to a `get_user_id`
    # string would silently skip rate limiting for this route.
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    content_length: Annotated[int | None, Header(alias="content-length")] = None,
) -> TranscribeAudioResponse:
    """Convert audio bytes into a transcript for bot adapters."""
    await require_bot_api_key(request)
    log.set(operation="bot_transcribe_audio", user={"id": user.user_id})

    # Imperative gate, not @require_subscription(): the bot API key is checked in the body, so a decorator would 402 an unverified caller (unlinked callers 401 earlier at get_current_user).
    # tiered_rate_limit already charged one transcription by this point — harmless, since a blocked user can't spend it. Outcome value matches _bot_turn_refused for one query across both bot surfaces.
    # No ChatMessageRefused here since a transcribe isn't a chat turn.
    try:
        await require_active_subscription(user.user_id, feature="bot_transcribe")
    except SubscriptionRequiredException:
        log.set(  # pragma: no mutate
            outcome="subscription_required", reason=BotRequestFailure.SUBSCRIPTION_REQUIRED
        )
        raise

    too_large = f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit."
    if content_length is not None and content_length > MAX_AUDIO_BYTES:
        raise _bot_request_refused(413, BotRequestFailure.AUDIO_TOO_LARGE, too_large)

    audio_bytes = await file.read(MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise _bot_request_refused(413, BotRequestFailure.AUDIO_TOO_LARGE, too_large)

    try:
        normalized = validate_audio_payload(content_type=file.content_type, size=len(audio_bytes))
    except AudioTooLargeError as e:
        raise _bot_request_refused(413, BotRequestFailure.AUDIO_TOO_LARGE, str(e)) from e
    except UnsupportedAudioFormatError as e:
        raise _bot_request_refused(415, BotRequestFailure.UNSUPPORTED_AUDIO_FORMAT, str(e)) from e

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
        raise _bot_request_refused(
            502, BotRequestFailure.TRANSCRIPTION_FAILED, "Transcription failed"
        ) from e

    # After the transcription succeeds: an event on entry would count failures
    # as successes. Length, not content — the transcript is user speech.
    capture(
        UserId(user.user_id),
        BotAudioTranscribed(audio_bytes=len(audio_bytes), transcript_length=len(text)),
    )
    log.set(outcome="transcribed")  # pragma: no mutate
    return TranscribeAudioResponse(text=text)
