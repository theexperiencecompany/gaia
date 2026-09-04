"""Exact-string tests for the seeded "Getting started" conversation.

The composed lines are stored verbatim as GAIA's own turn and are the first
thing every onboarded user reads, so the wording is the contract — a mutation
that changes phrasing, joining, ordering or which lines appear must go red here.
"""

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_conversation import (
    LINE_2,
    compose_first_conversation,
    gmail_connect_tool_data,
)


def _prefs(
    profession: str | None,
    needs: list[OnboardingNeed] | None,
    other_need: str | None = None,
) -> OnboardingPreferences:
    return OnboardingPreferences(profession=profession, needs=needs, other_need=other_need)


class TestComposeFirstConversationLines:
    def test_the_full_case_reads_as_four_lines(self) -> None:
        composed = compose_first_conversation(
            _prefs(
                "founder",
                [OnboardingNeed.INBOX, OnboardingNeed.CALENDAR, OnboardingNeed.BRIEFINGS],
                "chasing invoices",
            ),
            "telegram",
        )
        assert composed.lines == [
            "So: founder, drowning in email, back-to-back meetings, and mornings that "
            "start behind. That's most of a day. I can take a lot of it.",
            "Start with Gmail. Connect it and I'll get into your inbox tonight, sort what "
            "needs you from what doesn't, and have drafts waiting by morning.",
            "And I'm in your Telegram now. Text me from there whenever. If something "
            "needs you, I'll text first.",
            "And the chasing invoices part, say the word and I'll start on it.",
        ]

    def test_a_listed_profession_becomes_a_word(self) -> None:
        composed = compose_first_conversation(
            _prefs("engineering", [OnboardingNeed.RESEARCH]), None
        )
        assert composed.lines[0] == (
            "So: engineer and research eating your evenings. That's most of a day. "
            "I can take a lot of it."
        )

    def test_a_typed_sentence_profession_stays_whole(self) -> None:
        composed = compose_first_conversation(
            _prefs("I run a bakery", [OnboardingNeed.TODOS]), None
        )
        assert composed.lines[0] == (
            "So: I run a bakery and follow-ups slipping through. That's most of a day. "
            "I can take a lot of it."
        )

    def test_a_typed_article_profession_drops_the_article(self) -> None:
        composed = compose_first_conversation(_prefs("A plumber", [OnboardingNeed.MEMORY]), None)
        assert composed.lines[0] == (
            "So: plumber and re-explaining yourself. That's most of a day. I can take a lot of it."
        )

    def test_a_typed_sentence_profession_loses_its_final_punctuation(self) -> None:
        """It is spliced mid-sentence, so a kept full stop reads "So: I do UX. and
        drowning in email." Only the trailing stop goes — letters are not
        punctuation, and "UX" must survive intact."""
        composed = compose_first_conversation(_prefs("I do UX.", [OnboardingNeed.INBOX]), None)
        assert composed.lines[0] == (
            "So: I do UX and drowning in email. That's most of a day. I can take a lot of it."
        )

    def test_an_article_profession_keeps_every_word_after_the_article(self) -> None:
        """Only the article is dropped. Splitting on every space (or from the
        right) silently truncates a multi-word job to one word."""
        composed = compose_first_conversation(
            _prefs("A bakery owner", [OnboardingNeed.MEMORY]), None
        )
        assert composed.lines[0] == (
            "So: bakery owner and re-explaining yourself. That's most of a day. "
            "I can take a lot of it."
        )

    def test_a_double_spaced_article_profession_does_not_keep_the_extra_space(self) -> None:
        """Free text carries typos; splitting on the literal space leaves the
        second one glued to the front of the title, mid-sentence."""
        composed = compose_first_conversation(
            _prefs("A  bakery owner", [OnboardingNeed.MEMORY]), None
        )
        assert composed.lines[0] == (
            "So: bakery owner and re-explaining yourself. That's most of a day. "
            "I can take a lot of it."
        )

    def test_a_platform_with_no_display_name_is_capitalised(self) -> None:
        """PLATFORM_DISPLAY_NAMES only spells the bot platforms. A known source
        outside it still has to name itself — dropping the fallback puts "None"
        in the line the user reads."""
        composed = compose_first_conversation(_prefs("founder", []), "web")
        assert composed.lines[2].startswith("And I'm in your Web now.")

    def test_a_typed_title_is_lowered_mid_sentence(self) -> None:
        composed = compose_first_conversation(_prefs("Engineer", [OnboardingNeed.INBOX]), None)
        assert composed.lines[0] == (
            "So: engineer and drowning in email. That's most of a day. I can take a lot of it."
        )

    def test_other_profession_is_omitted_rather_than_invented(self) -> None:
        composed = compose_first_conversation(_prefs("other", [OnboardingNeed.INBOX]), None)
        assert composed.lines[0] == (
            "So: drowning in email. That's most of a day. I can take a lot of it."
        )

    def test_no_needs_swaps_the_tail(self) -> None:
        composed = compose_first_conversation(_prefs("founder", []), None)
        assert composed.lines[0] == "So: founder. I can take a lot off your plate."

    def test_no_answers_at_all_still_opens(self) -> None:
        composed = compose_first_conversation(_prefs(None, None), None)
        assert composed.lines[0] == "So: you're here. I can take a lot off your plate."

    def test_no_platform_drops_the_platform_line(self) -> None:
        composed = compose_first_conversation(_prefs("founder", [OnboardingNeed.INBOX]), None)
        assert composed.lines == [
            "So: founder and drowning in email. That's most of a day. I can take a lot of it.",
            LINE_2,
        ]

    def test_no_other_need_drops_the_last_line(self) -> None:
        composed = compose_first_conversation(_prefs("founder", [OnboardingNeed.INBOX]), "whatsapp")
        assert len(composed.lines) == 3
        assert composed.lines[2] == (
            "And I'm in your WhatsApp now. Text me from there whenever. If something "
            "needs you, I'll text first."
        )

    def test_imessage_keeps_its_capitalisation(self) -> None:
        composed = compose_first_conversation(_prefs("founder", []), "imessage")
        assert composed.lines[2].startswith("And I'm in your iMessage now.")

    def test_the_connect_card_rides_the_gmail_line(self) -> None:
        composed = compose_first_conversation(_prefs("founder", [OnboardingNeed.INBOX]), None)
        assert composed.lines[composed.gmail_card_line] == LINE_2
        assert gmail_connect_tool_data() == {
            "tool_name": "integration_connection_required",
            "data": {
                "integration_id": "gmail",
                "expired": False,
                "message": "To use Gmail features, please connect your account first.",
            },
        }


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
        composed = compose_first_conversation(_prefs(None, None), None)
        assert composed.follow_ups == ["What can you do for me?"]
