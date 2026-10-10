from collections.abc import Mapping
from typing import TypedDict

from pydantic import BaseModel, ConfigDict

from app.constants.log_tags import LogTag
from app.models.onboarding_models import WritingStyleExampleBlocks
from app.models.user_models import OnboardingSubdocument
from shared.py.wide_events import log


class PreferencePromptFields(BaseModel):
    """The OnboardingPreferences keys the system prompt reads, off a run's configurable.

    A lenient projection rather than OnboardingPreferences itself: that model
    re-judges a stored value against today's input rules on every validation,
    and a prompt must render what the user has, not refuse it.
    """

    model_config = ConfigDict(extra="ignore")

    profession: str | None = None
    response_style: str | None = None
    custom_instructions: str | None = None


class WritingStylePromptFields(BaseModel):
    """The stored ``onboarding.writing_style`` keys the email composer reads.

    ``example`` is the pipeline's block structure on current rows and a plain
    string on rows written before it existed.
    """

    model_config = ConfigDict(extra="ignore")

    summary: str | None = None
    user_edited_summary: str | None = None
    example: WritingStyleExampleBlocks | str | None = None


class OnboardingPreferencesRecord(TypedDict, total=False):
    """The OnboardingPreferences dump onboarding_preferences puts in a run's configurable.

    Only the fields the user set are present. needs and other_need stay object: the
    checkpointed bag is not re-validated, so their readers narrow them.
    """

    profession: str
    needs: object
    response_style: str
    other_need: object
    custom_instructions: str


def onboarding_preferences(
    onboarding: OnboardingSubdocument | None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Return the (preferences, writing_style) pair off a user's onboarding data.

    Pulled out once so reading doesn't drift between call sites. Returns
    mappings because both travel in the JSON-checkpointed run configurable.
    """
    if not onboarding:
        return None, None
    # Only what was stored: the typed model would otherwise add every
    # unset field as None, and the prompt formatters key off presence.
    preferences = (
        onboarding.preferences.model_dump(exclude_none=True) if onboarding.preferences else None
    )
    return preferences, onboarding.writing_style


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


def build_user_context_parts(preferences: Mapping[str, object]) -> list[str]:
    """Build formatted user-context lines from preferences for the system prompt."""
    fields = PreferencePromptFields.model_validate(preferences)
    log.set(
        operation="build_user_context_parts",
        has_profession=bool(fields.profession),
        has_response_style=bool(fields.response_style),
        has_custom_instructions=bool(fields.custom_instructions),
    )
    parts = []

    try:
        # Add profession context
        if fields.profession:
            profession = format_profession_for_display(fields.profession)
            if profession:
                parts.append(f"User Profession: {profession}")

        # Add communication style context
        if fields.response_style:
            style_instruction = format_response_style_instruction(fields.response_style)
            parts.append(f"Communication Style: {style_instruction}")

        # Add custom instructions
        if fields.custom_instructions:
            instructions = fields.custom_instructions.strip()
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
    writing_style: Mapping[str, object] | None,
) -> str:
    """Format the user's learned writing style into an email-composer prompt block."""
    if not writing_style:
        return ""

    style = WritingStylePromptFields.model_validate(writing_style)
    summary = style.user_edited_summary or style.summary or ""
    example_text = _example_blocks_to_text(style.example)

    if not summary:
        return ""

    lines = [
        "Learned Writing Style (match this tone and voice when composing the email):",
        f"  Style: {summary}",
    ]

    if example_text:
        lines.append(f'  Example email in their voice:\n    "{example_text}"')

    return "\n".join(lines)


def _example_blocks_to_text(raw: WritingStyleExampleBlocks | str | None) -> str:
    """Render example blocks ({greeting, body[], signoff, name}) or a legacy string as text."""
    if isinstance(raw, str):
        return raw
    if raw is None:
        return ""
    sections: list[str] = []
    greeting = raw.greeting.strip()
    if greeting:
        sections.append(greeting)
    for paragraph in raw.body:
        text = paragraph.strip()
        if text:
            sections.append(text)
    signoff_lines: list[str] = []
    signoff = raw.signoff.strip()
    if signoff:
        signoff_lines.append(signoff)
    name = raw.name.strip()
    if name:
        signoff_lines.append(name)
    if signoff_lines:
        sections.append("\n".join(signoff_lines))
    return "\n\n".join(sections)


def format_user_preferences_for_agent(
    preferences: Mapping[str, object] | None,
    writing_style: Mapping[str, object] | None = None,
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
