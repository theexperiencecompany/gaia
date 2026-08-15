"""Slack notification channel adapter.

Publishes the message to the Slack outbound queue; the Slack bot process
consumes it, converts to Slack mrkdwn, and posts to the user's DM.
"""

from app.models.chat_models import ConversationSource
from app.utils.notification.channels.external import ExternalPlatformAdapter


class SlackChannelAdapter(ExternalPlatformAdapter):
    """Publishes notifications to the user's linked Slack account's queue."""

    @property
    def platform(self) -> ConversationSource:
        return ConversationSource.SLACK
