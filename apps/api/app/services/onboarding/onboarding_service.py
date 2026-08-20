import asyncio
from typing import Any

from fastapi import BackgroundTasks, HTTPException

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.memory.engine import memory_engine
from app.models.onboarding_models import (
    ClarifyAnswerRecord,
    OnboardingResetCounts,
)
from app.models.user_models import (
    BioStatus,
    IntegrationSlug,
    OnboardingIntegrationsStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    OnboardingStatusResponse,
    UserDocument,
)
from app.services.integrations.integration_connection_service import (
    disconnect_integration,
)
from app.services.onboarding.intelligence_job import (
    abort_active_intelligence_job,
    abort_active_workflows_job,
    enqueue_intelligence_job,
    enqueue_workflows_job,
    is_workflows_job_live,
)
from app.services.onboarding.post_onboarding_service import seed_initial_user_data
from app.services.workflow.service import WorkflowService
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
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Complete a user's onboarding submission. Idempotent under concurrent
    retries via an atomic `onboarding: {$exists: false}` gate."""
    log.set(auth={"user_id": user_id})

    try:
        preferences = OnboardingPreferences(
            profession=onboarding_data.profession,
            response_style="casual",  # Default response style
            custom_instructions=None,
        )

        clarify_answers: list[ClarifyAnswerRecord] | None = None
        if onboarding_data.clarify_answers:
            kept: list[ClarifyAnswerRecord] = [
                {
                    "id": a.id,
                    "kind": a.kind,
                    "question": a.question,
                    "value": (a.value or "").strip() or None,
                }
                for a in onboarding_data.clarify_answers
                if a.value and a.value.strip()
            ]
            clarify_answers = kept or None

        focus = None
        if onboarding_data.focus and onboarding_data.focus.strip():
            focus = onboarding_data.focus.strip()

        # Atomic gate inside the repository: only the request that creates the
        # `onboarding` subdoc wins; concurrent POSTs and replays get None.
        # selected_integrations is already lowercased/stripped/deduped by the
        # IntegrationSlug type on OnboardingRequest — store as-is.
        updated_user = await user_repository.complete_onboarding(
            user_id,
            name=onboarding_data.name.strip(),
            timezone=onboarding_data.timezone.strip() if onboarding_data.timezone else None,
            phase=OnboardingPhase.PERSONALIZATION_PENDING,
            bio_status=BioStatus.PENDING,
            pipeline_mode="split" if onboarding_data.defer_workflows else "full",
            preferences=preferences,
            focus=focus,
            clarify_answers=clarify_answers,
            selected_integrations=(
                list(onboarding_data.selected_integrations)
                if onboarding_data.selected_integrations
                else None
            ),
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

        # Enqueue the pipeline before any other side effects; roll back the
        # subdoc on failure so the user isn't stuck with no worker job.
        try:
            await enqueue_intelligence_job(user_id)
        except Exception as e:
            log.error(
                f"{LogTag.ONBOARDING} Enqueue failed, rolling back onboarding state for user",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            try:
                await user_repository.clear_onboarding(user_id)
            except Exception as rollback_error:
                log.error(
                    f"{LogTag.ONBOARDING} Rollback also failed for user",
                    user_id=user_id,
                    error=str(rollback_error),
                    error_type=type(rollback_error).__name__,
                    exc_info=True,
                )
            raise HTTPException(
                status_code=503,
                detail="Could not start onboarding. Please retry.",
            ) from e

        background_tasks.add_task(seed_initial_user_data, user_id)

        log.info(f"{LogTag.ONBOARDING} Onboarding completed successfully for user", user_id=user_id)
        return _serialize_user(updated_user)

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


async def submit_onboarding_integrations(
    user_id: str,
    selected_integrations: list[IntegrationSlug],
) -> OnboardingIntegrationsStatus:
    """Persist the user's selected integrations and enqueue the workflows-phase
    job. Only valid for split-mode onboarding; idempotent under retries."""
    log.set(auth={"user_id": user_id})

    user = await user_repository.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    onboarding = user.onboarding or {}
    if not onboarding:
        raise HTTPException(status_code=409, detail="Onboarding has not been submitted yet")
    if onboarding.get("pipeline_mode") != "split":
        raise HTTPException(
            status_code=409, detail="Onboarding is not awaiting integration selection"
        )

    if onboarding.get("first_message_conversation_id"):
        log.info(f"{LogTag.ONBOARDING} integrations replay — onboarding already complete")
        return OnboardingIntegrationsStatus.ALREADY_COMPLETE
    if onboarding.get("workflows_job_id") and await is_workflows_job_live(user_id):
        log.info(f"{LogTag.ONBOARDING} integrations replay — workflows job already running")
        return OnboardingIntegrationsStatus.ALREADY_RUNNING

    await user_repository.set_selected_integrations(user_id, list(selected_integrations))

    job_id = await enqueue_workflows_job(user_id)
    if job_id is None:
        raise HTTPException(
            status_code=503, detail="Could not start workflow creation. Please retry."
        )

    log.info(
        f"{LogTag.ONBOARDING} integrations submitted, workflows phase queued",
        user_id=user_id,
        selected_count=len(selected_integrations),
        job_id=job_id,
    )
    return OnboardingIntegrationsStatus.QUEUED


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
            first_message_conversation_id=onboarding_data.get("first_message_conversation_id"),
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

    # Abort any in-flight pipeline first so it can't emit stage events
    # after the doc is wiped. Run both aborts independently — a failure in one
    # must not leave the other job live and still writing onboarding state.
    intelligence_result, workflows_result = await asyncio.gather(
        abort_active_intelligence_job(user_id),
        abort_active_workflows_job(user_id),
        return_exceptions=True,
    )
    if isinstance(intelligence_result, Exception):
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to abort intelligence job",
            intelligence_result=intelligence_result,
            user_id=user_id,
        )
    if isinstance(workflows_result, Exception):
        log.warning(
            f"{LogTag.ONBOARDING} reset_onboarding failed to abort workflows job",
            workflows_result=workflows_result,
            user_id=user_id,
        )

    onboarding = user.onboarding or {}
    workflow_ids: list[str] = onboarding.get("suggested_workflows", []) or []
    first_conversation_id: str | None = onboarding.get("first_message_conversation_id")

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
    if first_conversation_id:
        try:
            deleted = await conversation_repository.delete(first_conversation_id, user_id=user_id)
            conversation_deleted = int(deleted)
        except Exception as e:
            log.warning(
                f"{LogTag.ONBOARDING} reset_onboarding failed to delete conversation",
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
