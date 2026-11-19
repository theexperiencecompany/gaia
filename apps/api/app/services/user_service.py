from datetime import datetime

from fastapi import HTTPException

from app.constants.files import BlobKind
from app.db.repositories.users import user_repository
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours
from app.models.user_models import (
    ProfilePictureUpload,
    UserDocument,
    UserUpdate,
    UserUpdateResponse,
)
from app.services.analytics_service import capture
from app.services.blob_store import blob_store
from app.utils.timezone import Timezone
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsQuietHoursUpdated
from shared.py.wide_events import log


async def get_user_by_id(user_id: str) -> UserDocument | None:
    """Get user by ID from database."""
    log.set(component="user_service", user_id=user_id)
    try:
        user = await user_repository.get(user_id)
        return user
    except Exception as e:
        log.error("Error fetching user", user_id=user_id, error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=404, detail="User not found") from e


async def get_quiet_hours(user_id: str) -> QuietHours:
    """Return the user's quiet hours: their own, or 22:00 to 08:00 when they never set any."""
    user = await get_user_by_id(user_id)
    return (user.quiet_hours if user else None) or DEFAULT_QUIET_HOURS


async def set_quiet_hours(user_id: str, hours: QuietHours) -> QuietHours:
    """Store the user's quiet hours and report the change; 404 when there is no such user."""
    if await user_repository.set_quiet_hours(user_id, hours) is None:
        raise HTTPException(status_code=404, detail="User not found")
    capture(
        UserId(user_id),
        SettingsQuietHoursUpdated(
            enabled=hours.enabled, start_hour=hours.start_hour, end_hour=hours.end_hour
        ),
    )
    return hours


async def get_profile_timezone(user_id: str) -> Timezone:
    """Return the timezone on the user's profile; UTC when they have none or it is not one."""
    user = await get_user_by_id(user_id)
    return Timezone.parse(user.timezone if user else None)


async def quiet_hours_end(user_id: str) -> datetime | None:
    """Return when the user's quiet hours end when their own clock is inside them now, else None."""
    local_now = datetime.now((await get_profile_timezone(user_id)).tzinfo)
    hours = await get_quiet_hours(user_id)
    return hours.end_after(local_now) if hours.contains(local_now) else None


async def update_user_profile(
    user_id: str,
    name: str | None = None,
    picture: ProfilePictureUpload | None = None,
) -> UserUpdateResponse:
    log.set(
        component="user_service",
        user_id=user_id,
        operation="update_profile",
        has_picture=picture is not None,
    )
    try:
        user = await user_repository.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_fields: dict[str, str] = {}

        # Update name if provided
        if name is not None and name.strip():
            update_fields["name"] = name.strip()

        # Update picture if provided
        if picture and picture.data:
            try:
                user_email = user.email or ""
                public_id = f"user_{user_email.replace('@', '_at_').replace('.', '_dot_')}"
                update_fields["picture"] = await blob_store().put(
                    user_id,
                    public_id,
                    picture.data,
                    resource_type="image",
                    kind=BlobKind.AVATAR,
                    content_type=picture.content_type,
                )

            except Exception as e:
                log.error(
                    "Error uploading profile picture",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
                raise HTTPException(
                    status_code=500, detail="Failed to upload profile picture"
                ) from e

        # Only write (and bump updated_at) when something actually changed.
        updated_user = (
            await user_repository.update(user_id, UserUpdate(**update_fields))
            if update_fields
            else user
        )

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found after update")

        return UserUpdateResponse(
            user_id=updated_user.id,
            name=updated_user.name or "",
            # A legacy account can carry no email; the response schema wants a
            # string, so degrade to empty rather than 500-ing the whole update.
            email=updated_user.email or "",
            picture=updated_user.picture,
            updated_at=updated_user.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Error updating user profile",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise HTTPException(status_code=500, detail="Failed to update profile") from e
