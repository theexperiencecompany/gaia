"""The voice's reader, its unreadable replies and the way a rejected voice is sent back."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import pytest
from tests.factories import make_briefing_payload, make_user_id
from tests.helpers import captured_wide_event

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.briefing_prompts import RecentLines, voice_correction_note
from app.config.settings import settings
from app.constants.briefing import MAX_BRIEF_HEADLINE_CHARS, MAX_BRIEF_MESSAGE_CHARS, BriefOutcome
from app.constants.todos import GAIA_TRACKED_LABEL, WaitingOn
from app.models.brief_document_models import BriefingModel
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import BriefingItem, BriefingMood, BriefingSection, BriefVoice
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.models.todo_models import TodoDocument
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.services.briefing import checked_call, prose
from app.services.briefing.artifacts import gather_artifacts
from app.services.briefing.calendar_read import CalendarRead
from app.services.briefing.candidates.tracked import gaia_work_candidates
from app.services.briefing.clock import UserClock
from app.services.briefing.composition.compose import pool_values
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.facts import TODAY, Facts, FactSources, build_facts
from app.services.briefing.formats import opening_line
from app.services.briefing.prose import Writing, reader_block, written_brief
from app.services.briefing.sections import Chosen
from app.services.briefing.slots import BriefFact, SlotValues, render_slots
from app.services.briefing.work import TrackedWork

pytestmark = pytest.mark.unit

_USER_ID = make_user_id()
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


class TestAVoiceThatBreaksItsFacts:
    async def test_it_is_sent_back_once_with_the_problems_and_its_own_words(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broke = _voice(message="Nothing to say.")
        mended = _voice()
        asked = AsyncMock(side_effect=[broke, mended])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        voice, draft = await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        problem = (
            "the message never refers to the lead, fact 1 (Reply to Dan); say it in your own "
            "words as [your phrase](fact:1)"
        )
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note([problem], broke.model_dump_json(indent=2))}"
        )
        assert [call.kwargs["label"] for call in asked.await_args_list] == ["brief_voice"] * 2
        assert (voice, draft.message) == (mended, "Reply to Dan first.")

    async def test_a_message_claiming_a_state_its_fact_does_not_hold_is_sent_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        values = SlotValues(
            facts={1: BriefFact(title="Stripe payout", kind=ItemState.FAILED)}, counts={}
        )
        claimed = _voice(message="[The payout](fact:1) is done.")
        asked = AsyncMock(side_effect=[claimed, _voice(message="[The payout](fact:1) failed.")])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        await written_brief(_USER_ID, "PROMPT", Writing(values=values, lead=1))

        problem = (
            "the message says fact 1 'done', but its state is failed; say where it stands as "
            "its line does"
        )
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note([problem], claimed.model_dump_json(indent=2))}"
        )


def test_recent_lines_lists_every_line_each_recent_brief_printed_newest_first() -> None:
    briefs = [
        BriefingModel(
            user_id=_USER_ID,
            date="2026-11-08",
            payload=make_briefing_payload(
                headline="H2", lede="L2", caption="C2", message="Open two.\nMore."
            ),
        ),
        BriefingModel(
            user_id=_USER_ID,
            date="2026-11-07",
            payload=make_briefing_payload(headline="H1", lede="", caption="", message=None),
        ),
    ]

    assert prose.recent_lines(briefs) == RecentLines(
        headlines=["H2", "H1"], ledes=["L2"], captions=["C2"], openings=["Open two."]
    )


class TestAVoiceThatRepeatsOrOverclaims:
    """A line a recent brief printed, or a claim of how often something happens, is sent back."""

    @staticmethod
    def _asked(monkeypatch: pytest.MonkeyPatch, *voices: BriefVoice) -> AsyncMock:
        asked = AsyncMock(side_effect=list(voices))
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)
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


class TestAVoiceThatLinksFactsByCause:
    """Founder replay: a failed LinkedIn connect was said to block a draft sequence no fact tied to it."""

    _VALUES = SlotValues(
        facts={
            1: BriefFact(
                title="LinkedIn connect failure",
                words="401 auth checkpoint blocked the sender on Nov 20",
            ),
            2: BriefFact(title="YC founders outreach sequence", words="draft, awaiting approval"),
        },
        counts={},
    )

    @pytest.mark.regression
    async def test_a_cause_no_fact_it_names_states_is_sent_back_from_every_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        claimed = _voice(
            headline="The LinkedIn auth error is holding up your outreach",
            lede="A [failed connect](fact:1) is blocking [the sequence](fact:2).",
            message="[The connect](fact:1) failed. Fix that and the outreach path opens up.",
        )
        asked = AsyncMock(side_effect=[claimed, _voice(message="[The connect](fact:1) failed.")])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        await written_brief(_USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1))

        problems = [
            f"the {field} says {claim!r}: that one thing causes, blocks or gates another, and no "
            "fact it names says so; state each fact on its own, as its line does"
            for field, claim in (
                ("headline", "holding up"),
                ("lede", "blocking"),
                ("message", "opens up"),
            )
        ]
        assert asked.await_args_list[1].args[1] == (
            f"PROMPT\n\n{voice_correction_note(problems, claimed.model_dump_json(indent=2))}"
        )

    async def test_a_cause_the_named_facts_line_states_may_be_voiced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grounded = _voice(
            message="[The sender](fact:1) is blocked until you clear the checkpoint.",
        )
        asked = AsyncMock(side_effect=[grounded])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1))

        assert voice == grounded

    async def test_a_cause_another_fact_states_does_not_ground_this_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        borrowed = _voice(
            message="[The connect](fact:1) failed. [The sequence](fact:2) is blocked."
        )
        asked = AsyncMock(side_effect=[borrowed, _voice(message="[The connect](fact:1) failed.")])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        await written_brief(_USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1))

        assert asked.await_count == 2


@pytest.mark.regression
async def test_a_voice_calling_an_unlinked_todo_goal_work_is_sent_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Founder replay: the churned-subscriber email, linked to no goal, was voiced as goal work."""
    values = SlotValues(
        facts={
            1: BriefFact(title="Reply to Dan"),
            2: BriefFact(title="Churned-subscriber email"),
            3: BriefFact(title="Old-user discount email", goal_work=True),
        },
        counts={},
    )
    claimed = _voice(
        message="[Reply to Dan](fact:1) first. [The churn email](fact:2) is your goal work."
    )
    mended = _voice(message="[Reply to Dan](fact:1) first. [The email](fact:3) is goal work.")
    asked = AsyncMock(side_effect=[claimed, mended])
    monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

    voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=values, lead=1))

    problem = (
        "the message ties facts 2 to a goal, but they are not linked to one; only a goal's "
        "linked todos are its work, so name them in a sentence that does not speak of the goal"
    )
    assert asked.await_args_list[1].args[1] == (
        f"PROMPT\n\n{voice_correction_note([problem], claimed.model_dump_json(indent=2))}"
    )
    assert voice == mended


