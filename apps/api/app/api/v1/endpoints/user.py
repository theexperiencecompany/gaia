from datetime import UTC, datetime

from bson import ObjectId
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from workos import WorkOSClient

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.config.settings import settings
from app.constants.auth import WOS_SESSION_COOKIE
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import (
    AuthenticatedUser,
    AuthenticatedUserResponse,
    HoloCardOnboardingFields,
    PublicHoloCardResponse,
    UpdateHoloCardColorsResponse,
    UpdateTimezoneResponse,
    UserUpdate,
    UserUpdateResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event, track_logout
from app.services.onboarding.onboarding_service import get_user_onboarding_status
from app.services.user_service import update_user_profile
from app.utils.timezone import is_valid_timezone
from shared.py.wide_events import log

router = APIRouter()

workos = WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)


# exclude_none: the per-auth-path flags (impersonated/bot_authenticated/dev_bypass)
# and the optional profile fields are only meaningful when set — the response has
# always omitted them rather than sending nulls, and clients rely on that.
# evlog-map-disable-next-line audit -- read-only profile lookup, no state change to audit
@router.get("/me", response_model_exclude_none=True)
async def get_me(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUserResponse:
    """
    Returns the current authenticated user's details.
    Uses the dependency injection to fetch user data.
    """
    # Get onboarding status
    onboarding_status = await get_user_onboarding_status(user["user_id"])

    log.set(
        user={"id": user["user_id"], "email": user.get("email")},
        operation="get_me",
    )

    response = AuthenticatedUserResponse.model_validate(
        {**user, "message": "User retrieved successfully", "onboarding": onboarding_status}
    )

    log.set(outcome="success")
    return response


@router.patch("/me", response_model=UserUpdateResponse)
async def update_me(
    name: str | None = Form(None),
    picture: UploadFile | None = File(None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserUpdateResponse:
    """
    Update the current user's profile information.
    Supports updating name and profile picture.
    """
    user_id = user.get("user_id")
    log.set(
        user={"id": user_id, "email": user.get("email")},
        operation="update_me",
        has_picture_upload=bool(picture and picture.size and picture.size > 0),
    )

    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    # Process profile picture if provided
    picture_data = None
    if picture and picture.size and picture.size > 0:
        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if picture.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}",
            )

        # Validate file size (max 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        if picture.size > max_size:
            raise HTTPException(status_code=400, detail="File size too large. Maximum size is 5MB")

        picture_data = await picture.read()
        log.set(picture_size_bytes=picture.size)

    # Update user profile
    updated_user = await update_user_profile(user_id=user_id, name=name, picture_data=picture_data)

    changed_fields = [
        field
        for field, changed in (("name", name is not None), ("picture", picture_data is not None))
        if changed
    ]
    log.audit("profile updated", actor=user_id, changed_fields=changed_fields)
    capture_context_event(
        AnalyticsEvents.PROFILE_UPDATED,
        {
            "changed_field_count": len(changed_fields),
            "has_picture_upload": picture_data is not None,
        },
    )
    log.set(outcome="success")
    return updated_user


@router.patch("/name", response_model=UserUpdateResponse)
async def update_user_name(
    name: str = Form(...),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserUpdateResponse:
    """
    Update the user's name. This is the consolidated endpoint for name updates.
    """
    try:
        user_id = user.get("user_id")
        log.set(user={"id": user_id}, operation="update_user_name")

        if not user_id or not isinstance(user_id, str):
            raise HTTPException(status_code=400, detail="Invalid user ID")

        updated_user = await update_user_profile(user_id=user_id, name=name)
        log.audit("profile updated", actor=user_id, changed_fields=["name"])
        capture_context_event(AnalyticsEvents.PROFILE_UPDATED, {"changed_field_count": 1})
        log.set(outcome="success")
        return updated_user
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.API} Error updating user name",
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update name") from e


@router.patch("/timezone", response_model=UpdateTimezoneResponse)
async def update_user_timezone(
    user_timezone: str = Form(
        ...,
        description="User's timezone (e.g., 'America/New_York', 'Asia/Kolkata')",
        alias="timezone",
    ),
    user_id: str = Depends(get_user_id),
) -> UpdateTimezoneResponse:
    """
    Update user's timezone setting.
    This updates the root-level timezone field for the user.
    """
    try:
        log.set(
            user={"id": user_id},
            operation="update_user_timezone",
            timezone=user_timezone.strip(),
        )
        if not is_valid_timezone(user_timezone.strip()):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timezone: {user_timezone}. Use standard timezone identifiers like 'America/New_York', 'UTC', 'Asia/Kolkata'",
            )

        updated = await user_repository.update(user_id, UserUpdate(timezone=user_timezone.strip()))

        if updated is None:
            raise HTTPException(status_code=404, detail="User not found")

        log.audit("profile updated", actor=user_id, changed_fields=["timezone"])
        capture_context_event(AnalyticsEvents.PROFILE_UPDATED, {"changed_field_count": 1})
        log.set(outcome="success")
        return UpdateTimezoneResponse(
            success=True,
            message="Timezone updated successfully",
            timezone=user_timezone.strip(),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.API} Error updating timezone",
            user_id=user_id,
            timezone=user_timezone.strip(),
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update timezone") from e


