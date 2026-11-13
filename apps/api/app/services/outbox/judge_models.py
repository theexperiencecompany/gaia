"""What the Judge decides about one item: the verdict, and the closed vocabularies it is made of.

The verdict is stored on the item, so "why didn't you tell me?" is answered from it.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.services.outbox.models import UrgencyClass


class Relevance(StrEnum):
    """Whether the user still needs to be told, and if not, why."""

    NEW = "new"
    ALREADY_KNOWN = "already_known"
    MOOT = "moot"
    SUPERSEDED = "superseded"
    DUPLICATE = "duplicate"
    UNWANTED = "unwanted"


#: The relevances that record an item and never alert it.
NOT_WORTH_TELLING = frozenset(set(Relevance) - {Relevance.NEW})


class Sensitivity(StrEnum):
    """What could hurt if someone else saw the fact (lock screen, shared device, group)."""

    NONE = "none"
    PERSONAL = "personal"
    HEALTH = "health"
    FINANCE = "finance"
    CREDENTIALS = "credentials"
    THIRD_PARTY_PRIVATE = "third_party_private"
    SOCIAL_PRIVATE = "social_private"


#: What a lock screen never previews and a speaker never says aloud.
PRIVATE_SENSITIVITIES = frozenset(
    {Sensitivity.HEALTH, Sensitivity.FINANCE, Sensitivity.CREDENTIALS, Sensitivity.SOCIAL_PRIVATE}
)


class Moment(StrEnum):
    """Whether now is a bad moment to tell the user, whatever the urgency."""

    OK = "ok"
    HOLD = "hold"
    SOFTEN = "soften"


class Deadline(StrEnum):
    """When telling the user stops being useful, relative to now."""

    WITHIN_1H = "within_1h"
    WITHIN_TODAY = "within_today"
    BEFORE_NEXT_MORNING = "before_next_morning"
    LATER = "later"
    NONE = "none"


class UrgencyAnswer(StrEnum):
    """The urgency question's choices, named as the UrgencyClass members they become."""

    BACKGROUND = "background"
    ROUTINE = "routine"
    TIMELY = "timely"
    INTERRUPT = "interrupt"


class Authenticity(StrEnum):
    """Whether an update looks genuine."""

    GENUINE = "genuine"
    SUSPICIOUS = "suspicious"


class YesNo(StrEnum):
    """The answer to a decision question."""

    YES = "yes"
    NO = "no"


class JudgePass(StrEnum):
    """Which pass decided the verdict."""

    DECISIONS = "decisions"
    REASONING = "reasoning"


class JudgeUnavailableCause(StrEnum):
    """Why an item was decided without the Judge."""

    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


class ReasoningAnswer(BaseModel):
    """What the reasoning model returns: the Decisions questions, answered, and the free-form facts they cannot carry."""

    model_config = ConfigDict(extra="forbid")

    urgency: UrgencyAnswer
    deadline: Deadline
    relevance: Relevance
    sensitivity: Sensitivity
    moment: Moment
    authenticity: Authenticity
    worth_telling: YesNo
    within_minutes: YesNo
    before_checkin: YesNo
    wait_for_run: str | None = Field(
        description="The id of the one run in state.upcoming_runs to wait for, or null to tell it now."
    )
    reason: str = Field(description="One short line on why, for the log.")
    relevance_ref: str | None = Field(
        description="When relevance is not new: the subject or fact it relates to."
    )
    same_fact_key: str | None = Field(
        description="A short stable key for the real-world fact, equal for the same fact from any producer."
    )
    corrects: str | None = Field(
        description="When this contradicts something GAIA already told the user: what it corrects."
    )
    valid_until: datetime | None = Field(
        description="When the content stops being true or useful, when it does."
    )
    topics: list[str] = Field(description="Short topic tags for mutes and rules.")
    rules_applied: list[str] = Field(
        description="The user's own rules or profile answers that shaped the answers."
    )


class JudgeVerdict(BaseModel):
    """What one item means for this user now, as the Judge read it, before the Rails apply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    urgency: UrgencyClass
    deadline: Deadline
    deliver_by: datetime | None = Field(
        default=None, description="After this, telling the user loses most of its value."
    )
    valid_until: datetime | None = Field(
        default=None, description="After this, the content is wrong or useless."
    )
    relevance: Relevance
    relevance_ref: str | None = Field(
        default=None, description="The subject or fact the relevance relates to."
    )
    same_fact_key: str | None = Field(
        default=None, description="Stable key of the real-world fact, for cross-producer dedupe."
    )
    corrects: str | None = Field(
        default=None, description="Ref of a delivered fact this contradicts."
    )
    sensitivity: Sensitivity
    audience_ok_for_group: bool
    topics: list[str] = Field(default_factory=list)
    rules_applied: list[str] = Field(default_factory=list)
    moment: Moment
    suspicious: bool = Field(description="Looks like phishing or a scam: warn, never relay.")
    wait_for_run: str | None = Field(
        default=None, description="The upcoming run this item should be merged with."
    )
    wait_run_at: datetime | None = Field(
        default=None, description="When the run wait_for_run names starts."
    )
    wait_run_hit_rate: float | None = Field(
        default=None, description="The share of that run's last runs that produced something told."
    )
    reason: str
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="The Decisions pass's least confident decision question; None when that pass failed.",
    )
    not_worth_probability: float = Field(
        ge=0.0, le=1.0, description="How sure the Judge is that the item is not worth telling."
    )
    decided_by: JudgePass


class ItemJudgement(BaseModel):
    """What the Judge and the Rails made of an item, kept on it: the verdict, or that there was none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: JudgeVerdict | None = Field(
        default=None, description="None when the Judge was not asked or could not answer."
    )
    judge_unavailable: bool = Field(
        default=False,
        description="Both passes failed: the Rails decided from the producer's hints.",
    )
    raised_interrupt: bool = Field(
        default=False,
        description="The Judge raised this item to interrupt; it counts against the daily cap.",
    )
    sensitivity: Sensitivity = Sensitivity.NONE
