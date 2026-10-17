"""The headline and lede may only claim what the brief's own items show.

Built from a live brief that went out contradicting itself: the headline said
"Arjun's contract redlines need you today" over an empty needs-you section, and
the lede said "1 event today" over an empty calendar.
"""

from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.voice_check import VoicedCounts, voice_contradictions


def _payload(**overrides: Any) -> BriefingPayload:
    data: dict[str, Any] = {
        "kicker": "THE MORNING BRIEF",
        "date": "2026-10-14",
        "headline": "",
        "lede": "",
        "sections": [
            {
                "numeral": "I",
                "title": "GAIA'S WORK",
                "items": [{"text": "Investor update draft for October", "kind": "lookback"}],
            }
        ],
        "calendar": [],
        "tallies": {"done_by_you": 1, "done_by_gaia": 0},
        "mood": "clear",
        "caption": "",
    }
    data.update(overrides)
    return BriefingPayload.model_validate(data)


_NOTHING_SHOWN = VoicedCounts(waiting_on_you=0, done=0, in_progress=0, while_away=0, open_todos=0)

_NEEDS_PRIYA = [
    {
        "numeral": "I",
        "title": "NEEDS YOU",
        "items": [
            {"text": "Priya · pitch deck", "kind": "you", "todo_id": "t1"},
            {"text": "Dhruv · offer letter", "kind": "you", "todo_id": "t2"},
        ],
    }
]
_SEQUOIA = [{"date": "2026-10-14", "start": "11:00", "title": "Sequoia partner meeting"}]


class TestTheLiveContradictions:
    def test_a_headline_naming_a_need_over_an_empty_needs_you_section_is_rejected(
        self,
    ) -> None:
        problems = voice_contradictions(
            "Arjun's contract redlines need you today",
            "The investor update draft is done.",
            _payload(),
            _NOTHING_SHOWN,
        )

        assert any("needs the user" in p for p in problems)
        assert any("Arjun" in p for p in problems)

    def test_a_lede_counting_an_event_over_an_empty_calendar_is_rejected(self) -> None:
        problems = voice_contradictions(
            "The investor update draft is done",
            "The Inbox desk also flagged 2 items needing you, and 1 event today.",
            _payload(),
            _NOTHING_SHOWN,
        )

        assert any("event" in p for p in problems)
        assert any("2" in p for p in problems)


class TestProseThatMatchesTheItems:
    def test_counts_names_and_events_from_the_items_pass(self) -> None:
        problems = voice_contradictions(
            "Two replies need you before your 11:00 with Sequoia",
            "Priya wants the pitch deck and Dhruv the offer letter; 1 event today.",
            _payload(sections=_NEEDS_PRIYA, calendar=_SEQUOIA),
            _NOTHING_SHOWN,
        )

        assert problems == []

    @pytest.mark.parametrize(
        "lede",
        ["Nothing on the calendar today.", "No meetings today, and the update is done."],
    )
    def test_saying_the_calendar_is_empty_is_not_an_event_claim(self, lede: str) -> None:
        assert (
            voice_contradictions(
                "The investor update draft is done", lede, _payload(), _NOTHING_SHOWN
            )
            == []
        )

    def test_a_count_of_items_waiting_must_match_them(self) -> None:
        problems = voice_contradictions(
            "Three replies need you", "", _payload(sections=_NEEDS_PRIYA), _NOTHING_SHOWN
        )

        assert any("3" in p for p in problems)


def _items(*kinds: str, text: str = "a task") -> list[dict[str, Any]]:
    return [{"numeral": "I", "title": "WORK", "items": [{"text": text, "kind": k} for k in kinds]}]


_NO_TALLIES = {"done_by_you": 0, "done_by_gaia": 0}


