"""Referral routes: the owner's page, the public invite landing, invites, suggestions and opt-out."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import HTMLResponse

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.referrals import (
    ATTRIBUTION_WINDOW,
    CODE_MAX_LENGTH,
    INVITE_UNSUBSCRIBE_PATH,
    INVITE_UNSUBSCRIBE_PROMPT,
    REFERRAL_COOKIE_NAME,
    ReferralCopyVariant,
)
from app.schemas.errors import HTML_ROUTE_ERROR_RESPONSES
from app.schemas.referrals import (
    ReferralInviteRequest,
    ReferralInviteResponse,
    ReferralMeResponse,
    ReferralResolveResponse,
    ReferralSuggestionsResponse,
)
from app.services.referrals.attribution import ReferralAttribution, first_touch_cookie
from app.services.referrals.invites import (
    invite_unsubscribe_subject,
    send_invites,
    unsubscribe_invite_recipient,
)
from app.services.referrals.overview import get_referral_overview, resolve_referral_code
from app.services.referrals.suggestions import suggest_invitees
from app.utils.notification.unsubscribe import (
    UNSUBSCRIBE_INVALID_HTML,
    render_unsubscribe_confirmation,
)
from shared.py.wide_events import log

router = APIRouter()

ReferralCode = Annotated[str, Path(min_length=1, max_length=CODE_MAX_LENGTH)]


@router.get("/me")
async def get_my_referrals(user_id: Annotated[str, Depends(get_user_id)]) -> ReferralMeResponse:
    """The caller's link, gift, free months and friends; 403 REFERRAL_SUBSCRIPTION_REQUIRED when not subscribed."""
    log.set(user={"id": user_id}, referral={"operation": "me"})
    result = await get_referral_overview(user_id)
    log.set_ns("referral", friends=len(result.friends), months_earned=result.months_earned)
    return result


@router.get("/resolve/{code}")
@limiter.limit("60/minute")
async def resolve_code(
    request: Request,
    response: Response,
    code: ReferralCode,
    landing_variant: ReferralCopyVariant | None = None,
) -> ReferralResolveResponse:
    """Public: who sent this invite link and the gift it carries; sets the 30-day first-touch cookie."""
    log.set(referral={"operation": "resolve", "landing_variant": landing_variant})
    result = await resolve_referral_code(code)
    cookie = first_touch_cookie(
        request.cookies.get(REFERRAL_COOKIE_NAME),
        ReferralAttribution(code=code, landing_variant=landing_variant),
        valid=result.valid,
    )
    if cookie is not None:
        response.set_cookie(
            key=REFERRAL_COOKIE_NAME,
            value=cookie,
            max_age=int(ATTRIBUTION_WINDOW.total_seconds()),
            httponly=True,
            secure=settings.ENV == "production",
        )
    log.set_ns("referral", valid=result.valid, cookie_set=cookie is not None)
    return result


@router.get("/suggestions")
async def get_suggestions(
    user_id: Annotated[str, Depends(get_user_id)],
) -> ReferralSuggestionsResponse:
    """People the caller met or emailed in the last 90 days, ranked; computed on demand, never stored."""
    log.set(user={"id": user_id}, referral={"operation": "suggestions"})
    result = await suggest_invitees(user_id)
    log.set_ns("referral", suggestions=len(result.suggestions))
    return result


@router.post("/invites")
@limiter.limit("20/minute")
async def create_invites(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    payload: ReferralInviteRequest,
    user_id: Annotated[str, Depends(get_user_id)],
) -> ReferralInviteResponse:
    """Send an invite to each address; every address gets its own status, and one bad one fails nothing."""
    log.set(
        user={"id": user_id},
        referral={
            "operation": "invite",
            "surface": payload.surface,
            "requested": len(payload.emails),
        },
    )
    result = await send_invites(user_id, payload)
    log.audit("referral invites sent", actor=user_id, count=len(result.results))
    return result


@router.get(
    "/unsubscribe/{token}",
    response_class=HTMLResponse,
    responses={
        **HTML_ROUTE_ERROR_RESPONSES,
        400: {
            "description": "Invalid unsubscribe token",
            "content": {"text/html": {"schema": {"type": "string"}}},
        },
    },
)
async def invite_unsubscribe_confirmation(token: str) -> HTMLResponse:
    """Public: the confirm page an invite's opt-out link opens; the button POSTs, so a link scanner opts nobody out."""
    log.set(referral={"operation": "unsubscribe_confirmation"})
    if invite_unsubscribe_subject(token) is None:
        return HTMLResponse(content=UNSUBSCRIBE_INVALID_HTML, status_code=400)
    return HTMLResponse(
        content=render_unsubscribe_confirmation(
            INVITE_UNSUBSCRIBE_PROMPT, f"{INVITE_UNSUBSCRIBE_PATH}{token}"
        )
    )


@router.post(
    "/unsubscribe/{token}",
    response_class=HTMLResponse,
    responses={**HTML_ROUTE_ERROR_RESPONSES, 400: {"description": "Invalid unsubscribe token"}},
)
async def invite_unsubscribe(token: str) -> Response:
    """Public: opt the address out of every future invite, whoever sends it; the RFC 8058 one-click target."""
    log.set(referral={"operation": "unsubscribe"})
    if not await unsubscribe_invite_recipient(token):
        return Response(status_code=400)
    log.set_ns("referral", unsubscribed=True)
    return Response(status_code=200)
