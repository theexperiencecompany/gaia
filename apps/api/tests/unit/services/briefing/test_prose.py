"""The voice's reader, its unreadable replies and the way a rejected voice is sent back."""

from unittest.mock import AsyncMock

from pydantic import ValidationError
import pytest

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.briefing_prompts import RecentLines, voice_correction_note
from app.models.briefing_models import BriefVoice
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.services.briefing import prose
from app.services.briefing.errors import VoiceUnreadableError
from app.services.briefing.prose import Writing, opening_line, reader_block, written_brief
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


class TestAVoiceThatRepeatsOrOverclaims:
    """A line a recent brief printed, or a claim of how often something happens, is sent back."""

    @staticmethod
    def _asked(monkeypatch: pytest.MonkeyPatch, *voices: BriefVoice) -> AsyncMock:
        asked = AsyncMock(side_effect=list(voices))
        monkeypatch.setattr(prose, "ainvoke_structured", asked)
        return asked

    async def test_a_headline_or_opening_a_recent_brief_printed_is_sent_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _voice(
            headline="An open day, with room to reset",
            message="[Reply to Dan](fact:1) before lunch.\n\nThen nothing.",
        )
        asked = self._asked(monkeypatch, stale, _voice())
        recent = RecentLines(
            headlines=["An open day with room to reset."],
            openings=["Reply to Dan before lunch."],
        )

        voice, _ = await written_brief(
            _USER_ID, "PROMPT", Writing(values=_VALUES, lead=1, recent=recent)
        )

        problems = [
            "the headline repeats a recent brief's line ('An open day, with room to reset'); "
            "write today's in fresh words",
            "the message's opening repeats a recent brief's line ('Reply to Dan before lunch.'); "
            "write today's in fresh words",
        ]
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note(problems, stale.model_dump_json(indent=2))}"
        )
        assert voice == _voice()

    async def test_a_frequency_no_fact_states_is_sent_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rare = _voice(caption="A rare blank square on the calendar.", lede="Clear, as usual.")
        asked = self._asked(monkeypatch, rare, _voice())

        await written_brief(
            _USER_ID,
            "PROMPT",
            Writing(values=_VALUES, lead=1, grounds="The user's calendar has nothing today."),
        )

        problems = [
            "the lede says how often something happens ('usual') and no fact says so; "
            "say only what today's facts show",
            "the caption says how often something happens ('rare') and no fact says so; "
            "say only what today's facts show",
        ]
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note(problems, rare.model_dump_json(indent=2))}"
        )

    async def test_a_frequency_a_fact_states_may_be_voiced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grounded = _voice(caption="Rarely this quiet.")
        asked = self._asked(monkeypatch, grounded)

        voice, _ = await written_brief(
            _USER_ID,
            "PROMPT",
            Writing(values=_VALUES, lead=1, grounds="Calendar: rarely this quiet in a month."),
        )

        assert voice == grounded
        asked.assert_awaited_once()


@pytest.mark.parametrize(
    ("message", "opening"),
    [("\n  Priya replied overnight.\nMore.", "Priya replied overnight."), (" \n\t\n", "")],
    ids=["first-non-blank-line", "all-blank"],
)
def test_a_messages_opening_is_its_first_non_blank_line(message: str, opening: str) -> None:
    assert opening_line(message) == opening
