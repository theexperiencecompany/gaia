"""Post-onboarding personalization service."""

import random
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config.loggers import app_logger as logger
from app.core.websocket_manager import websocket_manager
from app.db.chromadb import ChromaClient
from app.db.mongodb.collections import users_collection, workflows_collection
from app.models.memory_models import MemoryEntry
from app.services.memory_service import memory_service
from bson import ObjectId
from langchain_google_genai import ChatGoogleGenerativeAI

HOUSES = ["frostpeak", "greenvale", "mistgrove", "bluehaven"]


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
        memories = await memory_service.get_all_memories(user_id=user_id)

        if not memories.memories:
            logger.info(
                f"No memories found for user {user_id}, using default workflows"
            )
            return await _get_default_workflows(limit)

        # Create query from memories
        query_parts = [m.content for m in memories.memories[:10]]
        query_text = " ".join(query_parts)[:1000]

        logger.info(f"Searching workflows with RAG query for user {user_id}")

        # Query ChromaDB workflows collection
        chroma_client = await ChromaClient.get_langchain_client(
            "workflows", create_if_not_exists=True
        )
        results = chroma_client.similarity_search(query_text, k=10)

        # Extract workflow IDs and verify they're public
        workflow_ids = []
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
            except Exception:
                continue

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


async def generate_personality_phrase(user_id: str, memories: List[MemoryEntry]) -> str:
    """
    Generate personality phrase using LLM.

    Args:
        user_id: User identifier
        memories: User's memories

    Returns:
        Generated personality phrase
    """
    profession = ""
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        profession = (
            user.get("onboarding", {}).get("preferences", {}).get("profession", "")
        )

        # Summarize memories
        memory_summary = "\n".join([m.content for m in memories[:10]])

        prompt = f"""Based on this user's profile:
Profession: {profession}
Memories: {memory_summary}

Generate a 2-3 word personality phrase that captures their essence.
Examples: "Curious Developer", "Creative Explorer", "Strategic Thinker", "Data Enthusiast"

Respond with ONLY the phrase, nothing else."""

        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", temperature=0.7)
        response = await llm.ainvoke(prompt)

        # Handle response content properly
        content = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        phrase = content.strip().strip('"').strip("'")
        logger.info(f"Generated personality phrase for user {user_id}: {phrase}")
        return phrase

    except Exception as e:
        logger.error(f"Error generating personality phrase: {e}", exc_info=True)
        # Fallback based on profession
        profession_map = {
            "developer": "Curious Developer",
            "designer": "Creative Designer",
            "engineer": "Innovative Engineer",
            "student": "Eager Learner",
            "manager": "Strategic Leader",
        }
        profession_lower = profession.lower() if profession else ""
        for key, value in profession_map.items():
            if key in profession_lower:
                return value
        return "Curious Adventurer"


async def generate_user_bio(user_id: str, memories: List[MemoryEntry]) -> str:
    """
    Generate user bio paragraph using LLM.

    Args:
        user_id: User identifier
        memories: User's memories

    Returns:
        Generated bio paragraph
    """
    profession = ""
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        name = user.get("name", "User")
        profession = (
            user.get("onboarding", {}).get("preferences", {}).get("profession", "")
        )

        # Check if user has Gmail integration
        integrations = user.get("integrations", [])
        has_gmail = any(i.get("id") == "gmail" for i in integrations)

        # Check if memories exist
        if not memories:
            if has_gmail:
                # Gmail connected but memories still processing
                return "Processing your insights... Please check back in a moment."
            else:
                # Gmail not connected
                return "Connect your Gmail to unlock your personalized GAIA bio"

        memory_summary = "\n".join([m.content for m in memories[:15]])

        prompt = f"""Write a brief, engaging bio paragraph (2-3 sentences) about {name}.

Profession: {profession}
What we know: {memory_summary}

Make it personal and interesting, like an 'About Me' section.
Respond with ONLY the paragraph, no introduction or formatting."""

        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", temperature=0.7)
        response = await llm.ainvoke(prompt)

        # Handle response content properly
        content = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        bio = content.strip()
        logger.info(f"Generated bio for user {user_id}")
        return bio

    except Exception as e:
        logger.error(f"Error generating user bio: {e}", exc_info=True)
        # On error, check if user has Gmail to return appropriate message
        try:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            integrations = user.get("integrations", []) if user else []
            has_gmail = any(i.get("id") == "gmail" for i in integrations)
            if has_gmail:
                return "Processing your insights... Please check back in a moment."
            else:
                return "Connect your Gmail to unlock your personalized GAIA bio"
        except:  # noqa: E722
            return "Connect your Gmail to unlock your personalized GAIA bio"


