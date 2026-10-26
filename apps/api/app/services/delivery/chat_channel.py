"""The one place a proactive message goes: where the user is active, else their first chat app.

A message GAIA sends on its own initiative (a workflow result, a fired
reminder, a notification that names no channel) belongs in one place, not on
every platform the user ever linked: fanning it out is the triple-delivery
bug, and the user reads it once anyway. This module owns that single choice:
where the user is active (a chat app or the GAIA app), else the first chat app
in their priority order, provided it is both linked and left enabled in
notification settings, else the GAIA app. Every proactive send path resolves
its target here and nowhere else.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.constants.log_tags import LogTag
from app.constants.notifications import DEFAULT_CHAT_CHANNEL_PRIORITY
from app.db.repositories.users import user_repository
from app.models.chat_channel_models import CHAT_CHANNEL_VALUES
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory
from app.models.platform_models import PlatformLinkEntry
from app.services.analytics_service import capture
from app.services.delivery.presence import active_surface, read_presence
from app.services.platform_link_service import linked_platforms_of
from app.utils.notification.channel_preferences import normalize_channel_preferences
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsChatChannelPriorityUpdated
from shared.py.wide_events import log

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
    capture(
        UserId(user_id),
        SettingsChatChannelPriorityUpdated(first=priority[0], count=len(priority)),
    )


#: Why a platform was chosen: the user wrote there within the active window, or it led their order.
ChatChannelBasis = Literal["recent_activity", "priority"]


@dataclass(frozen=True, slots=True)
class ChatChannel:
    """The platform a proactive message goes to, the account it reaches, and the rule that chose it."""

    source: ConversationSource
    platform_user_id: str
    basis: ChatChannelBasis
    #: The chat app the user is active on but that cannot be messaged (muted or no account id).
    unreachable_active: ConversationSource | None = None


#: Why nothing goes to a chat app: the user is active in the GAIA app, or no chat app is usable.
InAppReason = Literal["active_in_app", "no_chat_app"]


@dataclass(frozen=True, slots=True)
class InApp:
    """A proactive message that stays in the GAIA app, and why."""

    reason: InAppReason
    #: The chat app the user is active on but that cannot be messaged (muted or no account id).
    unreachable_active: ConversationSource | None = None


ProactiveTarget = ChatChannel | InApp


def pick_chat_channel(
    priority: list[str],
    linked: Mapping[str, PlatformLinkEntry],
    preferences: Mapping[str, bool],
    *,
    active: ConversationSource | None,
) -> ChatChannel | None:
    """Return the first platform, active then priority, that is linked, enabled and reachable.

    Pure so the ordering rules are provable without a database. A platform
    the user switched off, or linked without an account id (legacy row), is
    skipped and falls through to the next, even when it is the active one.
    None means no bot platform is usable.
    """
    candidates = [active.value, *priority] if active is not None else priority
    for platform in dict.fromkeys(candidates):
        entry: PlatformLinkEntry | None = linked.get(platform)
        if entry is None or not preferences.get(platform, True):
            continue
        source = ConversationSource.coerce(platform)
        platform_user_id = entry.get("platformUserId")
        if source is None or source not in BOT_CONVERSATION_SOURCES or not platform_user_id:
            continue
        basis: ChatChannelBasis = (
            "recent_activity" if active is not None and platform == active.value else "priority"
        )
        return ChatChannel(source=source, platform_user_id=str(platform_user_id), basis=basis)
    return None


async def _active_surface_of(user_id: str) -> ConversationSource | None:
    """Return the surface the user is active on now, or None when presence cannot be read."""
    try:
        presence = await read_presence(user_id)
    except Exception as e:  # a degraded signal: the message still goes out, by priority
        log.warning(
            f"{LogTag.NOTIFICATION} Chat channel presence read failed; using priority order",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return None
    return active_surface(presence, presence["captured_at"])


async def resolve_proactive_target(user_id: str) -> ProactiveTarget:
    """Return the one place a proactive message for user_id goes; the user and presence reads run together."""
    user, active = await asyncio.gather(user_repository.get(user_id), _active_surface_of(user_id))
    if user is None:
        return InApp(reason="no_chat_app")
    if SourceCategory.from_source(active) is SourceCategory.UI:
        return InApp(reason="active_in_app")
    channel = pick_chat_channel(
        resolve_channel_priority(user.chat_channel_priority),
        linked_platforms_of(user),
        normalize_channel_preferences(user.notification_channel_prefs),
        active=active,
    )
    if channel is None:
        return InApp(reason="no_chat_app", unreachable_active=active)
    if channel.basis == "priority":
        return replace(channel, unreachable_active=active)
    return channel
