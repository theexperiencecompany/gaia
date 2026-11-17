"""The explicit lifecycle of every input, reply, approval and piece of work, as the log folds them.

Each status is a tagged union: a value can only be one phase, with only that phase's fields.
Only app/services/conversation/lifecycle changes them, from log entries.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from shared.py.approvals import ActionResult, ApprovalDecider
from shared.py.conversation_wire import WIRE_CONFIG, FailureReason, ReplyOutcome


class _Status(BaseModel):
    model_config = WIRE_CONFIG


class InputOrigin(StrEnum):
    """What logged a waking input."""

    USER = "user"
    WORKFLOW = "workflow"
    WORK_RESULT = "work_result"
    INTEGRATION = "integration"


class MessageOpen(_Status):
    """No reply, hand-off or Stop has closed the input yet."""

    status: Literal["open"] = "open"


class MessageHandedOff(_Status):
    """The input was handed to work; the reply that reports the work answers it."""

    status: Literal["handed_off"] = "handed_off"
    task_id: str


class MessageAnswered(_Status):
    """A settled reply answered the input."""

    status: Literal["answered"] = "answered"
    reply_id: str
    outcome: Literal[ReplyOutcome.ANSWERED, ReplyOutcome.SILENT, ReplyOutcome.TRUNCATED]


class MessageFailed(_Status):
    """The reply that owed the input an answer failed; the user can retry it."""

    status: Literal["failed"] = "failed"
    reply_id: str
    reason: FailureReason


class MessageStopped(_Status):
    """A Stop covered the input before anything answered it."""

    status: Literal["stopped"] = "stopped"
    stop_seq: int = Field(ge=1)


MessageStatus = Annotated[
    MessageOpen | MessageHandedOff | MessageAnswered | MessageFailed | MessageStopped,
    Field(discriminator="status"),
]
LIVE_MESSAGE_STATUSES = (MessageOpen, MessageHandedOff)


class WorkResult(BaseModel):
    """The finished work a WORK_RESULT input reports, and the user messages that caused it."""

    model_config = WIRE_CONFIG

    task_id: str
    cause_from: int = Field(ge=1)
    cause_through: int = Field(ge=0)
    answers: tuple[str, ...]


class Message(BaseModel):
    """One waking input at its seq, and how far it got."""

    model_config = WIRE_CONFIG

    seq: int = Field(ge=1)
    id: str
    origin: InputOrigin
    status: MessageStatus
    result: WorkResult | None = None

    @model_validator(mode="after")
    def _result_exactly_on_work_results(self) -> "Message":
        if (self.result is None) is (self.origin is InputOrigin.WORK_RESULT):
            raise ValueError("a work result input carries its result, and only one does")
        return self

    @property
    def live(self) -> bool:
        """Return whether the input is still owed something."""
        return isinstance(self.status, LIVE_MESSAGE_STATUSES)


class AttemptStreaming(_Status):
    """The reply is open: the user sees it while its attempt runs."""

    status: Literal["streaming"] = "streaming"
    reply_id: str
    attempt_id: str
    seq: int = Field(ge=1)
    quote_target: str | None


class AttemptSettled(_Status):
    """The reply ended on its own terms; answers are the inputs it closed."""

    status: Literal["settled"] = "settled"
    reply_id: str
    outcome: Literal[
        ReplyOutcome.ANSWERED,
        ReplyOutcome.SILENT,
        ReplyOutcome.TRUNCATED,
        ReplyOutcome.INTERIM,
        ReplyOutcome.STOPPED,
    ]
    answers: tuple[str, ...]


class AttemptFailed(_Status):
    """The reply broke off; the inputs it owed stay retryable."""

    status: Literal["failed"] = "failed"
    reply_id: str
    reason: FailureReason


ReplyAttempt = Annotated[
    AttemptStreaming | AttemptSettled | AttemptFailed, Field(discriminator="status")
]


class WithdrawReason(StrEnum):
    """Why GAIA closed an approval nobody decided."""

    AGENT = "agent"
    RUN_ENDED = "run_ended"
    LOST = "lost"


class ApprovalPending(_Status):
    """Asked and not decided."""

    status: Literal["pending"] = "pending"


class ApprovalApproved(_Status):
    """Approved as asked; action is what running it did so far."""

    status: Literal["approved"] = "approved"
    decider: ApprovalDecider | None
    action: ActionResult | None = None


class ApprovalAmended(_Status):
    """Approved with a change the work applies before running it."""

    status: Literal["amended"] = "amended"
    decider: ApprovalDecider | None
    change: str = Field(min_length=1)
    action: ActionResult | None = None


class ApprovalDenied(_Status):
    """Denied; request is what the user asked for instead."""

    status: Literal["denied"] = "denied"
    decider: ApprovalDecider | None
    request: str | None = None


class ApprovalExpired(_Status):
    """Nobody decided before it lapsed."""

    status: Literal["expired"] = "expired"


class ApprovalWithdrawn(_Status):
    """GAIA closed it undecided."""

    status: Literal["withdrawn"] = "withdrawn"
    reason: WithdrawReason


class ApprovalCancelled(_Status):
    """The user stopped the work, or moved on, before deciding."""

    status: Literal["cancelled"] = "cancelled"


ApprovalStatus = Annotated[
    ApprovalPending
    | ApprovalApproved
    | ApprovalAmended
    | ApprovalDenied
    | ApprovalExpired
    | ApprovalWithdrawn
    | ApprovalCancelled,
    Field(discriminator="status"),
]


class Approval(BaseModel):
    """One approval a run asked for: its number while open, its lapse time and how it ended."""

    model_config = WIRE_CONFIG

    approval_id: str
    # The task that asked it: the approval lives and leaves with that run.
    owner: str
    # None only on a request logged before numbers were stamped.
    number: int | None = Field(default=None, ge=1)
    expires_at: AwareDatetime | None = None
    status: ApprovalStatus

    @property
    def pending(self) -> bool:
        """Return whether the approval still waits on a decision."""
        return isinstance(self.status, ApprovalPending)


class RunMode(StrEnum):
    """How a run sits beside the others: reported, its result landing elsewhere, or alone."""

    ATTACHED = "attached"
    DETACHED = "detached"
    EXCLUSIVE = "exclusive"


class RunRunning(_Status):
    """The run is working; carries are decided approvals it executes for an earlier ask."""

    status: Literal["running"] = "running"
    carries: tuple[str, ...] = ()


class RunAwaitingApproval(_Status):
    """The run waits on approvals it asked for."""

    status: Literal["awaiting_approval"] = "awaiting_approval"
    carries: tuple[str, ...] = ()


class RunParked(_Status):
    """The run ended waiting on its approvals: the decision continues the work, never a narration."""

    status: Literal["parked"] = "parked"


class RunDone(_Status):
    """The run finished."""

    status: Literal["done"] = "done"


class RunFailed(_Status):
    """The run failed."""

    status: Literal["failed"] = "failed"


class RunStopped(_Status):
    """A Stop or a cancellation ended the run."""

    status: Literal["stopped"] = "stopped"


class RunLost(_Status):
    """The run's process died without finishing it."""

    status: Literal["lost"] = "lost"


