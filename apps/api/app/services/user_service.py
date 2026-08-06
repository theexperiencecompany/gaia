from fastapi import HTTPException

from app.db.repositories.users import user_repository
from app.models.user_models import UserUpdate, user_to_legacy_dict
from app.utils.oauth_utils import upload_user_picture
from shared.py.wide_events import log


async def get_user_by_id(user_id: str) -> dict | None:
    """Get user by ID from database."""
    log.set(service="user_service", user_id=user_id)
    try:
        user = await user_repository.get(user_id)
        return user_to_legacy_dict(user) if user else None
    except Exception as e:
        log.error(f"Error fetching user {user_id}: {e}")
        raise HTTPException(status_code=404, detail="User not found")


async def update_user_profile(
    user_id: str,
    name: str | None = None,
    picture_data: bytes | None = None,
) -> dict:
    """Update user profile information."""
    log.set(
        service="user_service",
        user_id=user_id,
        operation="update_profile",
        has_picture=picture_data is not None,
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
        if picture_data:
            try:
                # Generate public_id for Cloudinary
                user_email = user.email or ""
                public_id = f"user_{user_email.replace('@', '_at_').replace('.', '_dot_')}"

                # Upload to Cloudinary
                update_fields["picture"] = await upload_user_picture(picture_data, public_id)

            except Exception as e:
                log.error(f"Error uploading profile picture: {e}")
                raise HTTPException(status_code=500, detail="Failed to upload profile picture")

        # Only write (and bump updated_at) when something actually changed.
        updated_user = (
            await user_repository.update(user_id, UserUpdate(**update_fields))
            if update_fields
            else user
        )

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found after update")

        return {
            "user_id": updated_user.id,
            "name": updated_user.name,
            "email": updated_user.email,
            "picture": updated_user.picture,
            "updated_at": updated_user.updated_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")
