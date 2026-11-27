"""The notification tools' card payloads: the notifications they list, and the one they sent."""

from typing import Literal

from app.models.notification.notification_models import (
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from app.schemas.common import ResponseModel


class NotificationListCard(ResponseModel):
    """The notification_data card: the notifications a list or search matched."""

    notifications: list[NotificationView]


class SentNotificationCard(ResponseModel):
    """The send_notification_data card, and what send_notification tells the model it sent."""

    success: Literal[True]
    notification_id: str
    title: str
    message: str
    notification_type: NotificationType
    status: NotificationStatus
    delivered_channels: list[str]
