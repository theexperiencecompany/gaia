"""Exact-string tests for the seeded "Getting started" conversation.

The composed lines are stored verbatim as GAIA's own turn and are the first
thing every onboarded user reads, so the wording is the contract — a mutation
that changes phrasing, joining, ordering or which lines appear must go red here.
"""

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_conversation import (
    LINE_2,
    REACTIONS,
    compose_first_conversation,
)


def _prefs(
    profession: str | None = "founder",
    needs: list[OnboardingNeed] | None = None,
    other_need: str | None = None,
) -> OnboardingPreferences:
    if needs is None:
        needs = [OnboardingNeed.INBOX]
    return OnboardingPreferences(profession=profession, needs=needs, other_need=other_need)


class TestComposeFirstConversationOpener:
    """The thread opens with the user's own words, assembled from their picks."""

    def test_the_full_case_is_three_sentences_in_first_person(self) -> None:
        composed = compose_first_conversation(
            _prefs(
                profession="founder",
                needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR, OnboardingNeed.BRIEFINGS],
                other_need="chasing suppliers for invoices.",
            ),
            "telegram",
        )
        assert composed.opener == (
            "I'm a founder. Email is out of control, my calendar is back-to-back, and "
            "I wake up already behind. Also, chasing suppliers for invoices."
        )

    def test_an_in_profession_reads_im_in(self) -> None:
        composed = compose_first_conversation(_prefs(profession="sales", needs=[]), None)
        assert composed.opener == "I'm in sales."

    def test_a_vowel_profession_gets_an(self) -> None:
        composed = compose_first_conversation(_prefs(profession="engineering", needs=[]), None)
        assert composed.opener == "I'm an engineer."

    def test_a_typed_sentence_stays_the_users_sentence(self) -> None:
        composed = compose_first_conversation(_prefs(profession="I run a bakery.", needs=[]), None)
        assert composed.opener == "I run a bakery."

    def test_a_typed_title_becomes_im_a(self) -> None:
        composed = compose_first_conversation(_prefs(profession="A Plumber", needs=[]), None)
        assert composed.opener == "I'm a plumber."

    def test_needs_alone_start_with_a_capital(self) -> None:
        composed = compose_first_conversation(
            _prefs(profession=None, needs=[OnboardingNeed.TODOS]), None
        )
        assert composed.opener == "Follow-ups slip through."

    def test_other_is_omitted_rather_than_invented(self) -> None:
        composed = compose_first_conversation(
            _prefs(profession="other", needs=[OnboardingNeed.INBOX]), None
        )
        assert composed.opener == "Email is out of control."

    def test_no_answers_at_all_still_says_something(self) -> None:
        composed = compose_first_conversation(_prefs(profession=None, needs=[]), None)
        assert composed.opener == "Hey."


class TestComposeFirstConversationLines:
    """GAIA answers the first need; she never reads the answers back."""

    def test_the_first_line_answers_the_first_need(self) -> None:
        composed = compose_first_conversation(
            _prefs(needs=[OnboardingNeed.CALENDAR, OnboardingNeed.INBOX]), "telegram"
        )
        assert composed.lines[0] == (
            "Calendar first. If the day is wall to wall, nothing else gets fixed."
        )

    def test_every_need_has_its_own_reaction(self) -> None:
        for need in OnboardingNeed:
            composed = compose_first_conversation(_prefs(needs=[need]), None)
            assert composed.lines[0] == REACTIONS[need]
            assert "So:" not in composed.lines[0]

    def test_no_needs_gets_the_open_reaction(self) -> None:
        composed = compose_first_conversation(_prefs(profession="founder", needs=[]), None)
        assert composed.lines[0] == "Good to know. Let's find out what I can take off you."

    def test_no_answers_at_all_gets_a_plain_hello_back(self) -> None:
        composed = compose_first_conversation(_prefs(profession=None, needs=[]), None)
        assert composed.lines[0] == "Hey. Let's find out what I can take off you."

    def test_the_full_case_reads_as_four_lines(self) -> None:
        composed = compose_first_conversation(
            _prefs(needs=[OnboardingNeed.INBOX], other_need="chasing invoices"), "telegram"
        )
        assert composed.lines == [
            "Email first. It's the one that eats everything else.",
            LINE_2,
            "And I'm in your Telegram now. Text me from there whenever. "
            "If something needs you, I'll text first.",
            "And the chasing invoices part, say the word and I'll start on it.",
        ]

    def test_a_platform_with_no_display_name_is_capitalised(self) -> None:
        composed = compose_first_conversation(_prefs(), "signal")
        assert composed.lines[2].startswith("And I'm in your Signal now.")

    def test_no_platform_drops_the_platform_line(self) -> None:
        composed = compose_first_conversation(_prefs(needs=[OnboardingNeed.INBOX]), None)
        assert composed.lines == [
            "Email first. It's the one that eats everything else.",
            LINE_2,
        ]

    def test_no_other_need_drops_the_last_line(self) -> None:
        composed = compose_first_conversation(_prefs(other_need=None), "telegram")
        assert len(composed.lines) == 3

    def test_imessage_keeps_its_capitalisation(self) -> None:
        composed = compose_first_conversation(_prefs(), "imessage")
        assert composed.lines[2].startswith("And I'm in your iMessage now.")

    def test_the_connect_card_rides_the_gmail_line(self) -> None:
        composed = compose_first_conversation(_prefs(), "telegram")
        assert composed.lines[composed.gmail_card_line] == LINE_2
        assert composed.gmail_card_line == 1


class TestComposeFirstConversationFollowUps:
    def test_other_need_leads_in_the_users_own_words(self) -> None:
        composed = compose_first_conversation(
            _prefs("founder", [OnboardingNeed.INBOX], "chasing invoices"), None
        )
        assert composed.follow_ups == [
            "Help me with chasing invoices",
            "Sort my inbox",
        ]

    def test_chips_follow_the_pick_order(self) -> None:
        composed = compose_first_conversation(
            _prefs("founder", [OnboardingNeed.AUTOMATION, OnboardingNeed.INBOX]), None
        )
        assert composed.follow_ups == ["Automate a chore for me", "Sort my inbox"]

    def test_at_most_three_chips(self) -> None:
        composed = compose_first_conversation(_prefs("founder", list(OnboardingNeed)), None)
        assert composed.follow_ups == [
            "Sort my inbox",
            "What's on my calendar this week?",
            "Set up my morning brief",
        ]

    def test_reach_has_no_chip_of_its_own(self) -> None:
        """ "Reach" is answered by the platform line, not by a chip."""
        composed = compose_first_conversation(_prefs("founder", [OnboardingNeed.REACH]), None)
        assert composed.follow_ups == ["What can you do for me?"]

    def test_the_fallback_is_never_empty(self) -> None:
        composed = compose_first_conversation(_prefs(None, []), None)
        assert composed.follow_ups == ["What can you do for me?"]
