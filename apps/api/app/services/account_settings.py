"""Account settings mutations — the real logic behind the account tools.

Each function validates typed input, applies through the owning repository or
service, and returns an agent-facing confirmation string. Invalid input raises
``AppError``; nothing here writes to JuiceFS (the projection refresh is the
tool wrapper's job).
"""

from app.db.repositories.users import user_repository
from app.models.user_models import OnboardingPreferences, UserUpdate
from app.services.voice_service import list_voices, set_user_voice
from app.utils.errors import AppError
from app.utils.timezone import is_valid_timezone

MAX_CUSTOM_INSTRUCTIONS_CHARS = 500

CHANNEL_FLAGS = ("telegram", "discord", "whatsapp", "slack", "email")


async def set_notification_channels(
    user_id: str,
    *,
    telegram: bool | None = None,
    discord: bool | None = None,
    whatsapp: bool | None = None,
    slack: bool | None = None,
    email: bool | None = None,
) -> str:
    """Set the given notification channel flags; unspecified channels untouched."""
    given = {
        channel: value
        for channel, value in [
            ("telegram", telegram),
            ("discord", discord),
            ("whatsapp", whatsapp),
            ("slack", slack),
            ("email", email),
        ]
        if value is not None
    }
    if not given:
        raise AppError(
            message="No channels were specified",
            why="the tool call did not include any channel flag",
            fix="Pass at least one channel, e.g. email=False",
            status_code=400,
        )
    await user_repository.set_channel_preferences(user_id, **given)
    changed = ", ".join(f"{c}={'on' if v else 'off'}" for c, v in given.items())
    return f"Notification settings updated ({changed})."


async def set_preferences(
    user_id: str,
    *,
    response_style: str | None = None,
    timezone: str | None = None,
) -> str:
    """Set response style (onboarding.preferences) and/or home timezone."""
    if response_style is None and timezone is None:
        raise AppError(
            message="Nothing to update",
            why="neither response_style nor timezone was provided",
            fix="Pass response_style (brief/detailed/casual/professional or a custom label) "
            "and/or an IANA timezone",
            status_code=400,
        )

    updated: list[str] = []
    if response_style is not None:
        style = response_style.strip()
        if not style:
            raise AppError(
                message="Response style cannot be empty",
                fix="Use one of brief, detailed, casual, professional — or pass a custom label",
                status_code=400,
            )
    if timezone is not None:
        tz = timezone.strip() if timezone else ""
        if not is_valid_timezone(tz):
            raise AppError(
                message=f"Invalid timezone '{tz}'",
                fix="Use an IANA identifier like 'America/New_York', 'Asia/Kolkata' or 'UTC'",
                status_code=400,
            )

    # Everything validated — only now does any write happen, so a bad
    # timezone can't ride in behind a good style (or vice versa).
    if response_style is not None:
        result = await user_repository.update_onboarding_preferences(
            user_id,
            # PATCH-style: fields_set holds only response_style, so the
            # repository writes just that dotted path.
            OnboardingPreferences.model_construct(response_style=response_style.strip()),
        )
        if result is None:
            raise AppError(message="User not found", status_code=404)
        updated.append(f"response style set to '{response_style.strip()}'")

    if timezone is not None:
        tz = timezone.strip()
        user = await user_repository.update(user_id, UserUpdate(timezone=tz))
        if user is None:
            raise AppError(message="User not found", status_code=404)
        updated.append(f"timezone set to {tz}")

    return f"Preferences updated: {'; '.join(updated)}."


async def set_custom_instructions(user_id: str, *, instructions: str) -> str:
    """Replace the standing custom instructions; an empty string clears them."""
    value = instructions.strip() or None
    if value is not None and len(value) > MAX_CUSTOM_INSTRUCTIONS_CHARS:
        raise AppError(
            message=f"Custom instructions must be {MAX_CUSTOM_INSTRUCTIONS_CHARS} characters or less",
            fix="Shorten the instructions and try again",
            status_code=400,
        )
    # model_construct (not __init__): builds a PATCH-style update whose
    # fields_set holds exactly what was passed, so the repository writes only
    # this one dotted path and never clobbers sibling preference fields.
    result = await user_repository.update_onboarding_preferences(
        user_id, OnboardingPreferences.model_construct(custom_instructions=value)
    )
    if result is None:
        raise AppError(message="User not found", status_code=404)
    return "Custom instructions cleared." if value is None else "Custom instructions updated."


async def select_voice(user_id: str, *, voice: str) -> str:
    """Select a voice by catalog name (case-insensitive) or ElevenLabs id."""
    query = voice.strip()
    catalog = await list_voices(user_id)
    match = next(
        (v for v in catalog.voices if v.voice_id == query or v.name.lower() == query.lower()),
        None,
    )
    if match is None:
        names = ", ".join(v.name for v in catalog.voices[:15])
        raise AppError(
            message=f"Unknown voice '{voice}'",
            why="it is not in this user's voice catalog",
            fix=f"Pick one from the catalog, e.g.: {names}",
            status_code=404,
        )
    await set_user_voice(user_id, match.voice_id)
    return f"Voice switched to {match.name}."


__all__ = [
    "select_voice",
    "set_custom_instructions",
    "set_notification_channels",
    "set_preferences",
]
