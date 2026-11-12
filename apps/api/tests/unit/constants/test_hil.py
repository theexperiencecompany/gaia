"""The approval decision values the analytics catalog spells on its own side of the shared-lib boundary."""

from typing import Literal, get_args, get_origin

from app.constants.hil import ApprovalDecision
from shared.py.analytics.catalog.hil import ApprovalDecided


def _literal_values(annotation: object) -> set[object]:
    if get_origin(annotation) is Literal:
        return set(get_args(annotation))
    return {value for arg in get_args(annotation) for value in _literal_values(arg)}


def test_the_approval_decided_event_allows_exactly_the_decisions_a_user_can_make() -> None:
    annotation = ApprovalDecided.model_fields["decision"].annotation
    assert _literal_values(annotation) == set(get_args(ApprovalDecision))
