"""Composing a brief: one call over the pool, sent back once with its problems named, then failing loud.

Faked seams: the structured model call and the faithfulness check's model call.
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition, ComposedChart, ComposedItems
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing.composition import compose
from app.services.briefing.composition.compose import compose_brief
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.faithfulness import CheckedProse, UnsupportedClaim
from app.utils.errors import AppError

USER = "64f1c0ffee0000000000abcd"
_CONTEXT = PoolContext(
    reader="Ada",
    timezone="Asia/Kolkata",
    today=date(2026, 11, 11),
    calendar_events=1,
    calendar_span="today",
    recent_openings=["Maya is waiting on the term sheet."],
)
_MEETINGS = DataSeries(
    id="calendar_meeting_hours",
    label="Meeting hours",
    unit="hours",
    source="googlecalendar",
    app="Google Calendar",
    shape=SeriesShape.TIME_SERIES,
    points=[
        SeriesPoint(x=f"2026-11-{d:02d}", y=y)
        for d, y in zip(range(5, 12), [2, 1.5, 2, 0, 0, 2.5, 7], strict=True)
    ],
)
POOL = FactPool(
    items={
        1: BriefCandidate(
            source="gmail",
            app="Gmail",
            state="you",
            title="Re: Series A term sheet",
            people=["Maya Chen"],
        ),
        2: BriefCandidate(source="gaia", app="GAIA", state="lookback", title="Board deck numbers"),
    },
    series=[_MEETINGS],
    quotes=[],
    goals=[],
    context=_CONTEXT,
    criteria={"Gmail": "a person waiting on a reply"},
)
_GOOD = BriefComposition.model_validate(
    {
        "blocks": [
            {
                "kind": "lead",
                "item": {
                    "id": 1,
                    "action": "reply",
                    "outcome": None,
                    "title": "Series A term sheet",
                    "detail": "Maya needs your sign-off",
                },
                "offer": "Send Maya the reply I drafted",
            },
            {
                "kind": "chart",
                "series_ids": ["calendar_meeting_hours"],
                "chart": "line",
                "title": "Meeting hours this week",
                "takeaway": "[[series:calendar_meeting_hours.peak_at]] holds [[series:calendar_meeting_hours.peak]] hours.",
            },
        ]
    }
)
_GROUPED = BriefComposition.model_validate(
    {
        "blocks": [
            {
                "kind": "items",
                "heading": "Landed overnight",
                "items": [
                    {
                        "id": 1,
                        "action": "reply",
                        "outcome": None,
                        "title": "Series A term sheet",
                        "detail": None,
                    }
                ],
            }
        ]
    }
)
_UNKNOWN_ID = BriefComposition.model_validate(
    {
        "blocks": [
            {
                "kind": "items",
                "heading": "Waiting on you",
                "items": [
                    {
                        "id": 7,
                        "action": "reply",
                        "outcome": None,
                        "title": "Nobody's thread",
                        "detail": None,
                    }
                ],
            }
        ]
    }
)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=_GOOD)
    monkeypatch.setattr(compose, "ainvoke_structured", mock)
    return mock


@pytest.fixture
def checker(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(compose, "unsupported_claims", mock)
    return mock


@pytest.fixture(autouse=True)
def headings(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(compose, "heading_problems", mock)
    return mock


def _prompt(model: AsyncMock, call: int = 0) -> str:
    return model.await_args_list[call].args[1]


class TestOneCall:
    async def test_a_holding_composition_comes_back_with_its_slots_filled(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        chart = composed.rendered.blocks[1]
        assert isinstance(chart, ComposedChart)
        assert chart.takeaway == "Wednesday holds 7 hours."
        assert model.await_count == 1
        assert model.await_args.args[0] is BriefComposition

    async def test_the_prompt_holds_the_whole_pool_the_criteria_and_the_day(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        await compose_brief(USER, POOL, "daily")

        prompt = _prompt(model)
        assert "Ada's morning brief for 2026-11-11" in prompt
        assert "1. [Gmail] waiting on you: Re: Series A term sheet | with Maya Chen" in prompt
        assert "2. [GAIA] done: Board deck numbers" in prompt
        assert "calendar_meeting_hours | Meeting hours, in hours" in prompt
        assert "- Gmail: a person waiting on a reply" in prompt
        assert (
            "Wednesday 11 November 2026, Asia/Kolkata.\n"
            "Calendar today: 1 event(s), every one listed below."
        ) in prompt
        assert '"Maya is waiting on the term sheet."' in prompt
        assert "{" not in prompt.split("## The pool", 1)[1].split("## Three compositions", 1)[0]

    async def test_a_weekly_composition_is_framed_as_the_week(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        await compose_brief(USER, POOL, "weekly")

        assert "Ada's weekly digest for the week ending 2026-11-11" in _prompt(model)

    async def test_a_pool_with_nothing_to_compose_makes_no_call(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        only_event = FactPool(
            items={
                1: BriefCandidate(
                    source="googlecalendar",
                    app="Google Calendar",
                    state="note",
                    title="Board call",
                    is_event=True,
                )
            },
            series=[],
            quotes=[],
            goals=[],
            context=_CONTEXT,
            criteria={},
        )

        composed = await compose_brief(USER, only_event, "daily")

        assert composed.rendered.blocks == []
        model.assert_not_awaited()
        checker.assert_not_awaited()


class TestTheTruthCheck:
    async def test_every_claim_the_composition_wrote_is_checked_with_its_slots_marked(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        await compose_brief(USER, POOL, "daily")

        user_id, facts, checked = checker.await_args.args
        assert user_id == USER
        assert "1. [Gmail] waiting on you: Re: Series A term sheet" in facts
        # The day's context is a fact too: an empty morning is checked against the whole calendar.
        assert "Calendar today: 1 event(s), every one listed below." in facts
        assert isinstance(checked, CheckedProse)
        assert checked.fields == (
            ("block 1 (lead) item 1 title", "Series A term sheet"),
            ("block 1 (lead) item 1 detail", "Maya needs your sign-off"),
            ("block 2 (chart) title", "Meeting hours this week"),
            ("block 2 (chart) takeaway", "⟦Wednesday⟧ holds ⟦7⟧ hours."),
        )

    async def test_a_heading_is_judged_against_its_items_and_not_by_the_truth_check(
        self, model: AsyncMock, checker: AsyncMock, headings: AsyncMock
    ) -> None:
        model.return_value = _GROUPED

        await compose_brief(USER, POOL, "daily")

        user_id, shown, pool = headings.await_args.args
        assert (user_id, pool) == (USER, POOL)
        assert shown.blocks[0].heading == "Landed overnight"
        assert all("heading" not in name for name, _ in checker.await_args.args[2].fields)

    async def test_a_heading_untrue_of_its_items_sends_it_back_named(
        self, model: AsyncMock, checker: AsyncMock, headings: AsyncMock
    ) -> None:
        model.side_effect = [_GROUPED, _GOOD]
        headings.side_effect = [['block 1 heading "Landed overnight" is not true of item(s) 1'], []]

        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        assert 'block 1 heading "Landed overnight" is not true of item(s) 1' in _prompt(model, 1)

    async def test_a_claim_the_pool_does_not_hold_sends_it_back_named(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        checker.side_effect = [
            [UnsupportedClaim(quote="Maya needs your sign-off", fact="absent", truth="no ask")],
            [],
        ]

        await compose_brief(USER, POOL, "daily")

        assert model.await_count == 2
        assert '"Maya needs your sign-off": no fact holds it; no ask' in _prompt(model, 1)


class TestItemWording:
    async def test_a_slot_in_an_items_wording_is_filled_and_a_figure_from_its_line_may_stay(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        worded = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "heading": "Waiting on you",
                        "items": [
                            {
                                "id": 1,
                                "action": "reply",
                                "outcome": None,
                                "title": "[[fact:1]]",
                                "detail": "Maya needs it by the 14th",
                            }
                        ],
                    }
                ]
            }
        )
        model.return_value = worded

        composed = await compose_brief(USER, POOL, "daily")

        group = composed.rendered.blocks[0]
        assert isinstance(group, ComposedItems)
        item = group.items[0]
        assert (item.title, item.detail) == ("Re: Series A term sheet", "Maya needs it by the 14th")
        assert (
            "block 1 (items) item 1 title",
            "⟦Re: Series A term sheet⟧",
        ) in checker.await_args.args[2].fields

    async def test_a_slot_in_an_items_wording_that_names_nothing_is_sent_back(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        bad = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "heading": "Money",
                        "items": [
                            {
                                "id": 1,
                                "action": "reply",
                                "outcome": None,
                                "title": "Term sheet",
                                "detail": "Overdue by [[fact:1.time]]",
                            }
                        ],
                    }
                ]
            }
        )
        model.side_effect = [bad, _GOOD]

        await compose_brief(USER, POOL, "daily")

        assert "the block 1 (items) item 1 detail: [[fact:1.time]]: fact 1 has no time" in _prompt(
            model, 1
        )


class TestRetryThenFailLoud:
    async def test_a_broken_composition_is_asked_again_once_with_its_problem_named(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        model.side_effect = [_UNKNOWN_ID, _GOOD]

        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        retry = _prompt(model, 1)
        assert retry.startswith(_prompt(model, 0))
        assert "sent back: block 1 (items), item 7: no item 7 in the pool." in retry

    async def test_a_reply_that_is_no_composition_is_asked_again_like_a_broken_one(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        """Gemini flash-lite answered in prose instead of the tool call; one sample is not the lane."""
        model.side_effect = [
            MalformedStructuredOutputError(
                "BriefComposition: reply made no BriefComposition tool call"
            ),
            _GOOD,
        ]

        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        assert "the answer was not a whole BriefComposition tool call" in _prompt(model, 1)

    async def test_no_composition_twice_fails_loud(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        model.side_effect = MalformedStructuredOutputError(
            "BriefComposition: reply stopped at the output cap"
        )

        with pytest.raises(AppError, match="composition broke its contract") as raised:
            await compose_brief(USER, POOL, "daily")

        assert "reply stopped at the output cap" in raised.value.why
        assert model.await_count == 2

    async def test_broken_twice_fails_loud_naming_the_problem(
        self, model: AsyncMock, checker: AsyncMock
    ) -> None:
        model.return_value = _UNKNOWN_ID

        with pytest.raises(AppError, match="composition broke its contract") as raised:
            await compose_brief(USER, POOL, "daily")

        assert raised.value.why == "block 1 (items), item 7: no item 7 in the pool"
        assert model.await_count == 2
        checker.assert_not_awaited()
