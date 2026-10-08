"""Notification events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class NotificationRead(ServerEvent):
    """A user marked a notification read."""

    event: ClassVar[str] = "notification:read"
    previous_names: ClassVar[tuple[str, ...]] = ("notification:dismissed",)
    budget_per_user_day: ClassVar[int] = 10

    count: int


class NotificationBulkAction(ServerEvent):
    """A user applied one action to several notifications at once."""

    event: ClassVar[str] = "notification:bulk_action"
    budget_per_user_day: ClassVar[int] = 50

    action: Identifier
    successful: int
    total: int


class NotificationActionExecuted(ServerEvent):
    """A user ran an action button on a notification."""

    event: ClassVar[str] = "notification:action_executed"
    budget_per_user_day: ClassVar[int] = 50


class NotificationUnsubscribed(ServerEvent):
    """A user unsubscribed from notification emails."""

    event: ClassVar[str] = "notification:unsubscribed"
    budget_per_user_day: ClassVar[int] = 10


class NotificationViewed(WebEvent):
    """A user clicked a notification in the notification center popover."""

    event: ClassVar[str] = "notification:viewed"
    budget_per_user_day: ClassVar[int] = 10

    notification_id: Identifier
    source: Literal["popover"]
