"""The brief message may only claim, link and run as long as the app signals shown allow."""

import pytest
from tests.unit.services.briefing.test_voice_check import _NOTHING_SHOWN, _payload

from app.constants.briefing import (
    BRIEF_MESSAGE_CHAR_CEILING,
    BRIEF_MESSAGE_CHARS_PER_SIGNAL,
    MAX_BRIEF_MESSAGE_CHARS,
)
from app.models.scout_models import Signal, SignalImportance
from app.services.briefing.voice_check import (
    message_char_limit,
    message_contradictions,
    voice_contradictions,
    voiced_signals,
)


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
