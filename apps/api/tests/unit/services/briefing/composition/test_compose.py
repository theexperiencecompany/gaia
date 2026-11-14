"""Composing a brief: one call over the pool, sent back once with its problems named, then failing loud.

Faked seams: the structured model call and the heading check.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.llm.client import StructuredCallOptions
from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.constants.briefing import BRIEF_COMPOSITION_LABEL
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition, ComposedChart, ComposedItems
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing.composition import compose
from app.services.briefing.composition.compose import compose_brief, pool_values
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.utils.errors import AppError

USER = "64f1c0ffee0000000000abcd"
_CONTEXT = PoolContext(
    reader="Ada",
    timezone="Asia/Kolkata",
    today=date(2026, 11, 11),
    calendar_events=1,
    calendar_connected=True,
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
                "state": "needs_you",
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
                "state": "needs_you",
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


@pytest.fixture(autouse=True)
def headings(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(compose, "heading_problems", mock)
    return mock


def _prompt(model: AsyncMock, call: int = 0) -> str:
    return model.await_args_list[call].args[1]


class TestOneCall:
    async def test_a_holding_composition_comes_back_with_its_slots_filled(
        self, model: AsyncMock
    ) -> None:
        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        chart = composed.rendered.blocks[1]
        assert isinstance(chart, ComposedChart)
        assert chart.takeaway == "Wednesday holds 7 hours."
        assert model.await_count == 1
        assert model.await_args.args[0] is BriefComposition

    async def test_the_prompt_holds_the_whole_pool_the_criteria_and_the_day(
        self, model: AsyncMock
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

    async def test_a_weekly_composition_is_framed_as_the_week(self, model: AsyncMock) -> None:
        await compose_brief(USER, POOL, "weekly")

        assert "Ada's weekly digest for the week ending 2026-11-11" in _prompt(model)

    async def test_a_pool_with_nothing_to_compose_makes_no_call(self, model: AsyncMock) -> None:
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


class TestTheHeadingCheck:
    async def test_a_heading_is_judged_against_its_rendered_items(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        model.return_value = _GROUPED

        await compose_brief(USER, POOL, "daily")

        user_id, shown, pool = headings.await_args.args
        assert (user_id, pool) == (USER, POOL)
        assert shown.blocks[0].heading == "Landed overnight"

    async def test_a_heading_untrue_of_its_items_sends_it_back_named(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        model.side_effect = [_GROUPED, _GOOD]
        headings.side_effect = [['block 1 heading "Landed overnight" is not true of item(s) 1'], []]

        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        assert 'block 1 heading "Landed overnight" is not true of item(s) 1' in _prompt(model, 1)


class TestItemWording:
    async def test_a_slot_in_an_items_wording_is_filled_and_a_figure_from_its_line_may_stay(
        self, model: AsyncMock
    ) -> None:
        worded = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "state": "needs_you",
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

    async def test_a_slot_in_an_items_wording_that_names_nothing_is_sent_back(
        self, model: AsyncMock
    ) -> None:
        bad = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "state": "needs_you",
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
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [_UNKNOWN_ID, _GOOD]

        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == _GOOD
        retry = _prompt(model, 1)
        assert retry.startswith(_prompt(model, 0))
        assert "sent back: block 1 (items), item 7: no item 7 in the pool." in retry
        # The retry sees what it wrote, so it can keep what was right.
        assert _UNKNOWN_ID.model_dump_json() in retry

    async def test_a_reply_that_is_no_composition_is_asked_again_like_a_broken_one(
        self, model: AsyncMock
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

    async def test_no_composition_twice_fails_loud(self, model: AsyncMock) -> None:
        model.side_effect = MalformedStructuredOutputError(
            "BriefComposition: reply stopped at the output cap"
        )

        with pytest.raises(AppError, match="composition broke its contract") as raised:
            await compose_brief(USER, POOL, "daily")

        assert "reply stopped at the output cap" in raised.value.why
        assert model.await_count == 2

    async def test_broken_twice_fails_loud_naming_the_problem(self, model: AsyncMock) -> None:
        model.return_value = _UNKNOWN_ID

        with pytest.raises(AppError, match="composition broke its contract") as raised:
            await compose_brief(USER, POOL, "daily")

        assert raised.value.why == "block 1 (items), item 7: no item 7 in the pool"
        assert model.await_count == 2


def _items_block(*items: dict[str, object]) -> BriefComposition:
    return BriefComposition.model_validate(
        {
            "blocks": [
                {"kind": "items", "state": "needs_you", "heading": "Waiting on you", "items": items}
            ]
        }
    )


def _item(item_id: int, title: str = "Term sheet", detail: str | None = None) -> dict[str, object]:
    return {"id": item_id, "action": "reply", "outcome": None, "title": title, "detail": detail}


class TestWhatSlotsRender:
    def test_a_due_item_renders_its_date_a_timed_one_its_time_and_a_count_is_kept(self) -> None:
        pool = FactPool(
            items={
                1: BriefCandidate(
                    source="gmail",
                    app="Gmail",
                    state="you",
                    title="Due",
                    due_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
                    count=3,
                ),
                2: BriefCandidate(
                    source="gmail",
                    app="Gmail",
                    state="you",
                    title="Timed",
                    time="11:00 AM",
                    due_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
                ),
                3: BriefCandidate(source="gmail", app="Gmail", state="you", title="Open"),
            },
            series=[],
            quotes=[],
            goals=[],
            context=_CONTEXT,
            criteria={},
        )

        facts = pool_values(pool).facts

        assert (facts[1].time, facts[1].count) == ("Tue Nov 3", 3)
        assert facts[2].time == "11:00 AM"
        assert facts[3].time is None

    async def test_a_lead_items_wording_is_filled(self, model: AsyncMock) -> None:
        model.return_value = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "lead",
                        "item": _item(1, title="[[fact:1]]", detail="From [[fact:2]]"),
                        "offer": "Send Maya the reply I drafted",
                    }
                ]
            }
        )

        composed = await compose_brief(USER, POOL, "daily")

        lead = composed.rendered.blocks[0]
        assert lead.model_dump()["item"]["title"] == "Re: Series A term sheet"
        assert lead.model_dump()["item"]["detail"] == "From Board deck numbers"

    async def test_a_linked_phrase_renders_as_plain_words_since_the_composition_links_nothing(
        self, model: AsyncMock
    ) -> None:
        model.return_value = _items_block(_item(1, title="[Maya's thread](fact:1)"))

        composed = await compose_brief(USER, POOL, "daily")

        group = composed.rendered.blocks[0]
        assert isinstance(group, ComposedItems)
        assert group.items[0].title == "Maya's thread"
        assert composed.rendered.blocks[0] != composed.written.blocks[0]

    async def test_a_linked_phrase_in_a_blocks_own_words_renders_as_plain_words(
        self, model: AsyncMock
    ) -> None:
        model.return_value = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "state": "needs_you",
                        "heading": "[Maya](fact:1) is waiting",
                        "items": [_item(1)],
                    }
                ]
            }
        )

        composed = await compose_brief(USER, POOL, "daily")

        group = composed.rendered.blocks[0]
        assert isinstance(group, ComposedItems)
        assert group.heading == "Maya is waiting"


class TestTheCallItself:
    async def test_the_call_is_labelled_metered_for_the_user_and_held_to_the_schema(
        self, model: AsyncMock
    ) -> None:
        await compose_brief(USER, POOL, "daily")

        assert model.await_args.kwargs == {
            "label": BRIEF_COMPOSITION_LABEL,
            "config": {"configurable": {"user_id": USER}},
            "options": StructuredCallOptions(schema_held=True),
        }

    async def test_the_first_ask_is_the_bare_prompt(self, model: AsyncMock) -> None:
        await compose_brief(USER, POOL, "daily")

        assert not _prompt(model).endswith("\n\n")
        assert "Your last composition was sent back" not in _prompt(model)

    async def test_a_pool_with_nothing_to_compose_returns_the_empty_composition_and_its_values(
        self, model: AsyncMock
    ) -> None:
        only_event = FactPool(
            items={
                1: BriefCandidate(
                    source="googlecalendar",
                    app="Google Calendar",
                    state="note",
                    title="Board call",
                    is_event=True,
                    time="9:00 AM",
                )
            },
            series=[],
            quotes=[],
            goals=[],
            context=_CONTEXT,
            criteria={},
        )

        composed = await compose_brief(USER, only_event, "daily")

        assert composed.written == BriefComposition(blocks=[])
        assert composed.values == pool_values(only_event)
        assert composed.values.facts[1].time == "9:00 AM"

    async def test_the_composed_values_are_what_the_pool_renders(self, model: AsyncMock) -> None:
        composed = await compose_brief(USER, POOL, "daily")

        assert composed.values == pool_values(POOL)
        assert composed.values.facts[1].title == "Re: Series A term sheet"


class TestWhatARejectionSays:
    async def test_every_problem_is_named_in_the_retry_and_logged(
        self, model: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = MagicMock()
        monkeypatch.setattr(compose, "log", log)
        model.side_effect = [_items_block(_item(7), _item(8)), _GOOD]

        await compose_brief(USER, POOL, "daily")

        problems = [
            "block 1 (items), item 7: no item 7 in the pool",
            "block 1 (items), item 8: no item 8 in the pool",
        ]
        log.warning.assert_called_once_with("briefing.composition_rejected", problems=problems)
        assert f"was sent back: {'; '.join(problems)}.\n" in _prompt(model, 1)

    async def test_a_reply_that_was_no_composition_is_retried_with_no_last_answer_and_its_reason(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [MalformedStructuredOutputError("cut off at the cap"), _GOOD]

        await compose_brief(USER, POOL, "daily")

        assert (
            "was sent back: the answer was not a whole BriefComposition tool call "
            "(cut off at the cap).\n"
            "This was your last composition:\n(no whole composition)\n"
        ) in _prompt(model, 1)

    async def test_the_failure_names_every_problem_what_was_tried_and_the_last_answer(
        self, model: AsyncMock
    ) -> None:
        broken = _items_block(_item(7), _item(8))
        model.return_value = broken

        with pytest.raises(AppError) as raised:
            await compose_brief(USER, POOL, "daily")

        error = raised.value
        assert error.message == "the brief's composition broke its contract"
        assert error.why == (
            "block 1 (items), item 7: no item 7 in the pool; "
            "block 1 (items), item 8: no item 8 in the pool"
        )
        assert error.fix == (
            "the composition was asked again once with the problems named; "
            "the next scheduled brief retries"
        )
        assert error.meta == {"answer": broken.model_dump()}

    async def test_a_failure_with_no_answer_at_all_carries_none(self, model: AsyncMock) -> None:
        model.side_effect = MalformedStructuredOutputError("cut off at the cap")

        with pytest.raises(AppError) as raised:
            await compose_brief(USER, POOL, "daily")

        assert raised.value.meta == {"answer": None}
        assert raised.value.why == (
            "the answer was not a whole BriefComposition tool call (cut off at the cap)"
        )


class TestAWeeklyRecaps:
    async def test_a_weekly_that_places_nothing_from_its_pool_is_sent_back(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [BriefComposition(blocks=[]), _GOOD]

        composed = await compose_brief(USER, POOL, "weekly")

        assert composed.written == _GOOD
        assert (
            "a weekly digest recaps the week: place what its pool holds of it (what got done, "
            "its series, each goal's progress, even a stalled one) instead of nothing"
        ) in _prompt(model, 1)

    async def test_a_daily_may_leave_its_whole_pool_out(self, model: AsyncMock) -> None:
        model.return_value = BriefComposition(blocks=[])

        composed = await compose_brief(USER, POOL, "daily")

        assert composed.written == BriefComposition(blocks=[])
        model.assert_awaited_once()
