from datetime import datetime, timezone

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.config.loggers import auth_logger as logger
from app.db.mongodb.collections import users_collection, workflows_collection
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
    queue_personalization,
    update_onboarding_preferences,
)
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from app.core.websocket_manager import websocket_manager

router = APIRouter()


@router.post("", response_model=OnboardingResponse)
async def complete_user_onboarding(
    onboarding_data: OnboardingRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tz_info: GET_USER_TZ_TYPE = Depends(get_user_timezone),
):
    """
    Complete user onboarding by storing preferences.

    Flow:
    - If user has Gmail connected: Email processor will trigger personalization after parsing
    - If no Gmail: Queue personalization ARQ job directly
    """
    try:
        updated_user = await complete_onboarding(
            user["user_id"],
            onboarding_data,
            background_tasks,
            user_timezone=tz_info[0],
        )

        composio_service = get_composio_service()
        connection_status = await composio_service.check_connection_status(
            ["gmail"], user["user_id"]
        )
        has_gmail = connection_status.get("gmail", False)

        # Check if Gmail emails have already been processed
        user_doc = await users_collection.find_one({"_id": ObjectId(user["user_id"])})
        email_already_processed = (
            user_doc.get("email_memory_processed", False) if user_doc else False
        )

        if has_gmail and not email_already_processed:
            # Gmail connected but not yet processed - queue email processing
            # Email processor will trigger personalization when done
            logger.info(
                f"User {user['user_id']} has Gmail (not processed) - queueing email processing"
            )
            from app.utils.redis_utils import RedisPoolManager

            try:
                pool = await RedisPoolManager.get_pool()
                await pool.enqueue_job(
                    "process_gmail_emails_to_memory", user["user_id"]
                )
                logger.info(f"Queued Gmail processing for user {user['user_id']}")
            except Exception as e:
                logger.error(f"Failed to queue Gmail processing: {e}", exc_info=True)
                # Fallback: queue personalization directly
                background_tasks.add_task(queue_personalization, user["user_id"])
        else:
            # No Gmail OR already processed - queue personalization directly
            reason = "already processed" if email_already_processed else "no Gmail"
            logger.info(
                f"User {user['user_id']} ({reason}) - queueing personalization directly"
            )
            background_tasks.add_task(queue_personalization, user["user_id"])

        return OnboardingResponse(
            success=True, message="Onboarding completed successfully", user=updated_user
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error completing onboarding: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to complete onboarding")


@router.get("/status", response_model=dict)
async def get_onboarding_status(user: dict = Depends(get_current_user)):
    """
    Get the current user's onboarding status and preferences.
    """
    status = await get_user_onboarding_status(user["user_id"])
    return status


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

        if not user_id or not isinstance(user_id, str):
            logger.error("[update_onboarding_phase] user_id is missing or not a string")
            raise HTTPException(status_code=400, detail="Invalid user_id")

        logger.info(
            f"[update_onboarding_phase] Updating phase to {phase} for user {user_id}"
        )

        # Update the phase in database
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "onboarding.phase": request.phase.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.modified_count == 0:
            logger.warning(
                f"[update_onboarding_phase] No document modified for user {user_id}"
            )
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(
            f"[update_onboarding_phase] Successfully updated phase to {phase} for user {user_id}, modified_count={result.modified_count}"
        )

        # Send WebSocket notification about phase update
        try:
            await websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "onboarding_phase_update",
                    "data": {"phase": phase},
                },
            )
            logger.info(
                f"[update_onboarding_phase] Sent WebSocket notification for phase update to {phase}"
            )
        except Exception as ws_error:
            logger.warning(
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
        logger.error(f"Error updating onboarding phase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update onboarding phase")


@router.patch("/preferences", response_model=dict)
async def update_user_preferences(
    preferences: OnboardingPreferences, user: dict = Depends(get_current_user)
):
    """
    Update user's onboarding preferences.
    This can be used from the settings page to update preferences after onboarding.
    """
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
        logger.error(f"Error updating preferences: {str(e)}", exc_info=True)
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
        logger.info(
            f"[get_onboarding_personalization] Fetching personalization for user {user_id}"
        )
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})

        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding = user_doc.get("onboarding", {})
        user_bio = onboarding.get("user_bio", "")
        # Check the phase to determine if personalization is complete
        phase = onboarding.get("phase", "initial")
        logger.info(
            f"[get_onboarding_personalization] User {user_id} has phase: {phase}, bio_status: {onboarding.get('bio_status')}"
        )
        has_personalization = phase in [
            "personalization_complete",
            "getting_started",
            "completed",
        ]

        # Get stored metadata or calculate if not stored (for older users)
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
                created_at.strftime("%b %d, %Y") if created_at else "Nov 21, 2024"
            )

        # Fetch full workflow objects
        workflow_ids = onboarding.get("suggested_workflows", [])
        workflows = []
        for wf_id in workflow_ids:
            try:
                query_id = ObjectId(wf_id) if ObjectId.is_valid(wf_id) else wf_id
                wf = await workflows_collection.find_one({"_id": query_id})
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
                logger.error(
                    f"Error fetching workflow {wf_id}: {str(e)}", exc_info=True
                )

        # Determine what bio to show based on bio_status
        bio_status = onboarding.get("bio_status", "pending")
        display_bio = user_bio

        # Override bio display based on status
        if bio_status in ["processing", BioStatus.PROCESSING]:
            display_bio = "Processing your insights... Please check back in a moment."
        elif bio_status in ["pending", BioStatus.PENDING]:
            # Check if user has Gmail via Composio to show appropriate message

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
        # For "no_gmail" and "completed" status, use the actual bio content
        # (no_gmail now has a default bio, completed has the full bio)

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
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching personalization: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to fetch personalization data"
        )
