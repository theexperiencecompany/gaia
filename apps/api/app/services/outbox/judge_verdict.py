"""Reading the Judge's answers into a JudgeVerdict: pure, so every threshold is provable without a model.

Both passes answer the same questions. The Decisions API returns a probability per choice; the
reasoning model returns one choice, read as a probability of 1 for it and 0 for the rest.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from app.constants.outbox_judge import (
    JUDGE_GATE_QUESTIONS,
    JUDGE_INTERRUPT_PROBABILITY,
    JUDGE_NO_WAIT,
    JUDGE_NOT_WORTH_PROBABILITY,
    JUDGE_SUSPICIOUS_PROBABILITY,
    JUDGE_TIMELY_PROBABILITY,
    JudgeQuestion,
)
from app.models.quiet_hours_models import QuietHours
from app.services.outbox.judge_models import (
    NOT_WORTH_TELLING,
    Authenticity,
    Deadline,
    JudgePass,
    JudgeVerdict,
    Moment,
    ReasoningAnswer,
    Relevance,
    Sensitivity,
    UrgencyAnswer,
    YesNo,
)
from app.services.outbox.models import UrgencyClass
from app.utils.timezone import Timezone

_NOT_NEW = tuple(relevance for relevance in Relevance if relevance in NOT_WORTH_TELLING)
_WITHIN_1H = timedelta(hours=1)
_ONE_DAY = timedelta(days=1)


class JudgeAnswerError(ValueError):
    """The Judge's answer cannot be read: a choice it was not offered, or a run that does not exist."""


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    """One question's answer: the choice, the probability of each choice, and how sure the model was."""

    choice: str
    probabilities: Mapping[str, float] = field(default_factory=dict)
    confidence: float | None = None

    def probability(self, value: str) -> float:
        """Return P(value); without probabilities, 1 for the chosen value and 0 for the rest."""
        if self.probabilities:
            return self.probabilities.get(value, 0.0)
        return 1.0 if self.choice == value else 0.0


@dataclass(frozen=True, slots=True)
class PassAnswers:
    """What one pass answered; the reasoning pass also carries the free-form facts a choice cannot."""

    answers: Mapping[JudgeQuestion, ChoiceAnswer]
    free_form: ReasoningAnswer | None = None

    def get(self, question: JudgeQuestion) -> ChoiceAnswer:
        """Return the answer to a question; raise when the pass skipped one it must answer."""
        answer = self.answers.get(question)
        if answer is None:
            raise JudgeAnswerError(f"the Judge gave no answer to {question.value}")
        return answer

    def gate_confidence(self) -> float:
        """Return the least confident of the decision-driving questions; a missing confidence is none."""
        return min(self.get(question).confidence or 0.0 for question in JUDGE_GATE_QUESTIONS)


def answers_from_reasoning(answer: ReasoningAnswer) -> PassAnswers:
    """Read the reasoning model's structured answer as one choice per question."""
    chosen: dict[JudgeQuestion, str] = {
        JudgeQuestion.URGENCY: answer.urgency.value,
        JudgeQuestion.DEADLINE: answer.deadline.value,
        JudgeQuestion.RELEVANCE: answer.relevance.value,
        JudgeQuestion.SENSITIVITY: answer.sensitivity.value,
        JudgeQuestion.MOMENT: answer.moment.value,
        JudgeQuestion.AUTHENTICITY: answer.authenticity.value,
        JudgeQuestion.WORTH_TELLING: answer.worth_telling.value,
        JudgeQuestion.WITHIN_MINUTES: answer.within_minutes.value,
        JudgeQuestion.BEFORE_CHECKIN: answer.before_checkin.value,
        JudgeQuestion.WAIT_FOR_RUN: answer.wait_for_run or JUDGE_NO_WAIT,
    }
    return PassAnswers(
        answers={question: ChoiceAnswer(choice) for question, choice in chosen.items()},
        free_form=answer,
    )


@dataclass(frozen=True, slots=True)
class UserClock:
    """The user's own clock: their timezone, and the hours they sleep."""

    timezone: Timezone
    quiet_hours: QuietHours


