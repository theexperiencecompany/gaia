"""The frames a conversation's event stream carries to clients; every one is tagged and idempotent."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.models.conversation_log_models import ConversationState, DisplayState, Entry
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
from shared.py.conversation_wire import (
    WIRE_CONFIG,
    ConversationUpdatedFrame,
    FrameKind,
    ImageData,
    ReplyDeltaFrame,
    ToolDataEntry,
)


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
    IMAGE_DATA = "image_data"


class ResponseEvent(ResponseFrame):
    """A chat stream response event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.RESPONSE] = StreamPayloadType.RESPONSE


class FollowUpActionsEvent(FollowUpActionsFrame):
    """A chat stream follow_up_actions event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.FOLLOW_UP_ACTIONS] = StreamPayloadType.FOLLOW_UP_ACTIONS


class TodoProgressEvent(TodoProgressFrame):
    """A chat stream todo_progress event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.TODO_PROGRESS] = StreamPayloadType.TODO_PROGRESS


class ReasoningEvent(BaseModel):
    """A chat stream reasoning event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.REASONING] = StreamPayloadType.REASONING
    reasoning: ReasoningPayload


class ToolDataEvent(BaseModel):
    """A chat stream tool_data event (a tool card), tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.TOOL_DATA] = StreamPayloadType.TOOL_DATA
    tool_data: ToolDataEntry


class ToolOutputEvent(BaseModel):
    """A chat stream tool_output event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.TOOL_OUTPUT] = StreamPayloadType.TOOL_OUTPUT
    tool_output: ToolOutputPayload


class MessageBoundaryEvent(BaseModel):
    """A chat stream message_boundary event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.MESSAGE_BOUNDARY] = StreamPayloadType.MESSAGE_BOUNDARY
    message_boundary: MessageBoundaryPayload


class SubagentStartEvent(BaseModel):
    """A chat stream subagent_start event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.SUBAGENT_START] = StreamPayloadType.SUBAGENT_START
    subagent_start: SubagentStartPayload


class SubagentEndEvent(BaseModel):
    """A chat stream subagent_end event, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.SUBAGENT_END] = StreamPayloadType.SUBAGENT_END
    subagent_end: SubagentEndPayload


class ImageEvent(BaseModel):
    """The image a run's image tool generated, tagged."""

    model_config = WIRE_CONFIG

    type: Literal[StreamPayloadType.IMAGE_DATA] = StreamPayloadType.IMAGE_DATA
    image_data: ImageData


StreamPayload = Annotated[
    ResponseEvent
    | ReasoningEvent
    | ToolDataEvent
    | ToolOutputEvent
    | MessageBoundaryEvent
    | SubagentStartEvent
    | SubagentEndEvent
    | FollowUpActionsEvent
    | TodoProgressEvent
    | ImageEvent,
    Field(discriminator="type"),
]


class EntryFrame(BaseModel):
    """A newly appended entry."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.ENTRY] = FrameKind.ENTRY
    seq: int = Field(ge=1)
    at: AwareDatetime
    entry: Entry


class EntryUpdatedFrame(BaseModel):
    """An entry changed in place; a client applies it only when entry.revision is newer than its own."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.ENTRY_UPDATED] = FrameKind.ENTRY_UPDATED
    seq: int = Field(ge=1)
    entry: Entry


class WorkDeltaFrame(BaseModel):
    """Streamed content of one background task."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.WORK_DELTA] = FrameKind.WORK_DELTA
    task_id: str
    # 0-based, +1 per delta in the task; a client ignores an index it already applied.
    index: int = Field(ge=0)
    payload: StreamPayload


class RetractFrame(BaseModel):
    """Everything an uncommitted reply attempt streamed is withdrawn; work is never retracted."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.RETRACT] = FrameKind.RETRACT
    attempt_id: str


class LiveTask(BaseModel):
    """One live background task, shown as one work bubble."""

    model_config = WIRE_CONFIG

    task_id: str
    awaiting_approval: bool


class StateFrame(BaseModel):
    """The conversation's display state after an append."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.STATE] = FrameKind.STATE
    head: int = Field(ge=0)
    display: DisplayState
    work: tuple[LiveTask, ...]


def state_frame(state: ConversationState) -> StateFrame:
    """Return the frame a client shows the conversation's status from."""
    work = tuple(
        LiveTask(task_id=item.task_id, awaiting_approval=bool(item.pending_approvals))
        for item in state.work
    )
    return StateFrame(head=state.head, display=state.display, work=work)


OutputFrame = Annotated[
    EntryFrame
    | EntryUpdatedFrame
    | ReplyDeltaFrame
    | WorkDeltaFrame
    | RetractFrame
    | StateFrame
    | ConversationUpdatedFrame,
    Field(discriminator="kind"),
]
