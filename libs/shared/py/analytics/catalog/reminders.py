"""Reminder events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent

__all__ = [
    "ReminderCreated",
    "ReminderDeleted",
    "ReminderPaused",
    "ReminderResumed",
    "ReminderUpdated",
]


class ReminderCreated(ServerEvent):
    """A user created a reminder."""

    event: ClassVar[str] = "reminder:created"
    budget_per_user_day: ClassVar[int] = 50

    is_recurring: bool


class ReminderUpdated(ServerEvent):
    """A user updated a reminder."""

    event: ClassVar[str] = "reminder:updated"
    budget_per_user_day: ClassVar[int] = 50


class ReminderPaused(ServerEvent):
    """A user paused a reminder."""

    event: ClassVar[str] = "reminder:paused"
    budget_per_user_day: ClassVar[int] = 50


class ReminderResumed(ServerEvent):
    """A user resumed a paused reminder."""

    event: ClassVar[str] = "reminder:resumed"
    budget_per_user_day: ClassVar[int] = 50


class ReminderDeleted(ServerEvent):
    """A user deleted a reminder."""

    event: ClassVar[str] = "reminder:deleted"
    budget_per_user_day: ClassVar[int] = 50
