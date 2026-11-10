from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.utils.notification.channels.base import ChannelAdapter
from shared.py.wide_events import log


class InAppChannelAdapter(ChannelAdapter[str]):
    """In-app notification channel adapter.

    The in-app channel is the stored notification record itself: nothing is
    sent here. The real-time push is the orchestrator's single outbox.message
    frame, published once every channel has settled and the record carries
    their statuses.
    """

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_INAPP

    def can_handle(self, notification: NotificationRequest) -> bool:  # noqa: ARG002 -- polymorphic interface; implementations keep the full signature
        """Return True — in-app delivery is always available for any request."""
        # The orchestrator decides targeting; checking the request's channel
        # list here would silently skip the record when auto-injected (list is empty).
        return True

    async def transform(self, notification: NotificationRequest) -> str:
        """Return the id of the stored record this channel stands for."""
        return notification.id

    async def deliver(self, content: str, user_id: str) -> ChannelDeliveryStatus:
        """Report the stored record as available in the in-app list."""
        log.info(
            f"{LogTag.NOTIFICATION} In-app notification recorded",
            user_id=user_id,
            notification_id=content,
        )
        return self._success()
