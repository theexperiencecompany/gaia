"""
User preferences utilities for formatting and processing user data.
Provides functions to format user preferences for agent system prompts.
"""

from typing import Optional, Dict, Any
from app.config.loggers import app_logger as logger


def format_response_style_instruction(response_style: str) -> str:
    """
    Format response style into instruction for agent.

    Args:
        response_style: User's preferred response style

    Returns:
        Formatted instruction string for the agent
    """
    style_map = {
        "brief": "Keep responses brief and to the point",
        "detailed": "Provide detailed and comprehensive responses",
        "casual": "Use a casual and friendly tone",
        "professional": "Maintain a professional and formal tone",
    }

    return style_map.get(response_style, response_style)


def format_profession_for_display(profession: str) -> str:
    """
    Format profession for display in agent context.

    Args:
        profession: User's profession

    Returns:
        Formatted profession string
    """
    if not profession:
        return ""

    # Capitalize and clean up the profession
    return profession.strip().title()


def build_user_context_parts(preferences: Dict[str, Any]) -> list[str]:
    """
    Build user context parts from preferences for agent system prompt.

    Args:
        preferences: Dictionary of user preferences

    Returns:
        List of formatted context strings
    """
    parts = []

    try:
        # Add profession context
        if preferences.get("profession"):
            profession = format_profession_for_display(preferences["profession"])
            if profession:
                parts.append(f"User Profession: {profession}")

        # Add communication style context
        if preferences.get("response_style"):
            style_instruction = format_response_style_instruction(
                preferences["response_style"]
            )
            parts.append(f"Communication Style: {style_instruction}")

        # Add custom instructions
        if preferences.get("custom_instructions"):
            instructions = preferences["custom_instructions"].strip()
            if instructions:
                parts.append(f"Special Instructions: {instructions}")

    except Exception as e:
        logger.warning(f"Error building user context parts: {str(e)}")

    return parts


def format_user_preferences_for_agent(preferences: Dict[str, Any]) -> Optional[str]:
    """
    Format user preferences into a string suitable for agent system prompt.

    Args:
        preferences: Dictionary of user preferences from onboarding

    Returns:
        Formatted string of user preferences or None if no valid preferences
    """
    if not preferences:
        return None

    try:
        parts = build_user_context_parts(preferences)

        if parts:
            return "\n".join(parts)

        return None

    except Exception as e:
        logger.error(f"Error formatting user preferences for agent: {str(e)}")
        return None


def validate_user_preferences(preferences: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and sanitize user preferences.

    Args:
        preferences: Raw user preferences dictionary

    Returns:
        Validated and sanitized preferences dictionary
    """
    validated = {}

    try:
        # Validate profession
        if preferences.get("profession"):
            profession = preferences["profession"].strip()
            if profession and len(profession) <= 50:
                validated["profession"] = profession

        # Validate response style
        if preferences.get("response_style"):
            response_style = preferences["response_style"].strip()
            if response_style:
                validated["response_style"] = response_style

        # Validate custom instructions
        if preferences.get("custom_instructions"):
            instructions = preferences["custom_instructions"].strip()
            if instructions and len(instructions) <= 500:
                validated["custom_instructions"] = instructions

    except Exception as e:
        logger.warning(f"Error validating user preferences: {str(e)}")

    return validated


def get_user_preference_summary(preferences: Dict[str, Any]) -> str:
    """
    Get a brief summary of user preferences for logging/debugging.

    Args:
        preferences: User preferences dictionary

    Returns:
        Brief summary string
    """
    if not preferences:
        return "No preferences set"

    summary_parts = []

    if preferences.get("profession"):
        summary_parts.append(f"Profession: {preferences['profession'][:20]}...")

    if preferences.get("response_style"):
        summary_parts.append(f"Style: {preferences['response_style']}")

    if preferences.get("custom_instructions"):
        summary_parts.append("Has custom instructions")

    return " | ".join(summary_parts) if summary_parts else "No preferences set"
