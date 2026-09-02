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
            compose_first_message(_prefs("founder", [OnboardingNeed.INBOX, OnboardingNeed.TODOS]))
            == "Hey. I'm a founder. Mostly need help with my inbox and my todos. Where do we start?"
        )

    def test_single_need_has_no_conjunction(self) -> None:
        assert (
            compose_first_message(_prefs("engineering", [OnboardingNeed.RESEARCH]))
            == "Hey. I'm an engineer. Mostly need help with research. Where do we start?"
        )

    def test_three_needs_use_an_oxford_comma(self) -> None:
        assert compose_first_message(
            _prefs(
                "sales",
                [OnboardingNeed.CALENDAR, OnboardingNeed.BRIEFINGS, OnboardingNeed.MEMORY],
            )
        ) == (
            "Hey. I'm in sales. Mostly need help with my calendar, my daily briefings, "
            "and remembering everything. Where do we start?"
        )

    def test_all_needs(self) -> None:
        assert compose_first_message(_prefs("student", list(OnboardingNeed))) == (
            "Hey. I'm a student. Mostly need help with my inbox, my calendar, "
            "my daily briefings, my todos, remembering everything, research, "
            "automating my routines, and reaching me wherever I am. Where do we start?"
        )

    def test_selection_order_is_preserved(self) -> None:
        """The user's tap order is the sentence order — not the enum's."""
        assert compose_first_message(
            _prefs("founder", [OnboardingNeed.TODOS, OnboardingNeed.INBOX])
        ) == ("Hey. I'm a founder. Mostly need help with my todos and my inbox. Where do we start?")

    def test_other_profession_is_omitted_rather_than_invented(self) -> None:
        assert (
            compose_first_message(_prefs("other", [OnboardingNeed.INBOX]))
            == "Hey. Mostly need help with my inbox. Where do we start?"
        )

    def test_missing_profession_is_omitted(self) -> None:
        assert (
            compose_first_message(_prefs(None, [OnboardingNeed.INBOX]))
            == "Hey. Mostly need help with my inbox. Where do we start?"
        )

    def test_no_needs_leaves_only_the_greeting(self) -> None:
        assert (
            compose_first_message(_prefs("founder", None))
            == "Hey. I'm a founder. Where do we start?"
        )

    def test_empty_preferences(self) -> None:
        assert compose_first_message(_prefs(None, None)) == "Hey. Where do we start?"

    @pytest.mark.parametrize(
        ("profession", "expected"),
        [
            ("architect", "Hey. I'm an architect. Where do we start?"),
            ("chef", "Hey. I'm a chef. Where do we start?"),
            ("Founder", "Hey. I'm a founder. Where do we start?"),
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
