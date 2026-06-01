from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationStatus,
)


class ChannelAdapter(ABC):
    """Base class for all notification channel adapters."""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        pass

    @abstractmethod
    def can_handle(self, notification: NotificationRequest) -> bool:
        pass

    @abstractmethod
    async def transform(self, notification: NotificationRequest) -> dict[str, Any]:
        """Transform notification content for this channel."""
        pass

    @abstractmethod
    async def deliver(self, content: dict[str, Any], user_id: str) -> ChannelDeliveryStatus:
        """Deliver notification via this channel."""
        pass

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
