"""Utilities for generating user profile card data (holo card) and bio."""

import random
from datetime import datetime
from typing import Any, Dict, List, Tuple

from bson import ObjectId

from app.agents.llm.client import init_llm
from app.agents.prompts.onboarding_prompts import (
    PERSONALITY_PHRASE_PROMPT,
    USER_BIO_PROMPT,
)
from app.config.loggers import app_logger as logger
from app.constants.profession_bios import get_random_bio_for_profession
from app.db.mongodb.collections import users_collection
from app.models.memory_models import MemoryEntry
from app.models.user_models import BioStatus
from app.services.composio.composio_service import get_composio_service

# Available houses for user assignment
HOUSES = ["frostpeak", "greenvale", "mistgrove", "bluehaven"]


def assign_random_house() -> str:
    """
    Randomly select a house for the user.

    Returns:
        House name (lowercase)
    """
    return random.choice(HOUSES)  # nosec B311


def generate_random_color() -> Tuple[str, int]:
    """
    Generate a random vibrant color or gradient for holo card overlay.

    50% chance of gradient vs solid color.
    Colors are HSL-based for better vibrancy control.

    Returns:
        Tuple of (color_string, opacity_percentage)
        - color_string: CSS color (rgba) or linear-gradient
        - opacity_percentage: 30-80%
    """
    is_gradient = random.random() > 0.5  # nosec B311

    def _hsl_to_rgb(h: float, s: float, lightness_val: float) -> Tuple[int, int, int]:
        """Convert HSL to RGB values."""
        if s == 0:
            r = g = b = lightness_val
        else:

            def hue_to_rgb(p: float, q: float, t: float) -> float:
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

            q = (
                lightness_val * (1 + s)
                if lightness_val < 0.5
                else lightness_val + s - lightness_val * s
            )
            p = 2 * lightness_val - q
            r = hue_to_rgb(p, q, h + 1 / 3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1 / 3)

        return round(r * 255), round(g * 255), round(b * 255)

    def _generate_vibrant_color() -> str:
        """Generate a single vibrant color in RGBA format."""
        hue = random.randint(0, 360) / 360  # nosec B311
        saturation = random.randint(70, 100) / 100  # nosec B311
        lightness = random.randint(40, 70) / 100  # nosec B311

        r, g, b = _hsl_to_rgb(hue, saturation, lightness)
        return f"rgba({r}, {g}, {b}, 1)"

    if is_gradient:
        # Generate gradient with two colors
        color1 = _generate_vibrant_color()
        color2 = _generate_vibrant_color()
        angle = random.randint(0, 360)  # nosec B311
        color_string = f"linear-gradient({angle}deg, {color1} 0%, {color2} 100%)"
    else:
        # Single solid color
        color_string = _generate_vibrant_color()

    # Random opacity between 30-80%
    opacity = random.randint(30, 80)  # nosec B311

    return color_string, opacity


async def get_user_metadata(user_id: str) -> Dict[str, Any]:
    """
    Calculate user metadata for profile card.

    Computes:
    - account_number: Sequential number based on creation date
    - member_since: Formatted date string

    Args:
        user_id: User ID

    Returns:
        Dict with account_number and member_since
    """
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return {"account_number": 1, "member_since": "Nov 21, 2024"}

        created_at = user.get("created_at")

        # Calculate account number (sequential based on creation)
        if created_at and isinstance(created_at, datetime):
            count = await users_collection.count_documents(
                {"created_at": {"$lt": created_at}}
            )
            account_number = count + 1
        else:
            account_number = 1

        # Format member since date
        member_since = (
            created_at.strftime("%b %d, %Y")
            if created_at and isinstance(created_at, datetime)
            else "Nov 21, 2024"
        )

        return {"account_number": account_number, "member_since": member_since}

    except Exception:
        # Fallback to defaults on error
        return {"account_number": 1, "member_since": "Nov 21, 2024"}


