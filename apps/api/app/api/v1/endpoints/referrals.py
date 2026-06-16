"""Referral program endpoints: hub overview, public code resolution, invites, vanity codes."""

from fastapi import APIRouter, Depends, Response

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.constants.referrals import (
    REFERRAL_COOKIE_MAX_AGE_SECONDS,
    REFERRAL_COOKIE_NAME,
)
from app.schemas.referral_schemas import (
    InviteContactsResponse,
    InviteRequest,
    InviteResponse,
    ReferralMeResponse,
    ResolveCodeResponse,
    UpdateCodeRequest,
    UpdateCodeResponse,
)
from app.services.referrals import referral_service
from shared.py.wide_events import log

router = APIRouter()


@router.get("/me", response_model=ReferralMeResponse)
async def get_my_referrals(user: dict = Depends(get_current_user)) -> ReferralMeResponse:
    """Return the current user's referral hub: code, points, ladder, stats, friends, rewards."""
    log.set(referral={"operation": "get_me"})
    return await referral_service.get_my_referral_overview(user["user_id"])


@router.get("/resolve/{code}", response_model=ResolveCodeResponse)
async def resolve_referral_code(code: str, response: Response) -> ResolveCodeResponse:
    """Public: resolve a referral code for the invite landing page.

    On a valid code, sets a first-party, ``SameSite=Lax`` attribution cookie so
    the WorkOS signup callback can credit the referrer. Lax lets the cookie ride
    the top-level OAuth redirect while staying off cross-site subrequests.
    """
    log.set(referral={"operation": "resolve", "code": code})
    result = await referral_service.resolve_code(code)
    if result.valid:
        response.set_cookie(
            key=REFERRAL_COOKIE_NAME,
            value=code.strip().lower(),
            max_age=REFERRAL_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            secure=settings.ENV == "production",
            samesite="lax",
        )
    return result


@router.get("/contacts", response_model=InviteContactsResponse)
async def get_invite_contacts(
    user: dict = Depends(get_current_user),
) -> InviteContactsResponse:
    """Suggest Google contacts to invite (deduped against users + prior invites)."""
    log.set(referral={"operation": "import_contacts"})
    return await referral_service.get_invite_contacts(user["user_id"])


@router.post("/invite", response_model=InviteResponse)
async def invite_friends(
    payload: InviteRequest, user: dict = Depends(get_current_user)
) -> InviteResponse:
    """Send referral invite emails to friends (deduped + rate-limited)."""
    log.set(referral={"operation": "invite"})
    return await referral_service.send_invites(user["user_id"], payload.emails)


@router.patch("/code", response_model=UpdateCodeResponse)
async def update_referral_code(
    payload: UpdateCodeRequest, user: dict = Depends(get_current_user)
) -> UpdateCodeResponse:
    """Set a custom vanity referral code."""
    log.set(referral={"operation": "update_code"})
    return await referral_service.update_referral_code(user["user_id"], payload.code)
