"""The faithfulness check judges every specific in the rendered prose and returns only the broken ones."""

from unittest.mock import AsyncMock

from pydantic import ValidationError
import pytest
from tests.helpers import captured_wide_event

from app.constants.briefing import BRIEF_FAITHFULNESS_LABEL, BRIEF_FAITHFULNESS_TEMPERATURE
from app.services.briefing import faithfulness
from app.services.briefing.faithfulness import (
    CheckedProse,
    CheckedSpecific,
    UnsupportedClaim,
    UnsupportedClaims,
    Verdict,
    unsupported_claims,
)

pytestmark = pytest.mark.unit

_USER = "64f1c0ffee0000000000abcd"
_FACTS = (
    "[Updates]\n- fact 1 | Done: Investor update\nToday's calendar:\n- fact 2 | 11:00 AM: Sequoia"
)
_DRAFT = CheckedProse(
    headline="Arjun's contract redlines need you today",
    lede="The investor update is still a draft.",
    caption="One meeting, one decision.",
    message="Arjun is waiting on the redlines.\nThen Sequoia at ⟦11:00 AM⟧.",
)


def _judged(*specifics: tuple[str, Verdict, int | None]) -> UnsupportedClaims:
    return UnsupportedClaims(
        specifics=[
            CheckedSpecific(quote=quote, verdict=verdict, fact=fact, truth="per the facts")
            for quote, verdict, fact in specifics
        ]
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    stub = AsyncMock(return_value=_judged())
    monkeypatch.setattr(faithfulness, "ainvoke_structured", stub)
    return stub


async def test_a_fabricated_or_contradicted_specific_comes_back_with_its_fact(
    model: AsyncMock,
) -> None:
    model.return_value = _judged(
        ("Arjun's contract redlines", "absent", None),
        ("still a draft", "contradicted", 1),
        ("Sequoia at 11:00 AM", "holds", 2),
    )

    assert await unsupported_claims(_USER, _FACTS, _DRAFT) == [
        UnsupportedClaim(quote="Arjun's contract redlines", fact="absent", truth="per the facts"),
        UnsupportedClaim(quote="still a draft", fact=1, truth="per the facts"),
    ]


async def test_a_contradiction_without_a_fact_id_reads_as_absent(model: AsyncMock) -> None:
    model.return_value = _judged(("still a draft", "contradicted", None))

    (claim,) = await unsupported_claims(_USER, _FACTS, _DRAFT)

    assert claim.fact == "absent"


async def test_a_claim_quoting_words_the_brief_never_wrote_is_dropped(model: AsyncMock) -> None:
    """Live: the checker on the Gemini lane quoted the facts ("Sent to fourteen investors")."""
    model.return_value = _judged(
        ("Sent to fourteen investors", "contradicted", 1),
        ("arjun is  waiting on the redlines", "absent", None),
    )

    claims = await unsupported_claims(_USER, _FACTS, _DRAFT)

    assert [c.quote for c in claims] == ["arjun is  waiting on the redlines"]


async def test_a_dropped_claim_is_logged_with_its_quote(model: AsyncMock) -> None:
    model.return_value = _judged(
        ("Sent to fourteen investors", "contradicted", 1),
        ("Then Sequoia", "absent", None),
        ("a made up sentence", "absent", None),
    )

    async with captured_wide_event() as event:
        claims = await unsupported_claims(_USER, _FACTS, _DRAFT)

    assert [c.quote for c in claims] == ["Then Sequoia"]
    assert {
        "msg": "briefing.faithfulness_unquoted",
        "quotes": ["Sent to fourteen investors", "a made up sentence"],
    } in event["warnings"]


async def test_a_quote_matches_the_prose_with_or_without_the_brackets_round_a_filled_value(
    model: AsyncMock,
) -> None:
    model.return_value = _judged(
        ("Sequoia at 11:00 AM.", "contradicted", 2),
        ("Then Sequoia at \u27e611:00 AM\u27e7.", "absent", None),
    )

    claims = await unsupported_claims(_USER, _FACTS, _DRAFT)

    assert [c.quote for c in claims] == [
        "Sequoia at 11:00 AM.",
        "Then Sequoia at \u27e611:00 AM\u27e7.",
    ]


async def test_the_model_reads_the_facts_and_every_rendered_field_at_zero_temperature(
    model: AsyncMock,
) -> None:
    await unsupported_claims(_USER, _FACTS, _DRAFT)

    schema, prompt = model.await_args.args
    assert schema is UnsupportedClaims
    assert _FACTS in prompt
    for line in (
        f"headline: {_DRAFT.headline}",
        f"lede: {_DRAFT.lede}",
        f"caption: {_DRAFT.caption}",
        f"message:\n{_DRAFT.message}",
    ):
        assert line in prompt
    kwargs = model.await_args.kwargs
    assert kwargs["label"] == BRIEF_FAITHFULNESS_LABEL
    assert kwargs["config"]["configurable"] == {"user_id": _USER}
    assert kwargs["options"].temperature == BRIEF_FAITHFULNESS_TEMPERATURE


@pytest.mark.parametrize(
    ("fact", "named"), [("absent", "no fact holds it"), (1, "fact 1 says otherwise")]
)
def test_a_claim_is_named_with_the_fact_it_breaks_or_as_absent(fact: int | str, named: str) -> None:
    claim = UnsupportedClaim.model_validate(
        {"quote": "the deck shipped", "fact": fact, "truth": "it is in progress"}
    )

    assert claim.problem() == f'"the deck shipped": {named}; it is in progress'


def test_the_schema_tells_the_model_what_is_never_a_specific() -> None:
    described = UnsupportedClaims.model_json_schema()["properties"]["specifics"]["description"]

    for allowed in ("vagueness", "synonym", "tone", "ordering", "left out", "⟦ ⟧"):
        assert allowed in described


def test_a_verdict_is_one_of_three_and_a_claim_names_a_fact_id_or_absent() -> None:
    with pytest.raises(ValidationError):
        CheckedSpecific.model_validate({"quote": "x", "verdict": "maybe", "fact": 1, "truth": "y"})
    with pytest.raises(ValidationError):
        UnsupportedClaim.model_validate({"quote": "x", "fact": "maybe", "truth": "y"})
