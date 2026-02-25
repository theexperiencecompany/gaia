from typing import Any, Mapping

from app.constants.notifications import DEFAULT_CHANNEL_PREFERENCES
from app.db.mongodb.collections import users_collection
from bson import ObjectId


def normalize_channel_preferences(prefs: Mapping[str, Any] | None) -> dict[str, bool]:
    """Apply default channel settings and coerce values to booleans."""
    source = prefs or {}
    return {
        channel: bool(source.get(channel, default_enabled))
        for channel, default_enabled in DEFAULT_CHANNEL_PREFERENCES.items()
    }


async def fetch_channel_preferences(user_id: str) -> dict[str, bool]:
    """Fetch and normalize per-user channel preference flags from MongoDB."""
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    raw_prefs = (user or {}).get("notification_channel_prefs")
    return normalize_channel_preferences(raw_prefs)
