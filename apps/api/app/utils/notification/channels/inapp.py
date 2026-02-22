import logging
from typing import Any, Dict

from app.core.websocket_manager import websocket_manager
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.utils.notification.channels.base import ChannelAdapter


class InAppChannelAdapter(ChannelAdapter):
    """In-app notification channel adapter.

    Pushes the notification payload to the connected client in real time via
    WebSocket using the ``notification.new`` event.  This is the *delivery*
    step for the in-app channel — the orchestrator subsequently fires a
    separate ``notification.delivered`` broadcast that carries the full record
    with channel-delivery statuses for all channels.  The two events serve
    different purposes and are not redundant:

    * ``notification.new``       — immediate display of the notification content
    * ``notification.delivered`` — status update after all channels have run
    """

    @property
    def channel_type(self) -> str:
        return "inapp"

    def can_handle(self, notification: NotificationRequest) -> bool:
        return any(ch.channel_type == "inapp" for ch in notification.channels)

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        return {
            "id": notification.id,
            "title": notification.content.title,
            "body": notification.content.body,
            "type": notification.type,
            "priority": notification.priority,
            "actions": [
                {
                    "id": action.id,
                    "type": action.type,
                    "label": action.label,
                    "style": action.style,
                    "requires_confirmation": action.requires_confirmation,
                    "confirmation_message": action.confirmation_message,
                    "config": action.config.model_dump(),
                }
                for action in (notification.content.actions or [])
            ],
            "metadata": notification.metadata,
            "created_at": notification.created_at.isoformat(),
        }

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        try:
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "notification.new",
                    "notification": content,
                },
            )
            logging.info(
                f"In-app notification delivered to user {user_id}: {content.get('title')}"
            )
            return self._success()
        except Exception as e:
            logging.error(
                f"Failed to deliver in-app notification to user {user_id}: {e}"
            )
            return self._error(str(e))
