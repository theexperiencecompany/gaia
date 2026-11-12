"""The conversation log: its entries, the state folded from them, and the frames clients read."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.constants.chat import ConversationSource
from app.models.chat_models import ToolDataEntry
from app.models.message_models import TodoRunWake
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


class EntryKind(StrEnum):
    """Discriminator of a conversation log entry."""

    USER_MESSAGE = "user_message"
    STOP_REQUESTED = "stop_requested"
    BARGE_IN = "barge_in"
    WORKFLOW_FIRED = "workflow_fired"
    TODO_WOKE = "todo_woke"
    NOTICE = "notice"
    WORK_STARTED = "work_started"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    WORK_FINISHED = "work_finished"
    REPLY = "reply"


class StopBy(StrEnum):
    """Who asked for a Stop: the user's button or command, or GAIA's cancel_executor tool."""

    USER = "user"
    GAIA = "gaia"


class WorkOutcome(StrEnum):
    """How a piece of background work ended."""

    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"


class ReplyOutcome(StrEnum):
    """How a finished reply ended."""

    ANSWERED = "answered"
    STOPPED = "stopped"
    FAILED = "failed"
    SILENT = "silent"


# Every way a pending approval resolves; mirrors resolution.DecisionKind, which lives in a service.
ApprovalDecision = Literal["approve", "deny", "timeout", "abandon"]


class _Entry(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1, description="Producer-minted idempotency key")


class UserMessage(_Entry):
    """A message the user sent from any surface."""

    kind: Literal[EntryKind.USER_MESSAGE] = EntryKind.USER_MESSAGE
    text: str
    surface: ConversationSource
    platform_message_id: str | None = None
    reply_to: str | None = None
    retry_of: str | None = None
    file_ids: tuple[str, ...] = ()
    voice: bool = False


class StopRequested(_Entry):
    """A Stop: cancels every input and piece of work caused at or before covers_through."""

    kind: Literal[EntryKind.STOP_REQUESTED] = EntryKind.STOP_REQUESTED
    by: StopBy
    # None covers everything before this entry.
    covers_through: int | None = Field(default=None, ge=0)


class BargeIn(_Entry):
    """The user spoke over a voice reply, having heard only heard_text of it."""

    kind: Literal[EntryKind.BARGE_IN] = EntryKind.BARGE_IN
    reply_id: str
    heard_text: str


class WorkflowFired(_Entry):
    """A workflow fired into this conversation."""

    kind: Literal[EntryKind.WORKFLOW_FIRED] = EntryKind.WORKFLOW_FIRED
    workflow_id: str
    execution_id: str
    # The fire's ARQ context bag, forwarded verbatim as execute_workflow_by_id receives it.
    context: dict[str, object]


class TodoWoke(_Entry):
    """A tracked todo's run woke."""

    kind: Literal[EntryKind.TODO_WOKE] = EntryKind.TODO_WOKE
    todo_id: str
    wake: TodoRunWake


class Notice(_Entry):
    """Text delivered to the user outside a step."""

    kind: Literal[EntryKind.NOTICE] = EntryKind.NOTICE
    text: str
    origin: str


class WorkStarted(_Entry):
    """Background work dispatched for the inputs through cause_through."""

    kind: Literal[EntryKind.WORK_STARTED] = EntryKind.WORK_STARTED
    task_id: str
    cause_through: int = Field(ge=1)
    answers: tuple[str, ...] = ()


class ApprovalRequested(_Entry):
    """Live work paused on the user's approval."""

    kind: Literal[EntryKind.APPROVAL_REQUESTED] = EntryKind.APPROVAL_REQUESTED
    task_id: str
    approval_id: str


class ApprovalDecided(_Entry):
    """A pending approval resolved."""

    kind: Literal[EntryKind.APPROVAL_DECIDED] = EntryKind.APPROVAL_DECIDED
    approval_id: str
    decision: ApprovalDecision


class WorkFinished(_Entry):
    """Background work ended."""

    kind: Literal[EntryKind.WORK_FINISHED] = EntryKind.WORK_FINISHED
    task_id: str
    outcome: WorkOutcome
    report: str


class ReplyEnd(BaseModel):
    """How a reply finished and what it answered; through is the newest answered seq."""

    model_config = _FROZEN

    outcome: ReplyOutcome
    answers: tuple[str, ...] = Field(min_length=1)
    through: int = Field(ge=1)


class Reply(_Entry):
    """GAIA's reply: open while end is None, finished once end is set."""

    kind: Literal[EntryKind.REPLY] = EntryKind.REPLY
    reply_id: str
    attempt_id: str
    text: str = ""
    tool_data: tuple[ToolDataEntry, ...] = ()
    follow_up_actions: tuple[str, ...] = ()
    # Characters of the reply the user heard before a voice barge-in.
    heard_through: int | None = Field(default=None, ge=0)
    end: ReplyEnd | None = None


Entry = Annotated[
    UserMessage
    | StopRequested
    | BargeIn
    | WorkflowFired
    | TodoWoke
    | Notice
    | WorkStarted
    | ApprovalRequested
    | ApprovalDecided
    | WorkFinished
    | Reply,
    Field(discriminator="kind"),
]

