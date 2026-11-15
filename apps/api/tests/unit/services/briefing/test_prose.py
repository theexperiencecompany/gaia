"""The voice's reader, its unreadable replies and the way a rejected voice is sent back."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import pytest
from tests.helpers import captured_wide_event

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.briefing_prompts import RecentLines, voice_correction_note
from app.constants.briefing import BriefOutcome
from app.constants.todos import GAIA_TRACKED_LABEL, WaitingOn
from app.models.briefing_models import BriefingItem, BriefingSection, BriefVoice
from app.models.todo_models import TodoDocument
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.services.briefing import prose
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.candidates.tracked import gaia_work_candidates
from app.services.briefing.context import TrackedWork, UserClock
from app.services.briefing.errors import VoiceUnreadableError
from app.services.briefing.facts import TODAY, FactSources, build_facts
from app.services.briefing.prose import Writing, opening_line, reader_block, written_brief
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import BriefFact, SlotValues

pytestmark = pytest.mark.unit

_USER_ID = "64f1c0ffee0000000000abcd"
_VALUES = SlotValues(facts={1: BriefFact(title="Reply to Dan")}, counts={})
_TZ = ZoneInfo("Asia/Kolkata")
_NOW = datetime(2026, 11, 9, 2, 30, tzinfo=UTC)
_CLOCK = UserClock(tz=_TZ, now_local=_NOW.astimezone(_TZ), date_str="2026-11-09", day_of_year=313)


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


class TestAVoiceThatSaysATitleTwice:
    """Regression: "Northwind's invoice is still past due: Northwind invoice." echoed its title."""

    _VALUES = SlotValues(facts={1: BriefFact(title="Northwind invoice")}, counts={})

    async def test_a_title_written_and_slotted_in_one_sentence_is_sent_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        echoed = _voice(message="The northwind invoice is still past due: [[fact:1]].")
        asked = AsyncMock(side_effect=[echoed, _voice(message="[Northwind](fact:1) is past due.")])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        _, draft = await written_brief(_USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1))

        problems = [
            "the message names 'Northwind invoice' in words and again with [[fact:1]]; keep one"
        ]
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note(problems, echoed.model_dump_json(indent=2))}"
        )
        assert draft.message == "Northwind is past due."

    async def test_a_title_said_again_in_the_next_sentence_stands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        again = _voice(message="[[fact:1]] is past due. The Northwind invoice went out Monday.")
        asked = AsyncMock(side_effect=[again])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1))

        assert voice == again
        asked.assert_awaited_once()

    async def test_an_echo_after_a_shared_title_in_the_sentence_is_still_caught(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        values = SlotValues(
            facts={
                1: BriefFact(title="Northwind invoice"),
                2: BriefFact(title="1:1"),
                3: BriefFact(title="1:1"),
            },
            counts={},
        )
        echoed = _voice(message="After [[fact:2]], the Northwind invoice: [[fact:1]].")
        asked = AsyncMock(side_effect=[echoed, _voice(message="[Northwind](fact:1) is due.")])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        await written_brief(_USER_ID, "PROMPT", Writing(values=values, lead=1))

        assert asked.await_count == 2

    async def test_two_facts_sharing_a_title_may_each_be_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replay: a day of 1:1s failed as "'1:1' twice in one sentence"."""
        values = SlotValues(
            facts={1: BriefFact(title="1:1", time="11:00 AM"), 2: BriefFact(title="1:1")},
            counts={},
        )
        both = _voice(message="A 1:1 at [[fact:1.time]], then [[fact:2]] [the 1:1](fact:1).")
        asked = AsyncMock(side_effect=[both])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=values, lead=1))

        assert voice == both
        asked.assert_awaited_once()


@pytest.mark.parametrize(
    ("message", "opening"),
    [("\n  Priya replied overnight.\nMore.", "Priya replied overnight."), (" \n\t\n", "")],
    ids=["first-non-blank-line", "all-blank"],
)
def test_a_messages_opening_is_its_first_non_blank_line(message: str, opening: str) -> None:
    assert opening_line(message) == opening


class TestAFigureTheFactsShow:
    """Replay of Dhruv's 2026-11-09: "another look set for Tue Nov 17" fell back to the plain voice."""

    async def test_a_date_an_items_standing_says_may_be_voiced_as_it_stands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doc = TodoDocument(
            id="t1",
            user_id=_USER_ID,
            title="Pitch prep research",
            labels=[GAIA_TRACKED_LABEL],
            waiting_on=WaitingOn.TIME,
            scheduled_at=datetime(2026, 11, 17, 9, 0, tzinfo=UTC),
        )
        [candidate] = gaia_work_candidates(TrackedWork(running=[doc]), _CLOCK)
        item = BriefingItem(
            text="Pitch prep research", kind="gaia", todo_id="t1", outcome=BriefOutcome.STARTED
        )
        chosen = Chosen(
            sections=[BriefingSection(numeral="I", title="Open", items=[item])],
            picked=[[(1, candidate)]],
        )
        facts = build_facts(
            chosen,
            FactSources(
                artifacts=gather_artifacts(TrackedWork(running=[doc])),
                open_todos=0,
                calendar=[],
                event_ids=[],
                span=TODAY,
                todos_note=None,
            ),
            _CLOCK,
        )
        quoted = _voice(message="[The pitch research](fact:1) gets another look Tue Nov 17.")
        asked = AsyncMock(side_effect=[quoted, _voice()])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=facts.values, lead=1))

        assert "stands: GAIA looks at it again Tue Nov 17" in facts.block
        assert voice == quoted
        asked.assert_awaited_once()


class TestTheBriefsWideEvent:
    async def test_every_rejected_draft_and_the_plain_fallback_are_on_the_brief_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dhruv's 2026-11-06/09 fell back plainly and prod could not say why each draft failed."""
        asked = AsyncMock(side_effect=[_voice(message="Nothing."), _voice(message="Still none.")])
        monkeypatch.setattr(prose, "ainvoke_structured", asked)

        async with captured_wide_event() as event:
            voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        missed = (
            "the message never refers to the lead, fact 1 (Reply to Dan); say it in your own "
            "words as [your phrase](fact:1)"
        )
        assert voice == prose.plain_voice(Writing(values=_VALUES, lead=1))
        assert event["brief_voice"] == {"attempts": 2, "plain": True, "rejections": [missed] * 2}

    async def test_a_brief_voiced_first_time_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(prose, "ainvoke_structured", AsyncMock(side_effect=[_voice()]))

        async with captured_wide_event() as event:
            await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        assert event["brief_voice"] == {"attempts": 1, "plain": False, "rejections": []}
