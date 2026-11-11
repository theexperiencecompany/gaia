"""The voice's reader, its unreadable replies and the way a rejected voice is sent back."""

from unittest.mock import AsyncMock

from pydantic import ValidationError
import pytest

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.briefing_prompts import voice_correction_note
from app.models.briefing_models import BriefVoice
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.services.briefing import prose
from app.services.briefing.errors import VoiceUnreadableError
from app.services.briefing.prose import Writing, reader_block, written_brief
from app.services.briefing.slots import BriefFact, SlotValues

pytestmark = pytest.mark.unit

_USER_ID = "64f1c0ffee0000000000abcd"
_VALUES = SlotValues(facts={1: BriefFact(title="Reply to Dan")}, counts={})


def _voice(**fields: str) -> BriefVoice:
    return BriefVoice.model_validate(
        {
            "headline": "A day",
            "lede": "It is a day.",
            "caption": "Reply first.",
            "mood": "packed",
            "message": "[Reply to Dan](fact:1) first.",
            **fields,
        }
    )


class TestReaderBlock:
    def test_the_voice_is_told_the_readers_name_timezone_and_profession(self) -> None:
        user = UserDocument(
            id=_USER_ID,
            name="Ada Lovelace",
            timezone="Asia/Kolkata",
            onboarding=OnboardingSubdocument.model_validate(
                {"preferences": {"profession": "founder"}}
            ),
        )

        assert reader_block(user).splitlines() == [
            "You're writing to Ada. Use their name at most once, only where a friend naturally "
            "would, never as a greeting.",
            "Their timezone: Asia/Kolkata.",
            "User Profession: Founder",
        ]

    def test_a_reader_without_name_timezone_or_profile_is_told_so(self) -> None:
        assert reader_block(UserDocument(id=_USER_ID)).splitlines() == [
            "You don't know their name, so never address them by name.",
            "Their timezone: UTC.",
        ]


class TestAnUnreadableReply:
    async def test_each_field_the_reply_got_wrong_is_named_without_its_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError) as invalid:
            BriefVoice.model_validate({"headline": "x"})
        malformed = MalformedStructuredOutputError("bad", llm_output="half")
        malformed.__cause__ = invalid.value
        monkeypatch.setattr(prose, "ainvoke_structured", AsyncMock(side_effect=malformed))

        with pytest.raises(VoiceUnreadableError) as raised:
            await prose._voice(_USER_ID, "prompt")

        assert raised.value.problems == [
            "lede: Field required",
            "caption: Field required",
            "mood: Field required",
            "message: Field required",
        ]
        assert raised.value.reply == "half"

    async def test_a_reply_with_no_schema_error_is_told_why(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        malformed = MalformedStructuredOutputError("the reply was cut short", llm_output=None)
        monkeypatch.setattr(prose, "ainvoke_structured", AsyncMock(side_effect=malformed))

        with pytest.raises(VoiceUnreadableError) as raised:
            await prose._voice(_USER_ID, "prompt")

        assert raised.value.problems == ["the reply was cut short"]


class TestAVoiceThatBreaksItsFacts:
    async def test_it_is_sent_back_once_with_the_problems_and_its_own_words(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broke = _voice(message="Nothing to say.")
        mended = _voice()
        asked = AsyncMock(side_effect=[broke, mended])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        voice, draft = await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        problem = (
            "the message never refers to the lead, fact 1 (Reply to Dan); say it in your own "
            "words as [your phrase](fact:1)"
        )
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note([problem], broke.model_dump_json(indent=2))}"
        )
        assert (voice, draft.message) == (mended, "Reply to Dan first.")
