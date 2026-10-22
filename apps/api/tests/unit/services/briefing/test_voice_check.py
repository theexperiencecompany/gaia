"""The headline and lede may only claim what the brief's own items show.

Built from a live brief that went out contradicting itself: the headline said
"Arjun's contract redlines need you today" over an empty needs-you section, and
the lede said "1 event today" over an empty calendar.
"""

from typing import Any

import pytest

from app.constants.briefing import (
    BRIEF_MESSAGE_CHAR_CEILING,
    BRIEF_MESSAGE_CHARS_PER_SIGNAL,
    MAX_BRIEF_MESSAGE_CHARS,
)
from app.models.briefing_models import BriefingPayload
from app.models.scout_models import Signal, SignalImportance
from app.services.briefing.voice_check import (
    VoicedCounts,
    message_char_limit,
    message_contradictions,
    voice_contradictions,
    voiced_signals,
)


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
            context="",
        )

        assert any("needs the user" in p for p in problems)
        assert any("Arjun" in p for p in problems)

    def test_a_lede_counting_an_event_over_an_empty_calendar_is_rejected(self) -> None:
        problems = voice_contradictions(
            "The investor update draft is done",
            "The Inbox desk also flagged 2 items needing you, and 1 event today.",
            _payload(),
            _NOTHING_SHOWN,
            context="",
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
            context="",
        )

        assert problems == []

    @pytest.mark.parametrize(
        "lede",
        ["Nothing on the calendar today.", "No meetings today, and the update is done."],
    )
    def test_saying_the_calendar_is_empty_is_not_an_event_claim(self, lede: str) -> None:
        assert (
            voice_contradictions(
                "The investor update draft is done", lede, _payload(), _NOTHING_SHOWN, context=""
            )
            == []
        )

    def test_a_count_of_items_waiting_must_match_them(self) -> None:
        problems = voice_contradictions(
            "Three replies need you",
            "",
            _payload(sections=_NEEDS_PRIYA),
            _NOTHING_SHOWN,
            context="",
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
            voice_contradictions(
                "2 done", "3 running and 4 notes.", payload, _NOTHING_SHOWN, context=""
            )
            == []
        )
        assert voice_contradictions("5 done", "", payload, _NOTHING_SHOWN, context="") == [
            "the prose counts 5, which no item count matches"
        ]

    def test_needs_you_counts_every_item_waiting_on_the_user_and_nothing_else(self) -> None:
        payload = _payload(sections=_items("you", "failed", "lookback"), tallies=_NO_TALLIES)

        assert voice_contradictions("2 need you", "", payload, _NOTHING_SHOWN, context="") == []

    def test_the_done_total_is_both_tallies_added(self) -> None:
        payload = _payload(tallies={"done_by_you": 2, "done_by_gaia": 3})

        assert (
            voice_contradictions("5 things finished", "", payload, _NOTHING_SHOWN, context="") == []
        )

    def test_a_number_the_items_quote_may_be_repeated(self) -> None:
        payload = _payload(sections=_items("lookback", text="Drafted 7 slides"))

        assert (
            voice_contradictions("7 slides drafted", "", payload, _NOTHING_SHOWN, context="") == []
        )

    def test_a_count_shown_to_the_model_may_be_voiced_and_no_other(self) -> None:
        counts = VoicedCounts(waiting_on_you=0, done=0, in_progress=0, while_away=0, open_todos=5)
        payload = _payload(sections=[], tallies=_NO_TALLIES)

        assert voice_contradictions("5 open todos", "", payload, counts, context="") == []
        assert voice_contradictions("6 open todos", "", payload, counts, context="") == [
            "the prose counts 6, which no item count matches"
        ]


