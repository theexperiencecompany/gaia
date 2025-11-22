from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import users_collection
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
)
from app.utils.user_preferences_utils import format_user_preferences_for_agent


async def complete_onboarding(
    user_id: str,
    onboarding_data: OnboardingRequest,
    user_timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete user onboarding by storing preferences and updating user profile.
    Uses atomic operations to prevent race conditions.

    Args:
        user_id: The user's MongoDB ID
        onboarding_data: The onboarding data from the frontend

    Returns:
        Updated user data with onboarding status

    Raises:
        HTTPException: If user not found, already onboarded, or update fails
    """
    try:
        # Convert string ID to ObjectId
        user_object_id = ObjectId(user_id)

        # Prepare onboarding preferences with default values for settings page
        preferences = OnboardingPreferences(
            profession=onboarding_data.profession,
            response_style="casual",  # Default response style
            custom_instructions=None,
            # Timezone removed from preferences - now only stored at root level
        )

        # Prepare update fields
        # Use dot notation to update specific fields without overwriting the entire onboarding object
        # This preserves personalization data (house, bio, etc.) if it was already generated
        update_fields = {
            "name": onboarding_data.name.strip(),
            "onboarding.completed": True,
            "onboarding.completed_at": datetime.now(timezone.utc),
            "onboarding.phase": OnboardingPhase.PERSONALIZATION_PENDING,
            "onboarding.bio_status": BioStatus.PENDING,
            "onboarding.preferences": preferences.model_dump(),
            "updated_at": datetime.now(timezone.utc),
        }

        # Always set timezone at root level from onboarding data
        if onboarding_data.timezone:
            update_fields["timezone"] = onboarding_data.timezone.strip()

        # Atomic update with conditions to prevent race conditions and duplicate onboarding
        updated_user = await users_collection.find_one_and_update(
            {
                "_id": user_object_id,
                # Ensure user exists and hasn't completed onboarding yet
                "$or": [
                    {"onboarding.completed": {"$ne": True}},
                    {"onboarding": {"$exists": False}},
                ],
            },
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )

        if not updated_user:
            # Check if user exists but onboarding is already complete
            existing_user = await users_collection.find_one({"_id": user_object_id})
            if not existing_user:
                raise HTTPException(status_code=404, detail="User not found")
            elif existing_user.get("onboarding", {}).get("completed", False):
                raise HTTPException(
                    status_code=409, detail="Onboarding already completed"
                )
            else:
                raise HTTPException(status_code=500, detail="Failed to update user")

        # Convert ObjectId to string for JSON serialization
        updated_user["_id"] = str(updated_user["_id"])
        updated_user["user_id"] = updated_user["_id"]

        logger.info(f"Onboarding completed successfully for user {user_id}")

        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error completing onboarding for user {user_id}: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to complete onboarding")


async def get_user_onboarding_status(user_id: str) -> Dict[str, Any]:
    """
    Get user's onboarding status and preferences.

    Args:
        user_id: The user's MongoDB ID

    Returns:
        Dictionary with onboarding status and preferences
    """
    try:
        user_object_id = ObjectId(user_id)
        user = await users_collection.find_one({"_id": user_object_id})

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding_data = user.get("onboarding", {})

        return {
            "completed": onboarding_data.get("completed", False),
            "completed_at": onboarding_data.get("completed_at"),
            "preferences": onboarding_data.get("preferences", {}),
        }

    except Exception as e:
        logger.error(
            f"Error getting onboarding status for user {user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to get onboarding status: {str(e)}"
        )


async def update_onboarding_preferences(
    user_id: str, preferences: OnboardingPreferences
) -> Dict[str, Any]:
    """
    Update user's onboarding preferences (for settings page).
    Uses atomic operations for data consistency.

    Args:
        user_id: The user's MongoDB ID
        preferences: Updated preferences

    Returns:
        Updated user data

    Raises:
        HTTPException: If user not found or update fails
    """
    try:
        user_object_id = ObjectId(user_id)

        # Sanitize and prepare preferences
        # First, validate using the Pydantic model which will handle empty string normalization
        validated_preferences = OnboardingPreferences(**preferences.model_dump())
        sanitized_preferences = validated_preferences.model_dump(exclude_none=True)

        if "custom_instructions" in sanitized_preferences:
            # Basic sanitization - remove potentially harmful content
            sanitized_preferences["custom_instructions"] = sanitized_preferences[
                "custom_instructions"
            ].strip()[:500]

        # Atomic update with user existence check
        updated_user = await users_collection.find_one_and_update(
            {"_id": user_object_id},
            {
                "$set": {
                    "onboarding.preferences": sanitized_preferences,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Convert ObjectId to string for JSON serialization
        updated_user["_id"] = str(updated_user["_id"])
        updated_user["user_id"] = updated_user["_id"]

        logger.info(f"Onboarding preferences updated successfully for user {user_id}")

        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error updating onboarding preferences for user {user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update preferences")


async def get_user_preferences_for_agent(user_id: str) -> Optional[str]:
    """
    Get formatted user preferences for agent system prompt.

    Args:
        user_id: The user's MongoDB ID

    Returns:
        Formatted string of user preferences or None if not available
    """
    try:
        user_object_id = ObjectId(user_id)
        user = await users_collection.find_one({"_id": user_object_id})

        if not user or not user.get("onboarding", {}).get("completed", False):
            return None

        prefs = user.get("onboarding", {}).get("preferences", {})

        if not prefs:
            return None

        # Use the modular utility function to format preferences
        return format_user_preferences_for_agent(prefs)

    except Exception as e:
        logger.error(
            f"Error getting user preferences for agent: {str(e)}", exc_info=True
        )
        return None