class TestAVoiceThatSaysATitleTwice:
    """Regression: "Northwind's invoice is still past due: Northwind invoice." echoed its title."""

    _VALUES = SlotValues(
        facts={1: BriefFact(title="Northwind invoice", time="Mon Nov 3", time_is_day=True)},
        counts={},
    )

    async def test_a_title_written_and_slotted_in_one_sentence_is_sent_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        echoed = _voice(message="The northwind invoice is still past due: [[fact:1]].")
        asked = AsyncMock(side_effect=[echoed, _voice(message="[Northwind](fact:1) is past due.")])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

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
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

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
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

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
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

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


def _pitch_research_facts() -> Facts:
    """Return the facts of one placed item of GAIA's, set to look at the work again Tue Nov 17."""
    doc = TodoDocument(
        id="t1",
        user_id=_USER_ID,
        title="Pitch prep research",
        labels=[GAIA_TRACKED_LABEL],
        waiting_on=WaitingOn.TIME,
        scheduled_at=datetime(2026, 11, 17, 9, 0, tzinfo=UTC),
    )
    [candidate] = gaia_work_candidates(TrackedWork(running=[doc]))
    item = BriefingItem(
        text="Pitch prep research",
        kind=ItemState.GAIA,
        todo_id="t1",
        outcome=BriefOutcome.STARTED,
    )
    chosen = Chosen(
        sections=[BriefingSection(numeral="I", title="Open", items=[item])],
        picked=[[(1, candidate)]],
    )
    return build_facts(
        chosen,
        FactSources(
            artifacts=gather_artifacts(TrackedWork(running=[doc])),
            open_todos=0,
            calendar=CalendarRead(),
            event_items={},
            span=TODAY,
            todos_note=None,
        ),
        pool_values(
            FactPool(
                items={1: candidate},
                series=[],
                quotes=[],
                goals=[],
                context=PoolContext(
                    reader="Ada",
                    clock=_CLOCK,
                    calendar=0,
                    calendar_span="today",
                    done_since=_NOW,
                ),
                criteria={},
            )
        ),
        _CLOCK,
    )


