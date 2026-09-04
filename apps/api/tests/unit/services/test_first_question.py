"""Rules for the one LLM-written line of the opening conversation.

The validator is the whole safety story: it is the only thing standing between
a model having an off day and the first sentence every new user reads. So every
rule gets a case that goes red when the rule is deleted, and the fallback path
gets one per failure shape (raised, timed out, unparseable, invalid).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_conversation import (
    compose_first_conversation,
    with_closing_question,
)
from app.services.onboarding.first_question import (
    _QuestionDraft,
    comms_voice_rules,
    compose_first_question,
    validate_draft,
)

MODULE = "app.services.onboarding.first_question"

GOOD_QUESTION = (
    "Founder with the inbox and the calendar on fire. What's actually the fight "
    "this month, product, growth, hiring, or just getting your mornings back?"
)
GOOD_CHIPS = ["Product", "Growth", "Hiring", "My mornings"]


def _prefs(
    profession: str | None = "founder",
    needs: list[OnboardingNeed] | None = None,
    other_need: str | None = None,
) -> OnboardingPreferences:
    return OnboardingPreferences(
        profession=profession,
        needs=needs if needs is not None else [OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
        other_need=other_need,
    )


def _reason(question: str, chips: list[str], preferences: OnboardingPreferences) -> str | None:
    rejection = validate_draft(question, chips, preferences)
    return rejection.reason if rejection else None


@pytest.mark.unit
class TestValidateDraft:
    def test_the_target_shape_passes(self) -> None:
        assert _reason(GOOD_QUESTION, GOOD_CHIPS, _prefs()) is None

    def test_a_statement_is_not_a_question(self) -> None:
        assert _reason("Founder with the inbox on fire.", GOOD_CHIPS, _prefs()) == "not_a_question"

    def test_an_exclamation_mark_is_rejected(self) -> None:
        question = "Founder with the inbox on fire! What's the fight this month?"
        assert _reason(question, GOOD_CHIPS, _prefs()) == "exclamation"

    def test_over_twenty_five_words_is_rejected(self) -> None:
        question = "Founder " + "and the inbox " * 9 + "what now?"
        assert _reason(question, GOOD_CHIPS, _prefs()) == "too_long"

    @pytest.mark.parametrize(
        "question",
        [
            "Founder with the inbox. How can I help you today?",
            "Founder with the inbox. What can I do for you first?",
            "Founder with the inbox. What should I assist with first?",
        ],
    )
    def test_assistant_boilerplate_is_rejected(self, question: str) -> None:
        assert _reason(question, GOOD_CHIPS, _prefs()) == "banned_phrase"

    def test_three_product_surfaces_is_a_feature_list(self) -> None:
        question = "Founder, want the inbox, the calendar, or a morning brief first?"
        assert _reason(question, GOOD_CHIPS, _prefs()) == "feature_list"

    def test_a_question_about_nobody_in_particular_is_rejected(self) -> None:
        assert _reason("So what are we starting on today?", GOOD_CHIPS, _prefs()) == (
            "nothing_they_said"
        )

    @pytest.mark.parametrize("chips", [["Product", "Growth"], ["A", "B", "C", "D", "E"]])
    def test_chips_outside_three_to_four_are_rejected(self, chips: list[str]) -> None:
        assert _reason(GOOD_QUESTION, chips, _prefs()) == "chip_count"

    def test_repeated_chips_are_rejected(self) -> None:
        chips = ["Product", "product", "Hiring"]
        assert _reason(GOOD_QUESTION, chips, _prefs()) == "duplicate_chips"

    def test_a_chip_over_four_words_is_rejected(self) -> None:
        chips = ["Product", "Growth", "Just getting my mornings back"]
        assert _reason(GOOD_QUESTION, chips, _prefs()) == "chip_too_long"

    def test_a_chip_ending_in_punctuation_is_rejected(self) -> None:
        assert _reason(GOOD_QUESTION, ["Product.", "Growth", "Hiring"], _prefs()) == (
            "chip_punctuation"
        )

    def test_the_typed_need_must_survive_into_what_they_see(self) -> None:
        preferences = _prefs(other_need="chasing invoices")
        assert _reason(GOOD_QUESTION, GOOD_CHIPS, preferences) == "other_need_dropped"

    def test_the_typed_need_on_a_chip_is_enough(self) -> None:
        preferences = _prefs(other_need="chasing invoices")
        chips = ["Product", "Growth", "Chasing invoices"]
        assert _reason(GOOD_QUESTION, chips, preferences) is None


@pytest.mark.unit
class TestVoiceRules:
    def test_the_rules_come_from_the_comms_prompt_itself(self) -> None:
        rules = comms_voice_rules()
        assert rules.startswith("## Voice")
        assert "TONE MIRRORING" in rules
        assert "## Length Modes" not in rules


@pytest.mark.unit
class TestComposeFirstQuestion:
    async def test_a_valid_draft_is_returned(self) -> None:
        draft = _QuestionDraft(question=GOOD_QUESTION, chips=GOOD_CHIPS)
        with (
            patch(f"{MODULE}.background_structured_runnable"),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(return_value=draft)),
        ):
            result = await compose_first_question(_prefs(), None)

        assert result is not None
        assert result.question == GOOD_QUESTION
        assert result.chips == GOOD_CHIPS

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), RuntimeError("provider exploded"), ValueError("not valid json")],
    )
    async def test_every_failure_falls_back(self, error: Exception) -> None:
        with (
            patch(f"{MODULE}.background_structured_runnable"),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(side_effect=error)),
        ):
            assert await compose_first_question(_prefs(), None) is None

    async def test_a_draft_breaking_a_rule_falls_back(self) -> None:
        draft = _QuestionDraft(question="How can I help you today?", chips=GOOD_CHIPS)
        with (
            patch(f"{MODULE}.background_structured_runnable"),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(return_value=draft)),
        ):
            assert await compose_first_question(_prefs(), None) is None


@pytest.mark.unit
class TestWithClosingQuestion:
    def test_the_question_replaces_the_static_say_the_word_line(self) -> None:
        preferences = _prefs(other_need="chasing invoices")
        composed = compose_first_conversation(preferences, "telegram")
        assert composed.lines[-1] == (
            "And the chasing invoices part, say the word and I'll start on it."
        )

        updated = with_closing_question(composed, preferences, GOOD_QUESTION, GOOD_CHIPS)

        assert len(updated.lines) == len(composed.lines)
        assert updated.lines[-1] == GOOD_QUESTION
        assert updated.lines[:-1] == composed.lines[:-1]
        assert updated.follow_ups == GOOD_CHIPS
        assert updated.gmail_card_line == composed.gmail_card_line

    def test_without_a_typed_need_the_question_is_appended(self) -> None:
        preferences = _prefs()
        composed = compose_first_conversation(preferences, "telegram")

        updated = with_closing_question(composed, preferences, GOOD_QUESTION, GOOD_CHIPS)

        assert updated.lines == [*composed.lines, GOOD_QUESTION]
        assert updated.follow_ups == GOOD_CHIPS
