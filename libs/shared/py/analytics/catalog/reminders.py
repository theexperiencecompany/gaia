"""Reminder events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr


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


class ReminderCompleted(ServerEvent):
    """The worker executed a reminder."""

    event: ClassVar[str] = "reminder:completed"
    budget_per_user_day: ClassVar[int] = 50

    reminder_id: ObjectIdStr
    agent: Identifier


class ReminderDeleted(ServerEvent):
    """A user deleted a reminder."""

    event: ClassVar[str] = "reminder:deleted"
    budget_per_user_day: ClassVar[int] = 50


__all__ = [
    "ReminderCompleted",
    "ReminderCreated",
    "ReminderDeleted",
    "ReminderPaused",
    "ReminderResumed",
    "ReminderUpdated",
]
