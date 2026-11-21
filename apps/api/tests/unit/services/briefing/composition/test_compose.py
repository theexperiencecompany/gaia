"""Composing a brief: one call over the pool, sent back once with its problems named, then salvaged.

Faked seams: the structured model call and the heading check.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

from pydantic import ValidationError
import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event, user_clock

from app.agents.llm.client import StructuredCallOptions
from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts import brief_check_prompts as says
from app.agents.prompts.brief_composition_prompts import (
    COMPOSITION_RETRY_NOTE,
    DAILY_FRAME,
    WEEKLY_FRAME,
)
from app.agents.prompts.brief_fact_prompts import UNREADABLE_COMPOSITION
from app.constants.briefing import BRIEF_COMPOSITION_LABEL, BriefAction, BriefingKind, BriefOutcome
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_composition_models import (
    BriefComposition,
    ChartKind,
    ComposedChart,
    ComposedItem,
    ComposedItems,
)
from app.models.brief_item_models import ItemState
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing import checked_call
from app.services.briefing.composition import compose
from app.services.briefing.composition.compose import compose_brief, pool_values
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.kinds import KIND_SPECS
from app.utils.errors import AppError

USER = make_user_id()
DAILY = KIND_SPECS[BriefingKind.DAILY]
WEEKLY = KIND_SPECS[BriefingKind.WEEKLY]
_CONTEXT = PoolContext(
    reader="Ada",
    clock=user_clock("Asia/Kolkata", date(2026, 11, 11)),
    calendar=1,
    calendar_span="today",
    done_since=datetime(2026, 11, 10, tzinfo=UTC),
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
            origin=CandidateOrigin.TRACKED,
            source="gmail",
            app="Gmail",
            state=ItemState.YOU,
            title="Re: Series A term sheet",
            people=["Maya Chen"],
            gaia_acts=True,
        ),
        2: BriefCandidate(
            origin=CandidateOrigin.TRACKED,
            source="gaia",
            app="GAIA",
            state=ItemState.LOOKBACK,
            title="Board deck numbers",
            gaia_acts=True,
        ),
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
#: Dhruv's Nov 11: a heading that types a figure no fact carries, which code cannot fix alone.
_STRAY_FIGURE = BriefComposition.model_validate(
    {
        "blocks": [
            {
                "kind": "items",
                "state": "needs_you",
                "heading": "9 replies waiting",
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
_STRAY_PROBLEM = (
    "the block 1 (items) heading types '9', a figure no fact carries; say it in words, from "
    "the facts, or leave it out"
)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=_GOOD)
    monkeypatch.setattr(checked_call, "ainvoke_structured", mock)
    return mock


@pytest.fixture(autouse=True)
def headings(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value={})
    monkeypatch.setattr(compose, "heading_problems", mock)
    return mock


def _prompt(model: AsyncMock, call: int = 0) -> str:
    return model.await_args_list[call].args[1]


class TestOneCall:
    async def test_a_holding_composition_comes_back_with_its_slots_filled(
        self, model: AsyncMock
    ) -> None:
        composed = await compose_brief(USER, POOL, DAILY)

        assert composed.written == _GOOD
        chart = composed.rendered.blocks[1]
        assert isinstance(chart, ComposedChart)
        assert chart.takeaway == "Wednesday holds 7 hours."
        assert model.await_count == 1
        assert model.await_args.args[0] is BriefComposition

    async def test_the_prompt_holds_the_whole_pool_the_criteria_and_the_day(
        self, model: AsyncMock
    ) -> None:
        await compose_brief(USER, POOL, DAILY)

        prompt = _prompt(model)
        assert DAILY_FRAME.format(reader="Ada", today="2026-11-11") in prompt
        assert (
            "1. [Gmail] waiting on you: Re: Series A term sheet | names Maya Chen"
            " (the app does not say their part in it) | GAIA can act on it"
        ) in prompt
        assert "2. [GAIA] done: Board deck numbers | GAIA can act on it" in prompt
        assert "calendar_meeting_hours | Meeting hours, in hours" in prompt
        assert "- Gmail: a person waiting on a reply" in prompt
        assert (
            "Wed Nov 11, 2026, Asia/Kolkata.\nCalendar today: 1 event(s), every one listed below."
        ) in prompt
        assert '"Maya is waiting on the term sheet."' in prompt
        assert "{" not in prompt.split("## The pool", 1)[1].split("## Three compositions", 1)[0]

    async def test_the_example_compositions_reach_the_model_as_json(self, model: AsyncMock) -> None:
        """Regression: the examples went out with every brace doubled, {{"blocks": [...]}}."""
        await compose_brief(USER, POOL, DAILY)

        examples = _prompt(model).split("## Three compositions", 1)[1]
        answers = [line for line in examples.splitlines() if line.startswith('{"blocks"')]
        assert len(answers) == 3
        assert "{{" not in examples

    async def test_a_weekly_composition_is_framed_as_the_week(self, model: AsyncMock) -> None:
        await compose_brief(USER, POOL, WEEKLY)

        assert WEEKLY_FRAME.format(reader="Ada", today="2026-11-11") in _prompt(model)

    async def test_a_pool_with_nothing_to_compose_makes_no_call(self, model: AsyncMock) -> None:
        only_event = FactPool(
            items={
                1: BriefCandidate(
                    origin=CandidateOrigin.EVENT,
                    source="googlecalendar",
                    app="Google Calendar",
                    state=ItemState.NOTE,
                    title="Board call",
                )
            },
            series=[],
            quotes=[],
            goals=[],
            context=_CONTEXT,
            criteria={},
        )

        composed = await compose_brief(USER, only_event, DAILY)

        assert composed.rendered.blocks == []
        model.assert_not_awaited()


class TestTheHeadingCheck:
    async def test_a_heading_is_judged_against_its_rendered_items(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        model.return_value = _GROUPED

        await compose_brief(USER, POOL, DAILY)

        user_id, shown, pool = headings.await_args.args
        assert (user_id, pool) == (USER, POOL)
        assert shown.blocks[0].heading == "Landed overnight"

    async def test_a_heading_untrue_of_its_items_sends_it_back_named(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        model.side_effect = [_GROUPED, _GOOD]
        headings.side_effect = [
            {1: 'block 1 heading "Landed overnight" is not true of item(s) 1'},
            {},
        ]

        composed = await compose_brief(USER, POOL, DAILY)

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

        composed = await compose_brief(USER, POOL, DAILY)

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

        await compose_brief(USER, POOL, DAILY)

        field = says.ITEM_FIELD.format(
            where=says.BLOCK_AT.format(number=1, kind="items"), id=1, name="detail"
        )
        problem = says.FACT_HAS_NO_FIELD.format(written="[[fact:1.time]]", id=1, field="time")
        assert says.SLOT_PROBLEM.format(field=field, problem=problem) in _prompt(model, 1)


class TestRetryThenFailLoud:
    async def test_a_broken_composition_is_asked_again_once_with_its_problem_named(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [_STRAY_FIGURE, _GOOD]

        composed = await compose_brief(USER, POOL, DAILY)

        assert composed.written == _GOOD
        retry = _prompt(model, 1)
        assert retry.startswith(_prompt(model, 0))
        assert f"sent back: {_STRAY_PROBLEM}." in retry
        # The retry sees what it wrote, so it can keep what was right.
        assert _STRAY_FIGURE.model_dump_json() in retry

    async def test_what_code_can_hold_it_to_is_enforced_not_sent_back(
        self, model: AsyncMock
    ) -> None:
        """Dhruv's Nov 8: 11 items over the cap of 10 failed the brief and he got nothing."""
        model.return_value = _items_block(_item(7), _item(1), _item(1))

        composed = await compose_brief(USER, POOL, DAILY)

        (group,) = composed.written.blocks
        assert isinstance(group, ComposedItems)
        assert [item.id for item in group.items] == [1]
        model.assert_awaited_once()

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

        composed = await compose_brief(USER, POOL, DAILY)

        assert composed.written == _GOOD
        unreadable = UNREADABLE_COMPOSITION.format(
            problems="BriefComposition: reply made no BriefComposition tool call"
        )
        assert unreadable in _prompt(model, 1)

    async def test_no_composition_twice_builds_the_brief_from_the_pool(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = MalformedStructuredOutputError(
            "BriefComposition: reply stopped at the output cap"
        )

        async with captured_wide_event() as event:
            composed = await compose_brief(USER, POOL, DAILY)

        asks, done = composed.rendered.blocks
        assert isinstance(asks, ComposedItems) and isinstance(done, ComposedItems)
        assert (asks.heading, [(i.id, i.action) for i in asks.items]) == (
            "To review",
            [(1, BriefAction.REVIEW)],
        )
        assert (done.heading, [(i.id, i.outcome) for i in done.items]) == (
            "Done",
            [(2, BriefOutcome.FINISHED)],
        )
        assert model.await_count == 2
        [salvaged] = event["errors"]
        assert (salvaged["msg"], salvaged["call"]) == (
            "briefing.checked_call_salvaged",
            "composition",
        )
        assert "reply stopped at the output cap" in salvaged["problems"]

    async def test_broken_twice_keeps_what_holds_under_a_heading_code_derives(
        self, model: AsyncMock
    ) -> None:
        model.return_value = _STRAY_FIGURE

        composed = await compose_brief(USER, POOL, DAILY)

        (group,) = composed.rendered.blocks
        assert isinstance(group, ComposedItems)
        assert (group.heading, [i.title for i in group.items]) == (
            "Replies to send",
            ["Series A term sheet"],
        )
        assert model.await_count == 2

    async def test_a_salvaged_brief_heads_each_group_by_its_items_without_asking_a_model(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        group = _items_block(_item(1, title="[[fact:1]]")).blocks[0]
        stray_chart = ComposedChart(
            kind="chart",
            chart=ChartKind.LINE,
            series_ids=["no_such_series"],
            title="Meeting hours",
            takeaway="A busy week.",
        )
        model.return_value = BriefComposition(blocks=[group, stray_chart])

        composed = await compose_brief(USER, POOL, DAILY)

        shown = _items_block(_item(1, title="Re: Series A term sheet"))
        assert composed.rendered == BriefComposition(
            blocks=[shown.blocks[0].model_copy(update={"heading": "Replies to send"})]
        )
        headings.assert_not_awaited()

    async def test_a_heading_check_that_fails_cannot_fail_the_salvage(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        """Regression: a salvage that re-ran the heading check failed when it left a group unjudged."""
        model.return_value = _STRAY_FIGURE
        headings.side_effect = AppError(message="unjudged", why="no verdict", fix="retry")

        composed = await compose_brief(USER, POOL, DAILY)

        (group,) = composed.rendered.blocks
        assert isinstance(group, ComposedItems) and group.heading == "Replies to send"

    async def test_a_heading_still_untrue_after_the_retry_gives_way_to_its_items_act(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        """Dhruv's Nov 15: a misfit heading twice failed the brief."""
        model.return_value = _GROUPED
        headings.return_value = {1: 'block 1 heading "Landed overnight" is not true of item 1'}

        composed = await compose_brief(USER, POOL, DAILY)

        (group,) = composed.rendered.blocks
        assert isinstance(group, ComposedItems)
        assert group.heading == "Replies to send"


class TestASalvageKeepsTheHeadingsThatPassed:
    async def test_only_the_misfit_heading_gives_way_and_to_one_true_of_its_items(
        self, model: AsyncMock, headings: AsyncMock
    ) -> None:
        """Founder's Nov 22: one misfit heading twice turned every group's heading to "Needs you"."""
        model.return_value = BriefComposition.model_validate(
            {
                "blocks": [
                    {
                        "kind": "items",
                        "state": "needs_you",
                        "heading": "Maya's term sheet",
                        "items": [_item(1, title="Series A term sheet")],
                    },
                    {
                        "kind": "items",
                        "state": "done",
                        "heading": "Still running",
                        "items": [
                            {
                                "id": 2,
                                "action": None,
                                "outcome": "finished",
                                "title": "Deck",
                                "detail": None,
                            }
                        ],
                    },
                ]
            }
        )
        headings.return_value = {2: 'block 2 heading "Still running" is not true of item 2'}

        composed = await compose_brief(USER, POOL, DAILY)

        assert [b.heading for b in composed.rendered.blocks if isinstance(b, ComposedItems)] == [
            "Maya's term sheet",
            "Done",
        ]
        assert headings.await_count == 2


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
                    origin=CandidateOrigin.TRACKED,
                    source="gmail",
                    app="Gmail",
                    state=ItemState.YOU,
                    title="Due",
                    due_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
                    count=3,
                ),
                2: BriefCandidate(
                    origin=CandidateOrigin.TRACKED,
                    source="gmail",
                    app="Gmail",
                    state=ItemState.YOU,
                    title="Timed",
                    time="11:00 AM",
                    due_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
                ),
                3: BriefCandidate(
                    origin=CandidateOrigin.TRACKED,
                    source="gmail",
                    app="Gmail",
                    state=ItemState.YOU,
                    title="Open",
                ),
            },
            series=[],
            quotes=[],
            goals=[],
            context=_CONTEXT,
            criteria={},
        )

        facts = pool_values(pool).facts

        assert (facts[1].time, facts[1].count) == ("Nov 3", 3)
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

        composed = await compose_brief(USER, POOL, DAILY)

        lead = composed.rendered.blocks[0]
        assert lead.model_dump()["item"]["title"] == "Re: Series A term sheet"
        assert lead.model_dump()["item"]["detail"] == "From Board deck numbers"

    async def test_a_linked_phrase_renders_as_plain_words_since_the_composition_links_nothing(
        self, model: AsyncMock
    ) -> None:
        model.return_value = _items_block(_item(1, title="[Maya's thread](fact:1)"))

        composed = await compose_brief(USER, POOL, DAILY)

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

        composed = await compose_brief(USER, POOL, DAILY)

        group = composed.rendered.blocks[0]
        assert isinstance(group, ComposedItems)
        assert group.heading == "Maya is waiting"


class TestTheCallItself:
    async def test_the_call_is_labelled_metered_for_the_user_and_held_to_the_schema(
        self, model: AsyncMock
    ) -> None:
        await compose_brief(USER, POOL, DAILY)

        assert model.await_args.kwargs == {
            "label": BRIEF_COMPOSITION_LABEL,
            "config": {"configurable": {"user_id": USER}},
            "options": StructuredCallOptions(schema_held=True),
        }

    async def test_the_first_ask_is_the_bare_prompt(self, model: AsyncMock) -> None:
        await compose_brief(USER, POOL, DAILY)

        assert not _prompt(model).endswith("\n\n")
        assert COMPOSITION_RETRY_NOTE.partition("{problems}")[0] not in _prompt(model)

    async def test_a_pool_with_nothing_to_compose_returns_the_empty_composition_and_its_values(
        self, model: AsyncMock
    ) -> None:
        only_event = FactPool(
            items={
                1: BriefCandidate(
                    origin=CandidateOrigin.EVENT,
                    source="googlecalendar",
                    app="Google Calendar",
                    state=ItemState.NOTE,
                    title="Board call",
                    time="9:00 AM",
                )
            },
            series=[],
            quotes=[],
            goals=[],
            context=_CONTEXT,
            criteria={},
        )

        composed = await compose_brief(USER, only_event, DAILY)

        assert composed.written == BriefComposition(blocks=[])
        assert composed.values == pool_values(only_event)
        assert composed.values.facts[1].time == "9:00 AM"

    async def test_the_composed_values_are_what_the_pool_renders(self, model: AsyncMock) -> None:
        composed = await compose_brief(USER, POOL, DAILY)

        assert composed.values == pool_values(POOL)
        assert composed.values.facts[1].title == "Re: Series A term sheet"


class TestWhatARejectionSays:
    async def test_every_problem_is_named_in_the_retry_and_logged(self, model: AsyncMock) -> None:
        broken = _items_block(_item(1, detail="x" * 200))
        stray = broken.blocks[0].model_copy(update={"heading": "9 replies waiting"})
        model.side_effect = [broken.model_copy(update={"blocks": [stray]}), _GOOD]

        async with captured_wide_event() as event:
            await compose_brief(USER, POOL, DAILY)

        problems = [
            "block 1 (items), item 1: a detail over 80 characters",
            _STRAY_PROBLEM,
        ]
        assert event["warnings"] == [
            {"msg": "briefing.checked_call_rejected", "call": "composition", "problems": problems}
        ]
        assert f"was sent back: {'; '.join(problems)}.\n" in _prompt(model, 1)

    async def test_a_reply_that_was_no_composition_is_retried_with_no_last_answer_and_its_reason(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [MalformedStructuredOutputError("cut off at the cap"), _GOOD]

        await compose_brief(USER, POOL, DAILY)

        assert (
            "was sent back: the answer was not a whole BriefComposition tool call "
            "(cut off at the cap).\n"
            "This was your last composition:\n(no whole composition)\n"
        ) in _prompt(model, 1)

    async def test_a_reply_off_the_schema_is_retried_naming_every_field_it_got_wrong(
        self, model: AsyncMock
    ) -> None:
        with pytest.raises(ValidationError) as invalid:
            ComposedItem.model_validate({"id": 1})
        off_schema = MalformedStructuredOutputError("BriefComposition: does not fit the schema")
        off_schema.__cause__ = invalid.value
        model.side_effect = [off_schema, _GOOD]

        await compose_brief(USER, POOL, DAILY)

        assert (
            "the answer was not a whole BriefComposition tool call "
            "(action: Field required; outcome: Field required; title: Field required; "
            "detail: Field required)"
        ) in _prompt(model, 1)


class TestAWeeklyRecaps:
    async def test_a_weekly_that_places_nothing_from_its_pool_is_sent_back(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [BriefComposition(blocks=[]), _GOOD]

        composed = await compose_brief(USER, POOL, WEEKLY)

        assert composed.written == _GOOD
        assert (
            "a weekly digest recaps the week: place what its pool holds of it (what got done, "
            "its series, each goal's progress, even a stalled one) instead of nothing"
        ) in _prompt(model, 1)

    async def test_a_daily_may_leave_its_whole_pool_out(self, model: AsyncMock) -> None:
        model.return_value = BriefComposition(blocks=[])

        composed = await compose_brief(USER, POOL, DAILY)

        assert composed.written == BriefComposition(blocks=[])
        model.assert_awaited_once()
