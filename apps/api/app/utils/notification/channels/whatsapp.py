"""WhatsApp notification channel adapter.

Publishes the message to the WhatsApp outbound queue; the WhatsApp bot process
consumes it, converts to WhatsApp formatting, and sends via Kapso.
"""

from app.constants.notifications import CHANNEL_TYPE_WHATSAPP
from app.models.chat_models import ConversationSource
from app.utils.notification.channels.external import ExternalPlatformAdapter


class WhatsAppChannelAdapter(ExternalPlatformAdapter):
    """Publishes notifications to the user's linked WhatsApp account's queue."""

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_WHATSAPP

    @property
    def platform(self) -> ConversationSource:
        return ConversationSource.WHATSAPP
