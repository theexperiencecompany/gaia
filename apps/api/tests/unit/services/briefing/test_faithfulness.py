"""The faithfulness check hands the model the facts and the rendered prose, and returns its claims."""

from unittest.mock import AsyncMock

import pytest

from app.constants.briefing import BRIEF_FAITHFULNESS_LABEL
from app.services.briefing import faithfulness
from app.services.briefing.faithfulness import CheckedProse, UnsupportedClaims, unsupported_claims

pytestmark = pytest.mark.unit

_USER = "64f1c0ffee0000000000abcd"
_FACTS = (
    "[Updates]\n- fact 1 | Done: Investor update\nToday's calendar:\n- fact 2 | 11:00 AM: Sequoia"
)
_FABRICATED = CheckedProse(
    headline="Arjun's contract redlines need you today",
    lede="The investor update went out.",
    caption="One meeting, one decision.",
    message="Arjun is waiting on the redlines.\nThen Sequoia at 11:00 AM.",
)
_ARJUN = '"Arjun\'s contract redlines need you": no fact names Arjun or a contract'


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    stub = AsyncMock(return_value=UnsupportedClaims(claims=[_ARJUN]))
    monkeypatch.setattr(faithfulness, "ainvoke_structured", stub)
    return stub


async def test_a_fabricated_claim_the_model_finds_is_returned(model: AsyncMock) -> None:
    assert await unsupported_claims(_USER, _FACTS, _FABRICATED) == [_ARJUN]


async def test_the_model_reads_the_facts_and_every_rendered_field(model: AsyncMock) -> None:
    await unsupported_claims(_USER, _FACTS, _FABRICATED)

    schema, prompt = model.await_args.args
    assert schema is UnsupportedClaims
    assert _FACTS in prompt
    for line in (
        f"headline: {_FABRICATED.headline}",
        f"lede: {_FABRICATED.lede}",
        f"caption: {_FABRICATED.caption}",
        f"message:\n{_FABRICATED.message}",
    ):
        assert line in prompt
    assert model.await_args.kwargs["label"] == BRIEF_FAITHFULNESS_LABEL
    assert model.await_args.kwargs["config"]["configurable"] == {"user_id": _USER}


async def test_a_blank_claim_is_no_claim(model: AsyncMock) -> None:
    model.return_value = UnsupportedClaims(claims=["  ", ""])

    assert await unsupported_claims(_USER, _FACTS, _FABRICATED) == []
