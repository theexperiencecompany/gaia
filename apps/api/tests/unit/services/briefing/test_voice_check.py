"""The headline and lede may only claim what the brief's own items show.

Built from a live brief that went out contradicting itself: the headline said
"Arjun's contract redlines need you today" over an empty needs-you section, and
the lede said "1 event today" over an empty calendar.
"""

from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.voice_check import voice_contradictions


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
        )

        assert any("needs the user" in p for p in problems)
        assert any("Arjun" in p for p in problems)

    def test_a_lede_counting_an_event_over_an_empty_calendar_is_rejected(self) -> None:
        problems = voice_contradictions(
            "The investor update draft is done",
            "The Inbox desk also flagged 2 items needing you, and 1 event today.",
            _payload(),
        )

        assert any("event" in p for p in problems)
        assert any("2" in p for p in problems)


class TestProseThatMatchesTheItems:
    def test_counts_names_and_events_from_the_items_pass(self) -> None:
        problems = voice_contradictions(
            "Two replies need you before your 11:00 with Sequoia",
            "Priya wants the pitch deck and Dhruv the offer letter; 1 event today.",
            _payload(sections=_NEEDS_PRIYA, calendar=_SEQUOIA),
        )

        assert problems == []

    @pytest.mark.parametrize(
        "lede",
        ["Nothing on the calendar today.", "No meetings today, and the update is done."],
    )
    def test_saying_the_calendar_is_empty_is_not_an_event_claim(self, lede: str) -> None:
        assert voice_contradictions("The investor update draft is done", lede, _payload()) == []

    def test_a_count_of_items_waiting_must_match_them(self) -> None:
        problems = voice_contradictions(
            "Three replies need you", "", _payload(sections=_NEEDS_PRIYA)
        )

        assert any("3" in p for p in problems)
