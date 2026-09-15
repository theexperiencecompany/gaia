"""Platform account linking routes for the bot API.

Split out of endpoints/bot.py: these three routes are the linking
handshake (mint a token, redeem a one-tap code, read a token's display
metadata) and share nothing with the chat/stream transport beyond the bot API
key check. Mounted on the same /api/v1/bot prefix, so no URL moved.
"""

from datetime import UTC, datetime, timedelta
import secrets

from fastapi import APIRouter, HTTPException, Request

from app.api.v1.endpoints.bot import require_bot_api_key
from app.config.settings import settings
from app.constants.auth import AUDIT_ACTOR_BOT_API, AUDIT_ACTOR_UNAUTHENTICATED
from app.constants.cache import PLATFORM_LINK_TOKEN_PREFIX, PLATFORM_LINK_TOKEN_TTL
from app.constants.general import NEW_MESSAGE_BREAKER
from app.db.redis import redis_cache
from app.models.bot_models import (
    CreateLinkTokenRequest,
    CreateLinkTokenResponse,
    LinkTokenInfoResponse,
    LinkTokenRecord,
    RedeemLinkCodeRequest,
    RedeemLinkCodeResponse,
)
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import error_responses
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.onboarding.first_contact import build_first_contact
from app.services.platform_link_code_service import (
    claim_platform_link_code,
    discard_platform_link_code,
    release_platform_link_code,
)
from app.services.platform_link_completion import (
    PostLinkSideEffectError,
    complete_platform_link,
)
from app.services.platform_link_service import require_platform_plan
from app.services.user_service import get_user_by_id
from app.utils.auth_utils import resolve_bot_user
from app.utils.errors import create_error
from shared.py.wide_events import log

router = APIRouter()


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


