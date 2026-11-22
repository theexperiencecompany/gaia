"""Every group heading is judged against the items under it, and a heading untrue of one is named.

Faked seam: the structured model call the heading check makes.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event, unfenced, user_clock

from app.constants.briefing import BRIEF_HEADING_CHECK_LABEL
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_composition_models import BriefComposition
from app.models.brief_item_models import ItemState
from app.models.scout_models import Signal, SignalMemoryDocument
from app.services.briefing.composition import headings
from app.services.briefing.composition.headings import (
    HeadingVerdict,
    HeadingVerdicts,
    heading_problems,
)
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.utils.errors import AppError

USER_ID = make_user_id()
POOL = FactPool(
    items={
        1: BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.YOU,
            title="Priya's offsite venues",
        ),
        2: BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.LOOKBACK,
            title="Investor update",
        ),
    },
    series=[],
    quotes=[],
    goals=[],
    context=PoolContext(
        reader="Ada",
        clock=user_clock("UTC", date(2026, 11, 11)),
        calendar=0,
        calendar_span="today",
        done_since=datetime(2026, 11, 10, tzinfo=UTC),
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


TWO_GROUPS = BriefComposition.model_validate(
    {
        "blocks": [
            {
                "kind": "items",
                "state": "needs_you",
                "heading": "Waiting on you",
                "items": [_item(1, "Offsite venues", action="review")],
            },
            {
                "kind": "items",
                "state": "done",
                "heading": "Landed overnight",
                "items": [_item(2, "Investor update", outcome="sent")],
            },
        ]
    }
)


def _fits(block: int) -> HeadingVerdict:
    return HeadingVerdict(block=block, why="fits", misfits=[], fits=True)


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
    await heading_problems(USER_ID, COMPOSITION, POOL)

    schema, prompt = model.await_args.args
    assert schema is HeadingVerdicts
    assert (
        'block 2, heading "Landed overnight", state done:\n'
        "- item 1: Offsite venues | waiting on you | action review\n"
        "- item 2: Investor update | done | outcome sent"
    ) in prompt
    assert model.await_args.kwargs["options"].schema_held is True


async def test_each_group_is_its_own_paragraph(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(verdicts=[_fits(1), _fits(2)])

    await heading_problems(USER_ID, TWO_GROUPS, POOL)

    assert (
        "- item 1: Offsite venues | waiting on you | action review\n"
        "\n"
        'block 2, heading "Landed overnight", state done:\n'
    ) in model.await_args.args[1]


async def test_item_titles_are_fenced_as_data(model: AsyncMock) -> None:
    await heading_problems(USER_ID, COMPOSITION, POOL)

    prompt = model.await_args.args[1]
    assert "Offsite venues" in prompt
    assert "Offsite venues" not in unfenced(prompt)


async def test_the_call_is_labelled_and_metered_to_the_user(model: AsyncMock) -> None:
    await heading_problems(USER_ID, COMPOSITION, POOL)

    assert model.await_args.kwargs["label"] == BRIEF_HEADING_CHECK_LABEL
    assert model.await_args.kwargs["config"] == {"configurable": {"user_id": USER_ID}}


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

    await heading_problems(USER_ID, bare, POOL)

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

    assert await heading_problems(USER_ID, bare, POOL) == {
        2: 'block 2 heading "Landed overnight" is not true of item 1 (waiting on you), '
        "item 2 (done, sent): mixed; move them under a heading true of what they are, or "
        "rename this group to one true of every item's act (sent)"
    }


async def test_a_verdict_naming_no_item_blames_its_items(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(
        verdicts=[HeadingVerdict(block=2, fits=False, misfits=[], why="too vague")]
    )

    assert await heading_problems(USER_ID, COMPOSITION, POOL) == {
        2: 'block 2 heading "Landed overnight" is not true of its items: too vague; move them '
        "under a heading true of what they are, or rename this group to one true of every "
        "item's act (review, sent)"
    }


async def test_a_heading_untrue_of_an_item_is_named_with_the_item(model: AsyncMock) -> None:
    assert await heading_problems(USER_ID, COMPOSITION, POOL) == {
        2: 'block 2 heading "Landed overnight" is not true of item 1 (waiting on you, review): '
        "still waits on approval; move them under a heading true of what they are, or rename "
        "this group to one true of every item's act (review, sent)"
    }


async def test_a_fitting_heading_is_no_problem(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(
        verdicts=[HeadingVerdict(block=2, fits=True, misfits=[], why="both can be read now")]
    )

    assert await heading_problems(USER_ID, COMPOSITION, POOL) == {}


async def test_a_group_left_unjudged_is_asked_about_again_alone(model: AsyncMock) -> None:
    """Founder's Nov 22: one verdict left out ("no verdict for block 5") failed the whole brief."""
    model.side_effect = [
        HeadingVerdicts(verdicts=[_fits(1)]),
        HeadingVerdicts(verdicts=[_fits(2)]),
    ]

    assert await heading_problems(USER_ID, TWO_GROUPS, POOL) == {}

    again = model.await_args_list[1].args[1]
    assert 'block 2, heading "Landed overnight"' in again
    assert "block 1," not in again