WorkRunStatus = Annotated[
    RunRunning | RunAwaitingApproval | RunParked | RunDone | RunFailed | RunStopped | RunLost,
    Field(discriminator="status"),
]
LIVE_RUN_STATUSES = (RunRunning, RunAwaitingApproval, RunParked)


class WorkRun(BaseModel):
    """One piece of background work from its start to its end, with every task handed to it."""

    model_config = WIRE_CONFIG

    task_id: str
    cause_from: int = Field(ge=1)
    cause_through: int = Field(ge=0)
    answers: tuple[str, ...]
    joined: tuple[str, ...] = ()
    mode: RunMode
    status: WorkRunStatus

    @property
    def live(self) -> bool:
        """Return whether the run has not ended."""
        return isinstance(self.status, LIVE_RUN_STATUSES)

    @property
    def carries(self) -> tuple[str, ...]:
        """Return the decided approvals the run executes, empty once it waits parked."""
        return (
            self.status.carries if isinstance(self.status, RunRunning | RunAwaitingApproval) else ()
        )


class Lifecycles(BaseModel):
    """Every live member of every lifecycle in a conversation; terminal ones live only in the log."""

    model_config = WIRE_CONFIG

    messages: tuple[Message, ...] = ()
    attempt: AttemptStreaming | None = None
    approvals: tuple[Approval, ...] = ()
    runs: tuple[WorkRun, ...] = ()

    @model_validator(mode="after")
    def _only_live_members_and_owned_waits(self) -> "Lifecycles":
        if not all(message.live for message in self.messages):
            raise ValueError("state holds live inputs only")
        if not all(run.live for run in self.runs):
            raise ValueError("state holds live runs only")
        runs = {run.task_id: run for run in self.runs}
        if any(approval.owner not in runs for approval in self.approvals):
            raise ValueError("an approval lives only beside its owner run")
        waiting = {approval.owner for approval in self.approvals if approval.pending}
        for run in self.runs:
            waits = isinstance(run.status, RunAwaitingApproval | RunParked)
            if waits is not (run.task_id in waiting):
                raise ValueError(
                    f"run {run.task_id} waits exactly while it owns a pending approval"
                )
        return self
