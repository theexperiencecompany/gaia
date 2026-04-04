"""Utilities for generating user profile card data (holo card) and bio."""

import random
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId

from app.agents.llm.client import init_llm
from app.agents.prompts.onboarding_prompts import (
    PERSONALITY_PHRASE_PROMPT,
    USER_BIO_PROMPT,
)
from shared.py.wide_events import log
from app.constants.profession_bios import get_random_bio_for_profession
from app.db.mongodb.collections import users_collection
from app.models.user_models import BioStatus

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


async def get_user_metadata(
    user_id: str, user: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Calculate user metadata for profile card.

    Computes:
    - account_number: Sequential number based on creation date
    - member_since: Formatted date string

    Args:
        user_id: User ID
        user: Pre-fetched user document (avoids redundant DB call)

    Returns:
        Dict with account_number and member_since
    """
    try:
        if user is None:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return {
                "account_number": 1,
                "member_since": datetime.now(timezone.utc).strftime("%b %d, %Y"),
            }

        created_at = user.get("created_at")

        # Derive a stable account number from user_id ObjectId creation timestamp
        # ObjectId encodes creation time — use epoch seconds as a unique, stable number
        oid = ObjectId(user_id)
        account_number = int(oid.generation_time.timestamp()) % 1_000_000

        # Format member since date
        member_since = (
            created_at.strftime("%b %d, %Y")
            if created_at and isinstance(created_at, datetime)
            else datetime.now(timezone.utc).strftime("%b %d, %Y")
        )

        return {"account_number": account_number, "member_since": member_since}

    except Exception:
        # Fallback to defaults on error
        return {
            "account_number": 1,
            "member_since": datetime.now(timezone.utc).strftime("%b %d, %Y"),
        }


async def generate_personality_phrase(
    user_id: str, context_summary: str, profession: str = ""
) -> str:
    """
    Generate a unique 2-3 word personality phrase using LLM.

    Args:
        user_id: User identifier
        context_summary: Structured context (triage summary, writing style, profiles, etc.)
        profession: User's profession (optional)

    Returns:
        Generated personality phrase (e.g., "Digital Alchemist")
    """
    log.set(
        operation="generate_personality_phrase",
        user_id=user_id,
        profession=profession,
    )
    try:
        prompt = PERSONALITY_PHRASE_PROMPT.format(
            profession=profession, memory_summary=context_summary
        )

        llm = init_llm(preferred_provider="gemini").bind(temperature=1.2, top_k=80)
        response = await llm.ainvoke(prompt)

        content = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        phrase = content.strip().strip('"').strip("'")
        log.info(f"Generated personality phrase for user {user_id}: {phrase}")
        return phrase

    except Exception as e:
        log.error(f"Error generating personality phrase: {e}", exc_info=True)
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
    user_id: str,
    context_summary: str,
    user: Optional[Dict[str, Any]] = None,
) -> Tuple[str, BioStatus]:
    """
    Generate user bio paragraph using LLM based on structured context.

    Args:
        user_id: User identifier
        context_summary: Structured context (triage summary, writing style, profiles, etc.)
        user: Pre-fetched user document (avoids redundant DB call)

    Returns:
        Tuple of (bio_text, bio_status)
    """
    log.set(operation="generate_user_bio", user_id=user_id)
    try:
        if user is None:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return ("Welcome to GAIA!", BioStatus.NO_GMAIL)

        name = user.get("name", "User")
        profession = (
            user.get("onboarding", {}).get("preferences", {}).get("profession", "")
        )

        # No context available — use profession-based fallback
        if not context_summary.strip():
            default_bio = get_random_bio_for_profession(name, profession or "other")
            return (default_bio, BioStatus.NO_GMAIL)

        prompt = USER_BIO_PROMPT.format(
            name=name, profession=profession, memory_summary=context_summary[:10000]
        )

        llm = init_llm(preferred_provider="gemini")
        response = await llm.ainvoke(prompt)

        content = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        bio = content.strip()
        log.info(f"Generated bio for user {user_id}")
        return bio, BioStatus.COMPLETED

    except Exception as e:
        log.error(f"Error generating user bio: {e}", exc_info=True)
        return ("Welcome to GAIA!", BioStatus.NO_GMAIL)


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