class TestCounts:
    def test_each_item_kind_can_be_counted_on_its_own(self) -> None:
        payload = _payload(
            sections=_items(*["lookback"] * 2, *["gaia"] * 3, *["note"] * 4), tallies=_NO_TALLIES
        )

        assert (
            voice_contradictions("2 done", "3 running and 4 notes.", payload, _NOTHING_SHOWN) == []
        )
        assert voice_contradictions("5 done", "", payload, _NOTHING_SHOWN) == [
            "the prose counts 5, which no item count matches"
        ]

    def test_needs_you_counts_every_item_waiting_on_the_user_and_nothing_else(self) -> None:
        payload = _payload(sections=_items("you", "failed", "lookback"), tallies=_NO_TALLIES)

        assert voice_contradictions("2 need you", "", payload, _NOTHING_SHOWN) == []

    def test_the_done_total_is_both_tallies_added(self) -> None:
        payload = _payload(tallies={"done_by_you": 2, "done_by_gaia": 3})

        assert voice_contradictions("5 things finished", "", payload, _NOTHING_SHOWN) == []

    def test_a_number_the_items_quote_may_be_repeated(self) -> None:
        payload = _payload(sections=_items("lookback", text="Drafted 7 slides"))

        assert voice_contradictions("7 slides drafted", "", payload, _NOTHING_SHOWN) == []

    def test_a_count_shown_to_the_model_may_be_voiced_and_no_other(self) -> None:
        counts = VoicedCounts(waiting_on_you=0, done=0, in_progress=0, while_away=0, open_todos=5)
        payload = _payload(sections=[], tallies=_NO_TALLIES)

        assert voice_contradictions("5 open todos", "", payload, counts) == []
        assert voice_contradictions("6 open todos", "", payload, counts) == [
            "the prose counts 6, which no item count matches"
        ]


class TestNames:
    def test_a_name_only_on_an_events_location_passes(self) -> None:
        calendar = [{"date": "2026-10-14", "start": "11:00", "title": "Lunch", "location": "Thea"}]

        problems = voice_contradictions(
            "Lunch today", "Meet at Thea's place.", _payload(calendar=calendar), _NOTHING_SHOWN
        )

        assert problems == []

    def test_a_name_must_be_a_whole_word_of_the_items_not_part_of_one(self) -> None:
        payload = _payload(sections=_items("lookback", text="Quarterly planning doc"))

        assert voice_contradictions(
            "The plan is set", "Ann's notes are in.", payload, _NOTHING_SHOWN
        ) == ["the prose names 'Ann', who is in no item or event"]


class TestTheQuietDay:
    """Regression: a day with nothing waiting got no brief, its honest prose rejected x3."""

    @pytest.mark.parametrize(
        "headline",
        [
            "Nothing needs you today",
            "Nobody is waiting on you this morning",
            "No replies need you, and none need your review",
        ],
    )
    def test_saying_nothing_needs_the_user_is_not_a_needs_claim(self, headline: str) -> None:
        payload = _payload(sections=[], tallies=_NO_TALLIES)

        assert voice_contradictions(headline, "A quiet day.", payload, _NOTHING_SHOWN) == []

    @pytest.mark.parametrize(
        "lede",
        [
            "There are 0 items waiting on you, 0 done, and 0 in progress.",
            "Zero meetings today.",
        ],
    )
    def test_a_zero_count_is_rejected_even_on_an_empty_day(self, lede: str) -> None:
        payload = _payload(sections=[], tallies=_NO_TALLIES)

        assert voice_contradictions("A quiet day", lede, payload, _NOTHING_SHOWN) == [
            "the prose counts 0; leave out what is not there instead of counting it"
        ]

    @pytest.mark.parametrize("term", ["held results", "lane", "sections"])
    def test_an_internal_term_is_rejected(self, term: str) -> None:
        problems = voice_contradictions(
            "A quiet day", f"Nothing in your {term}.", _payload(), _NOTHING_SHOWN
        )

        assert problems == [f"the prose names the internal term {term!r}"]

    def test_an_internal_word_quoted_by_an_item_passes(self) -> None:
        payload = _payload(
            sections=[
                {
                    "numeral": "I",
                    "title": "GAIA'S WORK",
                    "items": [{"text": "Bike lane petition", "kind": "lookback"}],
                }
            ]
        )

        assert (
            voice_contradictions("The bike lane petition is drafted", "", payload, _NOTHING_SHOWN)
            == []
        )

    def test_a_negation_in_an_earlier_clause_does_not_cancel_a_later_claim(self) -> None:
        problems = voice_contradictions(
            "Nothing on the calendar, but a reply needs you",
            "",
            _payload(sections=[]),
            _NOTHING_SHOWN,
        )

        assert any("needs the user" in p for p in problems)


class TestProblemWording:
    def test_each_contradiction_reads_as_one_plain_sentence(self) -> None:
        problems = voice_contradictions(
            "A reply needs you", "A meeting at noon.", _payload(), _NOTHING_SHOWN
        )

        assert problems == [
            "the prose says something needs the user, but no item needs them",
            "the prose mentions an event, but today's calendar is empty",
        ]
