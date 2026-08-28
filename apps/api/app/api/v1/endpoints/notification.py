import asyncio
from html import escape
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from fastapi.responses import HTMLResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.constants.notifications import EXPO_TOKEN_PATTERN, MAX_DEVICES_PER_USER
from app.db.repositories.users import user_repository
from app.models.device_token_models import (
    DeviceTokenRequest,
    DeviceTokenResponse,
)
from app.models.notification.notification_models import (
    ChannelPreferences,
    ChannelPreferencesUpdate,
    NotificationRecord,
    NotificationStatus,
    NotificationView,
)
from app.models.notification.request_models import (
    BulkActionRequest,
    BulkActionSummary,
    NotificationResponse,
    PaginatedNotificationsResponse,
)
from app.models.user_models import AuthenticatedUser
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.device_token_service import get_device_token_service
from app.services.notification_service import notification_service
from app.utils.notification.channel_preferences import fetch_channel_preferences
from app.utils.notification.unsubscribe import verify_unsubscribe_token
from shared.py.wide_events import NotificationContext, log

router = APIRouter()

_UNSUBSCRIBE_INVALID_HTML = (
    "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
    "text-align: center;'><p>This unsubscribe link is invalid.</p>"
    "</body></html>"
)


@router.get("/notifications/unsubscribe", response_class=HTMLResponse)
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


@router.post("/notifications/unsubscribe")
async def unsubscribe_from_emails(token: Annotated[str, Query()]) -> Response:
    """RFC 8058 one-click unsubscribe target (List-Unsubscribe-Post). Mail
    clients POST here; the response must be a blank 200."""
    user_id = verify_unsubscribe_token(token)
    if not user_id:
        return Response(status_code=400)

    log.set(user={"id": user_id}, operation="unsubscribe_email_one_click")
    await _disable_email_channel(user_id)
    log.set(outcome="success")
    return Response(status_code=200)


async def _disable_email_channel(user_id: str) -> None:
    await user_repository.set_channel_preferences(user_id, email=False)


