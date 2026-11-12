"""The conversation log: its entries, the state folded from them, and the step's decision types."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.constants.chat import ConversationSource
from app.constants.hil import ApprovalResolution
from app.models.chat_models import ReactionBy
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.todo_wake_models import TodoRunWake
from app.models.tool_data_models import ToolDataEntry
from shared.py.analytics.catalog.properties import Identifier

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
    REPLY_SETTLED = "reply_settled"
    INTEGRATION_NEEDED = "integration_needed"
    INTEGRATION_CONNECTED = "integration_connected"


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


class FailureReason(StrEnum):
    """Why a reply failed; a client words the line it shows under the reply from it."""

    # The model call failed (a provider error, a dropped stream).
    MODEL_ERROR = "model_error"
    # The turn ran out of steps before it answered.
    STEP_LIMIT = "step_limit"
    # The process answering died; a later reply answers again.
    SERVER_RESTART = "server_restart"


_MAY_ANSWER_NOTHING = frozenset({ReplyOutcome.STOPPED, ReplyOutcome.FAILED})


class Reaction(BaseModel):
    """An emoji on a user message; a field updated in place, never a state change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    emoji: str = Field(min_length=1)
    by: ReactionBy


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
    # The attached files as stored when the message was accepted, so every device shows them.
    files: tuple[FileData, ...] = ()
    voice: bool = False
    # What reframes the turn, as a chat send carried it: a pinned tool, a workflow to run,
    # a calendar event, the message replied to.
    selected_tool: Identifier | None = None
    tool_category: Identifier | None = None
    selected_workflow: SelectedWorkflowData | None = None
    selected_calendar_event: SelectedCalendarEventData | None = None
    reply_to_message: ReplyToMessageData | None = None
    reaction: Reaction | None = None
    # Bumped on each in-place update; a client applies an update only when it is newer.
    revision: int = Field(default=0, ge=0)


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
    # The live task this one was handed to while it ran; the two finish, and stop, as one.
    joins: str | None = None


class ApprovalRequested(_Entry):
    """Live work paused on the user's approval."""

    kind: Literal[EntryKind.APPROVAL_REQUESTED] = EntryKind.APPROVAL_REQUESTED
    task_id: str
    approval_id: str


class ApprovalDecided(_Entry):
    """A pending approval resolved."""

    kind: Literal[EntryKind.APPROVAL_DECIDED] = EntryKind.APPROVAL_DECIDED
    approval_id: str
    decision: ApprovalResolution


class WorkFinished(_Entry):
    """Background work ended."""

    kind: Literal[EntryKind.WORK_FINISHED] = EntryKind.WORK_FINISHED
    task_id: str
    outcome: WorkOutcome
    report: str
    # The cards the work showed; the reply that narrates it (reply_id = task_id) carries them.
    tool_data: tuple[ToolDataEntry, ...] = ()


class IntegrationNeeded(_Entry):
    """Work in this conversation is waiting on the user to connect an integration."""

    kind: Literal[EntryKind.INTEGRATION_NEEDED] = EntryKind.INTEGRATION_NEEDED
    integration_id: str
    integration_name: str


class IntegrationConnected(_Entry):
    """The user connected an integration this conversation's work was waiting on."""

    kind: Literal[EntryKind.INTEGRATION_CONNECTED] = EntryKind.INTEGRATION_CONNECTED
    integration_id: str
    integration_name: str
    # The IntegrationNeeded entry this connect answers.
    needed_id: str


class Reply(_Entry):
    """GAIA's reply, appended when the user first sees it; its content is filled in place."""

    kind: Literal[EntryKind.REPLY] = EntryKind.REPLY
    reply_id: str
    attempt_id: str
    text: str = ""
    tool_data: tuple[ToolDataEntry, ...] = ()
    follow_up_actions: tuple[str, ...] = ()
    # Characters of the reply the user heard before a voice barge-in.
    heard_through: int | None = Field(default=None, ge=0)
    # Bumped on each in-place fill; a client applies an update only when it is newer.
    revision: int = Field(default=0, ge=0)


