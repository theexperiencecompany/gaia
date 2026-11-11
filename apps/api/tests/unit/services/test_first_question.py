"""Rules for the one LLM-written line of the opening conversation.

The validator is the whole safety story: it is the only thing standing between
a model having an off day and the first sentence every new user reads. So every
rule gets a case that goes red when the rule is deleted, and the fallback path
gets one per failure shape (raised, timed out, unparseable, invalid).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_question import (
    _QuestionDraft,
    answers_fingerprint,
    comms_voice_rules,
    compose_first_question,
)

MODULE = "app.services.onboarding.first_question"

GOOD_CHIPS = ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]


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


@pytest.mark.unit
class TestVoiceRules:
    def test_the_rules_come_from_the_comms_prompt_itself(self) -> None:
        rules = comms_voice_rules()
        assert rules.startswith("## Voice")
        assert "MATCH THEM." in rules
        assert "## Reply, react, or stay silent" not in rules


@pytest.mark.unit
class TestComposeFirstQuestion:
    async def test_a_valid_draft_is_returned(self) -> None:
        draft = _QuestionDraft(chips=GOOD_CHIPS)
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(return_value=draft)),
        ):
            result = await compose_first_question(_prefs(), None)

        assert result is not None
        assert result.chips == GOOD_CHIPS

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), RuntimeError("provider exploded"), ValueError("not valid json")],
    )
    async def test_every_failure_falls_back(self, error: Exception) -> None:
        with (
            patch(f"{MODULE}.ainvoke_structured", AsyncMock(side_effect=error)),
        ):
            assert await compose_first_question(_prefs(), None) is None


@pytest.mark.unit
class TestAnswersFingerprint:
    def test_the_same_answers_hash_the_same(self) -> None:
        assert answers_fingerprint(_prefs()) == answers_fingerprint(_prefs())

    def test_casing_and_padding_are_the_same_answers(self) -> None:
        assert answers_fingerprint(_prefs(profession="Founder ")) == answers_fingerprint(_prefs())
