import logging
from typing import Any, Dict

from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.utils.notification.channels.base import ChannelAdapter


class InAppChannelAdapter(ChannelAdapter):
    """In-app notification channel adapter."""

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
                    "config": action.config.dict(),
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
            logging.info(
                f"Delivering in-app notification to user {user_id}: {content['title']}"
            )
            return self._success()
        except Exception as e:
            return self._error(str(e))
