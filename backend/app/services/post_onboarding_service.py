"""Post-onboarding personalization service."""

import asyncio
from datetime import datetime, timezone
from typing import List

from bson import ObjectId

from app.config.loggers import app_logger as logger
from app.core.websocket_manager import websocket_manager
from app.db.chromadb import ChromaClient
from app.db.mongodb.collections import users_collection, workflows_collection
from app.models.memory_models import MemorySearchResult
from app.models.user_models import BioStatus, OnboardingPhase
from app.services.memory_service import memory_service
from app.utils.profile_card import (
    generate_personality_phrase,
    generate_profile_card_design,
    generate_user_bio,
    get_user_metadata,
)
from app.utils.seeding_utils import (
    seed_initial_conversation,
    seed_initial_goal,
    seed_onboarding_todo,
)


async def emit_progress(
    user_id: str,
    stage: str,
    message: str,
    progress: int,
    details: dict | None = None,
) -> None:
    """Emit magical progress update to user via WebSocket."""
    await websocket_manager.broadcast_to_user(
        user_id,
        {
            "type": "personalization_progress",
            "data": {
                "stage": stage,
                "message": message,
                "progress": progress,
                "details": details or {},
            },
        },
    )


async def suggest_workflows_via_rag(user_id: str, limit: int = 4) -> List[str]:
    """
    Use RAG to find similar workflows based on user memories.

    Args:
        user_id: User identifier
        limit: Number of workflows to suggest

    Returns:
        List of workflow IDs
    """
    try:
        # Get user memories
        memories: MemorySearchResult = await memory_service.get_all_memories(
            user_id=user_id
        )

        if not memories.memories:
            logger.info(
                f"No memories found for user {user_id}, using default workflows"
            )
            return await _get_default_workflows(limit)

        # Create query from memories
        query_parts = [m.content for m in memories.memories]
        query_text = " ".join(query_parts)

        logger.info(f"Searching workflows with RAG query for user {user_id}")

        # Query ChromaDB workflows collection
        chroma_client = await ChromaClient.get_langchain_client(
            "workflows", create_if_not_exists=True
        )
        results = chroma_client.similarity_search(query_text, k=10)

        # Extract workflow IDs and verify they're public
        workflow_ids: List[str] = []
        for doc in results:
            wf_id = doc.metadata.get("workflow_id")
            if not wf_id:
                continue

            # Verify workflow exists and is public
            try:
                query_id = ObjectId(wf_id) if ObjectId.is_valid(wf_id) else wf_id
                workflow = await workflows_collection.find_one(
                    {"_id": query_id, "is_public": True}
                )
                if workflow and len(workflow_ids) < limit:
                    workflow_ids.append(str(wf_id))
            except Exception as e:
                logger.warning(f"Error verifying workflow {wf_id}: {e}")
                continue  # nosec B112

        # Fill with defaults if needed
        if len(workflow_ids) < limit:
            default_wfs = await _get_default_workflows(limit - len(workflow_ids))
            workflow_ids.extend(default_wfs)

        return workflow_ids[:limit]

    except Exception as e:
        logger.error(f"Error in workflow RAG: {e}", exc_info=True)
        return await _get_default_workflows(limit)


async def _get_default_workflows(limit: int = 4) -> List[str]:
    """Get default public workflows as fallback."""
    try:
        workflows = await workflows_collection.find(
            {"is_public": True}, limit=limit
        ).to_list(length=limit)
        return [str(wf["_id"]) for wf in workflows]
    except Exception as e:
        logger.error(f"Error fetching default workflows: {e}")
        return []


async def save_personalization_data(
    user_id: str,
    house: str,
    personality_phrase: str,
    user_bio: str,
    bio_status: BioStatus,
    workflow_ids: List[str],
    account_number: int,
    member_since: str,
    overlay_color: str,
    overlay_opacity: int,
) -> None:
    """
    Save personalization data to user document.

    Args:
        user_id: User identifier
        house: Assigned house
        personality_phrase: Generated phrase
        user_bio: Generated bio
        bio_status: Status of bio generation
        workflow_ids: Suggested workflow IDs
        account_number: User's account number
        member_since: Member since date
        overlay_color: Generated overlay color or gradient
        overlay_opacity: Opacity percentage
    """
    try:
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "onboarding.house": house,
                    "onboarding.personality_phrase": personality_phrase,
                    "onboarding.user_bio": user_bio,
                    "onboarding.bio_status": bio_status,
                    "onboarding.phase": OnboardingPhase.PERSONALIZATION_COMPLETE,
                    "onboarding.suggested_workflows": workflow_ids,
                    "onboarding.account_number": account_number,
                    "onboarding.member_since": member_since,
                    "onboarding.overlay_color": overlay_color,
                    "onboarding.overlay_opacity": overlay_opacity,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        logger.info(f"Saved personalization data for user {user_id}")

    except Exception as e:
        logger.error(f"Error saving personalization data: {e}", exc_info=True)


