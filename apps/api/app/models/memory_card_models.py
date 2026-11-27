"""The memory_data card's payload: what a memory tool did, discriminated on action."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from app.constants.memory import MemoryDocType
from app.models.memory_models import MemoryEntry
from app.schemas.common import ResponseModel


class MemoryAddOutcome(StrEnum):
    """How an explicit add was reconciled with what the user's memory already held."""

    NEW = "new"
    UPDATED = "updated"
    EXTENDED = "extended"
    DUPLICATE = "duplicate"


class MemoryJournalLine(ResponseModel):
    """One line of a journal day."""

    time: str | None
    text: str
    source: str | None


class MemoryJournalDay(ResponseModel):
    """One journal day; date is YYYY-MM-DD."""

    date: str
    entries: list[MemoryJournalLine]
    summary: str | None


class MemoryCardDocument(ResponseModel):
    """A core memory document as the card shows it; content is capped."""

    doc_type: MemoryDocType
    content: str
    version: int
    updated_at: str


class MemoryAddCard(ResponseModel):
    """A fact the user asked GAIA to remember."""

    action: Literal["add"] = "add"
    memories: list[MemoryEntry]
    folder: str
    outcome: MemoryAddOutcome
    message: str


class MemorySearchCard(ResponseModel):
    """The memories a search matched; folder is the search's scope, when it had one."""

    action: Literal["search"] = "search"
    query: str
    folder: str | None
    memories: list[MemoryEntry]
    message: str


class MemoryUpdateCard(ResponseModel):
    """A memory corrected to its new version."""

    action: Literal["update"] = "update"
    memories: list[MemoryEntry]
    message: str


class MemoryForgetCard(ResponseModel):
    """A memory forgotten, and why."""

    action: Literal["forget"] = "forget"
    memory_id: str
    reason: str
    message: str


class MemoryJournalCard(ResponseModel):
    """Journal days read or searched; query is set only for a search."""

    action: Literal["journal"] = "journal"
    query: str | None
    episodes: list[MemoryJournalDay]
    message: str


class MemoryDocumentCard(ResponseModel):
    """A core memory document read or rewritten."""

    action: Literal["document"] = "document"
    document: MemoryCardDocument
    updated: bool
    message: str


MemoryCardData = Annotated[
    MemoryAddCard
    | MemorySearchCard
    | MemoryUpdateCard
    | MemoryForgetCard
    | MemoryJournalCard
    | MemoryDocumentCard,
    Field(discriminator="action"),
]
