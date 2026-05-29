from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

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
    async def transform(self, notification: NotificationRequest) -> dict[str, Any]:
        """Transform notification content for this channel."""
        pass

    @abstractmethod
    async def deliver(self, content: dict[str, Any], user_id: str) -> ChannelDeliveryStatus:
        """Deliver notification via this channel."""
        pass

    async def deliver_text(self, text: str, user_id: str) -> ChannelDeliveryStatus:
        """Deliver a single plain chat message (raw Markdown) to ``user_id``.

        Bypasses the notification ``transform`` step — used to push agent-generated
        chat messages (not notifications) to a user's linked platform. The default
        passes the text straight through; adapters whose Markdown conversion lives
        in ``transform`` (rather than at send time) override this to convert first.
        """
        return await self.deliver({"text": text}, user_id)

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
