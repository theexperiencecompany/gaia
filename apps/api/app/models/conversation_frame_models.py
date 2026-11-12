"""The frames a conversation's event stream carries to clients; every one is tagged and idempotent."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.conversation_log_models import DisplayState, Entry
from app.models.stream_events import (
    FollowUpActionsFrame,
    MessageBoundaryPayload,
    ReasoningPayload,
    ResponseFrame,
    SubagentEndPayload,
    SubagentStartPayload,
    TodoProgressFrame,
    ToolOutputPayload,
)
from app.models.tool_data_models import ToolDataEntry

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class FrameKind(StrEnum):
    """Discriminator of an output frame on the conversation's event stream."""

    ENTRY = "entry"
    ENTRY_UPDATED = "entry_updated"
    REPLY_DELTA = "reply_delta"
    WORK_DELTA = "work_delta"
    RETRACT = "retract"
    STATE = "state"


class StreamPayloadType(StrEnum):
    """Tag of a delta payload; each value is the chat stream event key the payload carries."""

    RESPONSE = "response"
    REASONING = "reasoning"
    TOOL_DATA = "tool_data"
    TOOL_OUTPUT = "tool_output"
    MESSAGE_BOUNDARY = "message_boundary"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    FOLLOW_UP_ACTIONS = "follow_up_actions"
    TODO_PROGRESS = "todo_progress"


class ResponseEvent(ResponseFrame):
    """A chat stream response event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.RESPONSE] = StreamPayloadType.RESPONSE


class FollowUpActionsEvent(FollowUpActionsFrame):
    """A chat stream follow_up_actions event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.FOLLOW_UP_ACTIONS] = StreamPayloadType.FOLLOW_UP_ACTIONS


class TodoProgressEvent(TodoProgressFrame):
    """A chat stream todo_progress event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.TODO_PROGRESS] = StreamPayloadType.TODO_PROGRESS


class ReasoningEvent(BaseModel):
    """A chat stream reasoning event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.REASONING] = StreamPayloadType.REASONING
    reasoning: ReasoningPayload


class ToolDataEvent(BaseModel):
    """A chat stream tool_data event (a tool card), tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.TOOL_DATA] = StreamPayloadType.TOOL_DATA
    tool_data: ToolDataEntry


class ToolOutputEvent(BaseModel):
    """A chat stream tool_output event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.TOOL_OUTPUT] = StreamPayloadType.TOOL_OUTPUT
    tool_output: ToolOutputPayload


class MessageBoundaryEvent(BaseModel):
    """A chat stream message_boundary event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.MESSAGE_BOUNDARY] = StreamPayloadType.MESSAGE_BOUNDARY
    message_boundary: MessageBoundaryPayload


class SubagentStartEvent(BaseModel):
    """A chat stream subagent_start event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.SUBAGENT_START] = StreamPayloadType.SUBAGENT_START
    subagent_start: SubagentStartPayload


class SubagentEndEvent(BaseModel):
    """A chat stream subagent_end event, tagged."""

    model_config = _FROZEN

    type: Literal[StreamPayloadType.SUBAGENT_END] = StreamPayloadType.SUBAGENT_END
    subagent_end: SubagentEndPayload


StreamPayload = Annotated[
    ResponseEvent
    | ReasoningEvent
    | ToolDataEvent
    | ToolOutputEvent
    | MessageBoundaryEvent
    | SubagentStartEvent
    | SubagentEndEvent
    | FollowUpActionsEvent
    | TodoProgressEvent,
    Field(discriminator="type"),
]


class EntryFrame(BaseModel):
    """A newly appended entry."""

    model_config = _FROZEN

    kind: Literal[FrameKind.ENTRY] = FrameKind.ENTRY
    seq: int = Field(ge=1)
    at: AwareDatetime
    entry: Entry


class EntryUpdatedFrame(BaseModel):
    """An entry changed in place; a client applies it only when entry.revision is newer than its own."""

    model_config = _FROZEN

    kind: Literal[FrameKind.ENTRY_UPDATED] = FrameKind.ENTRY_UPDATED
    seq: int = Field(ge=1)
    entry: Entry


class ReplyDeltaFrame(BaseModel):
    """Streamed content of one comms attempt; reply_id is None until its reply entry exists."""

    model_config = _FROZEN

    kind: Literal[FrameKind.REPLY_DELTA] = FrameKind.REPLY_DELTA
    attempt_id: str
    reply_id: str | None
    # 0-based, +1 per delta in the attempt; a client ignores an index it already applied.
    index: int = Field(ge=0)
    payload: StreamPayload


class WorkDeltaFrame(BaseModel):
    """Streamed content of one background task."""

    model_config = _FROZEN

    kind: Literal[FrameKind.WORK_DELTA] = FrameKind.WORK_DELTA
    task_id: str
    # 0-based, +1 per delta in the task; a client ignores an index it already applied.
    index: int = Field(ge=0)
    payload: StreamPayload


class RetractFrame(BaseModel):
    """Everything an uncommitted reply attempt streamed is withdrawn; work is never retracted."""

    model_config = _FROZEN

    kind: Literal[FrameKind.RETRACT] = FrameKind.RETRACT
    attempt_id: str


class LiveTask(BaseModel):
    """One live background task, shown as one work bubble."""

    model_config = _FROZEN

    task_id: str
    awaiting_approval: bool


class StateFrame(BaseModel):
    """The conversation's display state after an append."""

    model_config = _FROZEN

    kind: Literal[FrameKind.STATE] = FrameKind.STATE
    head: int = Field(ge=0)
    display: DisplayState
    work: tuple[LiveTask, ...]


OutputFrame = Annotated[
    EntryFrame | EntryUpdatedFrame | ReplyDeltaFrame | WorkDeltaFrame | RetractFrame | StateFrame,
    Field(discriminator="kind"),
]
