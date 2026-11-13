"""The Updates feed: the record of what GAIA told the user and what it only kept, read off the outbox ledger."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.services.outbox.models import DropReason, ItemState, NoticeDisplay, SubjectKind


class UpdateFilter(StrEnum):
    """Which updates the feed lists."""

    ALL = "all"
    NEEDS_YOU = "needs_you"
    DONE = "done"
    FAILED = "failed"
    HELD = "held"


class UpdateOutcome(StrEnum):
    """Where the update left what it is about."""

    DONE = "done"
    #: Something GAIA only recorded or warned about, which asks nothing of the user.
    INFO = "info"
    NEEDS_YOU = "needs_you"
    FAILED = "failed"


class UpdateRow(BaseModel):
    """One thing GAIA reported: what it is about, what became of it, and the words it was told in."""

    report_id: str
    subject_kind: SubjectKind
    subject_label: str
    outcome: UpdateOutcome
    state: ItemState
    drop_reason: DropReason | None = None
    facts: list[str] = Field(description="What GAIA recorded, one claim per entry.")
    display: NoticeDisplay | None = Field(
        default=None,
        description="What a system notice says to the user, with the action it offers; None for any other report.",
    )
    told: list[str] | None = Field(
        default=None,
        description="The message the user was told, one entry per bubble; None when it was not told.",
    )
    held_until: datetime | None = Field(
        default=None, description="When a held update is told, when it waits for an instant."
    )
    conversation_id: str | None = Field(
        default=None, description="The conversation that owns the subject, which the row opens."
    )
    occurred_at: datetime
    told_at: datetime | None = None
    resolved_at: datetime | None = Field(
        default=None, description="When what the update asked of the user was done."
    )
    created_at: datetime


class UpdatesResponse(BaseModel):
    """A page of the feed, newest first."""

    updates: list[UpdateRow]
    next_before: datetime | None = Field(
        description="Pass as before to read the next page; None on the last page."
    )


class UnseenUpdates(BaseModel):
    """How many updates GAIA told the user since they last opened the feed."""

    count: int
