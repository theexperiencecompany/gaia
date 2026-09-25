"""Constants for the bot-facing API (/api/v1/bot/*)."""

from enum import StrEnum


class BotRequestFailure(StrEnum):
    """Why a bot request was refused or failed; the wide event's reason field."""

    BOT_API_KEY_INVALID = "bot_api_key_invalid"
    ACCOUNT_NOT_LINKED = "account_not_linked"
    INVALID_PLATFORM = "invalid_platform"
    MISSING_PLATFORM_HEADERS = "missing_platform_headers"
    AUDIO_TOO_LARGE = "audio_too_large"
    UNSUPPORTED_AUDIO_FORMAT = "unsupported_audio_format"
    TRANSCRIPTION_FAILED = "transcription_failed"
    SUBSCRIPTION_REQUIRED = "subscription_required"
