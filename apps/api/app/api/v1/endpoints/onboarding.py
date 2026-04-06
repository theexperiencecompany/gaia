from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from shared.py.wide_events import log

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import (
    todos_collection,
    users_collection,
    workflows_collection,
)
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import (
    BioStatus,
    OnboardingPhaseUpdateRequest,
    OnboardingPreferences,
    OnboardingRequest,
    OnboardingResponse,
)
from app.services.composio.composio_service import get_composio_service
from app.services.onboarding.onboarding_service import (
    complete_onboarding,
    get_user_onboarding_status,
    update_onboarding_preferences,
)
from app.services.onboarding.social_profile_service import save_confirmed_profiles
from app.services.onboarding.writing_style_service import (
    regenerate_example_for_style,
    save_generated_example,
    save_user_edited_summary,
)
from app.services.user_service import get_user_by_id

router = APIRouter()


@router.post("", response_model=OnboardingResponse)
async def complete_user_onboarding(
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tz_info: GET_USER_TZ_TYPE = Depends(get_user_timezone),
):
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

        try:
            from app.utils.redis_utils import RedisPoolManager

            pool = await RedisPoolManager.get_pool()
            await pool.enqueue_job(
                "process_onboarding_intelligence_task", user["user_id"]
            )
            log.info(f"Queued onboarding intelligence for user {user['user_id']}")
        except Exception as e:
            log.error(f"Failed to queue intelligence task: {e}", exc_info=True)

        return OnboardingResponse(
            success=True, message="Onboarding completed successfully", user=updated_user
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        log.error(f"Error completing onboarding: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to complete onboarding")


@router.get("/status", response_model=dict)
async def get_onboarding_status(user: dict = Depends(get_current_user)):
    """
    Get the current user's onboarding status and preferences.
    """
    log.set(
        user={"id": user["user_id"]},
        onboarding={"operation": "get_status"},
    )
    try:
        status = await get_user_onboarding_status(user["user_id"])
        is_complete = (
            status.get("is_complete", False) if isinstance(status, dict) else False
        )
        log.set(onboarding={"operation": "get_status", "is_complete": is_complete})
        return status
    except Exception as e:
        log.error(f"Error getting onboarding status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get onboarding status")


@router.post("/phase", response_model=dict)
async def update_onboarding_phase(
    request: OnboardingPhaseUpdateRequest, user: dict = Depends(get_current_user)
):
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
            log.error("[update_onboarding_phase] user_id is missing or not a string")
            raise HTTPException(status_code=400, detail="Invalid user_id")

        log.info(
            f"[update_onboarding_phase] Updating phase to {phase} for user {user_id}"
        )

        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "onboarding.phase": request.phase.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.matched_count == 0:
            log.warning(
                f"[update_onboarding_phase] No document found for user {user_id}"
            )
            raise HTTPException(status_code=404, detail="User not found")

        log.info(
            f"[update_onboarding_phase] Successfully updated phase to {phase} for user {user_id}, modified_count={result.modified_count}"
        )

        try:
            await websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "onboarding_phase_update",
                    "data": {"phase": phase},
                },
            )
            log.info(
                f"[update_onboarding_phase] Sent WebSocket notification for phase update to {phase}"
            )
        except Exception as ws_error:
            log.warning(
                f"[update_onboarding_phase] Failed to send WebSocket update: {ws_error}"
            )

        return {
            "success": True,
            "phase": phase,
            "message": f"Onboarding phase updated to {phase}",
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating onboarding phase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update onboarding phase")


@router.patch("/preferences", response_model=dict)
async def update_user_preferences(
    preferences: OnboardingPreferences, user: dict = Depends(get_current_user)
):
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

        return {
            "success": True,
            "message": "Preferences updated successfully",
            "user": updated_user,
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        log.error(f"Error updating preferences: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update preferences")


@router.get("/personalization")
async def get_onboarding_personalization(user: dict = Depends(get_current_user)):
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
        log.info(
            f"[get_onboarding_personalization] Fetching personalization for user {user_id}"
        )
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})

        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding = user_doc.get("onboarding", {})
        user_bio = onboarding.get("user_bio", "")
        phase = onboarding.get("phase", "initial")
        log.info(
            f"[get_onboarding_personalization] User {user_id} has phase: {phase}, bio_status: {onboarding.get('bio_status')}"
        )
        has_personalization = phase in [
            "personalization_complete",
            "getting_started",
            "completed",
        ]

        account_number = onboarding.get("account_number")
        member_since = onboarding.get("member_since")

        if not account_number or not member_since:
            created_at = user_doc.get("created_at")
            if created_at:
                count = await users_collection.count_documents(
                    {"created_at": {"$lt": created_at}}
                )
                account_number = count + 1
            else:
                account_number = 1

            member_since = (
                created_at.strftime("%b %d, %Y")
                if created_at
                else datetime.now(timezone.utc).strftime("%b %d, %Y")
            )

        workflow_ids = onboarding.get("suggested_workflows", [])
        workflows = []
        if workflow_ids:
            try:
                query_ids = [
                    ObjectId(wf_id) if ObjectId.is_valid(wf_id) else wf_id
                    for wf_id in workflow_ids
                ]
                cursor = workflows_collection.find({"_id": {"$in": query_ids}})
                wf_docs = {str(wf["_id"]): wf async for wf in cursor}
                for wf_id in workflow_ids:
                    wf = wf_docs.get(str(wf_id))
                    if wf:
                        workflows.append(
                            {
                                "id": str(wf["_id"]),
                                "title": wf.get("title", ""),
                                "description": wf.get("description", ""),
                                "steps": wf.get("steps", []),
                            }
                        )
            except Exception as e:
                log.error(f"Error fetching workflows: {str(e)}", exc_info=True)

        bio_status = onboarding.get("bio_status", "pending")
        display_bio = user_bio

        if bio_status in ["processing", BioStatus.PROCESSING]:
            display_bio = "Processing your insights... Please check back in a moment."
        elif bio_status in ["pending", BioStatus.PENDING]:
            composio_service = get_composio_service()
            connection_status = await composio_service.check_connection_status(
                ["gmail"], str(user_id)
            )
            has_gmail = connection_status.get("gmail", False)
            if has_gmail:
                display_bio = (
                    "Processing your insights... Please check back in a moment."
                )
            else:
                display_bio = "Setting up your profile..."

        raw_writing_style = onboarding.get("writing_style")
        raw_social_profiles = onboarding.get("social_profiles", [])
        triage_summary = onboarding.get("triage_summary")

        onboarding_todos: list[dict] = []
        try:
            todo_cursor = (
                todos_collection.find(
                    {"user_id": user_id, "labels": "onboarding"},
                    {"_id": 1, "title": 1, "description": 1, "source_email": 1},
                )
                .sort("created_at", -1)
                .limit(5)
            )
            onboarding_todos = [
                {
                    "id": str(t["_id"]),
                    "title": t.get("title", ""),
                    "description": t.get("description"),
                    "source_email": t.get("source_email"),
                }
                async for t in todo_cursor
            ]
        except Exception as e:
            log.warning(f"Failed to fetch onboarding todos: {e}")

        return {
            "phase": phase,
            "has_personalization": has_personalization,
            "house": onboarding.get("house", "Bluehaven"),
            "personality_phrase": onboarding.get(
                "personality_phrase", "Curious Adventurer"
            ),
            "user_bio": display_bio,
            "account_number": account_number,
            "member_since": member_since,
            "overlay_color": onboarding.get("overlay_color", "rgba(0,0,0,0)"),
            "overlay_opacity": onboarding.get("overlay_opacity", 40),
            "suggested_workflows": workflows,
            "name": user_doc.get("name", "User"),
            "holo_card_id": str(user_doc["_id"]),
            "first_message_conversation_id": onboarding.get(
                "first_message_conversation_id"
            ),
            "writing_style": {
                "style_summary": raw_writing_style.get(
                    "user_edited_summary", raw_writing_style.get("summary", "")
                ),
                "example": raw_writing_style.get("example", ""),
            }
            if raw_writing_style
            else None,
            "social_profiles": [
                {"platform": p.get("platform", ""), "url": p.get("url", "")}
                for p in raw_social_profiles
            ]
            if raw_social_profiles
            else None,
            "triage_summary": triage_summary,
            "onboarding_todos": onboarding_todos if onboarding_todos else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error fetching personalization: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to fetch personalization data"
        )


