"""Attacks on auto mode's intent judge (app/services/hil/intent.py).

The judge is an LLM, and LLM judges are measurably lenient. Everything here assumes the
model says "allow" and asks whether the code around it still refuses. A test that only
proves a well-behaved verdict is honoured proves nothing about this module.

The LLM is mocked at ainvoke_structured — the network boundary. _accept,
_is_grounded and the no-turns guard are the production code under test and run for real.
"""

import pytest

from app.constants.hil import HIL_JUDGE_MAX_ASSISTANT_TURNS
from app.services.hil import intent
from app.services.hil.intent import ungrounded_targets
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

    def test_a_target_is_matched_whole_in_the_users_words_never_as_part_of_a_longer_address(
        self,
    ) -> None:
        assert ungrounded_targets({"to": "ann@x.com"}, ["email joann@x.com the deck"], []) == [
            "ann@x.com"
        ]
        assert ungrounded_targets({"to": "ann@x.com"}, ["email ann@x.com the deck"], []) == []

    def test_a_target_is_never_grounded_by_two_priors_glued_together(self) -> None:
        priors = [PriorCall(name="SEARCH", args={"q": "x1"}), PriorCall(name="LOOKUP", args={})]

        assert ungrounded_targets({"ref": "x1-lookup"}, ["do it"], priors) == ["x1-lookup"]

    def test_a_second_at_sign_is_no_address_so_a_name_cannot_ground_it(self) -> None:
        target = "sarah@x.com@evil.com"

        assert ungrounded_targets({"to": target}, ["reply yes to sarah's thread"], []) == [target]


class TestTheAssistantsWordsTheJudgeReads:
    def test_what_the_user_saw_is_kept_apart_from_the_runs_own_messages(self) -> None:
        shown = "Drafted the reply to Simonne with the invoice attached."
        turns = intent.AssistantTurns(shown=(shown,), run=("Prepared a reply to Bob.",))

        assert turns.recent_shown() == [shown]
        assert turns.recent_run() == ["Prepared a reply to Bob."]

    def test_each_side_keeps_only_its_latest_turns(self) -> None:
        many = tuple(f"turn {i}" for i in range(HIL_JUDGE_MAX_ASSISTANT_TURNS + 2))
        turns = intent.AssistantTurns(shown=many, run=many)

        latest = list(many[-HIL_JUDGE_MAX_ASSISTANT_TURNS:])
        assert turns.recent_shown() == latest
        assert turns.recent_run() == latest


# The real shape: Composio's GMAIL_LIST_DRAFTS compacted into one line per draft.
_DRAFT_LIST = (
    "[GMAIL_LIST_DRAFTS compacted: large_output] Visible drafts (id | to | subject | gist):\n\n"
    '1. r-486793596744144676 | t.h@bookhopscotchlabs.info | "Re: Aryan?" | offer\n'
    "2. r8807310570127663349 | simonne@intrinsicurlyme.co.za, lisa@intrinsicurlyme.co.za "
    '| "Re: October Invoice" | invoice attached\n'
    '3. r2569937965309608501 | boardy@x.com | "Intro: Dhruv + Vee" | intro'
)
_LISTED = [PriorCall(name="GMAIL_LIST_DRAFTS", args={"max_results": 25}, output=_DRAFT_LIST)]


