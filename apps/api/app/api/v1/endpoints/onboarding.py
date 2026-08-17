from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.constants.log_tags import LogTag
from app.constants.todos import ONBOARDING_TODO_LIMIT
from app.core.websocket_manager import websocket_manager
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.onboarding_models import (
    ClarifyQuestionsResponse,
    OnboardingPhaseUpdateResponse,
    OnboardingResetResponse,
    PersistedTriageSummary,
    PersonalizationResponse,
    PersonalizationTodo,
    PersonalizationWorkflow,
    PersonalizationWritingStyle,
    RegenerateWritingStyleExampleResponse,
    SaveSocialProfilesResponse,
    SaveWritingStyleResponse,
    SocialProfile,
    WritingStyleExampleBlocks,
)
from app.models.user_models import (
    AuthenticatedUser,
    BioStatus,
    OnboardingIntegrationsRequest,
    OnboardingIntegrationsResponse,
    OnboardingPhaseUpdateRequest,
    OnboardingPreferences,
    OnboardingRequest,
    OnboardingResponse,
    OnboardingStatusResponse,
    UserDocument,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.composio.composio_service import get_composio_service
from app.services.onboarding.clarify_service import generate_clarify_questions
from app.services.onboarding.onboarding_service import (
    complete_onboarding,
    get_user_onboarding_status,
    reset_onboarding,
    submit_onboarding_integrations,
    update_onboarding_preferences,
)
from app.services.onboarding.social_profile_service import save_confirmed_profiles
from app.services.onboarding.writing_style_service import (
    regenerate_example_for_style,
    save_generated_example,
    save_user_edited_summary,
)
from shared.py.wide_events import log

router = APIRouter()

_BIO_PROCESSING_MESSAGE = "Processing your insights... Please check back in a moment."
_MEMBER_SINCE_FORMAT = "%b %d, %Y"
# Phases past which the personalization payload carries real, generated content.
_PERSONALIZED_PHASES = ("personalization_complete", "getting_started", "completed")


def _normalize_example_blocks(raw: object) -> WritingStyleExampleBlocks | None:
    """Normalize a persisted writing-style example (blocks or legacy string).

    Returns None when there is nothing renderable — including a stored example
    whose paragraphs are all whitespace, which the reveal card already treats
    identically to a missing example (it regenerates from the summary either way).
    """
    if isinstance(raw, dict):
        body = [str(p) for p in raw.get("body", []) if str(p).strip()]
        if not body:
            return None
        return WritingStyleExampleBlocks(
            greeting=str(raw.get("greeting", "")),
            body=body,
            signoff=str(raw.get("signoff", "")),
            name=str(raw.get("name", "")),
        )
    if isinstance(raw, str) and raw.strip():
        return WritingStyleExampleBlocks(greeting="", body=[raw.strip()], signoff="", name="")
    return None


@router.post("", response_model=OnboardingResponse)
async def complete_user_onboarding(
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    tz_info: Annotated[GET_USER_TZ_TYPE, Depends(get_user_timezone)],
) -> OnboardingResponse:
    """Complete user onboarding by storing preferences and queuing the intelligence pipeline."""
    log.set(
        user={"id": user["user_id"]},
        onboarding={
            "operation": "complete",
            "is_complete": True,
            "timezone": tz_info[0],
        },
    )

    try:
        updated_user = await complete_onboarding(
            user["user_id"],
            onboarding_data,
            background_tasks,
        )
        # No completion event here: this only QUEUES the pipeline. The worker
        # emits it once the phase actually reaches PERSONALIZATION_COMPLETE,
        # so a pipeline that fails afterwards is not counted as a completion.
        return OnboardingResponse(
            success=True, message="Onboarding completed successfully", user=updated_user
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error completing onboarding",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to complete onboarding") from e


@router.post(
    "/integrations",
    responses={500: {"description": "Failed to submit integrations"}},
)
async def submit_integrations(
    request: OnboardingIntegrationsRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OnboardingIntegrationsResponse:
    """Persist selected integrations and start the deferred workflows phase (split-mode onboarding)."""
    log.set(
        user={"id": user["user_id"]},
        onboarding={"operation": "submit_integrations"},
    )
    try:
        status = await submit_onboarding_integrations(
            user["user_id"], request.selected_integrations
        )
        log.set(onboarding={"result_status": status.value})
        return OnboardingIntegrationsResponse(success=True, status=status)
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error submitting integrations",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to submit integrations") from e


class ClarifyQuestionsRequest(BaseModel):
    name: str
    profession: str
    focus: str


@router.post("/clarify-questions")
async def get_clarify_questions(
    payload: ClarifyQuestionsRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ClarifyQuestionsResponse:
    """Generate the LLM 3-question follow-up for the no-Gmail path."""
    log.set(
        user={"id": user["user_id"]},
        onboarding={"operation": "clarify_questions"},
    )
    name = payload.name.strip() or "there"
    profession = payload.profession.strip() or "professional"
    focus = payload.focus.strip()
    if not focus:
        raise HTTPException(status_code=400, detail="Focus is required")

    questions = await generate_clarify_questions(name, profession, focus, user_id=user["user_id"])
    return ClarifyQuestionsResponse(questions=questions)


@router.post(
    "/reset",
    responses={500: {"description": "Failed to reset onboarding"}},
)
async def reset_user_onboarding(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OnboardingResetResponse:
    """Fully reset onboarding so the user can run the flow again from scratch."""
    log.set(user={"id": user["user_id"]}, onboarding={"operation": "reset"})
    try:
        counts = await reset_onboarding(user["user_id"])
        return OnboardingResetResponse(success=True, **counts.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error resetting onboarding",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to reset onboarding") from e


@router.get("/status")
async def get_onboarding_status(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OnboardingStatusResponse:
    """
    Get the current user's onboarding status and preferences.
    """
    log.set(
        user={"id": user["user_id"]},
        onboarding={"operation": "get_status"},
    )
    try:
        status = await get_user_onboarding_status(user["user_id"])
        log.set(onboarding={"operation": "get_status", "is_complete": status.completed})
        return status
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error getting onboarding status",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get onboarding status") from e


@router.post("/phase")
async def update_onboarding_phase(
    request: OnboardingPhaseUpdateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OnboardingPhaseUpdateResponse:
    """
    Update the user's onboarding phase.
    Used to track progress through onboarding stages.
    """
    try:
        user_id = user.get("user_id")
        phase = request.phase.value

        log.set(
            user={"id": user_id},
            onboarding={"operation": "update_step", "step": phase},
        )

        if not user_id or not isinstance(user_id, str):
            log.error(
                f"{LogTag.ONBOARDING} user_id is missing or not a string",
                user_id_type=type(user_id).__name__,
            )
            raise HTTPException(status_code=400, detail="Invalid user_id")

        log.info(f"{LogTag.ONBOARDING} Updating phase", user_id=user_id, phase=request.phase.value)

        matched = await user_repository.set_onboarding_phase(user_id, request.phase)

        if not matched:
            log.warning(f"{LogTag.ONBOARDING} No document found for user", user_id=user_id)
            raise HTTPException(status_code=404, detail="User not found")

        capture_context_event(AnalyticsEvents.ONBOARDING_STEP_COMPLETED, {"phase": phase})
        log.set_ns("onboarding", phase_updated=True)

        try:
            await websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "onboarding_phase_update",
                    "data": {"phase": phase},
                },
            )
            log.info(
                f"{LogTag.ONBOARDING} Sent WebSocket notification for phase update",
                phase=phase,
                user_id=user_id,
            )
        except Exception as ws_error:
            log.warning(
                f"{LogTag.ONBOARDING} Failed to send WebSocket update",
                user_id=user_id,
                error_type=type(ws_error).__name__,
                error=str(ws_error),
            )

        return OnboardingPhaseUpdateResponse(
            success=True,
            phase=request.phase,
            message=f"Onboarding phase updated to {phase}",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error updating onboarding phase",
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update onboarding phase") from e


@router.patch("/preferences")
async def update_user_preferences(
    preferences: OnboardingPreferences,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OnboardingResponse:
    """
    Update user's onboarding preferences.
    This can be used from the settings page to update preferences after onboarding.
    """
    log.set(
        user={"id": user["user_id"]},
        onboarding={"operation": "update_personality"},
    )

    try:
        updated_user = await update_onboarding_preferences(user["user_id"], preferences)
        # PATCH semantics: only the fields the caller actually sent were written,
        # so `fields` is what changed — not the whole preferences object.
        capture_context_event(
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {
                "setting": "onboarding_preferences",
                "fields": sorted(preferences.model_fields_set),
                "response_style": preferences.response_style,
                "has_custom_instructions": bool(preferences.custom_instructions),
            },
        )

        return OnboardingResponse(
            success=True,
            message="Preferences updated successfully",
            user=updated_user,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error updating preferences",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update preferences") from e


async def _resolve_account_identity(
    user_doc: UserDocument, onboarding: dict[str, Any]
) -> tuple[int, str]:
    """The stored account number and join date, derived from ``created_at`` on
    the first read (both are backfilled together or not at all)."""
    account_number = onboarding.get("account_number")
    member_since = onboarding.get("member_since")
    if account_number and member_since:
        return account_number, member_since

    created_at = user_doc.created_at
    if not created_at:
        return 1, datetime.now(UTC).strftime(_MEMBER_SINCE_FORMAT)

    return (
        await user_repository.count_created_before(created_at) + 1,
        created_at.strftime(_MEMBER_SINCE_FORMAT),
    )


async def _load_suggested_workflows(workflow_ids: list[str]) -> list[PersonalizationWorkflow]:
    """The suggested workflows in stored order. Soft-fails to an empty list —
    the reveal card renders without them rather than failing the whole read."""
    if not workflow_ids:
        return []
    try:
        wf_docs = {wf.id: wf for wf in await workflow_repository.find_by_ids(workflow_ids)}
        return [
            PersonalizationWorkflow(
                id=wf.id, title=wf.title, description=wf.description, steps=wf.steps
            )
            for wf_id in workflow_ids
            if (wf := wf_docs.get(wf_id))
        ]
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error fetching workflows",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return []


async def _resolve_display_bio(onboarding: dict[str, Any], user_id: str) -> str:
    """The bio to show now. While extraction is still pending we only promise a
    bio if there is a Gmail connection to extract one from."""
    bio_status = onboarding.get("bio_status", "pending")

    if bio_status in ["processing", BioStatus.PROCESSING]:
        return _BIO_PROCESSING_MESSAGE
    if bio_status not in ["pending", BioStatus.PENDING]:
        # onboarding is dict[str, Any] on the document; user_bio is stored as str.
        stored_bio: str = onboarding.get("user_bio", "")
        return stored_bio

    connection_status = await get_composio_service().check_connection_status(["gmail"], user_id)
    if connection_status.get("gmail", False):
        return _BIO_PROCESSING_MESSAGE
    return "Setting up your profile..."


def _build_writing_style(
    raw_writing_style: dict[str, Any] | None,
) -> PersonalizationWritingStyle | None:
    """Only surface writing_style if it has a usable summary; otherwise return
    None so the frontend skips the reveal."""
    if not raw_writing_style:
        return None
    resolved_summary = (
        raw_writing_style.get("user_edited_summary") or raw_writing_style.get("summary") or ""
    ).strip()
    if not resolved_summary:
        return None
    return PersonalizationWritingStyle(
        style_summary=resolved_summary,
        example=_normalize_example_blocks(raw_writing_style.get("example")),
    )


async def _load_onboarding_todos(user_id: str) -> list[PersonalizationTodo]:
    try:
        todos = await todo_repository.list_onboarding_todos(user_id, limit=ONBOARDING_TODO_LIMIT)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} Failed to fetch onboarding todos",
            error=str(e),
            error_type=type(e).__name__,
        )
        return []
    return [
        PersonalizationTodo(
            id=t.id,
            title=t.title or "",
            description=t.description,
            source_email=t.source_email,
        )
        for t in todos
    ]


@router.get("/personalization")
async def get_onboarding_personalization(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PersonalizationResponse:
    """
    Get personalization data (house, phrase, bio, workflows) for current authenticated user.
    Used as fallback if WebSocket fails or to refetch data.
    Returns default values if personalization hasn't completed yet.
    """
    try:
        user_id = user.get("user_id")
        log.set(
            user={"id": user_id},
            onboarding={"operation": "get_personalization"},
        )
        if not user_id or not isinstance(user_id, str):
            raise HTTPException(status_code=400, detail="Invalid user_id")
        log.info(f"{LogTag.ONBOARDING} Fetching personalization for user", user_id=user_id)
        user_doc = await user_repository.get(user_id)

        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding = user_doc.onboarding or {}
        phase = onboarding.get("phase", "initial")
        log.info(
            f"{LogTag.ONBOARDING} User onboarding state",
            user_id=user_id,
            phase=phase,
            bio_status=onboarding.get("bio_status"),
        )

        account_number, member_since = await _resolve_account_identity(user_doc, onboarding)
        display_bio = await _resolve_display_bio(onboarding, user_id)
        workflows = await _load_suggested_workflows(onboarding.get("suggested_workflows", []))
        onboarding_todos = await _load_onboarding_todos(user_id)

        raw_social_profiles = onboarding.get("social_profiles", [])
        raw_triage_summary = onboarding.get("triage_summary")

        return PersonalizationResponse(
            phase=phase,
            has_personalization=phase in _PERSONALIZED_PHASES,
            house=onboarding.get("house", "Bluehaven"),
            personality_phrase=onboarding.get("personality_phrase", "Curious Adventurer"),
            user_bio=display_bio,
            account_number=account_number,
            member_since=member_since,
            overlay_color=onboarding.get("overlay_color", "rgba(0,0,0,0)"),
            overlay_opacity=onboarding.get("overlay_opacity", 40),
            suggested_workflows=workflows,
            name=user_doc.name or "User",
            holo_card_id=user_doc.id,
            first_message_conversation_id=onboarding.get("first_message_conversation_id"),
            first_message=onboarding.get("first_message"),
            writing_style=_build_writing_style(onboarding.get("writing_style")),
            social_profiles=[
                SocialProfile(platform=p.get("platform", ""), url=p.get("url", ""))
                for p in raw_social_profiles
            ]
            if raw_social_profiles
            else None,
            triage_summary=(
                PersistedTriageSummary.model_validate(raw_triage_summary)
                if raw_triage_summary
                else None
            ),
            onboarding_todos=onboarding_todos or None,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Error fetching personalization",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch personalization data")


class WritingStyleEditRequest(BaseModel):
    edited_summary: str


class WritingStyleRegenerateRequest(BaseModel):
    edited_summary: str
    profession: str = ""


@router.post(
    "/writing-style",
    responses={500: {"description": "Failed to save writing style"}},
)
async def save_writing_style(
    request: WritingStyleEditRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SaveWritingStyleResponse:
    """Save a user-edited writing style summary from the onboarding reveal card."""
    user_id: str = user["user_id"]
    log.set(user={"id": user_id}, onboarding={"operation": "save_writing_style"})
    try:
        await save_user_edited_summary(user_id, request.edited_summary.strip())
        return SaveWritingStyleResponse(success=True)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Failed to save writing style",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to save writing style") from e


@router.post(
    "/writing-style/regenerate-example",
    responses={500: {"description": "Failed to regenerate writing style example"}},
)
async def regenerate_writing_style_example(
    request: WritingStyleRegenerateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> RegenerateWritingStyleExampleResponse:
    """Generate a new example email from an edited writing style summary."""
    user_id: str = user["user_id"]
    log.set(user={"id": user_id}, onboarding={"operation": "regenerate_style_example"})
    try:
        example = await regenerate_example_for_style(
            summary=request.edited_summary.strip(),
            user_id=user_id,
            profession=request.profession,
        )
        if example:
            await save_generated_example(user_id, example)
        return RegenerateWritingStyleExampleResponse(example=example)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Failed to regenerate writing style example",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to regenerate writing style example"
        ) from e


class SocialProfilesConfirmRequest(BaseModel):
    profiles: list[SocialProfile]


@router.post(
    "/social-profiles",
    responses={500: {"description": "Failed to save social profiles"}},
)
async def confirm_social_profiles(
    request: SocialProfilesConfirmRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SaveSocialProfilesResponse:
    """Save user-confirmed (and optionally edited) social profiles from onboarding."""
    user_id: str = user["user_id"]
    log.set(user={"id": user_id}, onboarding={"operation": "confirm_social_profiles"})
    try:
        await save_confirmed_profiles(user_id, request.profiles)
        return SaveSocialProfilesResponse(success=True, saved=len(request.profiles))
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Failed to save social profiles",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to save social profiles") from e