def assign_random_house() -> str:
    """Randomly select a house."""
    return random.choice(HOUSES)


def generate_random_color() -> tuple[str, int]:
    """
    Generate a random color or gradient for holo card overlay.

    Returns:
        Tuple of (color_string, opacity_percentage)
    """
    # 50% chance of gradient vs solid color
    is_gradient = random.random() > 0.5

    def generate_vibrant_color() -> str:
        """Generate a vibrant color in RGBA format."""
        hue = random.randint(0, 360)
        saturation = random.randint(70, 100)
        lightness = random.randint(40, 70)

        # Convert HSL to RGB
        h = hue / 360
        s = saturation / 100
        l = lightness / 100

        if s == 0:
            r = g = b = l
        else:

            def hue2rgb(p: float, q: float, t: float) -> float:
                if t < 0:
                    t += 1
                if t > 1:
                    t -= 1
                if t < 1 / 6:
                    return p + (q - p) * 6 * t
                if t < 1 / 2:
                    return q
                if t < 2 / 3:
                    return p + (q - p) * (2 / 3 - t) * 6
                return p

            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue2rgb(p, q, h + 1 / 3)
            g = hue2rgb(p, q, h)
            b = hue2rgb(p, q, h - 1 / 3)

        return f"rgba({round(r * 255)}, {round(g * 255)}, {round(b * 255)}, 1)"

    if is_gradient:
        # Generate random gradient
        color1 = generate_vibrant_color()
        color2 = generate_vibrant_color()
        angle = random.randint(0, 360)
        color_string = f"linear-gradient({angle}deg, {color1} 0%, {color2} 100%)"
    else:
        # Generate solid color
        color_string = generate_vibrant_color()

    # Random opacity between 30-80%
    opacity = random.randint(30, 80)

    return color_string, opacity


async def get_user_metadata(user_id: str) -> Dict[str, Any]:
    """
    Calculate user metadata.

    Args:
        user_id: User identifier

    Returns:
        Dict with account_number and member_since
    """
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        created_at = user.get("created_at")

        # Calculate account number
        if created_at:
            count = await users_collection.count_documents(
                {"created_at": {"$lt": created_at}}
            )
            account_number = count + 1
        else:
            account_number = 1

        # Format member since
        member_since = (
            created_at.strftime("%b %d, %Y") if created_at else "Nov 21, 2024"
        )

        return {"account_number": account_number, "member_since": member_since}

    except Exception as e:
        logger.error(f"Error getting user metadata: {e}", exc_info=True)
        return {"account_number": 1, "member_since": "Nov 21, 2024"}


async def save_personalization_data(
    user_id: str,
    house: str,
    personality_phrase: str,
    user_bio: str,
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

        # Get user memories
        memories_result = await memory_service.get_all_memories(user_id=user_id)
        memories = memories_result.memories

        # Run all tasks in parallel where possible
        import asyncio

        # Parallel tasks
        workflow_task = asyncio.create_task(suggest_workflows_via_rag(user_id, 4))
        personality_task = asyncio.create_task(
            generate_personality_phrase(user_id, memories)
        )
        bio_task = asyncio.create_task(generate_user_bio(user_id, memories))
        metadata_task = asyncio.create_task(get_user_metadata(user_id))

        # Wait for all
        workflow_ids, personality_phrase, user_bio, metadata = await asyncio.gather(
            workflow_task,
            personality_task,
            bio_task,
            metadata_task,
            return_exceptions=False,
        )

        # Always save personalization data
        # Even if bio is placeholder, we save it so user sees progress
        # Frontend checks if bio is placeholder via has_personalization flag
        logger.info(
            f"Saving personalization for user {user_id} with bio: {user_bio[:50]}..."
        )

        # Assign random house
        house = assign_random_house()

        # Generate random color/gradient
        overlay_color, overlay_opacity = generate_random_color()

        # Save to database (including account_number and member_since for persistence)
        await save_personalization_data(
            user_id,
            house,
            personality_phrase,
            user_bio,
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

    except Exception as e:
        logger.error(f"Error in post-onboarding personalization: {e}", exc_info=True)
