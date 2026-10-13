from fastapi import HTTPException

from app.constants.files import BlobKind
from app.db.repositories.users import user_repository
from app.models.user_models import (
    ProfilePictureUpload,
    UserDocument,
    UserUpdate,
    UserUpdateResponse,
)
from app.services.blob_store import blob_store
from app.utils.timezone import Timezone
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


async def get_profile_timezone(user_id: str) -> Timezone:
    """Return the timezone on the user's profile; UTC when they have none or it is not one."""
    user = await get_user_by_id(user_id)
    return Timezone.parse(user.timezone if user else None)


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
