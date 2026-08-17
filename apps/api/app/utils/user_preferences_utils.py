"""
User preferences utilities for formatting and processing user data.
Provides functions to format user preferences for agent system prompts.
"""

from collections.abc import Mapping

from app.constants.log_tags import LogTag
from app.utils.json_helpers import dict_bag, text_bag
from shared.py.wide_events import log


def stored_profession(onboarding: Mapping[str, object] | None) -> str:
    """The profession on a stored ``onboarding`` subdoc, or "" when it has none.

    Deliberately NOT ``OnboardingPreferences.model_validate``: those constraints
    (profession ≤ 50 chars, custom_instructions ≤ 500) guard what a user may
    *submit*, and stored rows predate them — the same reason
    ``UserDocument.onboarding`` carries ``SkipValidation``. Every caller wants
    one string for a prompt, and no prompt string is worth aborting a user's
    onboarding pipeline over.
    """
    return text_bag(dict_bag(onboarding or {}, "preferences"), "profession")


def format_response_style_instruction(response_style: str) -> str:
    """Map a user's response-style preference to an agent instruction."""
    style_map = {
        "brief": "Keep responses brief and to the point",
        "detailed": "Provide detailed and comprehensive responses",
        "casual": "Use a casual and friendly tone",
        "professional": "Maintain a professional and formal tone",
    }

    return style_map.get(response_style, response_style)


def format_profession_for_display(profession: str) -> str:
    """Title-case a profession string for display in agent context."""
    if not profession:
        return ""

    # Capitalize and clean up the profession
    return profession.strip().title()


def build_user_context_parts(preferences: dict[str, object]) -> list[str]:
    """Build formatted user-context lines from preferences for the system prompt."""
    log.set(
        operation="build_user_context_parts",
        has_profession=bool(preferences.get("profession")),
        has_response_style=bool(preferences.get("response_style")),
        has_custom_instructions=bool(preferences.get("custom_instructions")),
    )
    parts = []

    try:
        # Add profession context
        if preferences.get("profession"):
            profession = format_profession_for_display(text_bag(preferences, "profession"))
            if profession:
                parts.append(f"User Profession: {profession}")

        # Add communication style context
        if preferences.get("response_style"):
            style_instruction = format_response_style_instruction(
                text_bag(preferences, "response_style")
            )
            parts.append(f"Communication Style: {style_instruction}")

        # Add custom instructions
        if preferences.get("custom_instructions"):
            instructions = text_bag(preferences, "custom_instructions").strip()
            if instructions:
                parts.append(f"Special Instructions: {instructions}")

    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Error building user context parts",
            error=str(e),
            error_type=type(e).__name__,
        )

    return parts


def format_writing_style_for_prompt(
    writing_style: dict[str, object] | None,
) -> str:
    """Format the user's learned writing style into an email-composer prompt block."""
    if not writing_style:
        return ""

    summary = writing_style.get("user_edited_summary") or text_bag(writing_style, "summary")
    raw_example = writing_style.get("example")
    example_text = _example_blocks_to_text(raw_example)

    if not summary:
        return ""

    lines = [
        "Learned Writing Style (match this tone and voice when composing the email):",
        f"  Style: {summary}",
    ]

    if example_text:
        lines.append(f'  Example email in their voice:\n    "{example_text}"')

    return "\n".join(lines)


def _example_blocks_to_text(raw: object) -> str:
    """Render example blocks dict ({greeting, body[], signoff, name}) or legacy string as text."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    sections: list[str] = []
    greeting = text_bag(raw, "greeting").strip()
    if greeting:
        sections.append(greeting)
    for paragraph in raw.get("body", []):
        text = str(paragraph).strip()
        if text:
            sections.append(text)
    signoff_lines: list[str] = []
    signoff = text_bag(raw, "signoff").strip()
    if signoff:
        signoff_lines.append(signoff)
    name = text_bag(raw, "name").strip()
    if name:
        signoff_lines.append(name)
    if signoff_lines:
        sections.append("\n".join(signoff_lines))
    return "\n\n".join(sections)


def format_user_preferences_for_agent(
    preferences: dict[str, object],
    writing_style: dict[str, object] | None = None,
) -> str | None:
    """Format user preferences (and writing style) into a system-prompt block, or None."""
    if not preferences and not writing_style:
        return None

    try:
        parts = build_user_context_parts(preferences) if preferences else []

        style_block = format_writing_style_for_prompt(writing_style)
        if style_block:
            parts.append(f"\n{style_block}")

        if parts:
            return "\n".join(parts)

        return None

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error formatting user preferences for agent",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
