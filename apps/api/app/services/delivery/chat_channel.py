"""The ONE chat platform a proactive message goes to.

A message GAIA sends on its own initiative (a workflow result, a fired
reminder, a notification that names no channel) belongs on one platform, not
on every platform the user ever linked: fanning it out is the triple-delivery
bug, and the user reads it once anyway. This module owns that single choice:
the first platform in the user's priority order that is both linked and left
enabled in notification settings. Every proactive send path resolves its
platform here and nowhere else; the web app always gets the message as well.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.constants.notifications import DEFAULT_CHAT_CHANNEL_PRIORITY
from app.db.repositories.users import user_repository
from app.models.chat_channel_models import CHAT_CHANNEL_VALUES
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource
from app.models.platform_models import PlatformLinkEntry
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.platform_link_service import linked_platforms_of
from app.utils.notification.channel_preferences import normalize_channel_preferences

#: The chat platforms a priority list may contain — a stored document naming
#: anything else is filtered out here. Includes every bot platform, not just
#: the default order, so a user who puts iMessage first can use it.
VALID_CHAT_PLATFORMS: frozenset[str] = CHAT_CHANNEL_VALUES


def resolve_channel_priority(stored: list[str] | None) -> list[str]:
    """Return the user's stored chat-channel priority, or the default order.

    Unknown entries are dropped; a list that is empty after cleaning falls back
    to the default rather than resolving to "no channel", because an unusable
    stored value is a data problem, not a user preference for silence.
    """
    if isinstance(stored, list):
        cleaned = [p for p in stored if p in VALID_CHAT_PLATFORMS]
        if cleaned:
            return cleaned
    return list(DEFAULT_CHAT_CHANNEL_PRIORITY)


async def get_chat_channel_priority(user_id: str) -> list[str]:
    """Return the order the settings UI shows: the user's own, or the default."""
    user = await user_repository.get(user_id)
    return resolve_channel_priority(user.chat_channel_priority if user else None)


async def set_chat_channel_priority(user_id: str, priority: Sequence[str]) -> None:
    """Store a new order and report the change (platform names only, no content)."""
    await user_repository.set_chat_channel_priority(user_id, list(priority))
    capture_event(
        user_id,
        AnalyticsEvents.SETTINGS_CHAT_CHANNEL_PRIORITY_UPDATED,
        {"first": priority[0], "count": len(priority)},
    )


@dataclass(frozen=True, slots=True)
class ChatChannel:
    """The platform a proactive message goes to, and the account it reaches."""

    source: ConversationSource
    platform_user_id: str


def pick_chat_channel(
    priority: list[str],
    linked: Mapping[str, PlatformLinkEntry],
    preferences: Mapping[str, bool],
) -> ChatChannel | None:
    """Return the first platform in priority that is linked, enabled and reachable.

    Pure so the ordering rules are provable without a database. A platform
    the user switched off, or linked without an account id (legacy row), is
    skipped and falls through to the next. None means no bot platform is usable.
    """
    for platform in priority:
        entry = linked.get(platform)
        if entry is None or not preferences.get(platform, True):
            continue
        source = ConversationSource.coerce(platform)
        platform_user_id = entry.get("platformUserId")
        if source is None or source not in BOT_CONVERSATION_SOURCES or not platform_user_id:
            continue
        return ChatChannel(source=source, platform_user_id=str(platform_user_id))
    return None


async def resolve_chat_channel(user_id: str) -> ChatChannel | None:
    """Return the one chat platform for user_id, from a single read of their document."""
    user = await user_repository.get(user_id)
    if user is None:
        return None
    return pick_chat_channel(
        resolve_channel_priority(user.chat_channel_priority),
        linked_platforms_of(user),
        normalize_channel_preferences(user.notification_channel_prefs),
    )