async def process_post_onboarding_personalization(user_id: str) -> None:
    """
    Main orchestration function for post-onboarding personalization.

    Args:
        user_id: User identifier
    """
    try:
        logger.info(f"Starting post-onboarding personalization for user {user_id}")

        # Emit initial progress
        await emit_progress(
            user_id, "initializing", "✨ Preparing your magical space...", 5
        )

        # Set bio status to processing
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"onboarding.bio_status": BioStatus.PROCESSING}},
        )

        # Get user memories (this triggers email scanning if needed)
        await emit_progress(
            user_id, "discovering", "🔮 Discovering your essence...", 10
        )
        memories_result = await memory_service.get_all_memories(user_id=user_id)
        memories = memories_result.memories

        # Memories retrieved - emit progress
        await emit_progress(
            user_id,
            "analyzing",
            "🧠 Analyzing your patterns...",
            30,
            {"current": len(memories), "total": len(memories)},
        )

        # Run all tasks in parallel where possible
        await emit_progress(
            user_id, "crafting", "🎨 Crafting your unique identity...", 50
        )

        # Get user profession for personality phrase
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        profession = (
            user.get("onboarding", {}).get("preferences", {}).get("profession", "")
            if user
            else ""
        )

        # Parallel tasks
        workflow_task = asyncio.create_task(suggest_workflows_via_rag(user_id, 4))
        personality_task = asyncio.create_task(
            generate_personality_phrase(user_id, memories, profession)
        )
        bio_task = asyncio.create_task(generate_user_bio(user_id, memories))
        metadata_task = asyncio.create_task(get_user_metadata(user_id))

        # Wait for all
        workflow_ids, personality_phrase, bio_result, metadata = await asyncio.gather(
            workflow_task,
            personality_task,
            bio_task,
            metadata_task,
            return_exceptions=False,
        )

        # Unpack bio result
        user_bio, bio_status = bio_result

        # Emit progress after parallel tasks
        await emit_progress(
            user_id, "curating", "🔧 Curating your perfect toolkit...", 75
        )

        # Always save personalization data
        # Even if bio is placeholder, we save it so user sees progress
        # Frontend checks if bio is placeholder via has_personalization flag
        logger.info(
            f"Saving personalization for user {user_id} with bio: {user_bio[:50]}..."
        )

        # Generate profile card design (house, colors)
        card_design = generate_profile_card_design()
        house = card_design["house"]
        overlay_color = card_design["overlay_color"]
        overlay_opacity = card_design["overlay_opacity"]

        # Emit house assignment progress
        await emit_progress(
            user_id, "finalizing", f"🏠 Welcome to {house.title()}!", 90
        )

        # Save to database (including account_number and member_since for persistence)
        await save_personalization_data(
            user_id,
            house,
            personality_phrase,
            user_bio,
            bio_status,
            workflow_ids,
            metadata["account_number"],
            metadata["member_since"],
            overlay_color,
            overlay_opacity,
        )

        # Fetch full workflow objects
        workflows = []
        for wf_id in workflow_ids:
            try:
                # Handle both ObjectId and string IDs (some system workflows might use string IDs)
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
                logger.warning(f"Error fetching workflow {wf_id}: {e}")
                continue

        # Emit house assignment progress
        await emit_progress(
            user_id, "finalizing", f"🏠 Welcome to {house.title()}!", 90
        )

        # Only broadcast completion if bio is actually ready
        # COMPLETED: Bio generated from memories
        # NO_GMAIL: Static bio (user didn't connect Gmail)
        # PROCESSING: Still waiting for email processing - don't broadcast yet
        if bio_status in [BioStatus.COMPLETED, BioStatus.NO_GMAIL]:
            # Broadcast via WebSocket
            # Get user name for complete card data
            user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
            user_name = user_doc.get("name", "User") if user_doc else "User"

            personalization_data = {
                "has_personalization": True,
                "house": house,
                "personality_phrase": personality_phrase,
                "user_bio": user_bio,
                "account_number": metadata["account_number"],
                "member_since": metadata["member_since"],
                "overlay_color": overlay_color,
                "overlay_opacity": overlay_opacity,
                "suggested_workflows": workflows,
                "name": user_name,
                "holo_card_id": user_id,
            }

            # Emit final completion progress
            await emit_progress(user_id, "complete", "🎉 Your GAIA awaits!", 100)

            await websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "onboarding_personalization_complete",
                    "data": personalization_data,
                },
            )

            logger.info(
                f"Post-onboarding personalization complete for user {user_id}: house={house}, phrase={personality_phrase}"
            )
        else:
            logger.info(
                f"Personalization saved but not broadcasting completion yet - bio_status={bio_status}, "
                f"waiting for email processing to complete"
            )

    except Exception as e:
        logger.error(f"Error in post-onboarding personalization: {e}", exc_info=True)


async def seed_initial_user_data(user_id: str) -> None:
    """
    Seed initial data for a new user (onboarding todo, goal with linked todo, and conversation).
    Runs tasks in parallel to minimize background processing time.
    """
    try:
        logger.info(f"Starting parallel data seeding for user {user_id}")

        # Run seeding tasks in parallel
        # Note: Goal seeding automatically creates a comprehensive linked todo
        # The onboarding todo is separate and demonstrates standalone todo features
        await asyncio.gather(
            seed_onboarding_todo(user_id),
            seed_initial_goal(user_id),
            seed_initial_conversation(user_id),
        )

        logger.info(f"Completed parallel data seeding for user {user_id}")

    except Exception as e:
        logger.error(f"Error in seed_initial_user_data for user {user_id}: {e}")
