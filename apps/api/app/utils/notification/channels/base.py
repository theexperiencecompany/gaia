from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict

from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationStatus,
)

# Type alias for a platform send function: async (text) -> error_string | None
SendFn = Callable[[str], Coroutine[Any, Any, str | None]]


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
    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Transform notification content for this channel."""
        pass

    @abstractmethod
    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        """Deliver notification via this channel."""
        pass

    # -- Status helpers -----------------------------------------------------

    def _success(self) -> ChannelDeliveryStatus:
        return ChannelDeliveryStatus(
            channel_type=self.channel_type,
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(timezone.utc),
        )

    def _error(self, message: str) -> ChannelDeliveryStatus:
        return ChannelDeliveryStatus(
            channel_type=self.channel_type,
            status=NotificationStatus.PENDING,
            error_message=message,
        )

    def _skipped(self, message: str) -> ChannelDeliveryStatus:
        return ChannelDeliveryStatus(
            channel_type=self.channel_type,
            status=NotificationStatus.PENDING,
            skipped=True,
            error_message=message,
        )
