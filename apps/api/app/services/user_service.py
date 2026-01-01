import time
from datetime import datetime, timezone
from typing import Optional

from app.config.loggers import app_logger as logger, get_current_event
from app.db.mongodb.collections import users_collection
from bson import ObjectId
from fastapi import HTTPException


async def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get user by ID from database."""
    start_time = time.time()
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        duration_ms = (time.time() - start_time) * 1000

        wide_event = get_current_event()
        if wide_event:
            wide_event.add_db_query(duration_ms)

        if user:
            user["_id"] = str(user["_id"])
            logger.debug(
                "user_fetched_by_id",
                user_id=user_id,
                duration_ms=duration_ms,
            )
        else:
            logger.warning(
                "user_not_found_by_id",
                user_id=user_id,
                duration_ms=duration_ms,
            )
        return user
    except Exception as e:
        logger.error(
            "user_fetch_failed",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=404, detail="User not found")


async def get_user_by_email(email: str) -> Optional[dict]:
    """Get user by email from database."""
    start_time = time.time()
    try:
        user = await users_collection.find_one({"email": email})
        duration_ms = (time.time() - start_time) * 1000

        wide_event = get_current_event()
        if wide_event:
            wide_event.add_db_query(duration_ms)

        if user:
            user["_id"] = str(user["_id"])
            logger.debug(
                "user_fetched_by_email",
                email=email,
                user_id=user["_id"],
                duration_ms=duration_ms,
            )
        else:
            logger.warning(
                "user_not_found_by_email",
                email=email,
                duration_ms=duration_ms,
            )
        return user
    except Exception as e:
        logger.error(
            "user_fetch_by_email_failed",
            email=email,
            error=str(e),
            error_type=type(e).__name__,
        )
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
    from app.utils.oauth_utils import upload_user_picture

    start_time = time.time()
    logger.info(
        "profile_update_started",
        user_id=user_id,
        has_name=name is not None,
        has_picture=picture_data is not None,
        has_data=data is not None,
    )

    wide_event = get_current_event()
    if wide_event:
        wide_event.set_operation(
            operation="update_profile",
            resource_type="user",
            resource_id=user_id,
        )

    try:
        db_start = time.time()
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if wide_event:
            wide_event.add_db_query((time.time() - db_start) * 1000)

        if not user:
            logger.warning(
                "profile_update_user_not_found",
                user_id=user_id,
            )
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
                external_start = time.time()
                # Generate public_id for Cloudinary
                user_email = user.get("email", "")
                public_id = (
                    f"user_{user_email.replace('@', '_at_').replace('.', '_dot_')}"
                )

                # Upload to Cloudinary
                picture_url = await upload_user_picture(picture_data, public_id)
                update_data["picture"] = picture_url

                external_duration_ms = (time.time() - external_start) * 1000
                if wide_event:
                    wide_event.add_external_call(external_duration_ms)

                logger.info(
                    "profile_picture_uploaded",
                    user_id=user_id,
                    upload_duration_ms=external_duration_ms,
                )

            except Exception as e:
                logger.error(
                    "profile_picture_upload_failed",
                    user_id=user_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise HTTPException(
                    status_code=500, detail="Failed to upload profile picture"
                )

        # Update database
        db_start = time.time()
        await users_collection.update_one(
            {"_id": ObjectId(user_id)}, {"$set": update_data}
        )
        if wide_event:
            wide_event.add_db_query((time.time() - db_start) * 1000)

        # Fetch and return updated user
        updated_user = await get_user_by_id(user_id)

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found after update")

        logger.info(
            "profile_updated",
            user_id=user_id,
            fields_updated=list(update_data.keys()),
            duration_ms=(time.time() - start_time) * 1000,
        )

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
        logger.error(
            "profile_update_failed",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=500, detail="Failed to update profile")
