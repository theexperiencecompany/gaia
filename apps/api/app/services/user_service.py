from datetime import datetime, timezone
from typing import Optional

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import users_collection
from app.utils.oauth_utils import upload_user_picture
from bson import ObjectId
from fastapi import HTTPException


async def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get user by ID from database."""
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            user["_id"] = str(user["_id"])
        return user
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        raise HTTPException(status_code=404, detail="User not found")


async def get_user_by_email(email: str) -> Optional[dict]:
    """Get user by email from database."""
    try:
        user = await users_collection.find_one({"email": email})
        if user:
            user["_id"] = str(user["_id"])
        return user
    except Exception as e:
        logger.error(f"Error fetching user by email {email}: {e}")
        raise HTTPException(status_code=404, detail="User not found")


async def update_user_profile(
    user_id: str,
    name: Optional[str] = None,
    picture_data: Optional[bytes] = None,
    data: Optional[dict] = None,
) -> dict:
    """
    Update user profile information.

    Args:
        user_id: User ID
        name: New name (optional)
        picture_data: New profile picture data (optional)

    Returns:
        Updated user data
    """
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_data: dict = (
            {"updated_at": datetime.now(timezone.utc), **data}
            if data
            else {"updated_at": datetime.now(timezone.utc)}
        )

        # Update name if provided
        if name is not None and name.strip():
            update_data["name"] = name.strip()

        # Update picture if provided
        if picture_data:
            try:
                # Generate public_id for Cloudinary
                user_email = user.get("email", "")
                public_id = (
                    f"user_{user_email.replace('@', '_at_').replace('.', '_dot_')}"
                )

                # Upload to Cloudinary
                picture_url = await upload_user_picture(picture_data, public_id)
                update_data["picture"] = picture_url

            except Exception as e:
                logger.error(f"Error uploading profile picture: {e}")
                raise HTTPException(
                    status_code=500, detail="Failed to upload profile picture"
                )

        # Update database
        await users_collection.update_one(
            {"_id": ObjectId(user_id)}, {"$set": update_data}
        )

        # Fetch and return updated user
        updated_user = await get_user_by_id(user_id)

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found after update")

        return {
            "user_id": updated_user["_id"],
            "name": updated_user.get("name"),
            "email": updated_user.get("email"),
            "picture": updated_user.get("picture"),
            "updated_at": updated_user.get("updated_at"),
            "selected_model": updated_user.get("selected_model"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")
