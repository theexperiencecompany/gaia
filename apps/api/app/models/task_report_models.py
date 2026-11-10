"""The report an executor run files when it ends: the arguments of finish_task.

The field descriptions are the rules the model reads at the point of filling, so
they state what each field decides, in general terms.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.constants.agents import OutcomeState
from app.constants.task_report import (
    AnswerVerdict,
    FactKind,
    FailureReason,
    FailureRecovery,
    NeedsYouKind,
    TimeMeaning,
)


class _ReportModel(BaseModel):
    """Base of every report model: a field the contract does not name is refused."""

    model_config = ConfigDict(extra="forbid")


class FactTime(_ReportModel):
    """When the fact's thing happens, or the deadline it is due by."""

    at: str = Field(description="ISO 8601 date or datetime, with the day.")
    meaning: TimeMeaning = Field(
        description="happens: an event, flight or meeting. due_by: a deadline someone must meet."
    )
    if_missed: str | None = Field(
        default=None, description="What happens if a deadline is missed, when the source says."
    )


class ReportFact(_ReportModel):
    """One claim the user may be told, with what it rests on."""

    text: str = Field(
        description=(
            "One claim, neutral, as data and not a message; no tool names, ids or internal words. "
            "Answer the user's next question inside it: who, what exactly (the actual ask, decision, "
            "number or change), when, how much, what they must do and by when. Include every "
            "amount with its currency, every date with its day, every time, count and name the "
            "source has, plus the figure they would compare against (the old price, the previous date)."
        )
    )
    kind: FactKind = Field(
        description=(
            "did: you changed something and the system or the other party confirmed it is done. "
            "pending_confirmation: you submitted it and the other side only accepted it or will "
            "confirm later. observed: you read or found it in a source. inferred: your own "
            "conclusion, stated in no source. not_done: a deliverable that did not happen, "
            "including a send that bounced. Coverage gaps belong in scope.gaps, never here. "
            "Never put a conclusion inside an observed fact: it is a separate inferred fact."
        )
    )
    source_call_ids: list[str] = Field(
        default_factory=list,
        description=(
            "ids of the tool calls this fact comes from: the write call for did, "
            "pending_confirmation and not_done, the read for observed. Empty only for inferred."
        ),
    )
    time: FactTime | None = Field(
        default=None, description="Set when the fact has a date or time that matters."
    )
    counterparty: str | None = Field(
        default=None, description="Someone outside the user you acted toward, for what you did."
    )
    quote: str | None = Field(
        default=None, description="Verbatim excerpt, when the exact wording matters."
    )
    unprompted: bool = Field(
        default=False,
        description=(
            "True when you came across it and it affects the user soon although they did not ask: "
            "a deadline, money due or charged, an appointment, travel, a risk."
        ),
    )


class ReportAnswer(_ReportModel):
    """The product of a read-only ask; the points themselves are the facts."""

    recommendation: str | None = Field(
        default=None, description="Your pick, when asked to choose or compare."
    )
    verdict: AnswerVerdict | None = Field(
        default=None, description="The one-word answer to an 'is this true?' question."
    )


class ReportScope(_ReportModel):
    """How much of what there was to read or check was covered."""

    covered: str = Field(description="What you read or checked.")
    complete: bool = Field(description="Whether that was all of it.")
    gaps: list[str] = Field(
        description="What you could not cover, such as messages unread or a source that did not load."
    )


class NeedsYouOption(_ReportModel):
    """One choice the user can make, with what it costs them."""

    label: str = Field(description="The choice, as the user would name it.")
    consequence: str = Field(description="What picking it does, with its price or date.")


class ReportNeedsYou(_ReportModel):
    """What only the user can do to unblock the run."""

    kind: NeedsYouKind = Field(
        description="What is needed. Approvals are reported by the approval system, not here."
    )
    ask: str = Field(description="The one question or step, exact enough to act on.")
    options: list[NeedsYouOption] = Field(
        description="Each option with its consequence; empty when there is no choice."
    )
    expires_at: str | None = Field(
        default=None, description="ISO 8601 time the ask stops mattering, when it does."
    )


class ReportFailure(_ReportModel):
    """Why part or all of the run did not work."""

    reason: FailureReason = Field(description="The cause.")
    recovery: FailureRecovery = Field(
        description=(
            "user_can_rerun: trying again may work. needs_reconnect: a connection is broken or "
            "revoked. none: nothing the user can do."
        )
    )


class TaskReport(_ReportModel):
    """What the run did, in the structure GAIA's voice tells the user from."""

    outcome: OutcomeState | None = Field(
        default=None,
        description=(
            "Where the request stands, relative to what was ASKED. "
            "done: every deliverable was achieved or fully answered; other people's later "
            "actions (a reply, a refund posting, a delivery) are facts, not a reason for partial. "
            "partial: at least one deliverable was achieved and one was not (failed, blocked, "
            "pending confirmation), or a check could not cover what it was asked to; attach "
            "needs_you or failure for the missing part. "
            "failed: no deliverable was achieved because of an error (broken connections are "
            "failed with recovery needs_reconnect); give failure even when related information "
            "was found. "
            "needs_you: nothing was achieved yet and only the user can unblock it (a code, "
            "sign-in, choice, information, payment); for a pending approval leave needs_you "
            "empty, the approval system reports it. "
            "blocked: it cannot proceed; put the exact reason and what would unblock it in result. "
            "schedule: a tracked todo with a schedule or recurrence set in this run, or whose "
            "brief says it wakes you again, will wake GAIA to pick it up (a reminder only pings "
            "the user and does not count). "
            "subscribe: a trigger watch set in this run will. "
            "nothing_new: a scheduled or watch check covered its scope and found nothing worth "
            "telling (always with scope). "
            "no_action_needed: a conditional task whose condition did not hold. "
            "unverified: you cannot tell whether it happened. "
            "cancelled: the user stopped it. "
            "The executor always sets it."
        ),
    )
    facts: list[ReportFact] = Field(
        default_factory=list,
        description=(
            "Every fact the user needs about what was asked. Account for every action: each "
            "successful send, post, booking, payment, change or share gets a did or "
            "pending_confirmation fact with what it contained that matters, and a private detail "
            "about the user or another person that your own send exposed is reported there, "
            "naming who it concerns. Report each action taken under an earlier or standing "
            "permission as its own did fact with the terms you agreed to. Include unprompted "
            "findings, scanning every tool result for deadlines, charges, appointments and risks; "
            "a briefing includes every appointment and commitment today and tomorrow and every "
            "bill or deadline due soon. When two facts together change what the user must do, add "
            "the consequence as an inferred fact. If this run shows something reported earlier "
            "was wrong, add a fact starting 'Correction:' saying what was reported and what is true."
        ),
    )
    answer: ReportAnswer | None = Field(
        default=None, description="Only for read-only asks: your pick or the verdict."
    )
    scope: ReportScope | None = Field(
        default=None,
        description=(
            "Required whenever you read or checked things to answer, brief or monitor, and for "
            "nothing_new: what you covered, whether it was all of it, and the gaps."
        ),
    )
    needs_you: ReportNeedsYou | None = Field(
        default=None, description="What only the user can do to unblock you, with the options."
    )
    failure: ReportFailure | None = Field(
        default=None,
        description="Required when outcome is failed, and whenever part of the work failed.",
    )


class FinishTaskArgs(TaskReport):
    """The arguments of finish_task: the result text, and for the executor the report."""

    result: str = Field(
        description=(
            "The ACTUAL deliverable in full, not a description of what you did. If the task asked "
            "for a list, records or data, include every item with its details; the parent only "
            "sees what you put here."
        )
    )
