"""Briefing delivery-channel resolution.

A briefing goes to a SINGLE chat platform, not every linked one: in-app always,
plus the first chat platform in the user's priority order that is both linked and
enabled, plus email when enabled and the user has an address. Passing this as the
explicit channel list turns off the orchestrator's all-platforms auto-inject (the
triple-delivery bug); generic notifications keep the auto-inject fan-out.
"""

from bson import ObjectId

from app.constants.notifications import (
    CHANNEL_TYPE_EMAIL,
    CHANNEL_TYPE_INAPP,
    DEFAULT_CHAT_CHANNEL_PRIORITY,
)
from app.db.mongodb.collections import users_collection
from app.services.platform_link_service import PlatformLinkService
from app.utils.notification.channel_preferences import fetch_channel_preferences

# The four chat platforms a priority list may contain — the same set the priority
# endpoint validates against, so a stale doc can never route a brief elsewhere.
VALID_CHAT_PLATFORMS: frozenset[str] = frozenset(DEFAULT_CHAT_CHANNEL_PRIORITY)


def resolve_channel_priority(user: dict) -> list[str]:
    """The user's stored briefing chat-channel priority, or the default order.

    Drops any stored entry that is not one of the four chat platforms so a
    hand-edited or legacy document can never route a brief to an unknown channel.
    """
    stored = user.get("briefing_channel_priority")
    if isinstance(stored, list):
        cleaned = [p for p in stored if p in VALID_CHAT_PLATFORMS]
        if cleaned:
            return cleaned
    return list(DEFAULT_CHAT_CHANNEL_PRIORITY)


async def resolve_briefing_channels(user_id: str, user: dict) -> list[str]:
    """The explicit channels one briefing delivers to.

    Always in-app; plus the first chat platform in the user's priority order that
    is both linked and preference-enabled; plus email when enabled and the user
    has an address on file.
    """
    channels = [CHANNEL_TYPE_INAPP]

    prefs = await fetch_channel_preferences(user_id)
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    for platform in resolve_channel_priority(user):
        if platform in linked and prefs.get(platform, True):
            channels.append(platform)
            break

    if prefs.get(CHANNEL_TYPE_EMAIL, True) and (user.get("email") or "").strip():
        channels.append(CHANNEL_TYPE_EMAIL)

    return channels


async def get_channel_priority(user_id: str) -> list[str]:
    """The stored (or default) briefing chat-channel priority for a user."""
    user = await users_collection.find_one(
        {"_id": ObjectId(user_id)}, {"briefing_channel_priority": 1}
    )
    return resolve_channel_priority(user or {})


async def set_channel_priority(user_id: str, priority: list[str]) -> None:
    """Persist a user's briefing chat-channel priority order."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id)}, {"$set": {"briefing_channel_priority": priority}}
    )