class ReplySettled(_Entry):
    """The open reply's attempt ended; through is the newest seq it answered."""

    kind: Literal[EntryKind.REPLY_SETTLED] = EntryKind.REPLY_SETTLED
    reply_id: str
    outcome: ReplyOutcome
    answers: tuple[str, ...]
    # A recovered reply fails through the old settled_through, which is 0 before any reply.
    through: int = Field(ge=0)
    # The user message this reply visibly points at; None when it sits directly under what it answers.
    quote_target: str | None
    # Set exactly when outcome is FAILED.
    failure: FailureReason | None = None

    @model_validator(mode="after")
    def _answers_unless_cut_short(self) -> "ReplySettled":
        if (self.failure is None) is (self.outcome is ReplyOutcome.FAILED):
            raise ValueError("a failed reply names its failure, and only a failed one does")
        if not self.answers and self.outcome not in _MAY_ANSWER_NOTHING:
            raise ValueError(f"a {self.outcome} reply answers at least one entry")
        return self


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
    | Reply
    | ReplySettled
    | IntegrationNeeded
    | IntegrationConnected,
    Field(discriminator="kind"),
]

WakingEntry = UserMessage | BargeIn | WorkflowFired | WorkFinished | IntegrationConnected


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


class DisplayState(StrEnum):
    """The one status a client shows for a conversation."""

    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    AWAITING_APPROVAL = "awaiting_approval"


class LiveWork(BaseModel):
    """Background work that has started and not finished or been stopped."""

    model_config = _FROZEN

    task_id: str
    cause_through: int
    answers: tuple[str, ...]
    pending_approvals: frozenset[str]
    # Tasks handed to this work while it ran (WorkStarted.joins); a Stop that ends it ends them.
    joined: tuple[str, ...] = ()


class FinishedWork(BaseModel):
    """A finished task's waking result and the user messages that caused it, until a reply answers it."""

    model_config = _FROZEN

    seq: int = Field(ge=1)
    task_id: str
    cause_through: int
    answers: tuple[str, ...]


class ConversationState(BaseModel):
    """The fold of a conversation's log; only reduce changes it."""

    model_config = _FROZEN

    head: int = Field(ge=0)
    settled_through: int = Field(ge=0)
    stopped_through: int = Field(ge=0)
    # Seqs of waking entries no reply has answered yet, ascending.
    unsettled_waking: tuple[int, ...]
    comms: CommsPhase
    # The reply whose attempt has not settled yet: set by its Reply, cleared by its ReplySettled.
    open_reply: str | None
    work: tuple[LiveWork, ...]
    # One per WorkFinished seq in unsettled_waking.
    finished_work: tuple[FinishedWork, ...] = ()

    @property
    def display(self) -> DisplayState:
        """Return the status to show: comms first, then approvals, then work.

        An input waiting for its step is already GAIA's to answer, so it shows as thinking.
        """
        if self.comms is not CommsPhase.IDLE or self.unsettled_waking:
            return DisplayState.THINKING
        if any(item.pending_approvals for item in self.work):
            return DisplayState.AWAITING_APPROVAL
        return DisplayState.WORKING if self.work else DisplayState.IDLE


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
    REPLY_ALREADY_OPEN = "reply_already_open"
    REPLY_NOT_OPEN = "reply_not_open"
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


class VisibleEntry(BaseModel):
    """An entry the user can see in the conversation: a user message or a reply."""

    model_config = _FROZEN

    seq: int = Field(ge=1)
    id: str
    is_user_message: bool


class StepClaim(BaseModel):
    """A step's exclusive claim on a conversation, fenced by epoch."""

    model_config = _FROZEN

    conversation_id: str
    user_id: str
    epoch: int
