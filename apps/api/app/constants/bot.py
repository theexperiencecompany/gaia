"""Constants for the bot-facing API (/api/v1/bot/*)."""

from enum import StrEnum

from shared.py.bot_identity import (
    DISCORD_CLIENT_ID,
    SLACK_CLIENT_ID,
    TELEGRAM_USERNAME,
    WHATSAPP_NUMBER,
)

# The handles hosted GAIA runs its bots on, read from libs/shared/bot-identity.json
# so the API, the web build and the upstream check share one copy.
GAIA_CLOUD_TELEGRAM_BOT_USERNAME = TELEGRAM_USERNAME
GAIA_CLOUD_WHATSAPP_NUMBER = WHATSAPP_NUMBER
GAIA_CLOUD_DISCORD_CLIENT_ID = DISCORD_CLIENT_ID
GAIA_CLOUD_SLACK_CLIENT_ID = SLACK_CLIENT_ID


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
