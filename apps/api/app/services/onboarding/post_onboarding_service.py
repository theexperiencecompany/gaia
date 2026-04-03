"""Post-onboarding personalization service."""

import asyncio
from datetime import datetime, timezone
from typing import Any, List, Optional

from shared.py.wide_events import log
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import users_collection, workflows_collection
from app.models.memory_models import MemorySearchResult
from app.models.user_models import BioStatus, OnboardingPhase
from app.services.memory_service import memory_service
from app.utils.seeding_utils import (
    seed_initial_conversation,
    seed_onboarding_todo,
)
from bson import ObjectId


async def suggest_workflows_via_rag(
    user_id: str, limit: int = 4, memories: Optional[List] = None
) -> List[str]:
    """
    Use RAG to find similar workflows based on user memories.

    Args:
        user_id: User identifier
        limit: Number of workflows to suggest
        memories: Pre-fetched memories list. If None, fetches from memory_service.

    Returns:
        List of workflow IDs
    """
    try:
        # Get user memories (skip if pre-fetched)
        if memories is None:
            memories_result: MemorySearchResult = await memory_service.get_all_memories(
                user_id=user_id
            )
            memories = memories_result.memories

        if not memories:
            log.info(f"No memories found for user {user_id}, using default workflows")
            return await _get_default_workflows(limit)

        # Create query from memories
        query_parts = [m.content for m in memories]
        query_text = " ".join(query_parts)

        log.info(f"Searching workflows with RAG query for user {user_id}")

        # Query ChromaDB workflows collection
        chroma_client = await ChromaClient.get_langchain_client(
            "workflows", create_if_not_exists=True
        )
        results = chroma_client.similarity_search(query_text, k=10)

        # Batch verify all workflow IDs in a single query
        candidate_ids = []
        raw_id_map: dict[Any, str] = {}
        for doc in results:
            wf_id = doc.metadata.get("workflow_id")
            if not wf_id:
                continue
            try:
                query_id = ObjectId(wf_id) if ObjectId.is_valid(wf_id) else wf_id
                candidate_ids.append(query_id)
                raw_id_map[query_id] = str(wf_id)
            except Exception:
                continue  # nosec B112

        workflow_ids: List[str] = []
        if candidate_ids:
            cursor = workflows_collection.find(
                {"_id": {"$in": candidate_ids}, "is_public": True},
                {"_id": 1},
            )
            async for wf_doc in cursor:
                wf_str = raw_id_map.get(wf_doc["_id"], str(wf_doc["_id"]))
                workflow_ids.append(wf_str)
                if len(workflow_ids) >= limit:
                    break

        # Fill with defaults if needed
        if len(workflow_ids) < limit:
            default_wfs = await _get_default_workflows(limit - len(workflow_ids))
            workflow_ids.extend(default_wfs)

        return workflow_ids[:limit]

    except Exception as e:
        log.error(f"Error in workflow RAG: {e}", exc_info=True)
        return await _get_default_workflows(limit)


async def _get_default_workflows(limit: int = 4) -> List[str]:
    """Get default public workflows as fallback."""
    try:
        workflows = await workflows_collection.find(
            {"is_public": True}, limit=limit
        ).to_list(length=limit)
        return [str(wf["_id"]) for wf in workflows]
    except Exception as e:
        log.error(f"Error fetching default workflows: {e}")
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
        log.info(f"Saved personalization data for user {user_id}")

    except Exception as e:
        log.error(f"Error saving personalization data: {e}", exc_info=True)


async def seed_initial_user_data(user_id: str) -> None:
    """
    Seed initial data for a new user (onboarding todo and conversation).
    Runs tasks in parallel to minimize background processing time.
    """
    try:
        log.info(f"Starting parallel data seeding for user {user_id}")

        # Run seeding tasks in parallel
        await asyncio.gather(
            seed_onboarding_todo(user_id),
            seed_initial_conversation(user_id),
        )

        log.info(f"Completed parallel data seeding for user {user_id}")

    except Exception as e:
        log.error(f"Error in seed_initial_user_data for user {user_id}: {e}")
