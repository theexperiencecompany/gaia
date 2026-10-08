"""Calendar events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier


class CalendarEventCreated(ServerEvent):
    """A user created one calendar event, or a batch of them."""

    event: ClassVar[str] = "calendar:event_created"

    is_all_day: bool | None = None
    has_description: bool | None = None
    has_recurrence: bool | None = None
    recurrence_frequency: Identifier | None = None
    batch_size: int | None = None
    success_count: int | None = None
    failure_count: int | None = None


class CalendarEventUpdated(ServerEvent):
    """A user updated one calendar event, or a batch of them."""

    event: ClassVar[str] = "calendar:event_updated"

    batch_size: int | None = None
    success_count: int | None = None
    failure_count: int | None = None


class CalendarEventDeleted(ServerEvent):
    """A user deleted one calendar event, or a batch of them."""

    event: ClassVar[str] = "calendar:event_deleted"

    batch_size: int | None = None
    success_count: int | None = None
    failure_count: int | None = None


class CalendarPreferencesUpdated(ServerEvent):
    """A user changed which calendars are selected."""

    event: ClassVar[str] = "calendar:preferences_updated"
