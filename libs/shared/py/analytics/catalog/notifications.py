"""Notification events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent

__all__ = ["NotificationUnsubscribed"]


class NotificationUnsubscribed(ServerEvent):
    """A user unsubscribed from notification emails."""

    event: ClassVar[str] = "notification:unsubscribed"
    budget_per_user_day: ClassVar[int] = 10
