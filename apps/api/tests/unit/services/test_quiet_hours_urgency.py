"""The one quiet-hours urgent question and how its answer is read: one wording, one wake line.

A malformed answer must never read as urgency, so every missing or foreign probability raises
with the answer it read, and an unknown choice names the urgent question it refused.
"""

import pytest

from app.constants.trigger_gates import (
    TRIGGER_GATE_URGENT_CRITERIA,
    TRIGGER_GATE_URGENT_INSTRUCTIONS,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    UrgentChoice,
)
from app.models.jev_models import JevChoiceAnswer, JevDecisionsResponse
from app.services.quiet_hours_urgency import Urgency, read_urgency, urgency, urgent_question

pytestmark = pytest.mark.unit


def _body(probabilities: dict[str, float] | None, choice: str = "can_wait") -> JevDecisionsResponse:
    return JevDecisionsResponse.model_validate(
        {
            "answers": {
                TRIGGER_GATE_URGENT_QUESTION_KEY: {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": probabilities,
                }
            }
        }
    )


def test_the_question_is_the_wording_and_criteria_the_eval_asks() -> None:
    assert urgent_question() == {
        "type": "choice",
        "instructions": TRIGGER_GATE_URGENT_INSTRUCTIONS,
        "criteria": {choice.value: text for choice, text in TRIGGER_GATE_URGENT_CRITERIA.items()},
    }


def test_the_urgency_is_one_minus_can_wait_and_the_choice_it_leans_to() -> None:
    answer = JevChoiceAnswer(choice="can_wait", probabilities={"can_wait": 0.2, "meeting": 0.8})

    assert urgency(answer) == Urgency(probability=0.8, choice=UrgentChoice.MEETING)


def test_an_answer_that_uses_every_label_is_usable() -> None:
    answer = _body({"can_wait": 0.1, "incident": 0.3, "service_down": 0.3, "meeting": 0.3})

    resolved = read_urgency(answer)

    assert (resolved.probability, resolved.choice) == (pytest.approx(0.9), UrgentChoice.INCIDENT)


@pytest.mark.parametrize(
    "probabilities",
    [None, {}, {"can_wait": 0.5, "foreign": 0.5}, {"meeting": 0.5}],
    ids=["none", "empty", "foreign-label", "no-can-wait"],
)
def test_an_answer_with_no_usable_probabilities_is_refused_with_what_it_read(
    probabilities: dict[str, float] | None,
) -> None:
    with pytest.raises(ValueError) as caught:
        read_urgency(_body(probabilities))

    assert str(caught.value) == f"urgent answer has no usable probabilities: {probabilities!r}"


def test_an_unknown_choice_is_refused_by_the_urgent_question_it_answers() -> None:
    with pytest.raises(ValueError) as caught:
        read_urgency(_body({"meeting": 0.5}, choice="maybe"))

    assert str(caught.value) == "unknown JEV urgent choice: 'maybe'"
