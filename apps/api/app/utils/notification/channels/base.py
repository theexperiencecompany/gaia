from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Generic, TypeVar

from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationStatus,
)

TContent = TypeVar("TContent")


class ChannelAdapter(ABC, Generic[TContent]):
    """Base class for all notification channel adapters.

    Generic over the payload ``transform`` produces and ``deliver`` consumes,
    because every channel's payload is its own shape (a WebSocket frame for
    in-app, CommonMark parts for the bot queues). The type parameter is what
    keeps each adapter's two halves checked against each other; the
    orchestrator's registry holds them erased, since it only ever pipes one
    adapter's ``transform`` straight into that same adapter's ``deliver``.
    """

    @property
    @abstractmethod
    def channel_type(self) -> str:
        pass

    @abstractmethod
    def can_handle(self, notification: NotificationRequest) -> bool:
        pass

    @abstractmethod
    async def transform(self, notification: NotificationRequest) -> TContent:
        """Transform notification content for this channel."""

    @abstractmethod
    async def deliver(self, content: TContent, user_id: str) -> ChannelDeliveryStatus:
        """Deliver notification via this channel."""

    # -- Status helpers -----------------------------------------------------

    def _success(self) -> ChannelDeliveryStatus:
        return ChannelDeliveryStatus(
            channel_type=self.channel_type,
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(UTC),
        )

    def _error(self, message: str) -> ChannelDeliveryStatus:
        return ChannelDeliveryStatus(
            channel_type=self.channel_type,
            status=NotificationStatus.FAILED,
            error_message=message,
        )

    def _skipped(self, message: str) -> ChannelDeliveryStatus:
        return ChannelDeliveryStatus(
            channel_type=self.channel_type,
            status=NotificationStatus.FAILED,
            skipped=True,
            error_message=message,
        )
