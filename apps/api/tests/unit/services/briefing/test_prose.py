"""The voiced brief: asked of the model, held to its facts, retried once with the problems named.

Faked seams: the silent agent turn, the faithfulness model's claims and the short-link mint.
"""

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, call
from zoneinfo import ZoneInfo

import pytest
from tests.helpers import captured_wide_event

from app.agents.prompts.briefing_prompts import voice_correction_note, voice_unreadable_note
from app.constants.briefing import MAX_BRIEF_HEADLINE_CHARS
from app.models.short_link_models import ShortLinkTargetType
from app.models.user_models import UserDocument
from app.services.briefing import prose
from app.services.briefing.context import UserClock
from app.services.briefing.errors import BriefingGenerationError, VoiceUnreadableError
from app.services.briefing.facts import Facts
from app.services.briefing.faithfulness import CheckedProse, UnsupportedClaim
from app.services.briefing.prose import Writing, links_in, written_brief
from app.services.briefing.slots import BriefFact, CountSlot, SlotValues
from app.utils.auth_utils import build_user_context

_USER_ID = "64f1c0ffee0000000000abcd"
_TZ = ZoneInfo("Asia/Kolkata")
_NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
_CLOCK = UserClock(tz=_TZ, now_local=_NOW.astimezone(_TZ), date_str="2026-10-14", day_of_year=287)
_USER = build_user_context(UserDocument(id=_USER_ID, timezone="Asia/Kolkata"), auth_provider=None)
_PROMPT = "Write the brief."
_VALUES = SlotValues(
    facts={1: BriefFact(title="Reply to Dan"), 2: BriefFact(title="Approve the lease")},
    counts={CountSlot.NEEDS_YOU: 2},
)
_VOICE = {
    "headline": "[[count:needs_you]] things need you",
    "lede": "Dan is waiting.",
    "caption": "Reply first.",
    "mood": "clear",
    "message": "[Dan](fact:1) and [the lease](fact:2) wait on you.",
}


def _writing(
    values: SlotValues = _VALUES, must_mention: frozenset[int] = frozenset({1, 2})
) -> Writing:
    return Writing(
        values=values,
        context="everything the model was shown",
        must_mention=must_mention,
        kind="daily",
    )


def _fenced(voice: dict[str, str]) -> str:
    return f"```json\n{json.dumps(voice)}\n```"


