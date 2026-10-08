"""Memory and notes events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier


class MemoryCreated(ServerEvent):
    """A user added a memory."""

    event: ClassVar[str] = "memory:created"


class MemoryUpdated(ServerEvent):
    """A user edited a memory."""

    event: ClassVar[str] = "memory:updated"


class MemoryCleared(ServerEvent):
    """A user wiped their entire memory."""

    event: ClassVar[str] = "memory:cleared"

    deleted_count: int


class MemoryItemDeleted(ServerEvent):
    """A user deleted one memory."""

    event: ClassVar[str] = "memory:item_deleted"

    memory_id: Identifier


class MemoryDocumentUpdated(ServerEvent):
    """A user edited their memory document."""

    event: ClassVar[str] = "memory:document_updated"


class NotesCreated(ServerEvent):
    """A user created a note."""

    event: ClassVar[str] = "notes:created"


class NotesUpdated(ServerEvent):
    """A user updated a note."""

    event: ClassVar[str] = "notes:updated"


class NotesDeleted(ServerEvent):
    """A user deleted a note."""

    event: ClassVar[str] = "notes:deleted"
