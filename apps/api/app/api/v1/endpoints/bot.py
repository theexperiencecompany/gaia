import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
import json
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.constants.auth import AUDIT_ACTOR_BOT_API
from app.constants.cache import BOT_UPGRADE_LINK_PREFIX, BOT_UPGRADE_LINK_TTL
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager, with_heartbeat
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
    BotSettingsResponse,
    IntegrationInfo,
    LinkedUsersResponse,
    ResetSessionRequest,
    ResetSessionResponse,
    TranscribeAudioResponse,
    UnlinkAccountResponse,
)
from app.models.payment_models import PlanType
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.audio_transcription_service import (
    MAX_AUDIO_BYTES,
    AudioTooLargeError,
    UnsupportedAudioFormatError,
    transcribe_audio,
    validate_audio_payload,
)
from app.services.bot.stream_frames import (
    approval_frame,
    comment_keepalive_frame,
    done_frame,
    error_frame,
    keepalive_frame,
    message_boundary_frame,
    notice_frame,
    session_token_frame,
    stream_error_frame,
    text_frame,
)
from app.services.bot_service import (
    BotService,
    build_bot_message_request,
    charge_bot_turn,
)
from app.services.bot_token_service import create_bot_session_token
from app.services.chat.stream import run_chat_stream_background
from app.services.integrations.marketplace import get_integration_details
from app.services.integrations.user_integrations import get_user_integration_records
from app.services.payments.payment_service import payment_service
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

# A user who has never linked GAIA has no personal checkout link to offer, so
# this stays generic — the /auth flow that follows resolves their identity
# first, and the linked-but-free notice below picks up from there next turn.
_UNLINKED_PAYWALL_NOTICE = (
    "GAIA is paid only. Link your account with /auth, then subscribe to GAIA Pro to chat."
)


def _refusal_stream(error_code: str) -> StreamingResponse:
    """A one-frame SSE reply refusing the turn before any work starts.

    Bots read this endpoint with a streaming body, so a refusal must travel as
    an SSE error frame — an HTTP error status would leave them an unreadable
    body. The code is the contract the bot adapters switch on.
    """

    async def frame() -> AsyncGenerator[str, None]:
        yield error_frame(error_code)

    return StreamingResponse(frame(), media_type="text/event-stream")


def _refusal_stream_with_notice(notice_text: str, error_code: str) -> StreamingResponse:
    """`_refusal_stream`, preceded by a `notice` frame carrying free-form text.

    Used for the unlinked-user paywall notice: the `notice` frame delivers it
    as a real outbound message (`deliverOutOfBand` in the shared streamer),
    and the trailing `error` frame is untouched so the existing /auth-link
    flow (token minting, `buildAuthLinkMessage`) still fires — no adapter
    change needed for either half.
    """

    async def frame() -> AsyncGenerator[str, None]:
        yield notice_frame(notice_text)
        yield error_frame(error_code)

    return StreamingResponse(frame(), media_type="text/event-stream")


def _notice_only_stream(notice_text: str) -> StreamingResponse:
    """Answer a turn with one canned line and no agent run: `notice` + `done`.

    No `text` frame is ever sent, so `onDone` receives an empty `fullText`
    and delivers nothing further — the `notice` is the whole reply. Reuses
    the same generic frames the rate-limit notice (`_bot_rate_limit_notice`)
    already proves out for arbitrary, per-user text (a checkout link, a
    discount code) with zero bot-adapter changes.
    """

    async def frame() -> AsyncGenerator[str, None]:
        yield notice_frame(notice_text)
        yield done_frame("")

    return StreamingResponse(frame(), media_type="text/event-stream")


def _paywall_notice(checkout_url: str) -> str:
    notice = f"GAIA is paid only. Subscribe to GAIA Pro to keep chatting: {checkout_url}"
    if settings.PAYWALL_DISCOUNT_CODE:
        notice += f" Use code {settings.PAYWALL_DISCOUNT_CODE} for a discount."
    return notice


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