class ExecuteTodoRequest(BaseModel):
    todo_id: str


class ExecuteTodoResponse(BaseModel):
    success: bool
    message: str
    todo_id: str


@router.post("/execute-todo", response_model=ExecuteTodoResponse)
async def execute_onboarding_todo(
    request: ExecuteTodoRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone),
) -> ExecuteTodoResponse:
    """Execute a single onboarding todo via the agent. Runs in background, streams progress via WebSocket."""
    user_id = user.get("user_id") or str(user["_id"])
    todo_id = request.todo_id

    todo_doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id}
    )
    if not todo_doc:
        raise HTTPException(status_code=404, detail="Todo not found")

    todo_title = todo_doc.get("title", "")
    todo_description = todo_doc.get("description", "")

    user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
    conversation_id = (
        user_doc.get("onboarding", {}).get("first_message_conversation_id")
        if user_doc
        else None
    )
    if not conversation_id:
        raise HTTPException(status_code=400, detail="No onboarding conversation found")

    await websocket_manager.broadcast_to_user(
        user_id=user_id,
        message={
            "type": "onboarding_todo_executing",
            "data": {"todo_id": todo_id, "status": "started"},
        },
    )

    background_tasks.add_task(
        _execute_todo_background,
        user_id=user_id,
        todo_id=todo_id,
        todo_title=todo_title,
        todo_description=todo_description,
        conversation_id=conversation_id,
        user_timezone=user_timezone,
    )

    return ExecuteTodoResponse(
        success=True,
        message="Todo execution started",
        todo_id=todo_id,
    )


