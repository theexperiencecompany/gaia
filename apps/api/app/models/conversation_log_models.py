"""The conversation log: its entries, the state folded from them, and the step's decision types."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.constants.chat import ConversationSource
from app.models.chat_models import ImageData, ReactionBy
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.todo_wake_models import TodoRunWake
from app.models.tool_data_models import ToolDataEntry
from app.models.workflow_models import TriggerType
from app.models.workflow_trigger_models import WorkflowTriggerContext
from shared.py.analytics.catalog.attribution import Attribution
from shared.py.analytics.catalog.properties import Identifier
from shared.py.approvals import ActionResult, ApprovalDecider, ApprovalOutcome

# A defaulted field is always serialized, so the generated client type marks it required.
WIRE_CONFIG = ConfigDict(
    frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
)


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
    # The user spoke over it: the saved reply is what they heard, up to Reply.heard_through.
    TRUNCATED = "truncated"
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

    model_config = WIRE_CONFIG

    emoji: str = Field(min_length=1)
    by: ReactionBy


class _Entry(BaseModel):
    model_config = WIRE_CONFIG

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
    # The browser's PostHog session the message was sent from: what it causes is counted there.
    posthog_session_id: Identifier | None = None
    # Sent at account linking and answered there by the bot's introduction: it wakes no step.
    first_contact: bool = False
    pinned: bool = False
    # Shown on a todo run's wake message written before TodoWoke existed.
    todo_run_wake: TodoRunWake | None = None
    # History the entries migration rewrote: already answered, it wakes no step.
    imported: bool = False
    # Bumped on each in-place update; a client applies an update only when it is newer.
    revision: int = Field(default=0, ge=0)


class StopRequested(_Entry):
    """A Stop: cancels every input and piece of work caused at or before covers_through."""

    kind: Literal[EntryKind.STOP_REQUESTED] = EntryKind.STOP_REQUESTED
    by: StopBy
    # None covers everything before this entry.
    covers_through: int | None = Field(default=None, ge=0)


class BargeIn(_Entry):
    """The user spoke over a voice reply, having heard its text only up to heard_through characters."""

    kind: Literal[EntryKind.BARGE_IN] = EntryKind.BARGE_IN
    reply_id: str
    heard_through: int = Field(ge=0)


class WorkflowRun(BaseModel):
    """What a workflow's turn runs: the workflow, the trigger that fired it, and the fire's bookkeeping."""

    model_config = WIRE_CONFIG

    workflow: SelectedWorkflowData
    # The execution record this run closes; its tool calls are recorded under this id.
    execution_id: str = Field(min_length=1)
    # The zone the run's clock reads, resolved by the fire.
    timezone: str = Field(min_length=1)
    trigger: WorkflowTriggerContext
    # Who fired it, so the run that answers the fire is attributed to its schedule, trigger or user.
    attribution: Attribution


class WorkflowFired(_Entry):
    """A workflow fired into this conversation; it is answered on its own, never merged."""

    kind: Literal[EntryKind.WORKFLOW_FIRED] = EntryKind.WORKFLOW_FIRED
    run: WorkflowRun


class TodoReportForm(StrEnum):
    """What a tracked todo's run owes the user: a write-up, or its report as the todo's guidance formed it."""

    WRITE_UP = "write_up"
    # The reply only decides whether the report goes; the report goes as written.
    AS_WRITTEN = "as_written"


class TodoRun(BaseModel):
    """One run of a tracked todo: the todo, the run, what woke it and the report it owes."""

    model_config = WIRE_CONFIG

    todo_id: str = Field(min_length=1)
    # The run's own id: its finish entry and its durable finish job are keyed by it.
    run_id: str = Field(min_length=1)
    title: str
    trigger_type: TriggerType
    # Read when the run starts: a run that completes its todo tears its watches down.
    runs_once: bool
    wake: TodoRunWake
    report_form: TodoReportForm
    attribution: Attribution


class TodoWoke(_Entry):
    """A tracked todo's run woke; the work it starts answers it, and so does the reply that reports that work."""

    kind: Literal[EntryKind.TODO_WOKE] = EntryKind.TODO_WOKE
    run: TodoRun


class Notice(_Entry):
    """Text delivered to the user outside a step, with the cards of the work it reports."""

    kind: Literal[EntryKind.NOTICE] = EntryKind.NOTICE
    text: str
    origin: str
    tool_data: tuple[ToolDataEntry, ...] = ()
    follow_up_actions: tuple[str, ...] = ()


class WorkStarted(_Entry):
    """Background work dispatched for the inputs through cause_through."""

    kind: Literal[EntryKind.WORK_STARTED] = EntryKind.WORK_STARTED
    task_id: str
    cause_through: int = Field(ge=1)
    answers: tuple[str, ...] = ()
    # The live task this one was handed to while it ran; the two finish, and stop, as one.
    joins: str | None = None
    # A background subagent or browser job: its result lands in another run, so its finish wakes nothing.
    detached: bool = False
    # A workflow's playbook replay: it runs alone, so it never starts beside other work or a fire, nor they beside it.
    exclusive: bool = False


class ApprovalRequested(_Entry):
    """Live work paused on the user's approval."""

    kind: Literal[EntryKind.APPROVAL_REQUESTED] = EntryKind.APPROVAL_REQUESTED
    task_id: str
    approval_id: str
    # What the approval card shows, and when the request lapses (None: it never does).
    summary: str = ""
    expires_at: AwareDatetime | None = None


