"""Memory and notes events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier


class MemoryCreated(ServerEvent):
    """A user added a memory."""

    event: ClassVar[str] = "memory:created"
    budget_per_user_day: ClassVar[int] = 50


class MemoryUpdated(ServerEvent):
    """A user edited a memory."""

    event: ClassVar[str] = "memory:updated"
    budget_per_user_day: ClassVar[int] = 50


class MemoryCleared(ServerEvent):
    """A user wiped their entire memory."""

    event: ClassVar[str] = "memory:cleared"
    budget_per_user_day: ClassVar[int] = 50

    deleted_count: int


class MemoryItemDeleted(ServerEvent):
    """A user deleted one memory."""

    event: ClassVar[str] = "memory:item_deleted"
    budget_per_user_day: ClassVar[int] = 50

    memory_id: Identifier


class MemoryDocumentUpdated(ServerEvent):
    """A user edited their memory document."""

    event: ClassVar[str] = "memory:document_updated"
    budget_per_user_day: ClassVar[int] = 50


class NotesCreated(ServerEvent):
    """A user created a note."""

    event: ClassVar[str] = "notes:created"
    budget_per_user_day: ClassVar[int] = 50


class NotesUpdated(ServerEvent):
    """A user updated a note."""

    event: ClassVar[str] = "notes:updated"
    budget_per_user_day: ClassVar[int] = 50


class NotesDeleted(ServerEvent):
    """A user deleted a note."""

    event: ClassVar[str] = "notes:deleted"
    budget_per_user_day: ClassVar[int] = 50


__all__ = [
    "MemoryCleared",
    "MemoryCreated",
    "MemoryDocumentUpdated",
    "MemoryItemDeleted",
    "MemoryUpdated",
    "NotesCreated",
    "NotesDeleted",
    "NotesUpdated",
]
