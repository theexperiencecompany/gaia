from typing import Any

from fastapi import HTTPException

from app.constants.log_tags import LogTag
from app.constants.onboarding import (
    FIRST_CONVERSATION_ID_FIELD,
    GETTING_STARTED_CONVERSATION_ID_FIELD,
    HOLO_CONVERSATION_ID_FIELD,
)
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.memory.engine import memory_engine
from app.models.onboarding_models import OnboardingResetCounts
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    OnboardingStatusResponse,
    UserDocument,
)
from app.services.analytics_service import AnalyticsEvents, capture_event, identify_user
from app.services.integrations.integration_connection_service import (
    disconnect_integration,
)
from app.services.onboarding.first_conversation import (
    compose_first_conversation,
    with_starting_jobs,
)
from app.services.onboarding.first_question import (
    prewarm_first_question,
    resolve_first_question,
)
from app.services.onboarding.intelligence_job import abort_active_intelligence_job
from app.services.platform_link_service import linked_platforms_of
from app.services.workflow.service import WorkflowService
from app.utils.background_tasks import spawn_background_task
from app.utils.seeding_utils import seed_first_conversation
from shared.py.wide_events import log


def _serialize_user(user: UserDocument) -> dict[str, Any]:
    """The JSON-serializable user dict the onboarding endpoints return.

    Stays a ``dict[str, Any]`` deliberately: ``UserDocument`` is ``extra="allow"``
    precisely so these endpoints can spread the whole stored document into their
    response, and the frontend's ``UserInfo`` reads it that way. Narrowing this to
    a declared model would silently strip whatever undeclared fields production
    rows carry — a change to data returned to an external consumer, which is a
    product decision, not a typing fix (Type Safety item 14).
    """
    data = user.model_dump(mode="json", exclude={"id"})
    data["_id"] = user.id
    data["user_id"] = user.id
    return data


async def complete_onboarding(
    user_id: str,
    onboarding_data: OnboardingRequest,
) -> dict[str, Any]:
    """Complete a user's onboarding submission. Idempotent under concurrent
    retries via an atomic `onboarding.completed` gate in the repository.

    Submitting the answers IS completion: nothing is generated here, so the
    phase lands on COMPLETED and the user is routed straight into chat. The
    intelligence pipeline runs when Gmail is connected, whenever that is."""
    log.set(auth={"user_id": user_id})

    try:
        preferences = OnboardingPreferences(
            profession=onboarding_data.profession,
            needs=onboarding_data.needs,
            other_need=onboarding_data.other_need,
            response_style="casual",  # Default response style
            custom_instructions=None,
        )

        # Atomic gate inside the repository: only the request that creates the
        # `onboarding` subdoc wins; concurrent POSTs and replays get None.
        updated_user = await user_repository.complete_onboarding(
            user_id,
            timezone=onboarding_data.timezone.strip() if onboarding_data.timezone else None,
            phase=OnboardingPhase.COMPLETED,
            bio_status=BioStatus.PENDING,
            preferences=preferences,
        )

        if updated_user is None:
            existing = await user_repository.get(user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="User not found")
            log.info(
                f"{LogTag.ONBOARDING} complete_onboarding replay — onboarding already submitted",
                user_id=user_id,
                phase=(existing.onboarding or {}).get("phase"),
            )
            return _serialize_user(existing)

        # `dedupe_key` guards against a retried POST re-counting the milestone.
        # The typed need is free text, so only its presence travels; the
        # profession is a picked value (or a short typed job) and goes onto the
        # person profile so cohorts can cut by it.
        capture_event(
            user_id,
            AnalyticsEvents.ONBOARDING_COMPLETED,
            {
                "needs": sorted(need.value for need in onboarding_data.needs),
                "has_other_need": bool(onboarding_data.other_need),
            },
            dedupe_key=user_id,
        )
        identify_user(
            user_id,
            {"profession": onboarding_data.profession, "onboarding_completed": True},
        )

        seeded_user = await _seed_first_conversation(updated_user, preferences)

        log.info(f"{LogTag.ONBOARDING} Onboarding completed successfully for user", user_id=user_id)
        return _serialize_user(seeded_user or updated_user)

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error completing onboarding for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to complete onboarding") from e


