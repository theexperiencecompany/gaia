"""Attacks on auto mode's intent judge (app/services/hil/intent.py).

The judge is an LLM, and LLM judges are measurably lenient. Everything here assumes the
model says "allow" and asks whether the code around it still refuses. A test that only
proves a well-behaved verdict is honoured proves nothing about this module.

The LLM is mocked at ainvoke_structured — the network boundary. _accept,
_is_grounded and the no-turns guard are the production code under test and run for real.
"""

import pytest

from app.services.hil.intent import (
    ungrounded_targets,
)
from app.services.hil.utils import (
    PriorCall,
)

MODULE = "app.services.hil.intent"


class TestWhatCountsAsATarget:
    """Only who/which/how-much values need provenance; prose, dates and flags never do."""

    @pytest.mark.parametrize(
        "value",
        [
            "evt-abc",
            "#general",
            "room 42",
            "x" * 22 + "1",
            "1,000,000,000,000,000,000,000",
            "1000000000000000000000000.50",
            "$1000000000000000000000000",
        ],
        ids=["evt-prefix", "channel", "two-words", "23-chars", "commas", "decimal", "dollars"],
    )
    def test_a_reference_or_amount_from_nowhere_is_ungrounded(self, value: str) -> None:
        assert ungrounded_targets({"ref": value}, ["do it"], []) == [value]

    @pytest.mark.parametrize(
        "value",
        ["2026-09-01", "invoice 42 draft", "x" * 23 + "1", "x" * 26 + "1", "plain"],
        ids=["iso-date", "three-words", "24-chars", "27-chars", "no-digit"],
    )
    def test_dates_prose_and_long_tokens_are_not_targets(self, value: str) -> None:
        assert ungrounded_targets({"ref": value}, ["do it"], []) == []

    def test_a_two_character_number_is_a_target(self) -> None:
        assert ungrounded_targets({"count": 42}, ["do it"], []) == ["42"]

    def test_prose_fields_are_skipped_whatever_their_case_and_the_rest_still_count(
        self,
    ) -> None:
        args: dict[str, object] = {"body": "q3", "Subject": "ref 42x", "to": "x@y.com"}

        assert ungrounded_targets(args, ["do it"], []) == ["x@y.com"]

    def test_targets_inside_lists_and_nested_objects_count(self) -> None:
        args: dict[str, object] = {"to": ["a@x.com", "b@x.com"], "meta": {"cc": "c@x.com"}}

        assert ungrounded_targets(args, ["do it"], []) == ["a@x.com", "b@x.com", "c@x.com"]

    def test_an_unparseable_output_that_mentions_the_id_still_grounds_nothing(self) -> None:
        priors = [PriorCall(name="FIND", args={}, output="evt-4 is on friday")]

        assert ungrounded_targets({"event_id": "evt-4"}, ["cancel it"], priors) == ["evt-4"]

    def test_an_output_naming_one_id_among_amounts_still_identifies_it(self) -> None:
        output = '{"id": "d123", "total": "1,000", "tax": "12.50", "tip": "$40"}'
        priors = [PriorCall(name="GET_ORDER", args={}, output=output)]

        assert ungrounded_targets({"order_id": "d123"}, ["refund it"], priors) == []

    def test_a_target_is_never_grounded_by_two_priors_glued_together(self) -> None:
        priors = [PriorCall(name="SEARCH", args={"q": "x1"}), PriorCall(name="LOOKUP", args={})]

        assert ungrounded_targets({"ref": "x1-lookup"}, ["do it"], priors) == ["x1-lookup"]

    def test_a_second_at_sign_is_no_address_so_a_name_cannot_ground_it(self) -> None:
        target = "sarah@x.com@evil.com"

        assert ungrounded_targets({"to": target}, ["reply yes to sarah's thread"], []) == [target]