def deliver_by(deadline: Deadline, now: datetime, clock: UserClock) -> datetime | None:
    """Return the instant a deadline bucket ends at, or None when no instant follows from it."""
    local = clock.timezone.localize(now)
    match deadline:
        case Deadline.WITHIN_1H:
            return now + _WITHIN_1H
        case Deadline.WITHIN_TODAY:
            sleeps = datetime.combine(
                local.date(), time(clock.quiet_hours.start_hour), tzinfo=local.tzinfo
            )
            return max(sleeps.astimezone(UTC), now)
        case Deadline.BEFORE_NEXT_MORNING:
            wakes = datetime.combine(
                local.date(), time(clock.quiet_hours.end_hour), tzinfo=local.tzinfo
            )
            return (wakes if wakes > local else wakes + _ONE_DAY).astimezone(UTC)
        case Deadline.LATER | Deadline.NONE:
            return None


def _urgency(answers: PassAnswers) -> UrgencyClass:
    if (
        answers.get(JudgeQuestion.WITHIN_MINUTES).probability(YesNo.YES)
        >= JUDGE_INTERRUPT_PROBABILITY
    ):
        return UrgencyClass.INTERRUPT
    if answers.get(JudgeQuestion.BEFORE_CHECKIN).probability(YesNo.YES) >= JUDGE_TIMELY_PROBABILITY:
        return UrgencyClass.TIMELY
    urgency = answers.get(JudgeQuestion.URGENCY)
    routine = urgency.probability(UrgencyAnswer.ROUTINE)
    background = urgency.probability(UrgencyAnswer.BACKGROUND)
    return UrgencyClass.ROUTINE if routine >= background else UrgencyClass.BACKGROUND


def _relevance(answers: PassAnswers, not_worth_probability: float) -> Relevance:
    if not_worth_probability < JUDGE_NOT_WORTH_PROBABILITY:
        return Relevance.NEW
    relevance = answers.get(JudgeQuestion.RELEVANCE)
    reasons = {reason: relevance.probability(reason) for reason in _NOT_NEW}
    # Not worth telling with no specific reason named: the criterion is that it no longer matters.
    return (
        max(reasons, key=lambda reason: reasons[reason])
        if any(reasons.values())
        else Relevance.MOOT
    )


def _wait_for_run(answers: PassAnswers, offered_runs: Set[str]) -> str | None:
    answer = answers.answers.get(JudgeQuestion.WAIT_FOR_RUN)
    if answer is None or answer.choice == JUDGE_NO_WAIT:
        return None
    if answer.choice not in offered_runs:
        raise JudgeAnswerError(f"the Judge waits for run {answer.choice!r}, which was not offered")
    return answer.choice


def _reason(answers: PassAnswers) -> str:
    if answers.free_form is not None:
        return answers.free_form.reason
    parts = [
        f"{question.value}={answers.get(question).choice}"
        for question in (
            JudgeQuestion.WORTH_TELLING,
            JudgeQuestion.WITHIN_MINUTES,
            JudgeQuestion.BEFORE_CHECKIN,
            JudgeQuestion.DEADLINE,
        )
    ]
    return "Decisions: " + ", ".join(parts)


def build_verdict(
    answers: PassAnswers,
    *,
    decided_by: JudgePass,
    decisions_confidence: float | None,
    now: datetime,
    clock: UserClock,
    offered_runs: Set[str],
) -> JudgeVerdict:
    """Read one pass's answers into the verdict the Rails apply; raise JudgeAnswerError when they cannot be read."""
    not_worth = answers.get(JudgeQuestion.WORTH_TELLING).probability(YesNo.NO)
    sensitivity = Sensitivity(answers.get(JudgeQuestion.SENSITIVITY).choice)
    free_form = answers.free_form
    deadline = Deadline(answers.get(JudgeQuestion.DEADLINE).choice)
    return JudgeVerdict(
        urgency=_urgency(answers),
        deadline=deadline,
        deliver_by=deliver_by(deadline, now, clock),
        valid_until=free_form.valid_until if free_form else None,
        relevance=_relevance(answers, not_worth),
        relevance_ref=free_form.relevance_ref if free_form else None,
        same_fact_key=free_form.same_fact_key if free_form else None,
        corrects=free_form.corrects if free_form else None,
        sensitivity=sensitivity,
        audience_ok_for_group=sensitivity is Sensitivity.NONE,
        topics=free_form.topics if free_form else [],
        rules_applied=free_form.rules_applied if free_form else [],
        moment=Moment(answers.get(JudgeQuestion.MOMENT).choice),
        suspicious=answers.get(JudgeQuestion.AUTHENTICITY).probability(Authenticity.SUSPICIOUS)
        >= JUDGE_SUSPICIOUS_PROBABILITY,
        wait_for_run=_wait_for_run(answers, offered_runs),
        reason=_reason(answers),
        confidence=decisions_confidence,
        not_worth_probability=not_worth,
        decided_by=decided_by,
    )
