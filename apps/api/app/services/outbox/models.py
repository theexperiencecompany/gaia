"""What producers submit to the outbox, the states an item moves through, and what compose returns.

A report is facts, never user-facing prose: a RunReport wraps the typed report an
executor run files through finish_task, a NoticeReport is for producers with no model
(reminders). Every enum here is closed: adding a member is a reviewed change.
"""

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.outbox_attention import HoldReason
from app.models.ownership_models import DeliveryPolicy
from app.models.task_report_models import TaskReport
from app.schemas.outbound import OutboundAttachment
from app.services.outbox.prerendered import PrerenderedMessage


class SubjectKind(StrEnum):
    """What a report is about."""

    ASK = "ask"
    WORKFLOW_RUN = "workflow_run"
    TODO_RUN = "todo_run"
    REMINDER = "reminder"
    BROWSER_JOB = "browser_job"
    ACCOUNT = "account"
    APPROVAL = "approval"


class SubjectMerge(StrEnum):
    """How a later report of one subject treats an earlier one that has not been told yet."""

    #: The latest report stands; an older unsent one is superseded.
    REPLACE = "replace"
    #: Every report is told, in one message.
    ACCUMULATE = "accumulate"


class ProducerKind(StrEnum):
    """Which part of GAIA submitted a report."""

    EXECUTOR = "executor"
    WORKFLOW = "workflow"
    TODO = "todo"
    REMINDER = "reminder"
    BROWSER = "browser"
    ARTIFACT = "artifact"
    ACCOUNT = "account"
    APPROVAL = "approval"


class Initiative(StrEnum):
    """Who set the report in motion; the first two make it an answer, never an interruption budget."""

    ASKED = "asked"
    USER_SCHEDULED = "user_scheduled"
    SELF_INITIATED = "self_initiated"


class UrgencyClass(IntEnum):
    """How much a report may interrupt: background < routine < timely < interrupt."""

    BACKGROUND = 0
    ROUTINE = 1
    TIMELY = 2
    INTERRUPT = 3


class NoticeOutcome(StrEnum):
    """Where a notice leaves its subject."""

    INFO = "info"
    NEEDS_YOU = "needs_you"
    FAILED = "failed"
    #: Where a run is on its way; told only to someone watching it live.
    PROGRESS = "progress"


class ComposeMode(StrEnum):
    """What a message is for, which the composer words it by."""

    ANSWER = "answer"
    UNSOLICITED = "unsolicited"
    INTERRUPT = "interrupt"


class ItemState(StrEnum):
    """Where an item is on its way out: received, then queued or settled."""

    RECEIVED = "received"
    QUEUED = "queued"
    #: Decided to be told, at an instant that has not come.
    HELD = "held"
    COMPOSING = "composing"
    SENDING = "sending"
    SENT = "sent"
    DROPPED = "dropped"
    SUPERSEDED = "superseded"
    FAILED = "failed"


#: States an item can still leave: it has not been told, and nothing is telling it.
UNSENT_STATES = frozenset({ItemState.RECEIVED, ItemState.QUEUED, ItemState.HELD})


class DropReason(StrEnum):
    """Why an item is recorded and never alerted."""

    NOTHING_NEW = "nothing_new"
    CANCELLED = "cancelled"
    #: The composer judged it adds nothing the user needs.
    COMPOSE_SKIPPED = "compose_skipped"
    #: Progress nobody was watching live.
    NOT_WATCHING = "not_watching"
    #: Its `valid_until` passed before it could be told.
    EXPIRED = "expired"
    #: The user turned this producer's updates off, and the report needs nothing from them.
    USER_MUTED = "user_muted"
    #: The Judge found it no longer worth telling: the user knows it, it no longer matters, a
    #: newer update replaced it, it repeats one already delivered, or the user does not want it.
    ALREADY_KNOWN = "already_known"
    MOOT = "moot"
    SUPERSEDED = "superseded"
    DUPLICATE = "duplicate"
    UNWANTED = "unwanted"
    #: The user was told this same fact recently and has not acted on it: told again only after a growing wait.
    REPEAT_BACKOFF = "repeat_backoff"
    #: A routine message kept naming GAIA internals through every recompose, so none was sent.
    LEAK_UNRESOLVED = "leak_unresolved"


class ItemFailure(StrEnum):
    """Why an item that should have been told was not."""

    NO_DESTINATION = "no_destination"
    RECORD_FAILED = "record_failed"
    TRANSPORT_SKIPPED = "transport_skipped"
    TRANSPORT_FAILED = "transport_failed"