async def _execute_todo_background(
    user_id: str,
    todo_id: str,
    todo_title: str,
    todo_description: str,
    conversation_id: str,
    user_timezone: str,
) -> None:
    """Background task: execute a todo via the agent and broadcast results."""
    from app.agents.core.agent import call_agent_silent

    try:
        user_data = await get_user_by_id(user_id)
        if not user_data:
            log.error(f"[onboarding:execute-todo] User not found: {user_id}")
            return

        user_data["user_id"] = user_id

        task_message = f"Execute this todo for me: {todo_title}" + (
            f"\n\nContext: {todo_description}" if todo_description else ""
        )

        request = MessageRequestWithHistory(
            message=task_message,
            messages=[],
            fileIds=[],
            fileData=[],
            selectedTool=None,
            toolCategory=None,
            selectedWorkflow=None,
            selectedCalendarEvent=None,
            replyToMessage=None,
        )

        user_time = datetime.now(timezone.utc)

        complete_message, tool_data = await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            user_time=user_time,
        )

        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "onboarding_todo_executed",
                "data": {
                    "todo_id": todo_id,
                    "status": "completed",
                    "result": complete_message[:500] if complete_message else "",
                },
            },
        )

        log.info(
            f"[onboarding:execute-todo] Completed for user {user_id}, todo {todo_id}"
        )

    except Exception as e:
        log.error(
            f"[onboarding:execute-todo] Failed for user {user_id}, todo {todo_id}: {e}",
            exc_info=True,
        )
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "onboarding_todo_executed",
                "data": {
                    "todo_id": todo_id,
                    "status": "failed",
                    "result": "Something went wrong executing this todo.",
                },
            },
        )


# ── Writing style edit ────────────────────────────────────────────────────────


class WritingStyleEditRequest(BaseModel):
    edited_summary: str


class WritingStyleRegenerateRequest(BaseModel):
    edited_summary: str
    profession: str = ""


@router.post("/writing-style", response_model=dict)
async def save_writing_style(
    request: WritingStyleEditRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Save a user-edited writing style summary from the onboarding reveal card."""
    user_id: str = user["user_id"]
    log.set(user={"id": user_id}, onboarding={"operation": "save_writing_style"})
    try:
        await save_user_edited_summary(user_id, request.edited_summary.strip())
        return {"success": True}
    except Exception as e:
        log.error(f"[onboarding] Failed to save writing style: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save writing style")


@router.post("/writing-style/regenerate-example", response_model=dict)
async def regenerate_writing_style_example(
    request: WritingStyleRegenerateRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Generate a new example email from an edited writing style summary.
    Called after the user saves their edited summary on the reveal card.
    """
    user_id: str = user["user_id"]
    log.set(user={"id": user_id}, onboarding={"operation": "regenerate_style_example"})
    try:
        example = await regenerate_example_for_style(
            summary=request.edited_summary.strip(),
            profession=request.profession,
        )
        if example:
            await save_generated_example(user_id, example)
        return {"example": example}
    except Exception as e:
        log.error(
            f"[onboarding] Failed to regenerate writing style example: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to regenerate writing style example"
        )


# ── Social profiles confirm ───────────────────────────────────────────────────


class SocialProfileItem(BaseModel):
    platform: str
    url: str


class SocialProfilesConfirmRequest(BaseModel):
    profiles: list[SocialProfileItem]


@router.post("/social-profiles", response_model=dict)
async def confirm_social_profiles(
    request: SocialProfilesConfirmRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Save user-confirmed (and optionally edited) social profiles from onboarding."""
    user_id: str = user["user_id"]
    log.set(user={"id": user_id}, onboarding={"operation": "confirm_social_profiles"})
    try:
        profiles = [p.model_dump() for p in request.profiles]
        await save_confirmed_profiles(user_id, profiles)
        return {"success": True, "saved": len(profiles)}
    except Exception as e:
        log.error(f"[onboarding] Failed to save social profiles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save social profiles")
