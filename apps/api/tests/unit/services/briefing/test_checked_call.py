"""The one policy every checked brief call follows: ask, check, send back named, salvage in code."""

from unittest.mock import AsyncMock

from pydantic import BaseModel, ValidationError
import pytest
from tests.helpers import captured_wide_event

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.services.briefing import checked_call
from app.services.briefing.checked_call import (
    CheckedCall,
    Rejected,
    checked_structured_call,
    unreadable_problems,
)

_USER_ID = "u1"


class _Answer(BaseModel):
    word: str
    count: int


def _call(attempts: int = 2) -> CheckedCall[_Answer, str]:
    async def check(answer: _Answer) -> str | Rejected[_Answer]:
        if answer.word == "good":
            return f"held {answer.count}"
        return Rejected([f"{answer.word} is not good"], f"NOTE {answer.word}", answer)

    return CheckedCall(
        name="probe",
        schema=_Answer,
        label="probe",
        attempts=attempts,
        check=check,
        unreadable=lambda problems, reply: f"UNREADABLE {'; '.join(problems)} | {reply}",
        salvage=lambda last: f"salvaged from {last.word if last else None}",
    )


def _malformed_by_fields() -> MalformedStructuredOutputError:
    with pytest.raises(ValidationError) as invalid:
        _Answer.model_validate({"word": "x"})
    malformed = MalformedStructuredOutputError("bad", llm_output="half")
    malformed.__cause__ = invalid.value
    return malformed


class TestUnreadableProblems:
    def test_each_field_the_reply_got_wrong_is_named_without_its_text(self) -> None:
        assert unreadable_problems(_malformed_by_fields()) == ["count: Field required"]

    def test_a_reply_with_no_schema_error_is_told_why(self) -> None:
        cut = MalformedStructuredOutputError("the reply was cut short", llm_output=None)

        assert unreadable_problems(cut) == ["the reply was cut short"]


class TestTheCheckedCall:
    async def test_an_answer_that_holds_first_time_is_returned_and_said_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = AsyncMock(side_effect=[_Answer(word="good", count=3)])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        async with captured_wide_event() as event:
            result = await checked_structured_call(_USER_ID, "PROMPT", _call())

        assert result == "held 3"
        assert asked.await_args.args[1] == "PROMPT"
        assert event["brief_probe"] == {"attempts": 1, "salvaged": False, "rejections": []}

    async def test_a_rejected_answer_goes_back_with_its_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = AsyncMock(side_effect=[_Answer(word="bad", count=1), _Answer(word="good", count=2)])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        async with captured_wide_event() as event:
            result = await checked_structured_call(_USER_ID, "PROMPT", _call())

        assert result == "held 2"
        assert asked.await_args_list[1].args[1] == "PROMPT\n\nNOTE bad"
        assert event["brief_probe"] == {
            "attempts": 2,
            "salvaged": False,
            "rejections": ["bad is not good"],
        }

    async def test_an_unreadable_reply_goes_back_with_its_fields_and_the_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = AsyncMock(side_effect=[_malformed_by_fields(), _Answer(word="good", count=2)])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        assert await checked_structured_call(_USER_ID, "PROMPT", _call()) == "held 2"
        assert asked.await_args_list[1].args[1] == (
            "PROMPT\n\nUNREADABLE count: Field required | half"
        )

    async def test_past_the_last_attempt_code_salvages_from_the_last_kept_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = AsyncMock(
            side_effect=[_Answer(word="bad", count=1), _Answer(word="worse", count=1)]
        )
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        async with captured_wide_event() as event:
            result = await checked_structured_call(_USER_ID, "PROMPT", _call())

        assert result == "salvaged from worse"
        assert asked.await_count == 2
        assert event["brief_probe"]["salvaged"] is True
        (salvaged,) = [e for e in event["errors"] if e["msg"] == "briefing.checked_call_salvaged"]
        assert salvaged["call"] == "probe"
        assert salvaged["problems"] == "worse is not good"

    async def test_a_last_reply_that_is_unreadable_salvages_from_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = AsyncMock(side_effect=[_Answer(word="bad", count=1), _malformed_by_fields()])
        monkeypatch.setattr(checked_call, "ainvoke_structured", asked)

        assert await checked_structured_call(_USER_ID, "PROMPT", _call()) == "salvaged from None"
