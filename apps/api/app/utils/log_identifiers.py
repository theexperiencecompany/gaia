"""Hashed identifiers for wide-event fields that would otherwise carry PII."""

from app.config.settings import settings
from shared.py.logging import hash_log_identifier


def hash_platform_user_id(platform_user_id: str) -> str:
    """Hash a bot platform's user id with the bots' key, so user_hash joins their lines."""
    hashed: str = hash_log_identifier(
        platform_user_id, settings.BOT_LOG_HASH_SECRET or settings.GAIA_BOT_API_KEY
    )
    return hashed