async def test_a_group_still_unjudged_is_rejected_by_name(model: AsyncMock) -> None:
    model.side_effect = [HeadingVerdicts(verdicts=[_fits(1)]), HeadingVerdicts(verdicts=[])]

    async with captured_wide_event() as event:
        problems = await heading_problems(USER_ID, TWO_GROUPS, POOL)

    assert problems == {
        2: 'block 2 heading "Landed overnight" went unchecked against its items; head this '
        "group with words true of every item's act (sent)"
    }
    assert model.await_count == 2
    assert event["warnings"] == [
        {"msg": "briefing.heading_check_unjudged", "blocks": [2], "still_unjudged": [2]}
    ]


async def test_a_judged_group_is_never_asked_about_twice(model: AsyncMock) -> None:
    model.return_value = HeadingVerdicts(verdicts=[_fits(1), _fits(2)])

    await heading_problems(USER_ID, TWO_GROUPS, POOL)

    model.assert_awaited_once()


async def test_a_heading_check_whose_call_fails_fails_loud(model: AsyncMock) -> None:
    model.side_effect = AppError(message="provider down", why="5xx after retries", fix="retry")

    with pytest.raises(AppError, match="provider down"):
        await heading_problems(USER_ID, COMPOSITION, POOL)


async def test_a_composition_without_groups_makes_no_call(model: AsyncMock) -> None:
    only_note = BriefComposition.model_validate({"blocks": [{"kind": "note", "text": "Quiet."}]})

    assert await heading_problems(USER_ID, only_note, POOL) == {}
    model.assert_not_awaited()


def test_the_verdict_follows_its_reasoning_in_the_schema_the_model_fills() -> None:
    """Regression: with fits first, the check wrote "fits" in its why and still answered False."""
    fields = list(HeadingVerdict.model_json_schema()["properties"])

    assert fields.index("why") < fields.index("fits")
    assert fields[-1] == "fits"


async def test_an_item_an_earlier_brief_saw_unchanged_is_shown_as_not_new(model: AsyncMock) -> None:
    """Sim 12-05: issues the 12-04 brief saw, never mentioned, went out under "New GitHub issues"."""
    seen = SignalMemoryDocument(
        user_id=USER_ID,
        integration_id="github",
        external_id="1369",
        first_seen=datetime(2026, 11, 10, tzinfo=UTC),
        last_state="open",
    )
    known = replace(
        POOL, items={**POOL.items, 1: POOL.items[1].model_copy(update={"memory": seen})}
    )

    await heading_problems(USER_ID, COMPOSITION, known)

    prompt = model.await_args.args[1]
    assert "- item 1: Offsite venues | waiting on you | action review | not new" in prompt
    assert "- item 2: Investor update | done | outcome sent\n" in prompt + "\n"


async def test_an_item_the_app_made_before_the_last_brief_is_shown_as_not_new(
    model: AsyncMock,
) -> None:
    """Sim 12-03: issues made before the 12-02 brief, which never saw them, went out as new."""

    def issue(created: datetime) -> BriefCandidate:
        made = Signal(
            integration_id="github",
            app="GitHub",
            external_id=f"{created.day}",
            kind="issue",
            title="Emoji crash",
            created_at=created,
        )
        return POOL.items[1].model_copy(update={"signal": made})

    pool = replace(
        POOL,
        items={
            1: issue(datetime(2026, 11, 9, tzinfo=UTC)),
            2: issue(datetime(2026, 11, 10, 6, tzinfo=UTC)),
        },
    )

    await heading_problems(USER_ID, COMPOSITION, pool)

    prompt = model.await_args.args[1]
    assert "- item 1: Offsite venues | waiting on you | action review | not new" in prompt
    (made_after,) = [line for line in prompt.splitlines() if line.startswith("- item 2:")]
    assert not made_after.endswith("not new")
