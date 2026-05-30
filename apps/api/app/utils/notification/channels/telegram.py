"""Telegram notification channel adapter.

Publishes the message to the Telegram outbound queue; the Telegram bot process
consumes it, converts to Telegram HTML, and sends.
"""

from app.constants.notifications import CHANNEL_TYPE_TELEGRAM
from app.models.chat_models import ConversationSource
from app.utils.notification.channels.external import ExternalPlatformAdapter


class TelegramChannelAdapter(ExternalPlatformAdapter):
    """Publishes notifications to the user's linked Telegram account's queue."""

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_TELEGRAM

    @property
    def platform(self) -> ConversationSource:
        return ConversationSource.TELEGRAM
