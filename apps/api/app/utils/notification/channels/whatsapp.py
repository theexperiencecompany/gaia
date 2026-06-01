"""WhatsApp notification channel adapter.

Publishes the message to the WhatsApp outbound queue; the WhatsApp bot process
consumes it, converts to WhatsApp formatting, and sends via Kapso.
"""

from app.models.chat_models import ConversationSource
from app.utils.notification.channels.external import ExternalPlatformAdapter


class WhatsAppChannelAdapter(ExternalPlatformAdapter):
    """Publishes notifications to the user's linked WhatsApp account's queue."""

    @property
    def platform(self) -> ConversationSource:
        return ConversationSource.WHATSAPP
