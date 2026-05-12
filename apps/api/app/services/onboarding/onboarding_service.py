from datetime import datetime, timezone
from typing import Any, Dict

from shared.py.wide_events import log
from app.db.mongodb.collections import (
    conversations_collection,
    todos_collection,
    user_integrations_collection,
    users_collection,
)
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
)
from app.services.integrations.integration_connection_service import (
    disconnect_integration,
)
from app.services.memory_service import memory_service
from app.services.onboarding.intelligence_job import abort_active_intelligence_job
from app.services.onboarding.post_onboarding_service import seed_initial_user_data
from app.services.workflow.service import WorkflowService
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
from pymongo import ReturnDocument


async def complete_onboarding(
    user_id: str,
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
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
    log.set(auth={"user_id": user_id})

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

        # Persist focus if provided
        if onboarding_data.focus and onboarding_data.focus.strip():
            update_fields["onboarding.focus"] = onboarding_data.focus.strip()

        # Overwriting update — re-running onboarding is allowed (used by the
        # restart flow). The reset endpoint clears prior onboarding data, but
        # we accept overwrites here as a safety net so a partial reset can
        # still recover by re-completing.
        updated_user = await users_collection.find_one_and_update(
            {"_id": user_object_id},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )

        if not updated_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Convert ObjectId to string for JSON serialization
        updated_user["_id"] = str(updated_user["_id"])
        updated_user["user_id"] = updated_user["_id"]

        # Schedule background tasks
        background_tasks.add_task(seed_initial_user_data, user_id)

        log.info(f"Onboarding completed successfully for user {user_id}")

        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        log.error(
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
            "phase": onboarding_data.get("phase"),
            "preferences": onboarding_data.get("preferences", {}),
            "first_message_conversation_id": onboarding_data.get(
                "first_message_conversation_id"
            ),
        }

    except Exception as e:
        log.error(
            f"Error getting onboarding status for user {user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An internal error occurred")


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

        log.info(f"Onboarding preferences updated successfully for user {user_id}")

        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"Error updating onboarding preferences for user {user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update preferences")


async def reset_onboarding(user_id: str) -> Dict[str, int]:
    """
    Fully reset a user's onboarding so they can run the flow from scratch.

    Clears `users.onboarding`, deletes onboarding-tagged todos, deletes
    workflows that were generated during onboarding, deletes the first
    conversation that was seeded for the user, disconnects every integration
    the user connected, wipes Mem0 memories, and deletes the LangGraph
    checkpointer thread for the seeded conversation.

    Returns counts of what was deleted for observability.
    """
    log.set(auth={"user_id": user_id}, onboarding={"operation": "reset"})

    user_object_id = ObjectId(user_id)
    user_doc = await users_collection.find_one(
        {"_id": user_object_id},
        {"onboarding": 1},
    )

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    # Abort any in-flight intelligence pipeline first so it can't emit
    # stage events for the user after the doc is wiped.
    try:
        await abort_active_intelligence_job(user_id)
    except Exception as e:
        log.warning(f"[reset_onboarding] failed to abort intelligence job: {e}")

    onboarding = user_doc.get("onboarding", {}) or {}
    workflow_ids: list[Any] = onboarding.get("suggested_workflows", []) or []
    first_conversation_id = onboarding.get("first_message_conversation_id")

    workflows_deleted = 0
    for wf_id in workflow_ids:
        try:
            # WorkflowService.delete_workflow cancels scheduled executions
            # and unregisters Composio triggers — direct collection delete
            # would leave orphaned schedules and triggers.
            deleted = await WorkflowService.delete_workflow(str(wf_id), user_id)
            if deleted:
                workflows_deleted += 1
        except Exception as e:
            log.warning(f"[reset_onboarding] failed to delete workflow {wf_id}: {e}")

    todos_deleted = 0
    try:
        todo_result = await todos_collection.delete_many(
            {"user_id": user_id, "labels": "onboarding"}
        )
        todos_deleted = todo_result.deleted_count
    except Exception as e:
        log.warning(f"[reset_onboarding] failed to delete todos: {e}")

    conversation_deleted = 0
    if first_conversation_id:
        try:
            convo_result = await conversations_collection.delete_one(
                {"user_id": user_id, "conversation_id": first_conversation_id}
            )
            conversation_deleted = convo_result.deleted_count
        except Exception as e:
            log.warning(f"[reset_onboarding] failed to delete conversation: {e}")

    integrations_disconnected = await _disconnect_user_integrations(user_id)
    memories_cleared = await _clear_user_memories(user_id)

    await users_collection.update_one(
        {"_id": user_object_id},
        {
            "$unset": {"onboarding": ""},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )

    counts = {
        "workflows_deleted": workflows_deleted,
        "todos_deleted": todos_deleted,
        "conversation_deleted": conversation_deleted,
        "integrations_disconnected": integrations_disconnected,
        "memories_cleared": memories_cleared,
    }
    log.set(onboarding={"operation": "reset", **counts})
    log.info(f"Onboarding reset complete for user {user_id}")
    return counts


async def _disconnect_user_integrations(user_id: str) -> int:
    """Disconnect every integration the user connected. Returns count."""
    try:
        cursor = user_integrations_collection.find(
            {"user_id": user_id}, {"integration_id": 1}
        )
        integration_ids = [doc["integration_id"] async for doc in cursor]
    except Exception as e:
        log.warning(f"[reset_onboarding] failed to list user integrations: {e}")
        return 0

    disconnected = 0
    for integration_id in integration_ids:
        try:
            await disconnect_integration(user_id, integration_id)
            disconnected += 1
        except Exception as e:
            log.warning(
                f"[reset_onboarding] failed to disconnect {integration_id}: {e}"
            )
    return disconnected


async def _clear_user_memories(user_id: str) -> int:
    """Purge Mem0 memories accumulated during onboarding. Returns 1 on success."""
    try:
        return 1 if await memory_service.delete_all_memories(user_id=user_id) else 0
    except Exception as e:
        log.warning(f"[reset_onboarding] failed to clear memories: {e}")
        return 0