WakingEntry = UserMessage | BargeIn | WorkflowFired | WorkFinished


class LoggedEntry(BaseModel):
    """An entry at its position in the conversation's order."""

    model_config = _FROZEN

    seq: int = Field(ge=1)
    at: AwareDatetime
    entry: Entry


class CommsPhase(StrEnum):
    """What the comms model is doing."""

    IDLE = "idle"
    THINKING = "thinking"
    ANSWERING = "answering"


class ConversationDisplay(StrEnum):
    """The one status a client shows for a conversation."""

    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    AWAITING_APPROVAL = "awaiting_approval"


class WorkPhase(StrEnum):
    """Where background work stands, independent of comms."""

    NONE = "none"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"


class LiveWork(BaseModel):
    """Background work that has started and not finished or been stopped."""

    model_config = _FROZEN

    task_id: str
    cause_through: int
    answers: tuple[str, ...]
    pending_approvals: frozenset[str]


class ConversationState(BaseModel):
    """The fold of a conversation's log; only reduce changes it."""

    model_config = _FROZEN

    head: int = Field(ge=0)
    settled_through: int = Field(ge=0)
    stopped_through: int = Field(ge=0)
    # Seqs of waking entries no reply has answered yet, ascending.
    unsettled_waking: tuple[int, ...]
    comms: CommsPhase
    work: tuple[LiveWork, ...]

    @classmethod
    def empty(cls) -> "ConversationState":
        """Return the state of a conversation with no entries."""
        return cls(
            head=0,
            settled_through=0,
            stopped_through=0,
            unsettled_waking=(),
            comms=CommsPhase.IDLE,
            work=(),
        )

    @property
    def work_phase(self) -> WorkPhase:
        """Return the work phase, so an approval card stays up while comms is thinking."""
        if any(item.pending_approvals for item in self.work):
            return WorkPhase.AWAITING_APPROVAL
        return WorkPhase.RUNNING if self.work else WorkPhase.NONE

    @property
    def display(self) -> ConversationDisplay:
        """Return the status to show: comms first, then approvals, then work."""
        if self.comms is not CommsPhase.IDLE:
            return ConversationDisplay.THINKING
        return {
            WorkPhase.AWAITING_APPROVAL: ConversationDisplay.AWAITING_APPROVAL,
            WorkPhase.RUNNING: ConversationDisplay.WORKING,
            WorkPhase.NONE: ConversationDisplay.IDLE,
        }[self.work_phase]


class KickStep(BaseModel):
    """Run advance for this conversation."""

    model_config = _FROZEN


class Preempt(BaseModel):
    """Raise the running step's preempt hint."""

    model_config = _FROZEN

    stop_through: int | None = None
    barge_reply_id: str | None = None


class CancelWork(BaseModel):
    """Cancel exactly these tasks."""

    model_config = _FROZEN

    task_ids: tuple[str, ...] = Field(min_length=1)


class StartAck(BaseModel):
    """React to a user message the moment it is accepted."""

    model_config = _FROZEN

    message_id: str


Effect = KickStep | Preempt | CancelWork | StartAck


class Transition(BaseModel):
    """An accepted entry's next state and the effects the append must run."""

    model_config = _FROZEN

    state: ConversationState
    effects: tuple[Effect, ...]


class RejectReason(StrEnum):
    """Why reduce refused an entry; a rejected entry is never appended."""

    OUT_OF_ORDER = "out_of_order"
    STOP_COVERS_FUTURE = "stop_covers_future"
    CAUSE_STOPPED = "cause_stopped"
    CAUSE_NOT_BEFORE_WORK = "cause_not_before_work"
    TASK_ALREADY_LIVE = "task_already_live"
    TASK_NOT_LIVE = "task_not_live"
    REPLY_ANSWERS_FUTURE = "reply_answers_future"


class Rejected(BaseModel):
    """An entry reduce refused."""

    model_config = _FROZEN

    reason: RejectReason


class CommitReason(StrEnum):
    """What committed a comms attempt."""

    VISIBLE_TEXT = "visible_text"
    MODEL_OUTPUT = "model_output"
    REACTION = "reaction"


class Verdict(StrEnum):
    """What a running comms attempt does next."""

    CONTINUE = "continue"
    RESTART = "restart"
    STOP = "stop"
    TRUNCATE = "truncate"
    LOST = "lost"


class MergeGroup(StrEnum):
    """Waking inputs merge into one attempt only within a group."""

    INTERACTIVE = "interactive"
    BACKGROUND = "background"


class Batch(BaseModel):
    """The waking entries one comms attempt was given, seqs start through end."""

    model_config = _FROZEN

    start: int = Field(ge=1)
    end: int = Field(ge=1)
    waking: tuple[LoggedEntry, ...]
    first_at: AwareDatetime


class PreemptHint(BaseModel):
    """The advisory head a running step races its model call against."""

    model_config = _FROZEN

    head: int = Field(ge=0)
    stop_through: int = Field(ge=0)
    barge_reply_id: str | None = None
    epoch: int


class StepClaim(BaseModel):
    """A step's exclusive claim on a conversation, fenced by epoch."""

    model_config = _FROZEN

    conversation_id: str
    user_id: str
    epoch: int


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
