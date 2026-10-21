"""Hashed identifiers for wide-event fields that would otherwise carry PII."""

from app.config.settings import settings
from shared.py.logging import hash_log_identifier, text_shape
from shared.py.wide_events import TextShape


def _log_hash_secret() -> str | None:
    return settings.BOT_LOG_HASH_SECRET or settings.GAIA_BOT_API_KEY


def hash_platform_user_id(platform_user_id: str) -> str:
    """Hash a bot platform's user id with the bots' key, so user_hash joins their lines."""
    hashed: str = hash_log_identifier(platform_user_id, _log_hash_secret())
    return hashed


def user_text_shape(text: str) -> TextShape:
    """Shape of a user's query or message for a log field, keyed like every other log hash."""
    return text_shape(text, _log_hash_secret())
