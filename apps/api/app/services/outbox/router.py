"""Where a message goes: the one place that decides it, for every proactive send.

Record is not alert. A result is recorded where it belongs (its owner conversation)
whatever happens to the alert, and the alert goes to exactly one place: where the user
is active now (a chat app or the GAIA app), else, for an answer, back to the direct
message that asked, else the first chat app in their priority order that is linked and
left enabled in notification settings, else the GAIA app. A chat app the user asked to be
told on outranks all of that, when it is linked and enabled.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from app.constants.log_tags import LogTag
from app.db.repositories.bot_sessions import bot_session_repository
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory
from app.models.outbox_models import OutboxItemDocument
from app.models.platform_models import PlatformLinkEntry
from app.models.presence_models import PresenceSnapshot
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.delivery.chat_channel import resolve_channel_priority
from app.services.delivery.presence import active_surface, read_presence
from app.services.outbox.policy import is_answer
from app.services.platform_link_service import linked_platforms_of
from app.utils.notification.channel_preferences import normalize_channel_preferences
from shared.py.analytics.catalog.delivery import (
    ProactiveDestinationBasis,
    ProactiveDestinationKind,
)
from shared.py.wide_events import log

#: Why a platform was chosen: the user wrote there within the active window, it led their order,
#: the answer goes back to the direct message that asked, or the producer named it.
ChatChannelBasis = Literal["recent_activity", "priority", "owner_chat", "requested_channel"]


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


class NoDestinationError(RuntimeError):
    """A message has nowhere to go: the alert stays in the app and the user has no conversation there."""


@dataclass(frozen=True, slots=True)
class Route:
    """Where one message goes: the single alert, and every conversation that records it."""

    alert_conversation_id: str
    #: Every conversation the message is recorded in, the alert's first.
    recorded_in: tuple[str, ...]
    target: ProactiveTarget
    #: The chat app the user asked to be told on that could not be used, so the message says so.
    requested_unavailable: ConversationSource | None = None


def is_active_place(target: ProactiveTarget) -> bool:
    """Whether target is settled: where the user is active now or a chat app a producer named, not a fallback."""
    match target:
        case (
            ChatChannel(basis="recent_activity" | "requested_channel")
            | InApp(reason="active_in_app")
        ):
            return True
    return False


def destination_of(
    target: ProactiveTarget,
) -> tuple[ProactiveDestinationKind, ProactiveDestinationBasis]:
    """Return what kind of place target is and the rule that chose it."""
    if isinstance(target, ChatChannel):
        return "chat_app", target.basis
    return "in_app", target.reason


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
        presence: PresenceSnapshot = await read_presence(user_id)
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


async def _requested_chat_channel(
    user_id: str, source: ConversationSource | None
) -> ChatChannel | None:
    """Return the chat app a producer asked for when it is linked, enabled and reachable, else None."""
    if source is None:
        return None
    user = await user_repository.get(user_id)
    if user is None:
        return None
    channel = pick_chat_channel(
        [source.value],
        linked_platforms_of(user),
        normalize_channel_preferences(user.notification_channel_prefs),
        active=None,
    )
    return replace(channel, basis="requested_channel") if channel is not None else None


@dataclass(frozen=True, slots=True)
class _Owner:
    """The conversation that owns a subject's history."""

    conversation_id: str
    #: None for a chat in the GAIA app, which is stored without a source.
    source: ConversationSource | None

    @property
    def in_app(self) -> bool:
        return self.source not in BOT_CONVERSATION_SOURCES


async def _find_owner(user_id: str, conversation_id: str | None) -> _Owner | None:
    if conversation_id is None or not await conversation_repository.exists(
        conversation_id, user_id=user_id
    ):
        return None
    source = await conversation_repository.get_source(conversation_id, user_id=user_id)
    return _Owner(conversation_id, source)


async def _owner_dm_channel(owner: _Owner) -> ChatChannel | None:
    """Return the chat app the owner conversation is a direct message on, or None for an app chat or a group."""
    if owner.source is None or owner.in_app:
        return None
    session = await bot_session_repository.get_by_conversation_id(owner.conversation_id)
    if session is None or session.channel_id is not None:
        return None
    return ChatChannel(
        source=owner.source, platform_user_id=session.platform_user_id, basis="owner_chat"
    )


async def _latest_app_conversation_id(user_id: str) -> str:
    summaries = await conversation_repository.list_active_summaries(user_id, skip=0, limit=1)
    if not summaries:
        raise NoDestinationError(user_id)
    return summaries[0].conversation_id


async def _in_app_owner_ids(
    user_id: str, items: list[OutboxItemDocument], first: _Owner | None
) -> list[str]:
    """Return the app chats that own the items' subjects, the first item's first."""
    owners = [first] if first is not None else []
    for conversation_id in dict.fromkeys(
        item.report.subject.owner_conversation_id for item in items[1:]
    ):
        other = await _find_owner(user_id, conversation_id)
        if other is not None:
            owners.append(other)
    return [owner.conversation_id for owner in owners if owner.in_app]


async def route(user: AuthenticatedUser, items: list[OutboxItemDocument]) -> Route:
    """Decide where one message covering items goes; the first item's conversation is the owner it may go back to.

    A message that covers several subjects is also recorded in each other subject's app chat.

    Raises NoDestinationError when the alert stays in the app and the user has no conversation there.
    """
    owner = await _find_owner(user.user_id, items[0].report.subject.owner_conversation_id)
    requested = items[0].report.delivery_policy.channel
    requested_target = await _requested_chat_channel(user.user_id, requested)
    target: ProactiveTarget = requested_target or await resolve_proactive_target(user.user_id)
    if requested_target is None and owner is not None and not is_active_place(target):
        if any(is_answer(item.report) for item in items):
            target = await _owner_dm_channel(owner) or target

    if isinstance(target, ChatChannel):
        if owner is not None and target.basis == "owner_chat":
            alert_id = owner.conversation_id
        else:
            alert_id = await BotService.get_or_create_session(
                platform=target.source.value,
                platform_user_id=target.platform_user_id,
                channel_id=None,
                user=user,
                is_dm=True,
            )
    elif owner is not None and owner.in_app:
        alert_id = owner.conversation_id
    else:
        alert_id = await _latest_app_conversation_id(user.user_id)

    recorded_in = [alert_id]
    for conversation_id in await _in_app_owner_ids(user.user_id, items, owner):
        if conversation_id not in recorded_in:
            recorded_in.append(conversation_id)
    return Route(
        alert_conversation_id=alert_id,
        recorded_in=tuple(recorded_in),
        target=target,
        requested_unavailable=requested
        if requested is not None and requested_target is None
        else None,
    )