async def _may_mint_bot_upgrade_link(user_id: str) -> bool:
    """Whether this turn may mint a fresh Dodo session for ``user_id``.

    A ``SET NX EX`` window, the same gate shape as
    ``workflow_repository.claim_limit_notice`` — one mint per user per
    ``BOT_UPGRADE_LINK_TTL``, so a burst of blocked turns costs one session
    instead of one per message.

    Fails CLOSED, unlike that sibling, because what is at stake differs. There,
    losing the gate costs the user a duplicate notification; here it costs a
    trail of orphan Dodo sessions, and the newest of those buries the session
    the user actually paid on when ``get_latest_for_user`` looks for it. A
    degraded link is a marketing regression; a buried payment is a paying
    customer told they have no subscription.
    """
    try:
        claimed = await redis_cache.client.set(
            f"{BOT_UPGRADE_LINK_PREFIX}{user_id}", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL
        )
    except Exception as e:
        log.warning(
            f"{LogTag.PAYMENT} Bot upgrade-link window unavailable, falling back to pricing page",
            user={"id": user_id},
            payment={"operation": "bot_upgrade_link_window"},
            failure_reason="window_unavailable",
            error_type=type(e).__name__,
        )
        return False
    return bool(claimed)


async def _bot_upgrade_url(user_id: str) -> str:
    """A one-tap Dodo checkout URL for this user, or the pricing page.

    Bots are where the pricing page is worst: a WhatsApp user has to go find the
    web app and sign in before they can pay, and most never do. A personalised
    checkout link removes both steps and attributes the subscription correctly.

    Bounded by ``_may_mint_bot_upgrade_link``: this is the ONE place a bot turn
    reaches Dodo, and both walls that call it — the paid-only gate and the
    rate-limit notice — repeat for every message until the user acts, so an
    ungated mint here is one throwaway session per inbound message. Outside the
    window the caller still gets a working URL, just the pricing page rather
    than a personalised one. The session itself is never cached and never
    reused: Dodo sessions are single-use, and handing back a spent one shows
    "link expired" (see ``create_pro_checkout``).
    """
    if not await _may_mint_bot_upgrade_link(user_id):
        return f"{settings.FRONTEND_URL}/pricing"
    try:
        pro = await payment_service.create_pro_checkout(user_id)
    except Exception as e:
        # A marketing link must never cost the user their reply — degrade to the
        # pricing page, loudly.
        # Bounded fields, not provider error text: the event stays queryable
        # without leaking upstream payloads into telemetry.
        log.warning(
            f"{LogTag.PAYMENT} Could not mint bot upgrade link, falling back to pricing page",
            user={"id": user_id},
            payment={"operation": "bot_upgrade_link"},
            failure_reason="checkout_unavailable",
            error_type=type(e).__name__,
        )
        return f"{settings.FRONTEND_URL}/pricing"
    return pro.checkout.payment_link or f"{settings.FRONTEND_URL}/pricing"


def _bot_upgrade_url_once(user_id: str) -> Callable[[], Awaitable[str]]:
    """A per-request resolver for this user's upgrade URL, minted at most once.

    Called from the stream translator, which used to mint a fresh Dodo
    checkout for every rate-limit card it saw. The resolver stays lazy on
    purpose: resolving eagerly before the stream opens would mint a checkout
    session on every bot turn, including the paying users who never see a
    paywall.

    Only the within-turn bound. Across turns the cap lives in
    ``_bot_upgrade_url`` itself, so a caller that reaches it directly (the
    paid-only gate does, having no stream to hang a resolver off) is bounded
    too.
    """
    cached: list[str] = []

    async def resolve() -> str:
        if not cached:
            cached.append(await _bot_upgrade_url(user_id))
        return cached[0]

    return resolve


async def _bot_rate_limit_notice(
    chunk: dict[str, Any], upgrade_url: Callable[[], Awaitable[str]]
) -> str | None:
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
    if card.get("current_plan") != PlanType.PRO.value:
        notice += f" [Upgrade to Pro]({await upgrade_url()}) for higher limits."
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


