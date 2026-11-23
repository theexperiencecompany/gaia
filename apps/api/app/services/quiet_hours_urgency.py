"""The one quiet-hours urgent question every gate asks JEV, and how its answer is read.

Authored gates and the Inbox desk's email verdict both ride it next to their own questions,
so one wording and one wake line, P(urgent) >= 0.80, decide every quiet-hours bypass.
"""

from pydantic import BaseModel, ConfigDict

from app.constants.trigger_gates import (
    QUIET_HOURS_BYPASS_REASONS,
    TRIGGER_GATE_URGENT_CRITERIA,
    TRIGGER_GATE_URGENT_INSTRUCTIONS,
    TRIGGER_GATE_URGENT_PROBABILITY,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    UrgentChoice,
)
from app.models.jev_models import JevChoiceAnswer, JevDecisionsResponse

_URGENT_LABELS = frozenset(TRIGGER_GATE_URGENT_CRITERIA)


class Urgency(BaseModel):
    """How likely an event is worth waking the user for, and the urgent choice JEV leans to."""

    model_config = ConfigDict(frozen=True)

    probability: float
    choice: UrgentChoice

    @property
    def wakes(self) -> bool:
        return self.probability >= TRIGGER_GATE_URGENT_PROBABILITY

    @property
    def reason(self) -> str:
        """Why a wake interrupts quiet hours, as the run says it."""
        return QUIET_HOURS_BYPASS_REASONS[self.choice]


def urgent_question() -> dict[str, object]:
    """Return the urgent question as a Decisions request carries it."""
    return {
        "type": "choice",
        "instructions": TRIGGER_GATE_URGENT_INSTRUCTIONS,
        "criteria": {choice.value: text for choice, text in TRIGGER_GATE_URGENT_CRITERIA.items()},
    }


def urgency(answer: JevChoiceAnswer) -> Urgency:
    """Return P(urgent) as 1 - P(can_wait); raise ValueError without a P(can_wait) to trust.

    A missing can_wait would read as certain urgency, so it is malformed, never a wake.
    """
    probabilities = answer.probabilities
    if (
        not probabilities
        or not probabilities.keys() <= _URGENT_LABELS
        or UrgentChoice.CAN_WAIT not in probabilities
    ):
        raise ValueError(f"urgent answer has no usable probabilities: {probabilities!r}")
    leaning = max(QUIET_HOURS_BYPASS_REASONS, key=lambda choice: probabilities.get(choice, 0.0))
    return Urgency(probability=1 - probabilities[UrgentChoice.CAN_WAIT], choice=leaning)


def read_urgency(body: JevDecisionsResponse) -> Urgency:
    """Return the urgency a Decisions body answered; raise ValueError when it gave none to trust."""
    labels = _URGENT_LABELS
    return urgency(body.choice(TRIGGER_GATE_URGENT_QUESTION_KEY, labels, label="urgent "))
