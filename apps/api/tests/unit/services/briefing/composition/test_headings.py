"""Every group heading is judged against the items under it, and a heading untrue of one is named.

Faked seam: the structured model call the heading check makes.
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.constants.briefing import BRIEF_HEADING_CHECK_LABEL
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition
from app.services.briefing.composition import headings
from app.services.briefing.composition.headings import (
    HeadingVerdict,
    HeadingVerdicts,
    heading_problems,
)
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.utils.errors import AppError

USER = "64f1c0ffee0000000000abcd"
POOL = FactPool(
    items={
        1: BriefCandidate(source="gaia", app="GAIA", state="you", title="Priya's offsite venues"),
        2: BriefCandidate(source="gaia", app="GAIA", state="lookback", title="Investor update"),
    },
    series=[],
    quotes=[],
    goals=[],
    context=PoolContext(
        reader="Ada",
        timezone="UTC",
        today=date(2026, 11, 11),
        calendar_events=0,
        calendar_span="today",
        recent_openings=[],
    ),
    criteria={},
)


def _item(item_id: int, title: str, **side: str) -> dict[str, object]:
    return {"id": item_id, "action": None, "outcome": None, "title": title, "detail": None, **side}


COMPOSITION = BriefComposition.model_validate(
    {
        "blocks": [
            {"kind": "note", "text": "A light day."},
            {
                "kind": "items",
                "state": "done",
                "heading": "Landed overnight",
                "items": [
                    _item(1, "Offsite venues", action="review"),
                    _item(2, "Investor update", outcome="sent"),
                ],
            },
        ]
    }
)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(
        return_value=HeadingVerdicts(
            verdicts=[
                HeadingVerdict(block=2, fits=False, misfits=[1], why="still waits on approval")
            ]
        )
    )
    monkeypatch.setattr(headings, "ainvoke_structured", mock)
    return mock


async def test_each_group_is_shown_with_its_items_states_and_sides(model: AsyncMock) -> None:
    await heading_problems(USER, COMPOSITION, POOL)

    schema, prompt = model.await_args.args
    assert schema is HeadingVerdicts
    assert (
        'block 2, heading "Landed overnight", state done:\n'
        "- item 1: Offsite venues | waiting on you | action review\n"
        "- item 2: Investor update | done | outcome sent"
    ) in prompt
    assert model.await_args.kwargs["options"].schema_held is True


async def test_the_call_is_labelled_and_metered_to_the_user(model: AsyncMock) -> None:
    await heading_problems(USER, COMPOSITION, POOL)

    assert model.await_args.kwargs["label"] == BRIEF_HEADING_CHECK_LABEL
    assert model.await_args.kwargs["config"] == {"configurable": {"user_id": USER}}


async def test_an_item_with_neither_side_is_shown_as_neither(model: AsyncMock) -> None:
    bare = BriefComposition.model_validate(
        {
            "blocks": [
                {"kind": "note", "text": "A light day."},
                {
                    "kind": "items",
                    "state": "done",
                    "heading": "Landed overnight",
                    "items": [_item(1, "Offsite venues")],
                },
            ]
        }
    )

    await heading_problems(USER, bare, POOL)

    assert "- item 1: Offsite venues | waiting on you | neither" in model.await_args.args[1]


async def test_every_misfit_is_named_with_its_side_or_without_one(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(
        verdicts=[HeadingVerdict(block=2, fits=False, misfits=[1, 2], why="mixed")]
    )
    bare = BriefComposition.model_validate(
        {
            "blocks": [
                {"kind": "note", "text": "A light day."},
                {
                    "kind": "items",
                    "state": "done",
                    "heading": "Landed overnight",
                    "items": [
                        _item(1, "Offsite venues"),
                        _item(2, "Investor update", outcome="sent"),
                    ],
                },
            ]
        }
    )

    assert await heading_problems(USER, bare, POOL) == [
        'block 2 heading "Landed overnight" is not true of item 1 (waiting on you), '
        "item 2 (done, sent): mixed; move them under a heading true of what they are, or "
        "rename this group"
    ]


async def test_a_verdict_naming_no_item_blames_its_items(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(
        verdicts=[HeadingVerdict(block=2, fits=False, misfits=[], why="too vague")]
    )

    assert await heading_problems(USER, COMPOSITION, POOL) == [
        'block 2 heading "Landed overnight" is not true of its items: too vague; move them '
        "under a heading true of what they are, or rename this group"
    ]


async def test_a_heading_untrue_of_an_item_is_named_with_the_item(model: AsyncMock) -> None:
    assert await heading_problems(USER, COMPOSITION, POOL) == [
        'block 2 heading "Landed overnight" is not true of item 1 (waiting on you, review): '
        "still waits on approval; move them under a heading true of what they are, or rename "
        "this group"
    ]


async def test_a_fitting_heading_is_no_problem(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(
        verdicts=[HeadingVerdict(block=2, fits=True, misfits=[], why="both can be read now")]
    )

    assert await heading_problems(USER, COMPOSITION, POOL) == []


async def test_a_group_left_unjudged_fails_loud(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(verdicts=[])

    with pytest.raises(AppError) as raised:
        await heading_problems(USER, COMPOSITION, POOL)

    assert raised.value.message == "the brief's heading check left a group unjudged"
    assert raised.value.why == "no verdict for block(s) [2]"
    assert raised.value.fix == (
        "the next scheduled brief retries; a heading nobody checked is never shown"
    )
    assert raised.value.meta == {"answer": {"verdicts": []}}


async def test_a_composition_without_groups_makes_no_call(model: AsyncMock) -> None:
    only_note = BriefComposition.model_validate({"blocks": [{"kind": "note", "text": "Quiet."}]})

    assert await heading_problems(USER, only_note, POOL) == []
    model.assert_not_awaited()