@router.post(
    "/redeem-link-code",
    status_code=200,
    summary="Redeem Platform Link Code",
    description="Link a platform account using a one-tap code minted by the web at onboarding.",
    responses=error_responses(
        {
            400: "Code expired or already used",
            409: "Platform account linked to another GAIA user",
            429: "Platform requires a plan the user does not have",
        }
    ),
)
async def redeem_link_code(request: Request, body: RedeemLinkCodeRequest) -> RedeemLinkCodeResponse:
    """Consume a web-minted code and link the platform account that presented it.

    GAIA's whole first contact is composed here and delivered on the outbound
    queue; no model turn runs, the bubbles ARE the first message. They come
    back in the response only when that delivery failed, for the bot to send.

    Idempotent for the account the code already linked: a repeat tap on a spent
    code answers ``linked=True`` without running the link's side effects again.
    """
    await require_bot_api_key(request)
    log.set(operation="redeem_link_code", platform=body.platform)

    # Same guard as create_link_token: an API key holder must not be able to
    # redeem a code on behalf of an arbitrary platform user.
    state_platform = getattr(request.state, "bot_platform", None)
    state_user_id = getattr(request.state, "bot_platform_user_id", None)
    if (state_platform and state_platform != body.platform) or (
        state_user_id and state_user_id != body.platform_user_id
    ):
        log.audit(
            "platform link code rejected",
            actor=AUDIT_ACTOR_BOT_API,
            resource=body.platform_user_id,
            provider=body.platform,
            reason="platform_header_mismatch",
        )
        raise create_error(
            message="Request body does not match the authenticated bot headers",
            status_code=403,
        )

    claim = await claim_platform_link_code(body.code)
    payload = claim.payload
    if payload is None:
        # A spent code from an already-linked account is a second tap (deep
        # links and Telegram's /start re-fire), not a dead link. Replying with
        # the first tap's success avoids double side effects, for every platform.
        linked_user = await resolve_bot_user(body.platform, body.platform_user_id)
        if linked_user is not None:
            linked_user_id = linked_user.user_id
            log.set(user={"id": linked_user_id})
            log.audit(
                "platform link code already redeemed by this account",
                actor=linked_user_id,
                resource=body.platform_user_id,
                provider=body.platform,
            )
            log.set(outcome="success", is_new_link=False)
            # The first tap delivered the first contact; a second one owes
            # nothing, so there is nothing for the bot to send.
            return RedeemLinkCodeResponse(linked=True, delivered=True)

        if claim.in_flight:
            # A twin delivery holds the claim and is running the link right
            # now — the second tap above, arriving before the first finished.
            # The twin delivers the first contact, so this request stays silent.
            log.audit(
                "platform link code already being redeemed by this account",
                actor=AUDIT_ACTOR_BOT_API,
                resource=body.platform_user_id,
                provider=body.platform,
            )
            log.set(outcome="success", is_new_link=False)
            return RedeemLinkCodeResponse(linked=True, delivered=True)

        # Never log the code — it is the credential. The platform account that
        # presented it and the outcome are what make a probe findable.
        log.audit(
            "platform link code rejected",
            actor=AUDIT_ACTOR_BOT_API,
            resource=body.platform_user_id,
            provider=body.platform,
            reason="unknown_or_expired_code",
        )
        raise create_error(
            message="This link has expired or was already used.",
            why="the one-tap code is single-use and short-lived",
            fix="head back to GAIA on the web and pick your platform again",
            status_code=400,
        )

    log.set(user={"id": payload.user_id})
    profile: dict[str, str | None] = {"username": body.username, "display_name": body.display_name}

    try:
        await require_platform_plan(payload.user_id, body.platform)

        # First contact is composed here, not as a model turn — the opener turn
        # skipped per-pick promises and sometimes never produced connect links.
        # Link completion delivers it on the outbound queue.
        user = await get_user_by_id(payload.user_id)
        bubbles = await build_first_contact(
            payload.user_id, body.platform, user.name if user else None, payload.preferences
        )
        completion = await complete_platform_link(
            payload.user_id,
            body.platform,
            body.platform_user_id,
            profile=profile,
            first_contact=bubbles,
        )
    except PostLinkSideEffectError:
        # The link is written; only its follow-through failed. Spent, not released:
        # handed back, the retry would redeem it against the existing link and
        # publish the first contact a second time. The failure still surfaces.
        await discard_platform_link_code(body.code)
        raise
    except Exception:
        # Every refusal asks the user to tap the same link again, and the code is
        # the only way back without redoing onboarding: released, not spent.
        await release_platform_link_code(body.code)
        raise
    await discard_platform_link_code(body.code)
    log.audit(
        "platform account linked via one-tap code",
        actor=payload.user_id,
        resource=body.platform_user_id,
        provider=body.platform,
    )
    delivered = completion.first_contact_delivered
    log.set(outcome="success", is_new_link=completion.link.is_new_link, delivered=delivered)
    await _persist_first_contact(payload.user_id, body, bubbles)
    # A publish the queue refused is never retried, so the bubbles go back to
    # the bot that asked for the link rather than being lost.
    return RedeemLinkCodeResponse(
        linked=True, delivered=delivered, first_contact=[] if delivered else bubbles
    )


async def _persist_first_contact(
    user_id: str,
    body: RedeemLinkCodeRequest,
    bubbles: list[str],
) -> None:
    """Write the first contact into the platform's bot conversation.

    Nothing else does it, so without this the user's next message arrives
    into an empty thread. Best-effort: losing the transcript must never turn
    a successful link into an error, retried with a code already spent.
    """
    try:
        actor = AuthenticatedUser(user_id=user_id)
        conversation_id = await BotService.get_or_create_session(
            body.platform, body.platform_user_id, None, actor, is_dm=True
        )
        now = datetime.now(UTC)
        messages: list[MessageModel] = []
        # Only a turn the user really sent: WhatsApp/iMessage prefill is
        # editable and stored verbatim; Telegram's deep link carries no
        # text, so a canned-opener turn would fake input for "has spoken" checks.
        if body.first_message:
            messages.append(
                MessageModel(
                    type="user",
                    response=body.first_message,
                    date=(now - timedelta(milliseconds=100)).isoformat(),
                )
            )
        messages.append(
            MessageModel(
                type="bot",
                response=NEW_MESSAGE_BREAKER.join(bubbles),
                date=now.isoformat(),
            )
        )
        await update_messages(
            UpdateMessagesRequest(conversation_id=conversation_id, messages=messages),
            user=actor,
        )
    except Exception as e:
        # Swallowed deliberately (see above), but logged at error: nothing
        # retries this, so the thread is permanently missing the introduction
        # GAIA already sent. At warning it never reached an error dashboard.
        log.error(
            "could not persist the first-contact exchange",
            user={"id": user_id},
            provider=body.platform,
            error=str(e),
            error_type=type(e).__name__,
        )


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
