"""The frames a conversation's event stream carries to clients."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.conversation_log_models import ConversationDisplay, LoggedEntry, WorkPhase
from app.models.stream_events import (
    ApprovalRequestEntry,
    FollowUpActionsFrame,
    MessageBoundaryPayload,
    ReasoningPayload,
    ResponseFrame,
    SubagentEndPayload,
    SubagentStartPayload,
    TodoProgressFrame,
    ToolCallsDataEntry,
    ToolOutputPayload,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class FrameKind(StrEnum):
    """Discriminator of an output frame on the conversation's event stream."""

    ENTRY = "entry"
    ENTRY_UPDATED = "entry_updated"
    DELTA = "delta"
    RETRACT = "retract"
    STATE = "state"


DeltaPayload = (
    ResponseFrame
    | ReasoningPayload
    | ToolCallsDataEntry
    | ApprovalRequestEntry
    | ToolOutputPayload
    | MessageBoundaryPayload
    | SubagentStartPayload
    | SubagentEndPayload
    | FollowUpActionsFrame
    | TodoProgressFrame
)


class EntryFrame(BaseModel):
    """A newly appended entry."""

    model_config = _FROZEN

    kind: Literal[FrameKind.ENTRY] = FrameKind.ENTRY
    entry: LoggedEntry


class EntryUpdatedFrame(BaseModel):
    """An entry completed or changed in place, keyed by its seq."""

    model_config = _FROZEN

    kind: Literal[FrameKind.ENTRY_UPDATED] = FrameKind.ENTRY_UPDATED
    entry: LoggedEntry


class DeltaFrame(BaseModel):
    """Streamed content of an attempt, for exactly one of a reply or a task."""

    model_config = _FROZEN

    kind: Literal[FrameKind.DELTA] = FrameKind.DELTA
    attempt_id: str
    reply_id: str | None = None
    task_id: str | None = None
    payload: DeltaPayload

    @model_validator(mode="after")
    def _one_target(self) -> "DeltaFrame":
        if (self.reply_id is None) == (self.task_id is None):
            raise ValueError("a delta targets exactly one of reply_id or task_id")
        return self


class RetractFrame(BaseModel):
    """Everything an uncommitted attempt streamed is withdrawn."""

    model_config = _FROZEN

    kind: Literal[FrameKind.RETRACT] = FrameKind.RETRACT
    attempt_id: str


class StateFrame(BaseModel):
    """The conversation's display state after an append."""

    model_config = _FROZEN

    kind: Literal[FrameKind.STATE] = FrameKind.STATE
    head: int = Field(ge=0)
    display: ConversationDisplay
    work_phase: WorkPhase


OutputFrame = Annotated[
    EntryFrame | EntryUpdatedFrame | DeltaFrame | RetractFrame | StateFrame,
    Field(discriminator="kind"),
]
