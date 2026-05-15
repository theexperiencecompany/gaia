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
    """Mongo ObjectId is not JSON-serializable. Materialize both `_id` and
    `user_id` as strings so callers can return the doc straight to FastAPI."""
    user_doc["_id"] = str(user_doc["_id"])
    user_doc["user_id"] = user_doc["_id"]
    return user_doc


async def complete_onboarding(
    user_id: str,
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Complete a user's onboarding submission.

    Idempotent under concurrent retries. The write is gated by an atomic
    `onboarding: {$exists: false}` filter — only the request that creates
    the subdoc enqueues the intelligence pipeline + schedules seeding.
    Replays (OAuth bounce remount, back-nav from /c/{id}, manual refresh,
    React StrictMode double-fire) lose the race, fetch the existing doc,
    and return it as a 2xx with no side effects. The only legitimate path
    to a fresh run is `POST /onboarding/reset`, which `$unset`s the entire
    `onboarding` subdoc and reopens the gate.

    If enqueue fails after the gate is claimed, the subdoc is rolled back
    via `$unset` so the user can retry rather than being stuck with a
    `completed=true` flag and no worker job. Returns 503 in that case.

    Returns the updated (or existing, on replay) user document with stringy
    `_id` / `user_id`.
    """
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

        # Atomic gate: matches only when no `onboarding` subdoc exists yet.
        # Two states satisfy this:
        #   - Fresh user (oauth_service.store_user_info never writes onboarding.*)
        #   - Reset user (/onboarding/reset does $unset on the whole subdoc)
        # Anything else — pipeline running, reveals in progress, fully done —
        # has the subdoc and falls through to the replay branch. This is
        # narrower than gating on `onboarding.completed` and keeps the gate
        # decoupled from the meaning of `completed` (which other consumers
        # like oauth_service and cleanup_tasks rely on).
        #
        # MongoDB guarantees single-document update atomicity, so under
        # concurrent POSTs exactly one caller's filter matches and creates
        # the subdoc; the rest get None.
        updated_user = await users_collection.find_one_and_update(
            {"_id": user_object_id, "onboarding": {"$exists": False}},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )

        if updated_user is None:
            # Either the user doesn't exist, or the onboarding subdoc is
            # already present (someone else won the race, or this is a
            # remount-induced replay). Distinguish with one read.
            existing = await users_collection.find_one({"_id": user_object_id})
            if not existing:
                raise HTTPException(status_code=404, detail="User not found")
            log.info(
                "[complete_onboarding] replay — onboarding already submitted",
                user_id=user_id,
                phase=(existing.get("onboarding") or {}).get("phase"),
            )
            return _serialize_user(existing)

        # We won the gate. Try to enqueue the pipeline before scheduling any
        # other side effects. If enqueue fails (Redis down, etc.) we roll
        # back the subdoc so the user can retry — without rollback they'd
        # be stuck forever with `completed=true` but no worker job to drive
        # the reveals.
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

        # Enqueue succeeded — schedule the seeding background task. Done
        # after enqueue so a seeding failure can't poison the gate; seeding
        # failures are logged but non-fatal.
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