def _bot_stream_control_frame(
    chunk: str, conversation_id: str
) -> tuple[str | None, dict[str, Any] | None, bool]:
    """Peel Redis SSE framing off one raw chunk from ``_bot_stream_from_redis``.

    Returns ``(frame, data, stop)`` — see the tri-state contract below.
    """
    # A comment/[DONE]/malformed-JSON chunk yields a ready-to-send `frame`
    # (`data` is None); a content chunk yields the parsed payload as `data`
    # for `_bot_stream_payload_frame` (`frame` is None); a web-only
    # non-`data:` line yields both None. `stop` ends the stream after `frame`.
    if chunk.startswith(":"):
        return chunk, None, False

    # subscribe_stream id-tags every frame ("id: <redis-id>\ndata: ...") for
    # Last-Event-ID resume — split the id line off before the data checks, or
    # every content frame is silently dropped.
    if chunk.startswith("id: "):
        _, _, chunk = chunk.partition("\n")

    if not chunk.startswith("data: "):
        return None, None, False

    raw = chunk[len("data: ") :].strip()
    if raw == "[DONE]":
        return done_frame(conversation_id), None, True

    try:
        return None, json.loads(raw), False
    except json.JSONDecodeError as exc:
        log.warning(
            f"{LogTag.API} Bot stream: dropped a malformed SSE chunk",
            error_type=type(exc).__name__,
        )
        return None, None, False


async def _bot_stream_payload_frame(
    data: dict[str, Any], upgrade_url: Callable[[], Awaitable[str]]
) -> tuple[str | None, bool]:
    """Translate one parsed web SSE payload into a bot frame.

    Returns ``(frame, stop)`` — ``frame`` is ``None`` when nothing bots need.
    """
    # `frame` is None for a payload that carries nothing bots need (a
    # web-only field, an unrecognized shape). `stop` marks the terminal
    # `error` frame.
    if data.get("keepalive"):
        # Forward keepalives so bot clients reset inactivity timers.
        return keepalive_frame(), False

    # Surface rate-limit cards (web-only UI) to bots as a dedicated notice
    # frame the client delivers out of band, before the web-only fields are
    # dropped below.
    #
    # Its own frame, not a {"text"} one: text belongs to the assistant
    # message in flight, so a notice sent that way was dropped whenever that
    # message was discarded (a handoff preamble, a rewritten draft) — the
    # user hit a limit and was told nothing.
    if (rate_limit_notice := await _bot_rate_limit_notice(data, upgrade_url)) is not None:
        return notice_frame(rate_limit_notice), False

    # Surface HIL approval cards to bots as a dedicated frame the client
    # renders as an out-of-band prompt (before tool_data is dropped below).
    if (approval_payload := _bot_approval_payload(data)) is not None:
        return approval_frame(approval_payload), False

    # An assistant message just ended. Bots need this to know a bubble is
    # finished — and, when `discarded`, to take back the handoff preamble
    # they already showed.
    if "message_boundary" in data:
        return message_boundary_frame(data["message_boundary"]), False

    # Skip web-only fields.
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
        return None, False

    # Translate {"response": "..."} → {"text": "..."}
    if "response" in data:
        return text_frame(data["response"]), False
    if "error" in data:
        return error_frame(data["error"]), True

    return None, False


async def _bot_stream_entitlement_gate(user_id: str, platform: str) -> StreamingResponse | None:
    """Refuse a bot chat turn the linked user isn't entitled to send, or clear it.

    Re-checked every turn so a downgrade after linking is caught here.
    """
    # Two distinct gates: Pro-gated platform linking (premium platforms
    # only), then GAIA's paid-only gate, which blocks every platform
    # regardless of which ones require Pro to link at all.
    if await platform_requires_upgrade(user_id, platform):
        log.set(outcome="plan_required")  # pragma: no mutate
        _capture_bot_turn_refused(user_id, platform, "plan_required")
        return _refusal_stream(BOT_STREAM_ERROR_PLAN_REQUIRED)

    if not await is_paid(user_id):
        log.set(outcome="subscription_required")  # pragma: no mutate
        _capture_bot_turn_refused(user_id, platform, "subscription_required")
        return _notice_only_stream(_paywall_notice(await _bot_upgrade_url(user_id)))

    return None