async def generate_personality_phrase(
    user_id: str, memories: List[MemoryEntry], profession: str = ""
) -> str:
    """
    Generate a unique 2-3 word personality phrase using LLM.

    Args:
        user_id: User identifier
        memories: User's memories for context
        profession: User's profession (optional)

    Returns:
        Generated personality phrase (e.g., "Digital Alchemist")
    """
    try:
        # Summarize memories
        memory_summary = "\n".join([m.content for m in memories])

        prompt = PERSONALITY_PHRASE_PROMPT.format(
            profession=profession, memory_summary=memory_summary
        )

        llm = init_llm(preferred_provider="gemini").bind(temperature=1.0, top_k=50)
        response = await llm.ainvoke(prompt)

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


async def generate_user_bio(
    user_id: str, memories: List[MemoryEntry]
) -> Tuple[str, BioStatus]:
    """
    Generate user bio paragraph using LLM based on memories.

    Flow:
    - If no memories + Gmail + not processed → PROCESSING (waiting)
    - If no memories + Gmail + processed → COMPLETED (fallback bio)
    - If no memories + no Gmail → NO_GMAIL (profession bio)
    - If memories exist → COMPLETED (LLM-generated bio)

    Args:
        user_id: User identifier
        memories: User's memories

    Returns:
        Tuple of (bio_text, bio_status)
    """
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return ("Welcome to GAIA!", BioStatus.NO_GMAIL)

        name = user.get("name", "User")
        profession = (
            user.get("onboarding", {}).get("preferences", {}).get("profession", "")
        )

        # Check Gmail connection status
        composio_service = get_composio_service()
        connection_status = await composio_service.check_connection_status(
            ["gmail"], str(user_id)
        )
        has_gmail = connection_status.get("gmail", False)

        # Handle case: No memories
        if not memories:
            email_processed = user.get("email_memory_processed", False)

            if has_gmail and email_processed:
                # Emails processed but no memories - use fallback
                logger.warning(
                    f"Email processed but no memories for user {user_id}. Using fallback bio."
                )
                default_bio = get_random_bio_for_profession(name, profession or "other")
                return (default_bio, BioStatus.COMPLETED)
            elif has_gmail:
                # Gmail connected but emails not processed yet
                return (
                    "Processing your insights... Please check back in a moment.",
                    BioStatus.PROCESSING,
                )
            else:
                # No Gmail - use profession-based bio
                default_bio = get_random_bio_for_profession(name, profession or "other")
                return (default_bio, BioStatus.NO_GMAIL)

        # Generate bio from memories using LLM
        memory_summary = "\n".join([m.content for m in memories[:15]])

        prompt = USER_BIO_PROMPT.format(
            name=name, profession=profession, memory_summary=memory_summary
        )

        llm = init_llm(preferred_provider="gemini")
        response = await llm.ainvoke(prompt)

        content = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        bio = content.strip()
        logger.info(f"Generated bio for user {user_id}")
        return bio, BioStatus.COMPLETED

    except Exception as e:
        logger.error(f"Error generating user bio: {e}", exc_info=True)

        # Fallback on error
        try:
            composio_service = get_composio_service()
            connection_status = await composio_service.check_connection_status(
                ["gmail"], str(user_id)
            )
            has_gmail = connection_status.get("gmail", False)

            if has_gmail:
                return (
                    "Processing your insights... Please check back in a moment.",
                    BioStatus.PROCESSING,
                )
            else:
                return (
                    "Connect your Gmail to unlock your personalized GAIA bio",
                    BioStatus.NO_GMAIL,
                )
        except:  # noqa: E722
            return (
                "Connect your Gmail to unlock your personalized GAIA bio",
                BioStatus.NO_GMAIL,
            )


def generate_profile_card_design() -> Dict[str, Any]:
    """
    Generate complete profile card design (house, colors).

    Returns:
        Dict with house, overlay_color, overlay_opacity
    """
    house = assign_random_house()
    overlay_color, overlay_opacity = generate_random_color()

    return {
        "house": house,
        "overlay_color": overlay_color,
        "overlay_opacity": overlay_opacity,
    }
