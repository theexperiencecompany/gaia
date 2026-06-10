"""
User preferences utilities for formatting and processing user data.
Provides functions to format user preferences for agent system prompts.
"""

from typing import Any

from shared.py.wide_events import log


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


def build_user_context_parts(preferences: dict[str, Any]) -> list[str]:
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
            profession = format_profession_for_display(preferences["profession"])
            if profession:
                parts.append(f"User Profession: {profession}")

        # Add communication style context
        if preferences.get("response_style"):
            style_instruction = format_response_style_instruction(preferences["response_style"])
            parts.append(f"Communication Style: {style_instruction}")

        # Add custom instructions
        if preferences.get("custom_instructions"):
            instructions = preferences["custom_instructions"].strip()
            if instructions:
                parts.append(f"Special Instructions: {instructions}")

    except Exception as e:
        log.warning(f"Error building user context parts: {e!s}")

    return parts


def format_writing_style_for_prompt(
    writing_style: dict[str, Any] | None,
) -> str:
    """Format the user's learned writing style into an email-composer prompt block."""
    if not writing_style:
        return ""

    summary = writing_style.get("user_edited_summary") or writing_style.get("summary", "")
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


def _example_blocks_to_text(raw: Any) -> str:
    """Render example blocks dict ({greeting, body[], signoff, name}) or legacy string as text."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    sections: list[str] = []
    greeting = str(raw.get("greeting", "")).strip()
    if greeting:
        sections.append(greeting)
    for paragraph in raw.get("body", []):
        text = str(paragraph).strip()
        if text:
            sections.append(text)
    signoff_lines: list[str] = []
    signoff = str(raw.get("signoff", "")).strip()
    if signoff:
        signoff_lines.append(signoff)
    name = str(raw.get("name", "")).strip()
    if name:
        signoff_lines.append(name)
    if signoff_lines:
        sections.append("\n".join(signoff_lines))
    return "\n\n".join(sections)


def format_user_preferences_for_agent(
    preferences: dict[str, Any],
    writing_style: dict[str, Any] | None = None,
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
        log.error(f"Error formatting user preferences for agent: {e!s}")
        return None