@router.get("/holo-card/{card_id}")
# evlog-map-disable-next-line audit -- read-only public card lookup, no state change to audit
async def get_public_holo_card(card_id: str) -> PublicHoloCardResponse:
    """
    Get public holo card data by card ID (user ID).
    This endpoint is public and doesn't require authentication.
    Returns basic profile info without sensitive data like workflows.
    """
    try:
        log.set(operation="get_public_holo_card", card_id=card_id)

        if not ObjectId.is_valid(card_id):
            raise HTTPException(status_code=400, detail="Invalid card ID")

        user_doc = await user_repository.get(card_id)

        if not user_doc:
            raise HTTPException(status_code=404, detail="Card not found")

        onboarding = HoloCardOnboardingFields.model_validate(user_doc.onboarding or {})

        # Check if user has completed onboarding
        if not onboarding.house:
            raise HTTPException(status_code=404, detail="Card not found")

        # Get stored metadata or calculate if not stored (for older users)
        account_number = onboarding.account_number
        member_since = onboarding.member_since

        if not account_number or not member_since:
            created_at = user_doc.created_at
            if created_at:
                account_number = await user_repository.count_created_before(created_at) + 1
            else:
                account_number = 1

            member_since = (
                created_at.strftime("%b %d, %Y")
                if created_at
                else datetime.now(UTC).strftime("%b %d, %Y")
            )

        log.set(outcome="success")
        return PublicHoloCardResponse(
            house=onboarding.house,
            personality_phrase=onboarding.personality_phrase,
            user_bio=onboarding.user_bio,
            account_number=account_number,
            member_since=member_since,
            name=user_doc.name,
            overlay_color=onboarding.overlay_color,
            overlay_opacity=onboarding.overlay_opacity,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.API} Error fetching holo card",
            card_id=card_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch holo card data") from e


@router.patch("/holo-card/colors")
async def update_holo_card_colors(
    overlay_color: str = Form(..., description="Overlay color or gradient"),
    overlay_opacity: int = Form(..., description="Overlay opacity (0-100)"),
    user_id: str = Depends(get_user_id),
) -> UpdateHoloCardColorsResponse:
    """
    Update holo card overlay color and opacity.
    """
    try:
        log.set(
            user={"id": user_id},
            operation="update_holo_card_colors",
            overlay_color=overlay_color,
            overlay_opacity=overlay_opacity,
        )

        # Validate opacity range
        if not 0 <= overlay_opacity <= 100:
            raise HTTPException(status_code=400, detail="Opacity must be between 0 and 100")

        # Update user's onboarding data
        matched = await user_repository.set_holo_card_colors(
            user_id, overlay_color, overlay_opacity
        )

        if not matched:
            raise HTTPException(status_code=404, detail="User not found")

        log.audit(
            "profile updated",
            actor=user_id,
            changed_fields=["overlay_color", "overlay_opacity"],
        )
        capture_context_event(AnalyticsEvents.PROFILE_UPDATED, {"changed_field_count": 2})
        log.set(outcome="success")
        return UpdateHoloCardColorsResponse(
            success=True,
            message="Holo card colors updated successfully",
            overlay_color=overlay_color,
            overlay_opacity=overlay_opacity,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.API} Error updating holo card colors",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update holo card colors") from e


@router.post("/logout")
async def logout(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """
    Logout user and return logout URL for frontend redirection.
    """
    wos_session = request.cookies.get(WOS_SESSION_COOKIE)

    if not wos_session:
        raise HTTPException(status_code=401, detail="No active session")

    try:
        log.set(operation="logout")

        session = workos.user_management.load_sealed_session(
            sealed_session=wos_session,
            cookie_password=settings.WORKOS_COOKIE_PASSWORD,
        )

        if not session:
            raise HTTPException(status_code=401, detail="Invalid session")

        user_email: str | None = user.get("email")
        user_id: str | None = user.get("user_id")

        # The auth model always carries both fields, so an or-flip of this
        # guard is behaviorally unreachable (the mutation gate would never see
        # it red). pragma: no mutate
        if user_email and user_id:  # pragma: no mutate
            try:
                track_logout(user_id=user_id)
            except Exception as analytics_error:
                log.warning(
                    f"{LogTag.API} Failed to track logout analytics",
                    user_email=user_email,
                    error_type=type(analytics_error).__name__,
                    error=str(analytics_error),
                )

        logout_url = session.get_logout_url()

        log.audit("logged out", actor=user_id)

        # Create response with logout URL
        response = JSONResponse(content={"logout_url": logout_url})

        # Clear the session cookie
        response.delete_cookie(
            WOS_SESSION_COOKIE,
            httponly=True,
            path="/",
            secure=settings.ENV == "production",
            samesite="lax",
        )

        log.set(outcome="success")
        return response

    except Exception as e:
        log.error(
            f"{LogTag.API} Logout error",
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Logout failed") from e
