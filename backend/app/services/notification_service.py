from typing import Any, Dict, List, Optional

from app.models.notification.notification_models import (
    ActionResult,
    BulkActions,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.core.websocket_manager import websocket_manager
from app.utils.notification.actions import (
    ActionHandler,
)
from app.utils.notification.channels import ChannelAdapter
from app.utils.notification.orchestrator import NotificationOrchestrator
from fastapi import Request


# Service Factory
class NotificationService:
    """Main notification service - facade for the entire system"""

    def __init__(self):
        self.orchestrator = NotificationOrchestrator()

    # Expose orchestrator methods
    async def create_notification(
        self, request: NotificationRequest
    ) -> NotificationRecord | None:
        return await self.orchestrator.create_notification(request)

    async def execute_action(
        self,
        notification_id: str,
        action_id: str,
        user_id: str,
        request: Optional[Request],
    ) -> ActionResult:
        return await self.orchestrator.execute_action(
            notification_id, action_id, user_id, request=request
        )

    async def mark_as_read(
        self, notification_id: str, user_id: str
    ) -> NotificationRecord | None:
        return await self.orchestrator.mark_as_read(notification_id, user_id)

    async def get_user_notifications(
        self,
        user_id: str,
        status: Optional[NotificationStatus] = None,
        limit: int = 50,
        offset: int = 0,
        channel_type: Optional[str] = None,
        notification_type: Optional[NotificationType] = None,
        source: Optional[NotificationSourceEnum] = None,
    ) -> List[Dict[str, Any]]:
        return await self.orchestrator.get_user_notifications(
            user_id,
            status,
            limit,
            offset,
            channel_type,
            notification_type,
            source,
        )

    async def get_notification(
        self, notification_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a specific notification by ID for a user"""
        return await self.orchestrator.get_notification(
            notification_id=notification_id,
            user_id=user_id,
        )

    async def get_user_notifications_count(
        self,
        user_id: str,
        status: Optional[NotificationStatus] = None,
        channel_type: Optional[str] = None,
    ) -> int:
        """Get the count of notifications for a user"""
        return await self.orchestrator.storage.get_notification_count(
            user_id, status, channel_type
        )

    async def bulk_actions(
        self, notification_ids: List[str], user_id: str, action: BulkActions
    ) -> Dict[str, bool]:
        return await self.orchestrator.bulk_actions(notification_ids, user_id, action)

    # WebSocket management
    def add_websocket_connection(self, user_id: str, websocket: Any) -> None:
        websocket_manager.add_connection(user_id, websocket)

    def remove_websocket_connection(self, user_id: str, websocket: Any) -> None:
        websocket_manager.remove_connection(user_id, websocket)

    # Registration methods
    def register_channel_adapter(self, adapter: ChannelAdapter) -> None:
        self.orchestrator.register_channel_adapter(adapter)

    def register_action_handler(self, handler: ActionHandler) -> None:
        self.orchestrator.register_action_handler(handler)


# Global instance of the notification service
notification_service = NotificationService()