async def _seed_first_conversation(
    user: UserDocument, preferences: OnboardingPreferences
) -> UserDocument | None:
    """Seed GAIA's opening conversation and stamp its id on the onboarding subdoc.

    Best-effort by design: the welcome is a nicety, and a user whose completion
    write already landed must not be bounced back into the wizard because a
    conversation could not be created. Returns the re-read user document when the
    id was stored, so the completion response carries it.
    """
    user_id = user.id
    try:
        # Linking happens on the platform-pick step, before the answers are
        # submitted, so the link is already on the document we just wrote. A user
        # who skipped that step simply gets no platform line.
        connected_platform = next(iter(linked_platforms_of(user)), None)
        composed = compose_first_conversation()
        # Almost always a Redis read: the answers PATCH that preceded this
        # fired the model call in the background, so the user pays for it while
        # they are still clicking. A miss costs at most two seconds, and a
        # failed call means no chips rather than invented ones.
        jobs = await resolve_first_question(user_id, preferences, connected_platform)
        if jobs is not None:
            composed = with_starting_jobs(composed, jobs.chips)
        conversation_id = await seed_first_conversation(user_id, composed)
        if conversation_id is None:
            return None
        return await user_repository.set_first_conversation_id(user_id, conversation_id)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} complete_onboarding failed to seed the first conversation",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def get_user_onboarding_status(user_id: str) -> OnboardingStatusResponse:
    """Get user's onboarding status and preferences."""
    try:
        user = await user_repository.get(user_id)

        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding_data = user.onboarding or {}

        return OnboardingStatusResponse(
            completed=onboarding_data.get("completed", False),
            completed_at=onboarding_data.get("completed_at"),
            phase=onboarding_data.get("phase"),
            preferences=OnboardingPreferences.model_validate(
                onboarding_data.get("preferences") or {}
            ),
            first_message_conversation_id=onboarding_data.get(FIRST_CONVERSATION_ID_FIELD),
            getting_started_conversation_id=onboarding_data.get(
                GETTING_STARTED_CONVERSATION_ID_FIELD
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error getting onboarding status for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


async def update_onboarding_preferences(
    user_id: str, preferences: OnboardingPreferences
) -> dict[str, Any]:
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
        # PATCH semantics (applied by the repository, which writes only the fields
        # the caller actually set, each at its own dotted path): different settings
        # surfaces (Preferences vs. Custom Instructions) own disjoint fields, so a
        # partial save from one cannot clobber a field owned by the other. Values
        # are already normalized by the OnboardingPreferences validators (empty
        # string -> None, length capped), so they are persisted as-is.
        updated_user = await user_repository.update_onboarding_preferences(user_id, preferences)
        if updated_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Detached on purpose: the wizard's next screens are the latency budget
        # for the one model call the seeded conversation needs, and the PATCH
        # that saved the answers is where that budget starts. Failures stay
        # inside the task; a settings save must never fail over a nicety.
        try:
            spawn_background_task(
                prewarm_first_question(
                    user_id,
                    preferences,
                    next(iter(linked_platforms_of(updated_user)), None),
                ),
                name=f"prewarm_first_question:{user_id}",
            )
        except Exception as e:
            log.warning(
                f"{LogTag.ONBOARDING} could not start the first question prewarm",
                user_id=user_id,
                error=str(e)[:200],
                error_type=type(e).__name__,
            )

        log.info(
            f"{LogTag.ONBOARDING} Onboarding preferences updated successfully for user",
            user_id=user_id,
        )

        return _serialize_user(updated_user)

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error updating onboarding preferences for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update preferences") from e


async def reset_onboarding(user_id: str) -> OnboardingResetCounts:
    """Fully reset a user's onboarding so they can run the flow from scratch.
    Returns counts of what was deleted."""
    log.set(auth={"user_id": user_id}, onboarding={"operation": "reset"})

    user = await user_repository.get(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Abort any in-flight pipeline first so it can't emit stage events after the
    # doc is wiped.
    try:
        await abort_active_intelligence_job(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to abort personalization job",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

    onboarding = user.onboarding or {}
    # Legacy state: users who ran the pre-relocation onboarding still carry the
    # workflows it generated and the conversation it seeded. Nothing writes
    # either any more, but a reset must still clear them.
    workflow_ids: list[str] = onboarding.get("suggested_workflows") or []
    seeded_conversation_ids: list[str] = [
        cid
        for cid in (
            onboarding.get(FIRST_CONVERSATION_ID_FIELD),
            onboarding.get(GETTING_STARTED_CONVERSATION_ID_FIELD),
            onboarding.get(HOLO_CONVERSATION_ID_FIELD),
        )
        if cid
    ]

    workflows_deleted = 0
    for wf_id in workflow_ids:
        try:
            # Use the service (not a direct delete) so scheduled executions
            # and Composio triggers are cleaned up too.
            deleted = await WorkflowService.delete_workflow(str(wf_id), user_id)
            if deleted:
                workflows_deleted += 1
        except Exception as e:
            log.warning(
                f"{LogTag.ONBOARDING} reset_onboarding failed to delete workflow",
                wf_id=wf_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    todos_deleted = 0
    try:
        todos_deleted = await todo_repository.delete_onboarding_todos(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to delete todos",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

    conversation_deleted = 0
    for conversation_id in seeded_conversation_ids:
        try:
            deleted = await conversation_repository.delete(conversation_id, user_id=user_id)
            conversation_deleted += int(deleted)
        except Exception as e:
            log.warning(
                f"{LogTag.ONBOARDING} reset_onboarding failed to delete conversation",
                conversation_id=conversation_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    demo_conversations_deleted = 0
    try:
        demo_conversations_deleted = await conversation_repository.delete_onboarding_demos(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to delete demo conversations",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

    integrations_disconnected = await _disconnect_user_integrations(user_id)
    memories_cleared = await _clear_user_memories(user_id)

    await user_repository.reset_onboarding(user_id)

    counts = OnboardingResetCounts(
        workflows_deleted=workflows_deleted,
        todos_deleted=todos_deleted,
        conversation_deleted=conversation_deleted,
        demo_conversations_deleted=demo_conversations_deleted,
        integrations_disconnected=integrations_disconnected,
        memories_cleared=memories_cleared,
    )
    log.set(onboarding={"operation": "reset", **counts.model_dump()})
    log.info(f"{LogTag.ONBOARDING} Onboarding reset complete for user", user_id=user_id)
    return counts


async def _disconnect_user_integrations(user_id: str) -> int:
    try:
        uis = await user_integration_repository.list_for_user(user_id)
        integration_ids = [ui.integration_id for ui in uis]
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to list user integrations",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return 0

    disconnected = 0
    for integration_id in integration_ids:
        try:
            await disconnect_integration(user_id, integration_id)
            disconnected += 1
        except Exception as e:
            log.warning(
                f"{LogTag.ONBOARDING} reset_onboarding failed to disconnect",
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
    return disconnected


async def _clear_user_memories(user_id: str) -> int:
    try:
        return await memory_engine.delete_all(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to clear memories",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return 0
