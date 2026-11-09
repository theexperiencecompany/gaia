from datetime import UTC, datetime

from fastapi import HTTPException

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.memory.engine import memory_engine
from app.models.onboarding_models import OnboardingResetCounts
from app.models.user_models import (
    BioStatus,
    OnboardingAnswers,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    OnboardingStatusResponse,
    OnboardingSubdocument,
    OnboardingUser,
    UserDocument,
)
from app.services.analytics_service import capture, identify_user
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
from app.utils.auth_utils import with_local_onboarding_completed
from app.utils.background_tasks import spawn_background_task
from app.utils.seeding_utils import seed_first_conversation
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.onboarding import (
    OnboardingCompleted,
    OnboardingPhaseCompleted,
    OnboardingStarted,
    OnboardingStep,
)
from shared.py.wide_events import log


def _onboarding_status(user: UserDocument) -> OnboardingStatusResponse:
    """Return the client-facing onboarding state of user, with self-host's completion synthesized."""
    onboarding_data = with_local_onboarding_completed(user.onboarding or OnboardingSubdocument())
    return OnboardingStatusResponse(
        completed=onboarding_data.completed,
        completed_at=onboarding_data.completed_at,
        phase=onboarding_data.phase,
        preferences=onboarding_data.preferences or OnboardingPreferences.model_validate({}),
        first_message_conversation_id=onboarding_data.first_message_conversation_id,
        getting_started_conversation_id=onboarding_data.getting_started_conversation_id,
    )


def _onboarding_user(user: UserDocument) -> OnboardingUser:
    return OnboardingUser(user_id=user.id, onboarding=_onboarding_status(user))


async def complete_onboarding(
    user_id: str,
    onboarding_data: OnboardingRequest,
) -> OnboardingUser:
    """Complete a user's onboarding submission.

    Idempotent under concurrent retries via an atomic onboarding.completed gate.
    Submitting the answers IS completion: nothing is generated here, so the
    phase lands on COMPLETED and the user goes straight into chat. The
    intelligence pipeline runs whenever Gmail is connected.
    """
    log.set(auth={"user_id": user_id})

    try:
        preferences = OnboardingPreferences(
            profession=onboarding_data.profession,
            needs=onboarding_data.needs,
            other_need=onboarding_data.other_need,
            response_style="casual",  # Default response style
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
                phase=existing.onboarding.phase if existing.onboarding else None,
            )
            return _onboarding_user(existing)

        # The wizard submits only once the chosen platform's link has landed
        # (or the user went on without one), so the link is on this document.
        connected_platform = next(iter(linked_platforms_of(updated_user)), None)

        # Once per user: the atomic gate above returned early on a retried POST.
        # The typed need is free text (only presence travels); profession goes
        # onto the person profile so cohorts can cut by it.
        analytics_user = UserId(user_id)
        capture(
            analytics_user,
            OnboardingCompleted(
                needs=sorted(need.value for need in onboarding_data.needs),
                has_other_need=bool(onboarding_data.other_need),
                linked_platform=connected_platform,
            ),
        )
        identify_user(
            analytics_user,
            {"profession": onboarding_data.profession, "onboarding_completed": True},
        )

        stored = updated_user.onboarding.preferences if updated_user.onboarding else None
        seeded_user = await _seed_first_conversation(
            updated_user, stored or preferences, connected_platform
        )

        log.info(f"{LogTag.ONBOARDING} Onboarding completed successfully for user", user_id=user_id)
        return _onboarding_user(seeded_user or updated_user)

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


async def complete_onboarding_on_platform_link(user_id: str) -> None:
    """Finish onboarding when the platform step's bot link lands, so a user who never returns to the web tab is not left unfinished.

    Only for a user already past the paid reveal with stored answers; the web
    submit that may follow replays into the same atomic completion gate.
    """
    user = await user_repository.get(user_id)
    onboarding = user.onboarding if user else None
    if onboarding is None or onboarding.completed:
        return
    if OnboardingStep.PAID_REVEAL_SEEN not in onboarding.steps_reached:
        return
    stored = onboarding.preferences
    if stored is None or not stored.profession:
        return
    await complete_onboarding(
        user_id,
        OnboardingRequest(
            profession=stored.profession, needs=stored.needs or [], other_need=stored.other_need
        ),
    )


