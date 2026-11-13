"""Each decision a user can make maps onto exactly the outcomes the analytics catalog spells for it."""

from typing import get_args

from app.constants.hil import DECISION_OUTCOME, ApprovalDecision
from shared.py.analytics.catalog.hil import ApprovalDecided, DecidedOutcome


def test_every_user_decision_maps_onto_a_distinct_decided_outcome() -> None:
    assert set(DECISION_OUTCOME) == set(get_args(ApprovalDecision))
    assert sorted(DECISION_OUTCOME.values()) == sorted(get_args(DecidedOutcome))


def test_the_approval_decided_event_takes_exactly_the_decided_outcomes() -> None:
    annotation = ApprovalDecided.model_fields["outcome"].annotation
    assert set(get_args(annotation)) == {DecidedOutcome, type(None)}
