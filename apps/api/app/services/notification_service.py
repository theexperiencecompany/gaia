from fastapi import Request

from app.models.notification.notification_models import (
    ActionResult,
    BulkActions,
    NotificationListFilters,
    NotificationRecord,
    NotificationRequest,
    NotificationStatus,
    NotificationView,
)
from app.utils.notification.actions import (
    ActionHandler,
)
from app.utils.notification.channels import ChannelAdapter
from app.utils.notification.orchestrator import NotificationOrchestrator


# Service Factory
class NotificationService:
    """Main notification service - facade for the entire system."""

    def __init__(self) -> None:
        self.orchestrator = NotificationOrchestrator()

    # Expose orchestrator methods
    async def create_notification(self, request: NotificationRequest) -> NotificationRecord | None:
        return await self.orchestrator.create_notification(request)

    async def execute_action(
        self,
        notification_id: str,
        action_id: str,
        user_id: str,
        request: Request | None,
    ) -> ActionResult:
        return await self.orchestrator.execute_action(
            notification_id, action_id, user_id, request=request
        )

    async def mark_as_read(self, notification_id: str, user_id: str) -> NotificationRecord | None:
        return await self.orchestrator.mark_as_read(notification_id, user_id)

    async def get_user_notifications(
        self,
        user_id: str,
        *,
        filters: NotificationListFilters | None = None,
    ) -> list[NotificationView]:
        """Return a user's notifications, flattened for API/tool consumers."""
        return await self.orchestrator.get_user_notifications(user_id, filters=filters)

    async def get_notification(self, notification_id: str, user_id: str) -> NotificationView | None:
        """Get a specific notification by ID for a user."""
        return await self.orchestrator.get_notification(
            notification_id=notification_id,
            user_id=user_id,
        )

    async def get_user_notifications_count(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        channel_type: str | None = None,
    ) -> int:
        return await self.orchestrator.storage.get_notification_count(user_id, status, channel_type)

    async def bulk_actions(
        self, notification_ids: list[str], user_id: str, action: BulkActions
    ) -> dict[str, bool]:
        return await self.orchestrator.bulk_actions(notification_ids, user_id, action)

    async def mark_all_read(self, user_id: str, channel_type: str | None = None) -> int:
        return await self.orchestrator.mark_all_read(user_id, channel_type=channel_type)

    # WebSocket management

    # Registration methods
    def register_channel_adapter(self, adapter: ChannelAdapter) -> None:
        self.orchestrator.register_channel_adapter(adapter)

    def register_action_handler(self, handler: ActionHandler) -> None:
        self.orchestrator.register_action_handler(handler)


# Global instance of the notification service
notification_service = NotificationService()