async def _seed_first_conversation(
    user: UserDocument, preferences: OnboardingPreferences, connected_platform: str | None
) -> UserDocument | None:
    """Seed GAIA's opening conversation and stamp its id on the onboarding subdoc.

    Best-effort by design: the welcome is a nicety, and a user whose completion
    write already landed must not be bounced back into the wizard because a
    conversation could not be created. Returns the re-read user document when the
    id was stored, so the completion response carries it.
    """
    user_id = user.id
    try:
        composed = compose_first_conversation(preferences, connected_platform)
        # Almost always a Redis read: the PATCH that preceded this fired the
        # model call in the background. A miss costs at most two seconds; a
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

        return _onboarding_status(user)

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
) -> OnboardingUser:
    """Update a user's onboarding preferences (for the settings page)."""
    try:
        # PATCH semantics: the repository writes only fields the caller set, each
        # at its own dotted path, so Preferences and Custom Instructions (disjoint
        # fields) can't clobber each other.
        updated_user = await user_repository.update_onboarding_preferences(user_id, preferences)
        if updated_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        log.info(
            f"{LogTag.ONBOARDING} Onboarding preferences updated successfully for user",
            user_id=user_id,
        )

        return _onboarding_user(updated_user)

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


async def save_onboarding_answers(user_id: str, answers: OnboardingAnswers) -> OnboardingUser:
    """Store the wizard's Q1 and Q2 the moment they are confirmed, and stamp questions_answered.

    Written long before completion: the platform-link opener and the seeded
    first conversation are composed from these stored answers.
    """
    preferences = OnboardingPreferences(
        profession=answers.profession,
        needs=answers.needs,
        other_need=answers.other_need,
        language=answers.language,
    )
    updated_user = await user_repository.update_onboarding_preferences(user_id, preferences)
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Detached on purpose: the wizard's next screens are the latency budget for
    # the model call the seeded conversation needs; a miss only costs the chips.
    spawn_background_task(
        prewarm_first_question(
            user_id, preferences, next(iter(linked_platforms_of(updated_user)), None)
        ),
        name=f"prewarm_first_question:{user_id}",
    )
    await record_onboarding_step(user_id, OnboardingStep.QUESTIONS_ANSWERED, answers=answers)
    return _onboarding_user(updated_user)


async def record_onboarding_step(
    user_id: str, step: OnboardingStep, *, answers: OnboardingAnswers | None = None
) -> bool:
    """Stamp step on the user and report it once per onboarding run; False when already stamped."""
    reached_at = datetime.now(UTC)
    if not await user_repository.record_onboarding_step(user_id, step, reached_at):
        return False
    capture(
        UserId(user_id),
        _step_event(step, answers),
        Dedupe(key=f"onboarding_step:{step.value}", occurred_at=reached_at),
    )
    return True


def _step_event(
    step: OnboardingStep, answers: OnboardingAnswers | None
) -> OnboardingStarted | OnboardingPhaseCompleted:
    if step is OnboardingStep.STARTED:
        return OnboardingStarted()
    if answers is None:
        return OnboardingPhaseCompleted(phase=step)
    # The typed need is free text, so only its presence travels.
    return OnboardingPhaseCompleted(
        phase=step,
        needs=sorted(need.value for need in answers.needs),
        has_other_need=bool(answers.other_need),
    )


async def reset_onboarding(
    user_id: str, *, keep_connections: bool = False
) -> OnboardingResetCounts:
    """Fully reset a user's onboarding so they can run the flow from scratch.

    keep_connections leaves connected integrations and memories in place and
    only tears down onboarding state — the local dev reset, not the product's
    Restart button.
    """
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

    onboarding = user.onboarding or OnboardingSubdocument()
    # Legacy state: users who ran the pre-relocation onboarding still carry the
    # workflows it generated and the conversation it seeded. Nothing writes
    # either any more, but a reset must still clear them.
    workflow_ids: list[str] = onboarding.suggested_workflows
    seeded_conversation_ids: list[str] = [
        cid
        for cid in (
            onboarding.first_message_conversation_id,
            onboarding.getting_started_conversation_id,
            onboarding.holo_conversation_id,
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

    integrations_disconnected = (
        0 if keep_connections else await _disconnect_user_integrations(user_id)
    )
    memories_cleared = 0 if keep_connections else await _clear_user_memories(user_id)

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