@router.get("/notifications", response_model=PaginatedNotificationsResponse)
async def get_notifications(
    status: NotificationStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Number of notifications to return"),
    offset: int = Query(default=0, ge=0, description="Number of notifications to skip"),
    channel_type: str | None = Query(None, description="Filter by channel type (e.g., email, sms)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> PaginatedNotificationsResponse:
    """Get user's notifications with pagination"""
    user_id = current_user.get("user_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(
        user={"id": user_id},
        operation="list",
        notification=NotificationContext(operation="list", channel=channel_type)
        if channel_type
        else NotificationContext(operation="list"),
    )

    try:
        notifications, notification_count = await asyncio.gather(
            notification_service.get_user_notifications(
                user_id, status, limit, offset, channel_type
            ),
            notification_service.get_user_notifications_count(user_id, status, channel_type),
        )

        log.set(outcome="success")
        log.set_ns("notification", result_count=len(notifications), success=True)
        return PaginatedNotificationsResponse(
            notifications=notifications,
            total=notification_count,
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to get notifications",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/notifications/preferences/channels", response_model=ChannelPreferences)
async def get_channel_preferences(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ChannelPreferences:
    """Get user's notification channel preferences."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(user={"id": user_id})

    try:
        prefs = await fetch_channel_preferences(user_id)
        log.set(operation="get_channel_preferences", outcome="success")
        return ChannelPreferences(
            telegram=prefs["telegram"],
            discord=prefs["discord"],
            whatsapp=prefs["whatsapp"],
            slack=prefs["slack"],
        )
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to get channel preferences",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/notifications/preferences/channels", response_model=ChannelPreferences)
async def update_channel_preferences(
    preferences: ChannelPreferencesUpdate = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ChannelPreferences:
    """Update user's notification channel preferences."""
    user_id = current_user.get("user_id")
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
        capture_context_event(
            AnalyticsEvents.NOTIFICATION_PREFERENCE_UPDATED,
            {
                "changed_channel_count": len(changed),
                "channels_enabled": sorted(c for c, on in changed.items() if on is True),
                "channels_disabled": sorted(c for c, on in changed.items() if on is False),
            },
        )
        log.set(operation="update_channel_preferences", outcome="success")
        return ChannelPreferences(
            telegram=prefs["telegram"],
            discord=prefs["discord"],
            whatsapp=prefs["whatsapp"],
            slack=prefs["slack"],
        )
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to update channel preferences",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/notifications/{notification_id}/actions/{action_id}/execute")
async def execute_action(
    request: Request,
    notification_id: str = Path(..., description="Notification ID"),
    action_id: str = Path(..., description="Action ID"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> NotificationResponse[dict[str, Any]]:
    """Execute a notification action.

    ``data`` stays a free-form dict: it is whatever the matched ``ActionHandler``
    produced (``ActionResult.data``), which is open by design.
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(
        user={"id": user_id},
        operation="execute_action",
        notification=NotificationContext(operation="dispatch", notification_id=notification_id),
    )

    try:
        result = await notification_service.execute_action(
            notification_id, action_id, user_id, request=request
        )

        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)

        log.set(outcome="success")
        log.set_ns("notification", success=True)
        return NotificationResponse(
            success=True,
            message=result.message or "Action executed successfully",
            data=result.data,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to execute action",
            user_id=user_id,
            notification_id=notification_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/notifications/{notification_id}/read")
async def mark_as_read(
    notification_id: str = Path(..., description="Notification ID"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> NotificationResponse[NotificationRecord]:
    """Mark notification as read.

    ``data`` is the stored record, not the flattened ``NotificationView`` that
    ``GET /notifications/{id}`` returns — the two endpoints have always returned
    different shapes under the same key.
    """
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(
        user={"id": user_id},
        operation="mark_read",
        notification=NotificationContext(operation="read", notification_id=notification_id),
    )

    try:
        updated_notification = await notification_service.mark_as_read(notification_id, user_id)
        if not updated_notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        log.set(outcome="success")
        log.set_ns("notification", success=True)
        return NotificationResponse(
            success=True,
            message="Notification marked as read",
            data=updated_notification,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to mark notification as read",
            user_id=user_id,
            notification_id=notification_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/notifications/bulk-actions")
async def bulk_actions(
    request: BulkActionRequest = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> NotificationResponse[BulkActionSummary]:
    """Perform bulk actions on multiple notifications"""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    notification_ids = request.notification_ids or []
    log.set(
        user={"id": user_id},
        operation="bulk_actions",
        notification=NotificationContext(
            operation="mark_all_read", result_count=len(notification_ids)
        ),
    )

    try:
        if not notification_ids:
            raise HTTPException(status_code=400, detail="No notification IDs provided")

        results = await notification_service.bulk_actions(notification_ids, user_id, request.action)

        successful = sum(1 for success in results.values() if success)
        total = len(results)

        log.set_ns(
            "notification",
            result_count=successful,
            success=successful == total,
        )

        return NotificationResponse(
            success=True,
            message=f"Bulk action completed: {successful}/{total} successful",
            data=BulkActionSummary(results=results, successful=successful, total=total),
        )

    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to perform bulk actions",
            user_id=user_id,
            notification_count=len(notification_ids),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/notifications/register-device", response_model=DeviceTokenResponse)
async def register_device_token(
    request: DeviceTokenRequest = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> DeviceTokenResponse:
    """
    Register a device token for push notifications
    """
    user_id = current_user.get("user_id")

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
            return DeviceTokenResponse(success=True, message="Device registered successfully")
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/notifications/unregister-device", response_model=DeviceTokenResponse)
async def unregister_device_token(
    token: str = Body(..., embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> DeviceTokenResponse:
    """
    Unregister a device token
    """
    user_id = current_user.get("user_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(user={"id": user_id})

    try:
        device_token_service = get_device_token_service()

        # Unregister token (service verifies ownership via user_id filter)
        success = await device_token_service.unregister_device_token(token, user_id)

        if success:
            log.set(operation="unregister_device", outcome="success")
            return DeviceTokenResponse(success=True, message="Device unregistered successfully")
        return DeviceTokenResponse(success=False, message="Device token not found")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to unregister device token",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/notifications/{notification_id}")
async def get_notification(
    notification_id: str = Path(..., description="Notification ID"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> NotificationResponse[NotificationView]:
    """Get a specific notification."""
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated or user_id not found")

    log.set(
        user={"id": user_id},
        operation="get",
        notification=NotificationContext(operation="read", notification_id=notification_id),
    )

    try:
        notification = await notification_service.get_notification(notification_id, user_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        log.set(outcome="success")
        log.set_ns("notification", success=True)
        return NotificationResponse(
            success=True,
            message="Notification retrieved successfully",
            data=notification,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.NOTIFICATION} Failed to get notification",
            user_id=user_id,
            notification_id=notification_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
