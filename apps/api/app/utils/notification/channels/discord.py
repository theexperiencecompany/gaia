"""Discord notification channel adapter.

Publishes the message to the Discord outbound queue; the Discord bot process
consumes it and sends to the user's DM.
"""

from app.constants.notifications import CHANNEL_TYPE_DISCORD
from app.models.chat_models import ConversationSource
from app.utils.notification.channels.external import ExternalPlatformAdapter


class DiscordChannelAdapter(ExternalPlatformAdapter):
    """Publishes notifications to the user's linked Discord account's queue."""

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_DISCORD

    @property
    def platform(self) -> ConversationSource:
        return ConversationSource.DISCORD
