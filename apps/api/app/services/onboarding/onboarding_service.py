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
from app.services.onboarding.intelligence_job import (
    abort_active_intelligence_job,
    enqueue_intelligence_job,
)
from app.services.onboarding.post_onboarding_service import seed_initial_user_data
from app.services.workflow.service import WorkflowService
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
from pymongo import ReturnDocument


def _serialize_user(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Stringify `_id` / `user_id` so the doc is JSON-serializable."""
    user_doc["_id"] = str(user_doc["_id"])
    user_doc["user_id"] = user_doc["_id"]
    return user_doc


async def complete_onboarding(
    user_id: str,
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Complete a user's onboarding submission. Idempotent under concurrent
    retries via an atomic `onboarding: {$exists: false}` gate."""
    log.set(auth={"user_id": user_id})

    try:
        user_object_id = ObjectId(user_id)

        preferences = OnboardingPreferences(
            profession=onboarding_data.profession,
            response_style="casual",  # Default response style
            custom_instructions=None,
        )

        update_fields: Dict[str, Any] = {
            "name": onboarding_data.name.strip(),
            "onboarding.completed": True,
            "onboarding.completed_at": datetime.now(timezone.utc),
            "onboarding.phase": OnboardingPhase.PERSONALIZATION_PENDING,
            "onboarding.bio_status": BioStatus.PENDING,
            "onboarding.preferences": preferences.model_dump(),
            "updated_at": datetime.now(timezone.utc),
        }

        if onboarding_data.timezone:
            update_fields["timezone"] = onboarding_data.timezone.strip()

        if onboarding_data.focus and onboarding_data.focus.strip():
            update_fields["onboarding.focus"] = onboarding_data.focus.strip()

        if onboarding_data.clarify_answers:
            kept = [
                {
                    "id": a.id,
                    "kind": a.kind,
                    "question": a.question,
                    "value": (a.value or "").strip() or None,
                }
                for a in onboarding_data.clarify_answers
                if a.value and a.value.strip()
            ]
            if kept:
                update_fields["onboarding.clarify_answers"] = kept

        # Atomic gate: only the request that creates the `onboarding` subdoc
        # wins; concurrent POSTs and replays get None and fall through.
        updated_user = await users_collection.find_one_and_update(
            {"_id": user_object_id, "onboarding": {"$exists": False}},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )

        if updated_user is None:
            existing = await users_collection.find_one({"_id": user_object_id})
            if not existing:
                raise HTTPException(status_code=404, detail="User not found")
            log.info(
                "[complete_onboarding] replay — onboarding already submitted",
                user_id=user_id,
                phase=(existing.get("onboarding") or {}).get("phase"),
            )
            return _serialize_user(existing)

        # Enqueue the pipeline before any other side effects; roll back the
        # subdoc on failure so the user isn't stuck with no worker job.
        try:
            await enqueue_intelligence_job(user_id)
        except Exception as e:
            log.error(
                f"Enqueue failed, rolling back onboarding state for user {user_id}: {e}",
                exc_info=True,
            )
            try:
                await users_collection.update_one(
                    {"_id": user_object_id},
                    {"$unset": {"onboarding": ""}},
                )
            except Exception as rollback_error:
                log.error(
                    f"Rollback also failed for user {user_id}: {rollback_error}",
                    exc_info=True,
                )
            raise HTTPException(
                status_code=503,
                detail="Could not start onboarding. Please retry.",
            )

        background_tasks.add_task(seed_initial_user_data, user_id)

        log.info(f"Onboarding completed successfully for user {user_id}")
        return _serialize_user(updated_user)

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

    except HTTPException:
        raise
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
    """Fully reset a user's onboarding so they can run the flow from scratch.
    Returns counts of what was deleted."""
    log.set(auth={"user_id": user_id}, onboarding={"operation": "reset"})

    user_object_id = ObjectId(user_id)
    user_doc = await users_collection.find_one(
        {"_id": user_object_id},
        {"onboarding": 1},
    )

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    # Abort any in-flight pipeline first so it can't emit stage events
    # after the doc is wiped.
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
            # Use the service (not a direct delete) so scheduled executions
            # and Composio triggers are cleaned up too.
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

    demo_conversations_deleted = 0
    try:
        demo_result = await conversations_collection.delete_many(
            {"user_id": user_id, "is_onboarding_demo": True}
        )
        demo_conversations_deleted = demo_result.deleted_count
    except Exception as e:
        log.warning(f"[reset_onboarding] failed to delete demo conversations: {e}")

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
        "demo_conversations_deleted": demo_conversations_deleted,
        "integrations_disconnected": integrations_disconnected,
        "memories_cleared": memories_cleared,
    }
    log.set(onboarding={"operation": "reset", **counts})
    log.info(f"Onboarding reset complete for user {user_id}")
    return counts


async def _disconnect_user_integrations(user_id: str) -> int:
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
    try:
        return 1 if await memory_service.delete_all_memories(user_id=user_id) else 0
    except Exception as e:
        log.warning(f"[reset_onboarding] failed to clear memories: {e}")
        return 0
