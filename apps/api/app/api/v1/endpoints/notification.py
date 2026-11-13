from html import escape
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Response,
)
from fastapi.responses import HTMLResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.constants.notifications import EXPO_TOKEN_PATTERN, MAX_DEVICES_PER_USER
from app.db.repositories.users import user_repository
from app.models.channel_preference_models import ChannelPreferences, ChannelPreferencesUpdate
from app.models.device_token_models import (
    PushTokenRequest,
    PushTokenResponse,
)
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import HTML_ROUTE_ERROR_RESPONSES
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import capture
from app.services.device_token_service import get_device_token_service
from app.utils.channel_preferences import fetch_channel_preferences
from app.utils.email_unsubscribe import verify_unsubscribe_token
from shared.py.analytics import UserId
from shared.py.analytics.catalog.notifications import NotificationUnsubscribed
from shared.py.analytics.catalog.settings import SettingsNotificationsToggled
from shared.py.wide_events import log

router = APIRouter()

_UNSUBSCRIBE_INVALID_HTML = (
    "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
    "text-align: center;'><p>This unsubscribe link is invalid.</p>"
    "</body></html>"
)


@router.get(
    "/notifications/unsubscribe",
    response_class=HTMLResponse,
    responses={
        **HTML_ROUTE_ERROR_RESPONSES,
        400: {
            "description": "Invalid unsubscribe token",
            "content": {"text/html": {"schema": {"type": "string"}}},
        },
    },
)
async def unsubscribe_confirmation(token: Annotated[str, Query()]) -> HTMLResponse:
    """Unsubscribe confirmation page — no login required. Renders a confirm
    button that POSTs to the same URL, so a GET (mail-client link scanner,
    prefetch) can never silently unsubscribe the user; the POST is the
    one-click target for RFC 8058 clients."""
    if not verify_unsubscribe_token(token):
        return HTMLResponse(content=_UNSUBSCRIBE_INVALID_HTML, status_code=400)

    log.set(operation="unsubscribe_email_confirmation")
    escaped_token = escape(token)
    form = (
        "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
        "text-align: center;'><p>Want to stop receiving GAIA emails?</p>"
        f"<form method='post' action='/api/v1/notifications/unsubscribe?token={escaped_token}'>"
        "<button style='background-color: #00bbff; color: #ffffff; padding: 8px 16px; "
        "border: none; border-radius: 4px; cursor: pointer;'>Unsubscribe</button>"
        "</form></body></html>"
    )
    return HTMLResponse(content=form)


@router.post(
    "/notifications/unsubscribe",
    response_class=HTMLResponse,
    responses={**HTML_ROUTE_ERROR_RESPONSES, 400: {"description": "Invalid unsubscribe token"}},
)
async def unsubscribe_from_emails(token: Annotated[str, Query()]) -> Response:
    """RFC 8058 one-click unsubscribe target (List-Unsubscribe-Post). Mail
    clients POST here; the response must be a blank 200."""
    user_id = verify_unsubscribe_token(token)
    if not user_id:
        return Response(status_code=400)

    log.set(user={"id": user_id}, operation="unsubscribe_email_one_click")
    # Built before the write, so a token signed for a non-user id fails before it unsubscribes anyone.
    user = UserId(user_id)
    await _disable_email_channel(user_id)
    log.set(outcome="success")
    capture(user, NotificationUnsubscribed())
    return Response(status_code=200)


async def _disable_email_channel(user_id: str) -> None:
    await user_repository.set_channel_preferences(user_id, email=False)


@router.get("/notifications/preferences/channels", response_model=ChannelPreferences)
async def get_channel_preferences(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ChannelPreferences:
    """Get user's notification channel preferences."""
    user_id = current_user.user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(user={"id": user_id})

    try:
        prefs = await fetch_channel_preferences(user_id)
        log.set(operation="get_channel_preferences", outcome="success")
        return ChannelPreferences.model_validate(prefs)
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to get channel preferences",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to get channel preferences") from e


@router.put("/notifications/preferences/channels", response_model=ChannelPreferences)
async def update_channel_preferences(
    preferences: ChannelPreferencesUpdate = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ChannelPreferences:
    """Update user's notification channel preferences."""
    user_id = current_user.user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(
        user={"id": user_id},
        notification={"channel_preferences_update": preferences.model_dump(exclude_none=True)},
    )

    try:
        await user_repository.set_channel_preferences(
            user_id,
            telegram=preferences.telegram,
            discord=preferences.discord,
            whatsapp=preferences.whatsapp,
            slack=preferences.slack,
        )
        schedule_account_sync(user_id)

        prefs = await fetch_channel_preferences(user_id)
        changed = preferences.model_dump(exclude_unset=True)
        capture(
            UserId(user_id),
            SettingsNotificationsToggled(
                changed_channel_count=len(changed),
                channels_enabled=sorted(c for c, on in changed.items() if on is True),
                channels_disabled=sorted(c for c, on in changed.items() if on is False),
            ),
        )
        log.set(operation="update_channel_preferences", outcome="success")
        return ChannelPreferences.model_validate(prefs)
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to update channel preferences",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to update channel preferences") from e


@router.post("/notifications/register-device", response_model=PushTokenResponse)
async def register_device_token(
    request: PushTokenRequest = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> PushTokenResponse:
    """Register a device token for push notifications."""
    user_id = current_user.user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(
        user={"id": user_id},
        device={"platform": request.platform, "device_id": request.device_id},
    )

    # Validate token format
    if not EXPO_TOKEN_PATTERN.match(request.token):
        raise HTTPException(
            status_code=400,
            detail="Invalid push token format. Expected ExponentPushToken[...]",
        )

    try:
        device_token_service = get_device_token_service()

        # Check device limit
        device_count = await device_token_service.get_user_device_count(user_id)
        if device_count >= MAX_DEVICES_PER_USER:
            # Check if this token already exists (update is OK)
            if not await device_token_service.verify_token_ownership(request.token, user_id):
                raise HTTPException(
                    status_code=400,
                    detail=f"Maximum {MAX_DEVICES_PER_USER} devices allowed per user",
                )

        success = await device_token_service.register_device_token(
            user_id=user_id,
            token=request.token,
            platform=request.platform,
            device_id=request.device_id,
        )

        if success:
            log.set(operation="register_device", outcome="success")
            return PushTokenResponse(success=True, message="Device registered successfully")
        raise HTTPException(status_code=500, detail="Failed to register device token")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to register device token",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to register device token") from e


@router.post("/notifications/unregister-device", response_model=PushTokenResponse)
async def unregister_device_token(
    token: str = Body(..., embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> PushTokenResponse:
    """Unregister a device token."""
    user_id = current_user.user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(user={"id": user_id})

    try:
        device_token_service = get_device_token_service()

        # Unregister token (service verifies ownership via user_id filter)
        success = await device_token_service.unregister_device_token(token, user_id)

        if success:
            log.set(operation="unregister_device", outcome="success")
            return PushTokenResponse(success=True, message="Device unregistered successfully")
        return PushTokenResponse(success=False, message="Device token not found")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to unregister device token",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to unregister device token") from e
