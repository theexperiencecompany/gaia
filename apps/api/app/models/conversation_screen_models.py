"""The conversation screen: the ordered items every client renders, projected from the log by the server."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.chat_models import ImageData
from app.models.conversation_frame_models import (
    ConversationUpdatedFrame,
    FrameKind,
    ReplyDeltaFrame,
    RetractFrame,
    StateFrame,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    WIRE_CONFIG,
    ApprovalRequested,
    FailureReason,
    ReplyOutcome,
    UserMessage,
)
from app.models.message_models import ReplyToMessageData, SelectedWorkflowData
from app.models.todo_wake_models import TodoRunWake
from app.models.tool_data_models import ToolDataEntry


class ScreenItemKind(StrEnum):
    """What one item of the screen shows."""

    USER = "user"
    REPLY = "reply"
    WORK = "work"
    NOTICE = "notice"
    WORKFLOW_FIRED = "workflow_fired"
    TODO_WOKE = "todo_woke"


class WorkStatus(StrEnum):
    """Where a piece of work stands: live, or how it ended."""

    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"


class _Item(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Stable for the item's whole life, live and reloaded.
    id: str = Field(min_length=1)
    # The log position the item became visible at; the screen is ordered by it.
    seq: int = Field(ge=1)
    at: AwareDatetime


class UserItem(_Item):
    """A message the user sent, with GAIA's reaction to it."""

    kind: Literal[ScreenItemKind.USER] = ScreenItemKind.USER
    message: UserMessage


class ReplyItem(_Item):
    """GAIA's reply: its text and own cards; outcome is None while it is still being written."""

    kind: Literal[ScreenItemKind.REPLY] = ScreenItemKind.REPLY
    text: str
    tool_data: tuple[ToolDataEntry, ...]
    follow_up_actions: tuple[str, ...]
    image: ImageData | None
    pinned: bool
    quote: ReplyToMessageData | None
    outcome: ReplyOutcome | None
    failure: FailureReason | None
    narrates: tuple[str, ...]


class WorkItem(_Item):
    """One piece of work from its hand-off to its result, with every task handed to it."""

    kind: Literal[ScreenItemKind.WORK] = ScreenItemKind.WORK
    task_id: str
    status: WorkStatus
    # The approvals the work waits on, oldest first; empty once it ends.
    asking: tuple[ApprovalRequested, ...]
    handoff: ToolDataEntry | None
    tool_data: tuple[ToolDataEntry, ...]
    image: ImageData | None


class NoticeItem(_Item):
    """A proactive message delivered outside a reply."""

    kind: Literal[ScreenItemKind.NOTICE] = ScreenItemKind.NOTICE
    text: str
    tool_data: tuple[ToolDataEntry, ...]
    follow_up_actions: tuple[str, ...]


class WorkflowFiredItem(_Item):
    """The workflow card that started a run; the run's reply is its own item."""

    kind: Literal[ScreenItemKind.WORKFLOW_FIRED] = ScreenItemKind.WORKFLOW_FIRED
    workflow: SelectedWorkflowData


class TodoWokeItem(_Item):
    """What woke a tracked todo's run; its write-up is its own item."""

    kind: Literal[ScreenItemKind.TODO_WOKE] = ScreenItemKind.TODO_WOKE
    wake: TodoRunWake


ScreenItem = Annotated[
    UserItem | ReplyItem | WorkItem | NoticeItem | WorkflowFiredItem | TodoWokeItem,
    Field(discriminator="kind"),
]


class ScreenFrame(BaseModel):
    """The newest page of the screen; a client replaces what it holds from the first item's seq on."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.SCREEN] = FrameKind.SCREEN
    items: tuple[ScreenItem, ...]


class ScreenInsertFrame(BaseModel):
    """An item became visible; its seq is its position, before every item with a higher one."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.SCREEN_INSERT] = FrameKind.SCREEN_INSERT
    item: ScreenItem


class ScreenUpdateFrame(BaseModel):
    """An item already shown changed in place; it keeps its position."""

    model_config = WIRE_CONFIG

    kind: Literal[FrameKind.SCREEN_UPDATE] = FrameKind.SCREEN_UPDATE
    item: ScreenItem


ScreenPatch = ScreenInsertFrame | ScreenUpdateFrame

# What a client receives: the screen, its patches, and the raw deltas of what is still being written.
ScreenStreamFrame = Annotated[
    ScreenFrame
    | ScreenInsertFrame
    | ScreenUpdateFrame
    | ReplyDeltaFrame
    | WorkDeltaFrame
    | RetractFrame
    | StateFrame
    | ConversationUpdatedFrame,
    Field(discriminator="kind"),
]