class MessageState(StrEnum):
    """Where a message is on its way out."""

    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class ItemHold(BaseModel):
    """Why and until when an item waits; kept after its release, so the next hold counts what came before."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: HoldReason
    until: datetime
    since: datetime = Field(description="When the item was first held.")
    deferrals: int = Field(default=0, description="Times it was held to wait for a run.")


class Subject(BaseModel):
    """The thing a report is about, with an id that names the occurrence where the producer recurs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SubjectKind
    id: str = Field(min_length=1)
    owner_conversation_id: str | None = Field(
        default=None, description="The conversation that owns the subject's history."
    )
    label: str = Field(min_length=1, description="What the user calls it.")
    merge: SubjectMerge = SubjectMerge.REPLACE
    #: The recurring producer an occurrence belongs to; what GAIA did with its earlier occurrences is read by it.
    series: str | None = None


class _ReportBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1, description="Names the fact; a second submit is a no-op.")
    recipient: str = Field(min_length=1)
    producer: ProducerKind
    subject: Subject
    occurred_at: datetime
    initiative: Initiative
    delivery_policy: DeliveryPolicy = Field(default_factory=DeliveryPolicy)


class ProducerGuidance(BaseModel):
    """What the user wrote down about a producer, which binds whether and how its results are told."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    standing_rules: str | None = None
    key_details: str | None = None
    #: A producer that runs once exists to answer what the user asked: it is always told.
    runs_once: bool = False
    #: An outside owner sets the report's form: the result is told exactly as written.
    verbatim: bool = False


class ApprovalOutcome(StrEnum):
    """What became of an action the user was asked to approve."""

    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DecidedApproval(BaseModel):
    """An approval the user's run asked for that has since been settled, in the words the user knows it by."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    outcome: ApprovalOutcome


class RunReport(_ReportBase):
    """The report of an executor run: the finish_task report, plus what the code knows of the run."""

    kind: Literal["run"] = "run"
    report: TaskReport
    #: The deliverable the run handed back, which the message is worded from beside the facts.
    result: str = ""
    #: How the run's own calls disagreed with its report; set exactly when the outcome was downgraded.
    review_problem: str | None = None
    #: Why the run interrupts the user's quiet hours, set exactly when its trigger's gate let it through them.
    interrupt_reason: str | None = None
    guidance: ProducerGuidance | None = None
    #: The approvals the run asked for that are settled now; final, whatever the run's own thread says.
    decided_approvals: list[DecidedApproval] = Field(default_factory=list)

    @model_validator(mode="after")
    def _outcome_declared(self) -> Self:
        if self.report.outcome is None:
            raise ValueError("a run report declares its outcome")
        return self


class NoticeReport(_ReportBase):
    """A report from a producer with no model: facts written by the producer's own code."""

    kind: Literal["notice"] = "notice"
    outcome: NoticeOutcome
    facts: list[str] = Field(default_factory=list)
    #: Files the notice carries by reference; the bot fetches the bytes.
    artifacts: list[OutboundAttachment] = Field(default_factory=list)
    #: Fixed copy said as it is, with no model; the notice's facts then name nothing to word.
    prerendered: PrerenderedMessage | None = None
    #: After this instant the notice is no longer worth telling.
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _says_something(self) -> Self:
        if not (self.facts or self.artifacts or self.prerendered):
            raise ValueError("a notice carries facts, artifacts or a prerendered message")
        return self


OutboxReport = Annotated[RunReport | NoticeReport, Field(discriminator="kind")]


def facts_of(report: OutboxReport) -> list[str]:
    """Return what the report says happened, one claim per entry."""
    if isinstance(report, RunReport):
        return [fact.text for fact in report.report.facts]
    return report.facts


class Disposition(StrEnum):
    """What the composer did with one item."""

    INCLUDE = "include"
    SKIP = "skip"


class ItemDisposition(BaseModel):
    """The composer's decision on one item."""

    item_id: str = Field(description="The report_id of the item.")
    action: Disposition = Field(
        description="include: the message says it. skip: it adds nothing the user needs."
    )
    reason: str = Field(description="One line on why, for the log.")


class ComposeResult(BaseModel):
    """What the composer returns: a decision per item, and the message as bubbles."""

    dispositions: list[ItemDisposition] = Field(
        description="Exactly one entry for each item, by item_id."
    )
    parts: list[str] = Field(
        description="The message in GAIA's voice, one entry per bubble; empty when every item is skipped."
    )
