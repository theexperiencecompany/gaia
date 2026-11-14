"""The conversation screen: the ordered items every client renders, projected from the log by the server."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from app.models.conversation_frame_models import RetractFrame, StateFrame
from app.models.conversation_log_models import ApprovalRequested, UserMessage
from app.models.message_models import SelectedWorkflowData
from app.models.todo_wake_models import TodoRunWake
from shared.py import conversation_wire as wire
from shared.py.conversation_wire import (
    ConversationUpdatedFrame,
    ImageData,
    ReplyDeltaFrame,
    ReplyItem,
    ScreenItemBase,
    ScreenItemKind,
    ToolDataEntry,
    ToolTimeline,
)


class WorkStatus(StrEnum):
    """Where a piece of work stands: live, or how it ended."""

    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"


class UserItem(ScreenItemBase):
    """A message the user sent, with GAIA's reaction to it."""

    kind: Literal[ScreenItemKind.USER] = ScreenItemKind.USER
    message: UserMessage


class WorkItem(ScreenItemBase):
    """One piece of work from its hand-off to its result, with every task handed to it."""

    kind: Literal[ScreenItemKind.WORK] = ScreenItemKind.WORK
    task_id: str
    status: WorkStatus
    # The approvals the work waits on, oldest first; empty once it ends.
    asking: tuple[ApprovalRequested, ...]
    handoff: ToolDataEntry | None
    tool_data: tuple[ToolDataEntry, ...]
    # The hand-off's card and the work's cards, as the thread shows them.
    timeline: ToolTimeline
    image: ImageData | None


class NoticeItem(ScreenItemBase):
    """A proactive message delivered outside a reply."""

    kind: Literal[ScreenItemKind.NOTICE] = ScreenItemKind.NOTICE
    bubbles: tuple[str, ...]
    tool_data: tuple[ToolDataEntry, ...]
    timeline: ToolTimeline
    follow_up_actions: tuple[str, ...]


class WorkflowFiredItem(ScreenItemBase):
    """The workflow card that started a run; the run's reply is its own item."""

    kind: Literal[ScreenItemKind.WORKFLOW_FIRED] = ScreenItemKind.WORKFLOW_FIRED
    workflow: SelectedWorkflowData


class TodoWokeItem(ScreenItemBase):
    """What woke a tracked todo's run; its write-up is its own item."""

    kind: Literal[ScreenItemKind.TODO_WOKE] = ScreenItemKind.TODO_WOKE
    wake: TodoRunWake


ScreenItem = Annotated[
    UserItem | ReplyItem | WorkItem | NoticeItem | WorkflowFiredItem | TodoWokeItem,
    Field(discriminator="kind"),
]

#: The items whose text search reads and a pin marks.
TextItem = Annotated[UserItem | ReplyItem | NoticeItem, Field(discriminator="kind")]


class ScreenFrame(wire.ScreenFrame[ScreenItem]):
    """The newest page of the screen; a client replaces what it holds from the first item's seq on."""


class ScreenInsertFrame(wire.ScreenInsertFrame[ScreenItem]):
    """An item became visible; its seq is its position, before every item with a higher one."""


class ScreenUpdateFrame(wire.ScreenUpdateFrame[ScreenItem]):
    """An item already shown changed in place; it keeps its position."""


ScreenPatch = ScreenInsertFrame | ScreenUpdateFrame

# What a client receives: the screen, its patches, and the deltas of the reply still being written.
ScreenStreamFrame = Annotated[
    ScreenFrame
    | ScreenInsertFrame
    | ScreenUpdateFrame
    | ReplyDeltaFrame
    | RetractFrame
    | StateFrame
    | ConversationUpdatedFrame,
    Field(discriminator="kind"),
]