class TestAFigureTheFactsShow:
    """Replays of Dhruv's 2026-11-06 and 11-09: the day GAIA looks again sent the voice back."""

    @pytest.mark.parametrize(
        "message",
        [
            "[The pitch research](fact:1) gets another look Tue Nov 17.",
            "[The pitch research](fact:1) gets another look [[fact:1.time]].",
        ],
        ids=["typed-as-it-stands", "by-its-time-slot"],
    )
    async def test_the_day_an_items_standing_says_may_be_voiced(
        self, monkeypatch: pytest.MonkeyPatch, message: str
    ) -> None:
        facts = _pitch_research_facts()
        drafted = _voice(message=message)
        asked = AsyncMock(side_effect=[drafted, _voice()])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=facts.values, lead=1))

        assert "stands: GAIA looks at it again [[fact:1.time]] (Tue Nov 17)" in facts.block
        assert render_slots(voice.message, facts.values, {}) == (
            "The pitch research gets another look Tue Nov 17."
        )
        asked.assert_awaited_once()


class TestTheBriefsWideEvent:
    async def test_every_rejected_draft_and_the_salvage_are_on_the_brief_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dhruv's 2026-11-06/09 fell back plainly and prod could not say why each draft failed."""
        asked = AsyncMock(side_effect=[_voice(message="Nothing."), _voice(message="Nothing new.")])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        async with captured_wide_event() as event:
            voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        missed = (
            "the message never refers to the lead, fact 1 (Reply to Dan); say it in your own "
            "words as [your phrase](fact:1)"
        )
        assert voice.message == "- [[fact:1]]\n\nNothing new."
        assert event["brief_voice"] == {
            "attempts": 2,
            "salvaged": True,
            "rejections": [missed] * 2,
            "dropped_sentences": 0,
            "plain": False,
        }

    async def test_a_brief_voiced_first_time_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(checked_call, "ainvoke_structured", AsyncMock(side_effect=[_voice()]))

        async with captured_wide_event() as event:
            await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        assert event["brief_voice"] == {"attempts": 1, "salvaged": False, "rejections": []}

    async def test_an_unreadable_reply_is_on_the_event_as_every_field_it_got_wrong(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError) as invalid:
            BriefVoice.model_validate({"headline": "x", "lede": "y", "caption": "z"})
        malformed = MalformedStructuredOutputError("bad", llm_output="half")
        malformed.__cause__ = invalid.value
        asked = AsyncMock(side_effect=[malformed, _voice()])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        async with captured_wide_event() as event:
            await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1))

        assert event["brief_voice"]["rejections"] == [
            "mood: Field required; message: Field required"
        ]

    async def test_a_draft_broken_two_ways_is_on_the_event_as_both(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _voice(headline="An open day", message="[Reply to Dan](fact:1) before lunch.")
        asked = AsyncMock(side_effect=[stale, _voice()])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)
        recent = RecentLines(headlines=["An open day"], openings=["Reply to Dan before lunch."])

        async with captured_wide_event() as event:
            await written_brief(_USER_ID, "PROMPT", Writing(values=_VALUES, lead=1, recent=recent))

        assert event["brief_voice"]["rejections"] == [
            "the headline repeats a recent brief's line ('An open day'); write today's in fresh "
            "words; the message's opening repeats a recent brief's line "
            "('Reply to Dan before lunch.'); write today's in fresh words"
        ]


