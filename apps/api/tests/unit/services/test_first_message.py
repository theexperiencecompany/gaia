"""Exact-string tests for the onboarding first message.

The text is sent verbatim as the user's own turn on every surface (web,
Telegram, WhatsApp, iMessage), so its wording is the contract — a mutation that
changes phrasing, joining, or ordering must go red here.
"""

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_message import NEED_PHRASES, compose_first_message


def _prefs(profession: str | None, needs: list[OnboardingNeed] | None) -> OnboardingPreferences:
    return OnboardingPreferences(profession=profession, needs=needs)


class TestComposeFirstMessage:
    def test_founder_with_two_needs(self) -> None:
        assert (
            compose_first_message(
                _prefs("founder", [OnboardingNeed.INBOX, OnboardingNeed.TODOS])
            )
            == "Hi! I'm a founder. I could use help with my inbox and my todos. Who are you?"
        )

    def test_single_need_has_no_conjunction(self) -> None:
        assert (
            compose_first_message(_prefs("engineering", [OnboardingNeed.RESEARCH]))
            == "Hi! I'm an engineer. I could use help with research. Who are you?"
        )

    def test_three_needs_use_an_oxford_comma(self) -> None:
        assert compose_first_message(
            _prefs(
                "sales",
                [OnboardingNeed.CALENDAR, OnboardingNeed.BRIEFINGS, OnboardingNeed.MEMORY],
            )
        ) == (
            "Hi! I'm in sales. I could use help with my calendar, my daily briefings, "
            "and remembering everything. Who are you?"
        )

    def test_all_needs(self) -> None:
        assert compose_first_message(_prefs("student", list(OnboardingNeed))) == (
            "Hi! I'm a student. I could use help with my inbox, my calendar, "
            "my daily briefings, my todos, remembering everything, research, "
            "automating my routines, and reaching me wherever I am. Who are you?"
        )

    def test_selection_order_is_preserved(self) -> None:
        """The user's tap order is the sentence order — not the enum's."""
        assert compose_first_message(
            _prefs("founder", [OnboardingNeed.TODOS, OnboardingNeed.INBOX])
        ) == ("Hi! I'm a founder. I could use help with my todos and my inbox. Who are you?")

    def test_other_profession_is_omitted_rather_than_invented(self) -> None:
        assert (
            compose_first_message(_prefs("other", [OnboardingNeed.INBOX]))
            == "Hi! I could use help with my inbox. Who are you?"
        )

    def test_missing_profession_is_omitted(self) -> None:
        assert (
            compose_first_message(_prefs(None, [OnboardingNeed.INBOX]))
            == "Hi! I could use help with my inbox. Who are you?"
        )

    def test_no_needs_leaves_only_the_greeting(self) -> None:
        assert compose_first_message(_prefs("founder", None)) == "Hi! I'm a founder. Who are you?"

    def test_empty_preferences(self) -> None:
        assert compose_first_message(_prefs(None, None)) == "Hi! Who are you?"

    @pytest.mark.parametrize(
        ("profession", "expected"),
        [
            ("architect", "Hi! I'm an architect. Who are you?"),
            ("chef", "Hi! I'm a chef. Who are you?"),
            ("Founder", "Hi! I'm a founder. Who are you?"),
        ],
    )
    def test_free_form_profession_gets_the_right_article(
        self, profession: str, expected: str
    ) -> None:
        """Settings and pre-Q1 users store arbitrary text here."""
        assert compose_first_message(_prefs(profession, None)) == expected

    def test_output_is_stable_across_calls(self) -> None:
        prefs = _prefs("founder", [OnboardingNeed.INBOX, OnboardingNeed.TODOS])
        assert compose_first_message(prefs) == compose_first_message(prefs)

    def test_every_need_has_a_phrase(self) -> None:
        """A new OnboardingNeed member without a phrase would KeyError at runtime."""
        assert set(NEED_PHRASES) == set(OnboardingNeed)