class ApprovalDecided(_Entry):
    """A pending approval ended; decider names who approved or denied it (None when nobody did).

    An approved action's end is logged as the same decision restated with action set; the latest
    one for an approval is its card's state.
    """

    kind: Literal[EntryKind.APPROVAL_DECIDED] = EntryKind.APPROVAL_DECIDED
    approval_id: str
    outcome: ApprovalOutcome
    decider: ApprovalDecider | None = None
    action: ActionResult | None = None


class WorkFinished(_Entry):
    """Background work ended."""

    kind: Literal[EntryKind.WORK_FINISHED] = EntryKind.WORK_FINISHED
    task_id: str
    outcome: WorkOutcome
    report: str
    # The cards the work showed; the reply that narrates it (reply_id = task_id) carries them.
    tool_data: tuple[ToolDataEntry, ...] = ()
    # What the review of the run's declared outcome adds for the reply; not part of the report.
    note: str = ""
    # The run's own word that its report holds nothing for the user.
    nothing_for_user: bool = False
    # The image the work generated; the reply that narrates it carries it beside its cards.
    image: ImageData | None = None
    # A chat run that left its proposals to the user: the decision starts the work that carries
    # them out, so while one waits this work is not finished. Todo and workflow runs report instead.
    continued_by_decision: bool = False


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
    # A generated image the reply shows, as history the entries migration rewrote stored it.
    image: ImageData | None = None
    # The user message the reply quotes, known when it opens so a first bubble can quote it.
    quote_target: str | None = None
    # Characters of the reply the user heard before a voice barge-in.
    heard_through: int | None = Field(default=None, ge=0)
    pinned: bool = False
    # History the entries migration rewrote: no attempt wrote it, so it opens nothing.
    imported: bool = False
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
    # Settles an imported Reply, which never opened; old history may hold a reply to nothing.
    imported: bool = False

    @model_validator(mode="after")
    def _answers_unless_cut_short(self) -> "ReplySettled":
        if (self.failure is None) is (self.outcome is ReplyOutcome.FAILED):
            raise ValueError("a failed reply names its failure, and only a failed one does")
        if not self.answers and self.outcome not in _MAY_ANSWER_NOTHING and not self.imported:
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

WakingEntry = UserMessage | WorkflowFired | WorkFinished | IntegrationConnected


class LoggedEntry(BaseModel):
    """An entry at its position in the conversation's order."""

    model_config = WIRE_CONFIG

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

    model_config = WIRE_CONFIG

    task_id: str
    cause_through: int
    answers: tuple[str, ...]
    pending_approvals: frozenset[str]
    # Tasks handed to this work while it ran (WorkStarted.joins); a Stop that ends it ends them.
    joined: tuple[str, ...] = ()
    detached: bool = False
    exclusive: bool = False
    # Its run ended while it waited on an approval: the decision continues it, never a narration.
    ended: bool = False


class FinishedWork(BaseModel):
    """A finished task's waking result and the user messages that caused it, until a reply answers it."""

    model_config = WIRE_CONFIG

    seq: int = Field(ge=1)
    task_id: str
    cause_through: int
    answers: tuple[str, ...]


class ConversationState(BaseModel):
    """The fold of a conversation's log; only reduce changes it."""

    model_config = WIRE_CONFIG

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
    # Seqs of WorkflowFired entries in unsettled_waking: a fire while one is here is refused.
    unsettled_fires: tuple[int, ...] = ()

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

    model_config = WIRE_CONFIG


class Preempt(BaseModel):
    """Raise the running step's preempt hint."""

    model_config = WIRE_CONFIG

    stop_through: int | None = None
    barge_reply_id: str | None = None


class CancelWork(BaseModel):
    """Cancel exactly these tasks, and close the approvals they wait on."""

    model_config = WIRE_CONFIG

    task_ids: tuple[str, ...] = Field(min_length=1)
    approval_ids: tuple[str, ...] = ()


class StartAck(BaseModel):
    """React to a user message the moment it is accepted."""

    model_config = WIRE_CONFIG

    message_id: str


Effect = KickStep | Preempt | CancelWork | StartAck


class Transition(BaseModel):
    """An accepted entry's next state and the effects the append must run."""

    model_config = WIRE_CONFIG

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
    FIRE_OVERLAPS = "fire_overlaps"


class Rejected(BaseModel):
    """An entry reduce refused."""

    model_config = WIRE_CONFIG

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

    model_config = WIRE_CONFIG

    start: int = Field(ge=1)
    end: int = Field(ge=1)
    waking: tuple[LoggedEntry, ...]
    first_at: AwareDatetime


class PreemptHint(BaseModel):
    """The advisory head a running step races its model call against."""

    model_config = WIRE_CONFIG

    head: int = Field(ge=0)
    stop_through: int = Field(ge=0)
    barge_reply_id: str | None = None
    epoch: int


class VisibleEntry(BaseModel):
    """An entry the user can see in the conversation: a user message or a reply."""

    model_config = WIRE_CONFIG

    seq: int = Field(ge=1)
    id: str
    is_user_message: bool


class StepClaim(BaseModel):
    """A step's exclusive claim on a conversation, fenced by epoch."""

    model_config = WIRE_CONFIG

    conversation_id: str
    user_id: str
    epoch: int
    # The step was taken from a holder that died, so what it appended may never have been published.
    took_over: bool = False
