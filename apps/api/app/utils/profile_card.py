"""Utilities for generating user profile card data (holo card) and bio."""

from datetime import UTC, datetime
import random
from typing import Any

from bson import ObjectId
from langchain_core.messages import HumanMessage

from app.agents.llm.client import init_llm
from app.agents.prompts.onboarding_prompts import HOLO_CARD_PROMPT
from app.constants.profession_bios import get_random_bio_for_profession
from app.db.mongodb.collections import users_collection
from app.models.onboarding_models import HoloCardLLMOutput
from app.models.user_models import BioStatus
from shared.py.wide_events import log

# Available houses for user assignment
HOUSES = ["frostpeak", "greenvale", "mistgrove", "bluehaven"]


def assign_random_house() -> str:
    """
    Randomly select a house for the user.

    Returns:
        House name (lowercase)
    """
    return random.choice(HOUSES)  # nosec B311


def generate_random_color() -> tuple[str, int]:
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

    def _hsl_to_rgb(h: float, s: float, lightness_val: float) -> tuple[int, int, int]:
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


async def get_user_metadata(user_id: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if user is None:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return {
                "account_number": 1,
                "member_since": datetime.now(UTC).strftime("%b %d, %Y"),
            }

        created_at = user.get("created_at")

        # Stable account number derived from the ObjectId creation timestamp.
        oid = ObjectId(user_id)
        account_number = int(oid.generation_time.timestamp()) % 1_000_000

        # Format member since date
        member_since = (
            created_at.strftime("%b %d, %Y")
            if created_at and isinstance(created_at, datetime)
            else datetime.now(UTC).strftime("%b %d, %Y")
        )

        return {"account_number": account_number, "member_since": member_since}

    except Exception:
        # Fallback to defaults on error
        return {
            "account_number": 1,
            "member_since": datetime.now(UTC).strftime("%b %d, %Y"),
        }


def _phrase_fallback(profession: str) -> str:
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


async def generate_holo_card_content(
    user_id: str,
    context_summary: str,
    user: dict[str, Any] | None = None,
) -> tuple[str, str, BioStatus]:
    """Generate the holo card's personality phrase and bio in one structured LLM call."""
    log.set(operation="generate_holo_card_content", user_id=user_id)

    if user is None:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
    name = (user or {}).get("name", "User")
    profession = (user or {}).get("onboarding", {}).get("preferences", {}).get("profession", "")

    if not context_summary.strip():
        default_bio = get_random_bio_for_profession(name, profession or "other")
        return _phrase_fallback(profession), default_bio, BioStatus.NO_GMAIL

    try:
        prompt = HOLO_CARD_PROMPT.format(
            name=name,
            profession=profession or "",
            context_summary=context_summary[:10000],
        )
        llm = init_llm(preferred_provider="gemini").bind(temperature=1.0)
        structured_llm = llm.with_structured_output(HoloCardLLMOutput)
        result: HoloCardLLMOutput = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        phrase = result.personality_phrase.strip().strip('"').strip("'")
        bio = result.user_bio.strip()
        log.info(f"Generated holo card content for user {user_id}: phrase='{phrase}'")
        return phrase, bio, BioStatus.COMPLETED

    except Exception as e:
        log.error(f"Error generating holo card content: {e}", exc_info=True)
        return (
            _phrase_fallback(profession),
            get_random_bio_for_profession(name, profession or "other"),
            BioStatus.NO_GMAIL,
        )


def generate_profile_card_design() -> dict[str, Any]:
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
