from collections.abc import Mapping
from typing import Any

from app.constants.notifications import DEFAULT_CHANNEL_PREFERENCES
from app.db.repositories.users import user_repository


def normalize_channel_preferences(prefs: Mapping[str, Any] | None) -> dict[str, bool]:
    """Apply default channel settings and coerce values to booleans."""
    source = prefs or {}
    return {
        channel: bool(source.get(channel, default_enabled))
        for channel, default_enabled in DEFAULT_CHANNEL_PREFERENCES.items()
    }


async def fetch_channel_preferences(user_id: str) -> dict[str, bool]:
    """Fetch and normalize per-user channel preference flags from MongoDB."""
    user = await user_repository.get(user_id)
    raw_prefs = user.notification_channel_prefs if user else None
    return normalize_channel_preferences(raw_prefs)
