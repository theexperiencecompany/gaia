"""Notification events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "NotificationActionExecuted",
    "NotificationBulkAction",
    "NotificationRead",
    "NotificationUnsubscribed",
    "NotificationViewed",
]


class NotificationRead(ServerEvent):
    """A user marked a notification read."""

    event: ClassVar[str] = "notification:read"

    count: int


class NotificationBulkAction(ServerEvent):
    """A user applied one action to several notifications at once."""

    event: ClassVar[str] = "notification:bulk_action"

    action: Identifier
    successful: int
    total: int


class NotificationActionExecuted(ServerEvent):
    """A user ran an action button on a notification."""

    event: ClassVar[str] = "notification:action_executed"


class NotificationUnsubscribed(ServerEvent):
    """A user unsubscribed from notification emails."""

    event: ClassVar[str] = "notification:unsubscribed"


class NotificationViewed(WebEvent):
    """A user clicked a notification in the notification center popover."""

    event: ClassVar[str] = "notification:viewed"

    notification_id: Identifier
    source: Literal["popover"]