@pytest.fixture
def turn(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    fake = AsyncMock(return_value=_fenced(_VOICE))
    monkeypatch.setattr(prose, "run_briefing_turn", fake)
    return fake


@pytest.fixture
def claims(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    fake = AsyncMock(return_value=[])
    monkeypatch.setattr(prose, "unsupported_claims", fake)
    return fake


class TestLinksIn:
    async def test_only_the_deliverables_the_message_links_are_minted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mint = AsyncMock(
            side_effect=lambda user_id, target_type, target_id: f"https://l/{target_id}"
        )
        monkeypatch.setattr(prose, "optional_short_link", mint)
        facts = Facts(
            sections=[],
            block="",
            values=_VALUES,
            deliverables={1: "t1", 2: "t2"},
            addresses={3: "https://app.example/x", 4: "https://app.example/y"},
            must_mention=frozenset(),
        )

        links = await links_in(_USER_ID, "[b](fact:2) and [c](fact:3)", facts)

        assert links == {2: "https://l/t2", 3: "https://app.example/x"}
        mint.assert_awaited_once_with(_USER_ID, ShortLinkTargetType.TODO_DELIVERABLE, "t2")


class TestWrittenBrief:
    async def test_the_first_ask_is_the_bare_prompt_and_the_check_reads_the_filled_prose(
        self, turn: AsyncMock, claims: AsyncMock
    ) -> None:
        voice, draft = await written_brief(_USER, _CLOCK, _PROMPT, _writing())

        assert turn.await_args_list == [call(_USER, _CLOCK, _PROMPT, conversation_key="daily")]
        assert voice.headline == "[[count:needs_you]] things need you"
        assert draft.headline == "2 things need you"
        claims.assert_awaited_once_with(
            _USER_ID,
            "everything the model was shown",
            CheckedProse(
                headline="⟦2⟧ things need you",
                lede="Dan is waiting.",
                caption="Reply first.",
                message="Dan and the lease wait on you.",
            ),
        )

    async def test_an_unreadable_reply_is_logged_and_asked_again_with_why(
        self, turn: AsyncMock, claims: AsyncMock
    ) -> None:
        turn.side_effect = ["no json here", _fenced(_VOICE)]

        async with captured_wide_event() as event:
            await written_brief(_USER, _CLOCK, _PROMPT, _writing())

        [warning] = [w for w in event["warnings"] if w["msg"] == "briefing.voice_unreadable"]
        assert warning["raw_length"] == len("no json here")
        retry_prompt = turn.await_args_list[1].args[2]
        assert retry_prompt == f"{_PROMPT}\n\n{voice_unreadable_note(warning['problems'])}"

    async def test_unreadable_twice_fails_with_why_and_never_the_text(
        self, turn: AsyncMock, claims: AsyncMock
    ) -> None:
        turn.return_value = "no json here"

        with pytest.raises(VoiceUnreadableError) as raised:
            await written_brief(_USER, _CLOCK, _PROMPT, _writing())

        assert turn.await_count == 2
        assert "no json here" not in str(raised.value)

    async def test_prose_breaking_its_facts_is_sent_back_once_then_fails_naming_every_problem(
        self, turn: AsyncMock, claims: AsyncMock
    ) -> None:
        turn.return_value = _fenced({**_VOICE, "message": "Nothing to say."})
        problems = [
            "the message never refers to fact 1 (Reply to Dan); "
            "say it in your own words as [your phrase](fact:1)",
            "the message never refers to fact 2 (Approve the lease); "
            "say it in your own words as [your phrase](fact:2)",
        ]

        with pytest.raises(BriefingGenerationError) as raised:
            await written_brief(_USER, _CLOCK, _PROMPT, _writing())

        assert str(raised.value) == (
            f"The brief's prose does not hold to its facts: {problems[0]}; {problems[1]}"
        )
        assert turn.await_count == 2
        assert turn.await_args_list[1].args[2] == f"{_PROMPT}\n\n{voice_correction_note(problems)}"
        claims.assert_not_awaited()

    async def test_an_unsupported_claim_is_a_problem_and_is_logged_as_rejected(
        self, turn: AsyncMock, claims: AsyncMock
    ) -> None:
        claim = UnsupportedClaim(quote="Dan is waiting", fact="absent", truth="Dan wrote nothing")
        claims.side_effect = [[claim], []]

        async with captured_wide_event() as event:
            await written_brief(_USER, _CLOCK, _PROMPT, _writing())

        assert {"msg": "briefing.voice_rejected", "problems": [claim.problem()]} in event[
            "warnings"
        ]
        assert claim.problem() in turn.await_args_list[1].args[2]

    async def test_a_field_over_its_limit_once_filled_is_named_with_its_limit(
        self, turn: AsyncMock, claims: AsyncMock
    ) -> None:
        long_title = "t" * (MAX_BRIEF_HEADLINE_CHARS + 1)
        values = SlotValues(facts={3: BriefFact(title=long_title)}, counts={})
        turn.return_value = _fenced({**_VOICE, "headline": "[[fact:3]]", "message": "[[fact:3]]"})

        with pytest.raises(BriefingGenerationError) as raised:
            await written_brief(
                _USER, _CLOCK, _PROMPT, _writing(values=values, must_mention=frozenset())
            )

        assert str(raised.value) == (
            "The brief's prose does not hold to its facts: the headline once its slots are "
            f"filled: String should have at most {MAX_BRIEF_HEADLINE_CHARS} characters"
        )