def _bot_stream_failure_logger(
    stream_id: str, conversation_id: str
) -> Callable[[asyncio.Task[Any]], None]:
    """Build the ``on_done`` callback that logs an unhandled background stream failure."""

    def _log_stream_failure(t: asyncio.Task[Any]) -> None:
        if not t.cancelled() and (exc := t.exception()):
            log.error(
                f"{LogTag.API} Background stream task failed",
                stream_id=stream_id,
                conversation_id=conversation_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    return _log_stream_failure


async def _bot_stream_from_redis(
    request: Request,
    *,
    stream_id: str,
    conversation_id: str,
    upgrade_url: Callable[[], Awaitable[str]],
    session_token: str,
    platform: str,
) -> AsyncGenerator[str, None]:
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
        platform=platform,
    ):
        # Send session token as first event
        yield session_token_frame(session_token)

        # Send initial keepalive to establish connection
        yield comment_keepalive_frame()

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
                    break  # pragma: no mutate — last stmt in the loop; return is identical

                frame, data, stop = _bot_stream_control_frame(chunk, conversation_id)
                if frame is not None:
                    yield frame
                    if stop:
                        return
                    continue
                if data is None:
                    continue

                payload_frame, stop = await _bot_stream_payload_frame(data, upgrade_url)
                if payload_frame is not None:
                    yield payload_frame
                if stop:
                    break  # pragma: no mutate — last stmt in the loop; return is identical
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
            yield stream_error_frame()


@router.post(
    "/chat-stream",
    status_code=200,
    response_class=StreamingResponse,
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
        return _refusal_stream_with_notice(
            _UNLINKED_PAYWALL_NOTICE, BOT_STREAM_ERROR_NOT_AUTHENTICATED
        )

    user_id = _resolve_user_id(user)
    user["user_id"] = user_id  # Ensure user_id is always set in the dict
    log.set(user={"id": user_id}, outcome="success")

    if (refusal := await _bot_stream_entitlement_gate(user_id, body.platform)) is not None:
        return refusal

    await charge_bot_turn(user_id, body)

    conversation_id = await BotService.get_or_create_session(
        body.platform, body.platform_user_id, body.channel_id, user, is_dm=body.is_dm
    )

    message_request = await build_bot_message_request(body, conversation_id, user_id)

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
    spawn_background_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=message_request,
            user=user,
            conversation_id=conversation_id,
            source=body.platform,
        ),
        on_done=_bot_stream_failure_logger(stream_id, conversation_id),
    )

    # One resolver for the whole request, built before the stream opens, so a
    # turn that hits the rate limit repeatedly reuses one checkout link instead
    # of minting a fresh one per chunk.
    upgrade_url = _bot_upgrade_url_once(user_id)

    # The translator above drops every web-only frame, so the socket can go
    # quiet for minutes while the turn is busy. with_heartbeat guarantees a
    # byte on the wire regardless, so no proxy in the path can mistake a
    # working stream for a dead one.
    return StreamingResponse(
        with_heartbeat(
            _bot_stream_from_redis(
                request,
                stream_id=stream_id,
                conversation_id=conversation_id,
                upgrade_url=upgrade_url,
                session_token=session_token,
                platform=body.platform,
            )
        ),
        media_type="text/event-stream",
    )


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
        body.platform, body.platform_user_id, body.channel_id, user, is_dm=body.is_dm
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
        402: {"description": "Subscription required."},
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

    # Paid-only gate, imperative rather than `@require_subscription()`: the bot
    # API key is checked in the body, so a decorator would 402 a caller whose
    # key was never verified. An unlinked caller never reaches here —
    # `get_current_user` 401s first — so unlinked behavior is unchanged.
    # Ordering wart: `@tiered_rate_limit` already charged one transcription
    # against the caller's quota by this point. Harmless for a blocked user
    # (they cannot spend it) and not worth moving the key check to a
    # dependency for, which would fork this route from `bot_chat_stream`.
    #
    # `require_active_subscription` already logs the block and fires
    # PAYWALL_BLOCKED with this feature name; what it cannot do is stamp THIS
    # route's wide event. Without the outcome, "are voice notes failing on the
    # paywall or on the provider?" — the question an incident actually asks —
    # has no answer, because a refused transcribe and a served one leave
    # identical events. The value matches `_bot_stream_entitlement_gate` so one
    # query covers both bot surfaces. No CHAT_MESSAGE_REFUSED here: a
    # transcribe is not a chat turn, and counting it as one would inflate the
    # bot's refused-turn rate with events that have no turn behind them.
    try:
        await require_active_subscription(str(user["user_id"]), feature="bot_transcribe")
    except SubscriptionRequiredException:
        log.set(outcome="subscription_required")  # pragma: no mutate
        raise

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
    log.set(outcome="transcribed")  # pragma: no mutate
    return TranscribeAudioResponse(text=text)