class TestALastVoiceThatStillBreaks:
    """Founder brief_b4f24ff8d403: one goal sentence the retry repeated sent the whole brief plain."""

    _VALUES = SlotValues(
        facts={
            1: BriefFact(title="LinkedIn connect attempt failed"),
            2: BriefFact(title="Churned-subscriber email"),
        },
        counts={},
    )

    async def _salvaged(self, monkeypatch: pytest.MonkeyPatch, last: BriefVoice) -> BriefVoice:
        monkeypatch.setattr(checked_call, "ainvoke_structured", AsyncMock(side_effect=[last] * 2))
        voice, _ = await written_brief(_USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1))
        return voice

    @pytest.mark.regression
    async def test_only_the_rejected_sentence_and_the_one_pointing_back_at_it_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        last = _voice(
            headline="A failed LinkedIn send",
            message="[The LinkedIn connect](fact:1) failed on an auth error. "
            "[The churn email](fact:2) is your goal work. That one is worth an hour.\n\n"
            "Your calendar is open.",
        )

        async with captured_wide_event() as event:
            voice = await self._salvaged(monkeypatch, last)

        assert voice == last.model_copy(
            update={
                "message": "[The LinkedIn connect](fact:1) failed on an auth error.\n\n"
                "Your calendar is open."
            }
        )
        assert event["brief_voice"] | {"rejections": []} == {
            "attempts": 2,
            "salvaged": True,
            "rejections": [],
            "dropped_sentences": 2,
            "plain": False,
        }

    async def test_a_dropped_headline_and_a_missing_lead_get_their_plain_pieces_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        last = _voice(
            headline="[The churn email](fact:2) is your goal work",
            message="[The churn email](fact:2) waits on a send.",
        )

        voice = await self._salvaged(monkeypatch, last)

        assert voice == last.model_copy(
            update={
                "headline": "Your brief",
                "message": "- [[fact:1]]\n\n[The churn email](fact:2) waits on a send.",
            }
        )

    async def test_it_goes_plain_only_with_neither_headline_nor_lede_left(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        goal = "[The churn email](fact:2) is your goal work."
        last = _voice(headline=goal.rstrip("."), lede=goal)

        voice = await self._salvaged(monkeypatch, last)

        assert voice == prose.plain_voice(Writing(values=self._VALUES, lead=1))


class TestAVoiceTooLongOnceFilled:
    async def test_a_headline_past_its_limit_once_its_slots_fill_is_sent_back_naming_the_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        values = SlotValues(
            facts={1: BriefFact(title="Sign " + "the long agreement " * 6)}, counts={}
        )
        asked = AsyncMock(
            side_effect=[
                _voice(headline="Today: [[fact:1]]", message="[It](fact:1) first."),
                _voice(headline="One long signing today", message="[It](fact:1) first."),
            ]
        )
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        _, draft = await written_brief(_USER_ID, "PROMPT", Writing(values=values, lead=1))

        retry = asked.await_args_list[1].args[1]
        assert (
            "the headline once its slots are filled: String should have at most "
            f"{MAX_BRIEF_HEADLINE_CHARS} characters"
        ) in retry
        assert draft.headline == "One long signing today"


class TestThePlainVoice:
    def test_it_lists_the_lead_first_then_every_fact_by_its_slot_and_time(self) -> None:
        values = SlotValues(
            facts={1: BriefFact(title="Reply to Dan"), 2: BriefFact(title="Board", time="3 PM")},
            counts={},
        )

        assert prose.plain_voice(Writing(values=values, lead=2)) == BriefVoice(
            headline="Your brief",
            lede="",
            caption="",
            mood=BriefingMood.CLEAR,
            message="- [[fact:2]] ([[fact:2.time]])\n- [[fact:1]]",
        )

    def test_it_drops_the_last_lines_until_the_rendered_message_fits(self) -> None:
        """The first two lines render to exactly the limit, so they stay and the third goes."""
        first = "a" * 100
        second = "b" * (MAX_BRIEF_MESSAGE_CHARS - len(f"- {first}\n- "))
        values = SlotValues(
            facts={1: BriefFact(title=first), 2: BriefFact(title=second), 3: BriefFact(title="c")},
            counts={},
        )

        voice = prose.plain_voice(Writing(values=values, lead=None))

        assert voice.message == "- [[fact:1]]\n- [[fact:2]]"
        assert len(render_slots(voice.message, values, {})) == MAX_BRIEF_MESSAGE_CHARS

    def test_a_dropped_line_goes_whole_its_time_with_it(self) -> None:
        """Without its time the third line would fit exactly, so only a whole-line cut drops it."""
        first = "a" * 100
        second = "b" * (MAX_BRIEF_MESSAGE_CHARS - len(f"- {first}\n- \n- c"))
        values = SlotValues(
            facts={
                1: BriefFact(title=first),
                2: BriefFact(title=second),
                3: BriefFact(title="c", time="9 AM"),
            },
            counts={},
        )

        voice = prose.plain_voice(Writing(values=values, lead=None))

        assert voice.message == "- [[fact:1]]\n- [[fact:2]]"


class TestTheLinksAMessageMakes:
    async def test_only_each_deliverable_the_message_links_is_minted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mint = AsyncMock(
            side_effect=lambda user_id, target: ShortLink(
                slug=f"link-{target.id}", user_id=user_id, target=target
            )
        )
        monkeypatch.setattr(prose, "attach_link", mint)
        facts = Facts(
            sections=[],
            block="",
            signals="",
            values=_VALUES,
            deliverables={1: "t1", 2: "t2"},
            addresses={3: "https://linear.app/i/3", 4: "https://linear.app/i/4"},
            lead=None,
        )

        links = await prose.links_in(_USER_ID, "[The memo](fact:2) and [the issue](fact:4).", facts)

        assert links == {4: "https://linear.app/i/4", 2: f"{settings.SHORTLINK_BASE_URL}/link-t2"}
        mint.assert_awaited_once_with(
            _USER_ID, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id="t2")
        )


