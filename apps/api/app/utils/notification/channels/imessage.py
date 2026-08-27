"""iMessage notification channel adapter.

Publishes the message to the iMessage outbound queue; the iMessage bot process
consumes it and sends via the Photon Spectrum SDK.
"""

from app.models.chat_models import ConversationSource
from app.utils.notification.channels.external import ExternalPlatformAdapter


class ImessageChannelAdapter(ExternalPlatformAdapter):
    """Publishes notifications to the user's linked iMessage account's queue."""

    @property
    def platform(self) -> ConversationSource:
        return ConversationSource.IMESSAGE
