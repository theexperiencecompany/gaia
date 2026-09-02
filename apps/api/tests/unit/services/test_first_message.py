"""Exact-string tests for the onboarding first message.

The text is sent verbatim as the user's own turn on every surface (web,
Telegram, WhatsApp, iMessage), so its wording is the contract — a mutation that
changes phrasing, joining, or ordering must go red here.
"""

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_message import NEED_PHRASES, compose_first_message


def _prefs(
    profession: str | None,
    needs: list[OnboardingNeed] | None,
    other_need: str | None = None,
) -> OnboardingPreferences:
    return OnboardingPreferences(profession=profession, needs=needs, other_need=other_need)


class TestComposeFirstMessage:
    def test_founder_with_two_needs(self) -> None:
        assert (
            compose_first_message(_prefs("founder", [OnboardingNeed.INBOX, OnboardingNeed.TODOS]))
            == "Hey. I'm a founder. I'm drowning in email and follow-ups slip through. "
            "Where do we start?"
        )

    def test_single_need_has_no_conjunction(self) -> None:
        assert (
            compose_first_message(_prefs("engineering", [OnboardingNeed.RESEARCH]))
            == "Hey. I'm an engineer. Research eats my evenings. Where do we start?"
        )

    def test_three_needs_use_an_oxford_comma(self) -> None:
        assert compose_first_message(
            _prefs(
                "sales",
                [OnboardingNeed.CALENDAR, OnboardingNeed.BRIEFINGS, OnboardingNeed.MEMORY],
            )
        ) == (
            "Hey. I'm in sales. My week is back-to-back meetings, I start every day behind, "
            "and I repeat myself a lot. Where do we start?"
        )

    def test_all_needs(self) -> None:
        assert compose_first_message(_prefs("student", list(OnboardingNeed))) == (
            "Hey. I'm a student. I'm drowning in email, my week is back-to-back meetings, "
            "I start every day behind, follow-ups slip through, I repeat myself a lot, "
            "research eats my evenings, I do the same chores every single day, "
            "and I want you wherever I am. Where do we start?"
        )

    def test_selection_order_is_preserved(self) -> None:
        """The user's tap order is the sentence order — not the enum's."""
        assert compose_first_message(
            _prefs("founder", [OnboardingNeed.TODOS, OnboardingNeed.INBOX])
        ) == (
            "Hey. I'm a founder. Follow-ups slip through and I'm drowning in email. "
            "Where do we start?"
        )

    def test_other_profession_is_omitted_rather_than_invented(self) -> None:
        assert (
            compose_first_message(_prefs("other", [OnboardingNeed.INBOX]))
            == "Hey. I'm drowning in email. Where do we start?"
        )

    def test_missing_profession_is_omitted(self) -> None:
        assert (
            compose_first_message(_prefs(None, [OnboardingNeed.INBOX]))
            == "Hey. I'm drowning in email. Where do we start?"
        )

    def test_no_needs_leaves_only_the_greeting(self) -> None:
        assert (
            compose_first_message(_prefs("founder", None))
            == "Hey. I'm a founder. Where do we start?"
        )

    def test_empty_preferences(self) -> None:
        assert compose_first_message(_prefs(None, None)) == "Hey. Where do we start?"

    def test_typed_need_follows_the_picked_ones_as_its_own_sentence(self) -> None:
        """Their words are never bent into the list's grammar."""
        assert compose_first_message(
            _prefs("founder", [OnboardingNeed.INBOX], other_need="chasing invoices")
        ) == (
            "Hey. I'm a founder. I'm drowning in email. Also, chasing invoices. Where do we start?"
        )

    def test_typed_need_alone_stands_as_the_sentence(self) -> None:
        assert (
            compose_first_message(_prefs("founder", [], other_need="chasing invoices"))
            == "Hey. I'm a founder. Chasing invoices. Where do we start?"
        )

    @pytest.mark.parametrize("typed", ["chasing invoices.", "chasing invoices!"])
    def test_typed_need_is_not_double_punctuated(self, typed: str) -> None:
        assert (
            compose_first_message(_prefs(None, [OnboardingNeed.INBOX], other_need=typed))
            == "Hey. I'm drowning in email. Also, chasing invoices. Where do we start?"
        )

    def test_blank_typed_need_is_dropped_by_the_model(self) -> None:
        assert (
            compose_first_message(_prefs("founder", [OnboardingNeed.INBOX], other_need="   "))
            == "Hey. I'm a founder. I'm drowning in email. Where do we start?"
        )

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

    @pytest.mark.parametrize(
        ("typed", "expected"),
        [
            # The Q1 field asks "What do you do?", so people answer in sentences;
            # forcing "I'm a" in front of one produced "I'm an I'm a founder...".
            (
                "I'm a founder and designer building a startup",
                "Hey. I'm a founder and designer building a startup. Where do we start?",
            ),
            ("I am a nurse.", "Hey. I am a nurse. Where do we start?"),
            ("I run a bakery", "Hey. I run a bakery. Where do we start?"),
            ("We make climbing shoes", "Hey. We make climbing shoes. Where do we start?"),
            ("a freelance designer", "Hey. I'm a freelance designer. Where do we start?"),
            ("an ops lead", "Hey. I'm an ops lead. Where do we start?"),
            ("the CFO", "Hey. I'm the CFO. Where do we start?"),
        ],
    )
    def test_typed_profession_written_as_a_sentence_is_kept_whole(
        self, typed: str, expected: str
    ) -> None:
        assert compose_first_message(_prefs(typed, None)) == expected

    def test_output_is_stable_across_calls(self) -> None:
        prefs = _prefs("founder", [OnboardingNeed.INBOX, OnboardingNeed.TODOS])
        assert compose_first_message(prefs) == compose_first_message(prefs)

    def test_every_need_has_a_phrase(self) -> None:
        """A new OnboardingNeed member without a phrase would KeyError at runtime."""
        assert set(NEED_PHRASES) == set(OnboardingNeed)