class TestASalvageCountsAndKeepsByField:
    """Each field drops what breaks or repeats, every drop is counted, and what is left must still hold."""

    _VALUES = SlotValues(
        facts={
            1: BriefFact(title="LinkedIn connect attempt failed"),
            2: BriefFact(title="Churned-subscriber email", app="Gmail"),
        },
        counts={},
    )
    _HEADLINE = "[The LinkedIn connect](fact:1) failed"
    _KEPT_MESSAGE = "[The LinkedIn connect](fact:1) failed on an auth error."

    def _last(self) -> BriefVoice:
        return _voice(
            headline=self._HEADLINE,
            lede="It is a day. [The churn email](fact:2) is your goal work.",
            caption="Reply to the churn email",
            message=f"{self._KEPT_MESSAGE} [The churn email](fact:2) is a GAIA todo.",
        )

    async def _salvaged(
        self, monkeypatch: pytest.MonkeyPatch, recent: RecentLines
    ) -> tuple[BriefVoice, dict[str, object]]:
        last = self._last()
        monkeypatch.setattr(checked_call, "ainvoke_structured", AsyncMock(side_effect=[last] * 2))
        async with captured_wide_event() as event:
            voice, _ = await written_brief(
                _USER_ID, "PROMPT", Writing(values=self._VALUES, lead=1, recent=recent)
            )
        return voice, event["brief_voice"]

    async def test_each_fields_drop_is_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recent = RecentLines(
            headlines=[render_slots(self._HEADLINE, self._VALUES, {})],
            captions=["Reply to the churn email"],
        )

        voice, event = await self._salvaged(monkeypatch, recent)

        assert voice == self._last().model_copy(
            update={
                "headline": "Your brief",
                "lede": "It is a day.",
                "caption": "",
                "message": self._KEPT_MESSAGE,
            }
        )
        assert (event["dropped_sentences"], event["plain"]) == (4, False)

    async def test_a_message_kept_on_a_recent_opening_still_fails_its_check_and_goes_plain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recent = RecentLines(openings=[render_slots(self._KEPT_MESSAGE, self._VALUES, {})])

        voice, event = await self._salvaged(monkeypatch, recent)

        assert voice == prose.plain_voice(Writing(values=self._VALUES, lead=1))
        assert event["plain"] is True
