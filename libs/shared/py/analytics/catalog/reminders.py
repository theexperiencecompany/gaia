"""Reminder events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr


class ReminderCreated(ServerEvent):
    """A user created a reminder."""

    event: ClassVar[str] = "reminder:created"

    is_recurring: bool


class ReminderUpdated(ServerEvent):
    """A user updated a reminder."""

    event: ClassVar[str] = "reminder:updated"


class ReminderPaused(ServerEvent):
    """A user paused a reminder."""

    event: ClassVar[str] = "reminder:paused"


class ReminderResumed(ServerEvent):
    """A user resumed a paused reminder."""

    event: ClassVar[str] = "reminder:resumed"


class ReminderCompleted(ServerEvent):
    """The worker executed a reminder."""

    event: ClassVar[str] = "reminder:completed"

    reminder_id: ObjectIdStr
    agent: Identifier


class ReminderDeleted(ServerEvent):
    """A user deleted a reminder."""

    event: ClassVar[str] = "reminder:deleted"