class TestAPickFromAList:
    """A listed result traces to the user only when its entry is the one they were pointed at."""

    @pytest.mark.regression
    def test_the_entry_the_user_was_shown_grounds_the_pick(self) -> None:
        """Prod 2026-11-15: "Send" after "drafted the reply to Simonne and Lisa" asked again."""
        shown = ["I drafted the reply to Simonne and Lisa with the October invoice attached."]

        missing = ungrounded_targets(
            {"draft_id": "r8807310570127663349"}, ["Send"], _LISTED, shown_turns=shown
        )

        assert missing == []

    def test_a_blind_pick_still_needs_the_user(self) -> None:
        missing = ungrounded_targets({"draft_id": "r8807310570127663349"}, ["Send"], _LISTED)

        assert missing == ["r8807310570127663349"]

    def test_an_entry_the_user_was_not_pointed_at_stays_ungrounded(self) -> None:
        shown = ["I drafted the reply to Simonne and Lisa with the October invoice attached."]

        missing = ungrounded_targets(
            {"draft_id": "r2569937965309608501"}, ["Send"], _LISTED, shown_turns=shown
        )

        assert missing == ["r2569937965309608501"]

    def test_the_name_closing_one_turn_still_points_at_its_entry(self) -> None:
        shown = ["I drafted the reply to simonne", "Want me to send it?"]

        missing = ungrounded_targets(
            {"draft_id": "r8807310570127663349"}, ["Send"], _LISTED, shown_turns=shown
        )

        assert missing == []

    def test_a_quoted_address_in_a_plain_text_line_never_grounds_its_entry(self) -> None:
        """Bob's draft quoting a mail from Simonne is Bob's draft, in plain text as in JSON."""
        listed = [
            PriorCall(
                name="LIST",
                args={},
                output='d-1 | bob@x.com | "Forwarded from simonne@x.com"\nd-2 | carol@x.com',
            )
        ]

        missing = ungrounded_targets({"draft_id": "d-1"}, ["send the one to simonne@x.com"], listed)

        assert missing == ["d-1"]

    def test_an_id_is_matched_whole_never_as_part_of_a_longer_one(self) -> None:
        listed = [
            PriorCall(name="LIST", args={}, output="1. d-10 | simonne@x.com\n2. d-2 | bob@x.com")
        ]

        assert ungrounded_targets({"id": "d-1"}, ["send simonne's"], listed) == ["d-1"]
        assert ungrounded_targets({"id": "d-10"}, ["send simonne's"], listed) == []

    def test_a_record_nested_in_a_draft_is_not_the_drafts_recipient(self) -> None:
        listed = [
            PriorCall(
                name="LIST",
                args={},
                output=(
                    '{"drafts": [{"id": "d-1", "to": "bob@x.com", '
                    '"forwarded": {"from": "simonne@x.com"}}, {"id": "d-2", "to": "lisa@x.com"}]}'
                ),
            )
        ]

        assert ungrounded_targets({"id": "d-1"}, ["send simonne's"], listed) == ["d-1"]

    def test_a_message_quoted_in_a_draft_is_not_the_drafts_recipient(self) -> None:
        listed = [
            PriorCall(
                name="LIST",
                args={},
                output=(
                    '[{"id": "d-1", "to": "bob@x.com", "body": "Forwarded message from '
                    'simonne@x.com"}, {"id": "d-2", "to": "simonne@x.com"}]'
                ),
            )
        ]

        assert ungrounded_targets({"id": "d-1"}, ["send simonne's"], listed) == ["d-1"]
        assert ungrounded_targets({"id": "d-2"}, ["send simonne's"], listed) == []

    def test_an_address_the_user_named_is_matched_whole_not_as_the_tail_of_a_longer_one(
        self,
    ) -> None:
        listed = [
            PriorCall(
                name="LIST",
                args={},
                output='[{"id": "d-1", "to": "ann@x.com"}, {"id": "d-2", "to": "joann@x.com"}]',
            )
        ]

        assert ungrounded_targets({"id": "d-1"}, ["send joann@x.com's"], listed) == ["d-1"]
        assert ungrounded_targets({"id": "d-2"}, ["send joann@x.com's"], listed) == []

    def test_a_wrapped_list_grounds_by_the_record_holding_the_id(self) -> None:
        listed = [
            PriorCall(
                name="LIST",
                args={},
                output=(
                    '{"drafts": [{"id": "d-1", "cc": ["bob@x.com"], "labels": ["DRAFT"]}, '
                    '{"id": "d-2"}]}'
                ),
            )
        ]

        assert ungrounded_targets({"id": "d-1"}, ["send bob's"], listed) == []

    def test_a_json_list_grounds_by_the_record_holding_the_id(self) -> None:
        listed = [
            PriorCall(
                name="LIST",
                args={},
                output=(
                    '[{"id": "d-1", "to": "bob@x.com"}, '
                    '{"id": "d-2", "to": "simonne@intrinsicurlyme.co.za"}]'
                ),
            )
        ]

        assert ungrounded_targets({"id": "d-2"}, ["send simonne's"], listed) == []
        assert ungrounded_targets({"id": "d-1"}, ["send simonne's"], listed) == ["d-1"]