class TestNames:
    def test_a_name_only_on_an_events_location_passes(self) -> None:
        calendar = [{"date": "2026-10-14", "start": "11:00", "title": "Lunch", "location": "Thea"}]

        problems = voice_contradictions(
            "Lunch today",
            "Meet at Thea's place.",
            _payload(calendar=calendar),
            _NOTHING_SHOWN,
            context="",
        )

        assert problems == []

    def test_a_name_must_be_a_whole_word_of_the_items_not_part_of_one(self) -> None:
        payload = _payload(sections=_items("lookback", text="Quarterly planning doc"))

        assert voice_contradictions(
            "The plan is set", "Ann's notes are in.", payload, _NOTHING_SHOWN, context=""
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

        assert (
            voice_contradictions(headline, "A quiet day.", payload, _NOTHING_SHOWN, context="")
            == []
        )

    @pytest.mark.parametrize(
        "lede",
        [
            "There are 0 items waiting on you, 0 done, and 0 in progress.",
            "Zero meetings today.",
        ],
    )
    def test_a_zero_count_is_rejected_even_on_an_empty_day(self, lede: str) -> None:
        payload = _payload(sections=[], tallies=_NO_TALLIES)

        assert voice_contradictions("A quiet day", lede, payload, _NOTHING_SHOWN, context="") == [
            "the prose counts 0; leave out what is not there instead of counting it"
        ]

    @pytest.mark.parametrize("term", ["held results", "lane", "sections"])
    def test_an_internal_term_is_rejected(self, term: str) -> None:
        problems = voice_contradictions(
            "A quiet day", f"Nothing in your {term}.", _payload(), _NOTHING_SHOWN, context=""
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
            voice_contradictions(
                "The bike lane petition is drafted", "", payload, _NOTHING_SHOWN, context=""
            )
            == []
        )

    def test_a_negation_in_an_earlier_clause_does_not_cancel_a_later_claim(self) -> None:
        problems = voice_contradictions(
            "Nothing on the calendar, but a reply needs you",
            "",
            _payload(sections=[]),
            _NOTHING_SHOWN,
            context="",
        )

        assert any("needs the user" in p for p in problems)


class TestProblemWording:
    def test_each_contradiction_reads_as_one_plain_sentence(self) -> None:
        problems = voice_contradictions(
            "A reply needs you", "A meeting at noon.", _payload(), _NOTHING_SHOWN, context=""
        )

        assert problems == [
            "the prose says something needs the user, but no item needs them",
            "the prose mentions an event, but today's calendar is empty",
        ]


def _message_problems(
    message: str, payload: BriefingPayload, *, context: str = "", require_coverage: bool = True
) -> list[str]:
    return message_contradictions(
        message,
        payload,
        _NOTHING_SHOWN,
        context=context,
        require_coverage=require_coverage,
    )


def _needs(text: str, kind: str = "you") -> list[dict[str, Any]]:
    return [{"numeral": "I", "title": "NEEDS YOU", "items": [{"text": text, "kind": kind}]}]


@pytest.mark.unit
class TestMessageCoverage:
    """The written message must mention everything waiting on the user and every event."""

    def test_a_message_that_skips_a_needs_you_item_is_rejected(self) -> None:
        payload = _payload(sections=_NEEDS_PRIYA, calendar=[])

        assert _message_problems("Priya's deck is ready for a look.", payload) == [
            "the message never mentions 'Dhruv · offer letter', which is waiting on the user"
        ]

    def test_a_message_that_skips_an_event_is_rejected(self) -> None:
        payload = _payload(calendar=_SEQUOIA)

        assert _message_problems("The investor update draft is done.", payload) == [
            "the message never mentions today's 'Sequoia partner meeting'"
        ]

    def test_a_paraphrase_that_shares_a_word_stem_covers_the_item(self) -> None:
        payload = _payload(sections=_needs("Approve the Stripe invoices"))

        assert _message_problems("Stripe's invoice needs your approval.", payload) == []

    def test_a_failed_item_needs_mentioning_like_any_other_ask(self) -> None:
        payload = _payload(sections=_needs("Sync Stripe invoices", kind="failed"))

        assert _message_problems("Quiet morning.", payload) == [
            "the message never mentions 'Sync Stripe invoices', which is waiting on the user"
        ]

    def test_a_mentioned_event_is_covered(self) -> None:
        payload = _payload(calendar=_SEQUOIA)

        assert _message_problems("The Sequoia meeting is this morning.", payload) == []

    def test_a_shared_common_word_does_not_cover_an_item(self) -> None:
        payload = _payload(sections=_needs("Sign the lease today"))

        assert _message_problems("Quiet today.", payload) == [
            "the message never mentions 'Sign the lease today', which is waiting on the user"
        ]

    def test_a_four_letter_word_is_enough_to_cover_an_item(self) -> None:
        payload = _payload(sections=_needs("Acme contract renewal"))

        assert _message_problems("Acme is waiting on you.", payload) == []

    def test_finished_work_does_not_have_to_be_mentioned(self) -> None:
        assert _message_problems("Quiet morning.", _payload()) == []

    def test_a_winback_or_wind_down_note_is_exempt_from_coverage(self) -> None:
        payload = _payload(sections=_NEEDS_PRIYA, calendar=_SEQUOIA)

        assert _message_problems("Still raising?", payload, require_coverage=False) == []


@pytest.mark.unit
class TestMessageFacts:
    def test_a_name_from_the_rest_of_the_context_is_true(self) -> None:
        problems = _message_problems(
            "The investor update is done, and the deck for Accel is next.",
            _payload(),
            context="Goal: raise a seed round; warm intro to Accel pending",
        )

        assert problems == []

    def test_a_name_in_nothing_the_model_was_shown_is_rejected(self) -> None:
        problems = _message_problems("The investor update is done, so ping Marcus.", _payload())

        assert problems == ["the prose names 'Marcus', who is in no item or event"]

    def test_a_zero_quoted_from_a_title_is_the_title_not_a_count(self) -> None:
        payload = _payload(sections=_needs("Fix the Series 0 deck"))

        assert _message_problems("The Series 0 deck needs a fix.", payload) == []

    def test_a_count_no_fact_supports_is_rejected(self) -> None:
        problems = _message_problems("The investor update is one of 9 things done.", _payload())

        assert problems == ["the prose counts 9, which no item count matches"]

    @pytest.mark.parametrize("dash", ["—", "–"])
    def test_an_em_or_en_dash_is_rejected(self, dash: str) -> None:
        problems = _message_problems(f"The investor update is done {dash} finally.", _payload())

        assert problems == ["the message uses an em or en dash; use commas, periods or parentheses"]

    def test_a_message_exactly_at_the_length_cap_passes(self) -> None:
        message = ("The investor update is done. " * 60)[:MAX_BRIEF_MESSAGE_CHARS]

        assert _message_problems(message, _payload()) == []

    def test_a_message_past_the_length_cap_is_rejected(self) -> None:
        message = "The investor update is done. " * 60

        assert _message_problems(message, _payload()) == [
            f"the message runs {len(message)} characters; keep it under {MAX_BRIEF_MESSAGE_CHARS}"
        ]


def _quiet_signals(count: int) -> list[Signal]:
    return [
        Signal(
            integration_id="todoist",
            app="Todoist",
            external_id=str(n),
            kind="task",
            title=f"Errand {n}",
        )
        for n in range(count)
    ]


@pytest.mark.unit
class TestTheLengthCapScalesWithTheApps:
    def test_with_no_app_signal_the_cap_is_the_base(self) -> None:
        assert message_char_limit(0) == MAX_BRIEF_MESSAGE_CHARS

    def test_each_signal_adds_its_room(self) -> None:
        assert message_char_limit(5) == MAX_BRIEF_MESSAGE_CHARS + 5 * BRIEF_MESSAGE_CHARS_PER_SIGNAL

    def test_no_amount_of_signals_passes_the_ceiling(self) -> None:
        assert message_char_limit(10_000) == BRIEF_MESSAGE_CHAR_CEILING

    @pytest.mark.regression
    def test_a_full_day_of_app_items_gets_the_room_it_needs(self) -> None:
        """Day 2 failed: 1728 characters over 20 signals against a flat 1500 cap."""
        message = ("The investor update is done. " * 60)[:1728]

        problems = message_contradictions(
            message,
            _payload(),
            _NOTHING_SHOWN,
            context="",
            require_coverage=False,
            signals=_quiet_signals(20),
        )

        assert problems == []

    def test_past_the_scaled_cap_the_message_is_rejected_naming_that_cap(self) -> None:
        cap = message_char_limit(2)
        message = ("The investor update is done. " * 80)[: cap + 1]

        problems = message_contradictions(
            message,
            _payload(),
            _NOTHING_SHOWN,
            context="",
            require_coverage=False,
            signals=_quiet_signals(2),
        )

        assert problems == [f"the message runs {cap + 1} characters; keep it under {cap}"]


_VENUE_FACTS = (
    "- done: Offsite venue shortlist | summary: three venues for 24 people, "
    "two breakout rooms, under 6,000 EUR"
)


@pytest.mark.unit
class TestNumbersFromTheFactsShown:
    """Regression for #1166: a figure in an item's summary is a fact, as digits or words."""

    def test_the_headline_and_lede_may_voice_a_summary_figure(self) -> None:
        problems = voice_contradictions(
            "Three venues for 24 people",
            "The shortlist holds 2 breakout rooms each.",
            _payload(),
            _NOTHING_SHOWN,
            context=_VENUE_FACTS,
        )

        assert problems == []

    def test_the_message_may_voice_a_spelled_out_summary_figure_as_a_digit(self) -> None:
        problems = _message_problems(
            "The venue shortlist is done: 3 venues, 24 people, 2 breakout rooms.",
            _payload(),
            context=_VENUE_FACTS,
        )

        assert problems == []

    def test_a_figure_beside_the_summary_is_still_invented(self) -> None:
        problems = _message_problems(
            "The venue shortlist is done: 5 venues for 24 people.",
            _payload(),
            context=_VENUE_FACTS,
        )

        assert problems == ["the prose counts 5, which no item count matches"]

    def test_counting_zero_is_still_rejected_beside_a_summary(self) -> None:
        problems = _message_problems(
            "The venue shortlist is done, with 0 venues over budget.",
            _payload(),
            context=_VENUE_FACTS,
        )

        assert problems == [
            "the prose counts 0; leave out what is not there instead of counting it"
        ]


_REVIEW = Signal(
    integration_id="github",
    app="GitHub",
    external_id="7",
    kind="pull request waiting on your review",
    title="Retry policy for webhooks",
    importance=SignalImportance.HIGH,
    url="https://github.com/acme/api/pull/7",
)
_TICKET = Signal(
    integration_id="linear",
    app="Linear",
    external_id="ENG-3",
    kind="issue assigned to you",
    title="Rotate staging credentials",
    url="https://linear.app/acme/issue/ENG-3",
)
_SIGNALS_SHOWN = f"[GitHub] {_REVIEW.title} link: {_REVIEW.url}\n[Linear] {_TICKET.title}"


def _signal_problems(message: str) -> list[str]:
    return message_contradictions(
        message,
        _payload(),
        _NOTHING_SHOWN,
        context=_SIGNALS_SHOWN,
        require_coverage=True,
        signals=[_REVIEW, _TICKET],
    )


@pytest.mark.unit
class TestSignalClaims:
    def test_an_important_signal_the_message_never_names_is_rejected(self) -> None:
        assert _signal_problems("Rotate staging credentials when you get a minute.") == [
            "the message never mentions 'Retry policy for webhooks' in GitHub, which is important"
        ]

    def test_a_message_naming_every_important_signal_passes(self) -> None:
        assert (
            _signal_problems(f"[The webhook retry policy]({_REVIEW.url}) needs your review.") == []
        )

    def test_a_link_no_fact_carries_is_rejected(self) -> None:
        problems = _signal_problems(
            "The [webhook retry policy](https://github.com/acme/api/pull/8) needs your review."
        )

        assert problems == [
            "the message links to https://github.com/acme/api/pull/8, which no fact carries"
        ]

    def test_a_bare_link_ending_a_sentence_is_the_link_without_the_stop(self) -> None:
        assert _signal_problems(f"The webhook retry policy needs your review: {_REVIEW.url}.") == []

    def test_a_need_is_true_when_only_an_app_needs_the_user(self) -> None:
        problems = voice_contradictions(
            "A review needs you",
            "",
            _payload(),
            _NOTHING_SHOWN,
            context=_SIGNALS_SHOWN,
            signals=[_REVIEW],
        )

        assert problems == []

    def test_the_signals_spoken_of_are_found_by_link_or_by_title(self) -> None:
        message = f"[That PR]({_REVIEW.url}) first. Then the staging credentials."

        assert voiced_signals(message, [_REVIEW, _TICKET]) == [_REVIEW, _TICKET]
        assert voiced_signals("Nothing from your apps today.", [_REVIEW, _TICKET]) == []
