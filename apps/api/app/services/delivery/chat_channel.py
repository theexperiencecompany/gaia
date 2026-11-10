"""The user's chat-channel priority: the order their proactive messages try chat apps in.

The choice itself, where a proactive message goes, is made by app.services.outbox.router.
"""

from collections.abc import Sequence

from app.constants.notifications import DEFAULT_CHAT_CHANNEL_PRIORITY
from app.db.repositories.users import user_repository
from app.models.chat_channel_models import CHAT_CHANNEL_VALUES
from app.services.analytics_service import capture
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsChatChannelPriorityUpdated

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
