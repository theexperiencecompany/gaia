"""The composition contract: ids only and each once, charts that fit their series, the page budget, slots."""

from collections.abc import Mapping
from datetime import date

import pytest

from app.constants.briefing import (
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    MAX_BAR_CATEGORIES,
    MAX_BRIEF_BLOCKS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    MIN_TREND_POINTS,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition
from app.models.brief_pool_models import (
    DataSeries,
    GoalOrigin,
    GoalState,
    QuoteSpan,
    SeriesPoint,
    SeriesShape,
)
from app.services.briefing.composition.checks import composition_problems
from app.services.briefing.composition.compose import pool_values
from app.services.briefing.fact_pool.pool import FactPool, PoolContext

_DAYS = [f"2026-11-{d:02d}" for d in range(5, 12)]


def _series(
    series_id: str, ys: list[float], *, unit: str = "hours", days: list[str] | None = None
) -> DataSeries:
    xs = days or _DAYS[-len(ys) :]
    return DataSeries(
        id=series_id,
        label=series_id,
        unit=unit,
        source="gaia",
        app="GAIA",
        shape=SeriesShape.TIME_SERIES,
        points=[SeriesPoint(x=x, y=y) for x, y in zip(xs, ys, strict=True)],
    )


def _categories(series_id: str, count: int) -> DataSeries:
    return DataSeries(
        id=series_id,
        label="open invoice",
        unit="USD",
        source="stripe",
        app="Stripe",
        shape=SeriesShape.CATEGORICAL,
        points=[SeriesPoint(x=f"INV-{n}", y=100 * n) for n in range(1, count + 1)],
    )


def _item(title: str, **fields: object) -> BriefCandidate:
    return BriefCandidate.model_validate(
        {"source": "gaia", "app": "GAIA", "state": "you", "title": title, **fields}
    )


# Titles hold no bare figure, so a figure typed beside them is the composition's own.
_TITLES = [
    "Acme invoice",
    "Priya's offsite venues",
    "Board deck numbers",
    "Lisbon flights",
    "Checkout bug",
    "Hiring loop",
    "Pricing page copy",
    "Seed round memo",
    "Design review",
    "Lease renewal",
    "Visa paperwork",
    "Team offsite agenda",
]

POOL = FactPool(
    items={
        **{n: _item(title) for n, title in enumerate(_TITLES, start=1)},
        13: _item("Board call", state="note", is_event=True, time="4:00 PM"),
        14: _item("Re: Re: Fwd: the revised Series A term sheet, with all redlines"),
    },
    series=[
        _series("meetings", [2, 1.5, 2, 0, 0, 2.5, 7]),
        _series("short", [1, 2, 3]),
        _series(
            "late_start", [1, 2, 3, 4, 5, 6, 7], days=[f"2026-11-{d:02d}" for d in range(6, 13)]
        ),
        _series("threads_closed", [1, 0, 2, 3, 1, 0, 4], unit="threads"),
        _series("threads_taken", [2, 1, 2, 4, 1, 1, 3], unit="threads"),
        _series("emails", [9, 8, 7, 9, 8, 9, 30], unit="emails"),
        _categories("invoices", MAX_BAR_CATEGORIES),
        _categories("all_invoices", MAX_BAR_CATEGORIES + 1),
    ],
    quotes=[
        QuoteSpan(
            id="q1",
            text="Can you confirm by Friday?",
            author="Maya",
            source="gmail",
            app="Gmail",
            item_id=1,
        )
    ],
    goals=[GoalState(id="g1", statement="Ship v3", origin=GoalOrigin.MEMORY, done=2, open=1)],
    context=PoolContext(
        reader="Ada",
        timezone="UTC",
        today=date(2026, 11, 11),
        calendar_events=1,
        calendar_span="today",
        recent_openings=[],
    ),
    criteria={},
)


def _ask(item_id: int) -> dict[str, object]:
    title = POOL.items[item_id].title if item_id in POOL.items else "Somebody's thread"
    return {"id": item_id, "action": "reply", "title": title}


def _items(*ids: int, heading: str = "Waiting on you") -> dict[str, object]:
    return {"kind": "items", "heading": heading, "items": [_ask(i) for i in ids]}


def _chart(
    *series_ids: str, chart: str = "line", takeaway: str = "Today is the heaviest."
) -> dict[str, object]:
    return {
        "kind": "chart",
        "series_ids": list(series_ids),
        "chart": chart,
        "title": "This week",
        "takeaway": takeaway,
    }


def _problems(*blocks: Mapping[str, object]) -> list[str]:
    composition = BriefComposition.model_validate({"blocks": list(blocks)})
    return composition_problems(composition, POOL, pool_values(POOL))


class TestAHoldingComposition:
    def test_every_kind_of_block_over_real_ids_holds(self) -> None:
        assert (
            _problems(
                {"kind": "lead", "items": [_ask(13)], "offer": "Prep the board call notes"},
                {"kind": "quote", "quote_id": "q1"},
                _items(1, 2),
                _chart("meetings", takeaway="Today holds [[series:meetings.peak]] hours."),
                _chart("threads_closed", "threads_taken", chart="stacked_bar"),
                {"kind": "progress", "goal_id": "g1"},
                {"kind": "note", "text": "A light day after [[fact:13]]."},
            )
            == []
        )

    def test_an_empty_composition_holds(self) -> None:
        assert _problems() == []


class TestIdsOnlyAndEachOnce:
    @pytest.mark.parametrize(
        ("block", "problem"),
        [
            (_items(99), "block 1 (items), item 99: no item 99 in the pool"),
            (_chart("nope"), "block 1 (chart): no series nope in the pool"),
            ({"kind": "quote", "quote_id": "q9"}, "block 1 (quote): no quote q9 in the pool"),
            ({"kind": "progress", "goal_id": "g9"}, "block 1 (progress): no goal g9 in the pool"),
        ],
        ids=["item", "series", "quote", "goal"],
    )
    def test_an_unknown_id_of_any_kind_is_named(
        self, block: dict[str, object], problem: str
    ) -> None:
        assert _problems(block) == [problem]

    def test_an_item_placed_in_two_blocks_is_named(self) -> None:
        assert _problems(_items(1, 2), _items(2, heading="Also")) == [
            "placed more than once: item 2"
        ]

    def test_a_series_drawn_by_two_charts_is_named(self) -> None:
        assert _problems(_chart("meetings"), _chart("meetings", chart="spark")) == [
            "placed more than once: series meetings"
        ]

    def test_a_calendar_event_can_only_lead(self) -> None:
        assert _problems(_items(13)) == [
            "block 1 (items), item 13: a calendar event can only lead; the edition draws the day's calendar"
        ]


class TestChartsFitTheirSeries:
    @pytest.mark.parametrize("chart", ["line", "spark"])
    def test_a_trend_on_fewer_than_five_days_is_refused(self, chart: str) -> None:
        assert len(POOL.series_by_id["short"].points) < MIN_TREND_POINTS

        assert _problems(_chart("short", chart=chart)) == [
            f"block 1 (chart): a {chart} needs a time series of at least {MIN_TREND_POINTS} days"
        ]

    def test_a_line_over_series_on_different_days_is_refused(self) -> None:
        assert _problems(_chart("meetings", "late_start")) == [
            "block 1 (chart): a line over several series needs them to share their days"
        ]
        assert _problems(_chart("threads_closed", "threads_taken")) == []

    def test_a_trend_on_categories_is_refused(self) -> None:
        assert _problems(_chart("invoices")) == [
            f"block 1 (chart): a line needs a time series of at least {MIN_TREND_POINTS} days"
        ]

    def test_a_bar_over_twelve_categories_is_refused_and_twelve_holds(self) -> None:
        assert _problems(_chart("invoices", chart="bar")) == []
        assert _problems(_chart("all_invoices", chart="bar")) == [
            f"block 1 (chart): a bar draws at most {MAX_BAR_CATEGORIES} bars, not 13"
        ]

    def test_a_bar_draws_one_series_and_a_spark_one_line(self) -> None:
        assert _problems(_chart("threads_closed", "threads_taken", chart="bar")) == [
            "block 1 (chart): a bar draws one series; stack several"
        ]
        assert _problems(_chart("threads_closed", "threads_taken", chart="spark")) == [
            "block 1 (chart): a spark draws one series"
        ]

    def test_a_stack_needs_two_series_of_one_unit_on_the_same_days(self) -> None:
        assert _problems(_chart("meetings", chart="stacked_bar")) == [
            "block 1 (chart): a stacked_bar needs two or more series sharing their days or categories"
        ]
        assert _problems(_chart("meetings", "emails", chart="stacked_bar")) == [
            "block 1 (chart): a stacked_bar stacks one unit, not emails, hours"
        ]
        assert _problems(_chart("meetings", "invoices", chart="stacked_bar")) == [
            "block 1 (chart): a stacked_bar needs two or more series sharing their days or categories"
        ]

    def test_a_chart_without_its_kind_or_series_is_named(self) -> None:
        assert _problems({"kind": "chart", "title": "Week", "takeaway": "Busy."}) == [
            "block 1 (chart): no chart kind (bar, line, spark, stacked_bar)",
            "block 1 (chart): no series_ids",
        ]


class TestThePageBudget:
    def test_more_blocks_than_a_brief_holds_is_refused(self) -> None:
        notes: list[dict[str, object]] = [
            {"kind": "note", "text": f"Note {chr(97 + n)}."} for n in range(MAX_BRIEF_BLOCKS + 1)
        ]

        assert _problems(*notes) == [
            f"{MAX_BRIEF_BLOCKS + 1} blocks; a brief holds at most {MAX_BRIEF_BLOCKS}"
        ]

    def test_more_items_than_a_brief_holds_is_refused(self) -> None:
        groups = [
            _items(1, 2, 3, 4, 5),
            _items(6, 7, 8, 9, 10, heading="Also"),
            _items(11, heading="And"),
        ]

        assert _problems(*groups) == [
            f"{MAX_BRIEF_ITEMS + 1} items in all; a brief holds at most {MAX_BRIEF_ITEMS}"
        ]

    def test_a_group_over_its_size_or_empty_is_refused(self) -> None:
        assert _problems(_items(*range(1, MAX_ITEMS_PER_BLOCK + 2))) == [
            f"block 1 (items): {MAX_ITEMS_PER_BLOCK + 1} items; a group holds 1 to {MAX_ITEMS_PER_BLOCK}"
        ]
        assert _problems(_items()) == [
            f"block 1 (items): 0 items; a group holds 1 to {MAX_ITEMS_PER_BLOCK}"
        ]

    def test_a_third_chart_is_refused(self) -> None:
        charts = [_chart("meetings"), _chart("emails"), _chart("threads_closed")]

        assert _problems(*charts) == ["3 charts; a brief holds at most 2"]


class TestEachBlockHasItsShape:
    def test_an_item_with_both_or_neither_of_action_and_outcome_is_refused(self) -> None:
        both = {"id": 1, "action": "reply", "outcome": "sent", "title": "Acme invoice"}
        neither = {"id": 2, "title": "Offsite venues"}

        assert _problems({"kind": "items", "heading": "Mixed", "items": [both, neither]}) == [
            "block 1 (items), item 1: give exactly one of action (it needs the user) or outcome (it got somewhere)",
            "block 1 (items), item 2: give exactly one of action (it needs the user) or outcome (it got somewhere)",
        ]

    def test_a_title_is_measured_as_the_brief_shows_it_with_its_slots_filled(self) -> None:
        long_title = {"id": 14, "action": "reply", "title": "[[fact:14]]"}

        assert _problems({"kind": "items", "heading": "Waiting", "items": [long_title]}) == [
            f"block 1 (items), item 14: a title of 63 characters, over {BRIEF_ITEM_TITLE_MAX_CHARS}"
        ]

    def test_an_item_the_composition_left_untitled_is_named(self) -> None:
        untitled: dict[str, object] = {
            "kind": "items",
            "heading": "Waiting",
            "items": [{"id": 1, "action": "reply"}],
        }

        assert _problems(untitled) == ["block 1 (items), item 1: no title"]

    def test_a_lead_opens_the_brief_with_one_item_and_an_offer(self) -> None:
        assert _problems(_items(1), {"kind": "lead", "items": [_ask(2), _ask(3)]}) == [
            "block 2 (lead): a lead opens the brief, so it is block 1",
            "block 2 (lead): a lead holds exactly one item, not 2",
            "block 2 (lead): no offer",
        ]

    def test_a_lead_reports_nothing_it_asks(self) -> None:
        reported = {"id": 1, "outcome": "failed", "title": "Acme invoice"}

        assert _problems({"kind": "lead", "items": [reported], "offer": "Retry it"}) == [
            "block 1 (lead): a lead is something to act on, so its item has an action"
        ]

    def test_two_leads_are_refused(self) -> None:
        lead: dict[str, object] = {"kind": "lead", "items": [_ask(1)], "offer": "Draft it"}

        assert "2 leads; a brief has at most one" in _problems(lead, {**lead, "items": [_ask(2)]})

    def test_a_heading_past_its_length_or_missing_is_refused(self) -> None:
        long = "h" * (BRIEF_HEADING_MAX_CHARS + 1)

        assert _problems(_items(1, heading=long)) == [
            f"block 1 (items): a heading of {BRIEF_HEADING_MAX_CHARS + 1} characters, over {BRIEF_HEADING_MAX_CHARS}"
        ]
        assert _problems({"kind": "items", "items": [_ask(1)]}) == ["block 1 (items): no heading"]

    def test_a_field_another_kind_of_block_owns_is_never_read(self) -> None:
        """Gemini flash-lite set goal_id on a chart and heading on a lead; neither is shown."""
        stray: dict[str, object] = {
            "kind": "note",
            "text": "Quiet day.",
            "series_ids": ["meetings"],
            "heading": "Typed 7 hours",
            "items": [_ask(99)],
        }

        assert _problems(stray, _chart("meetings")) == []


class TestNoFreeNumbers:
    def test_an_events_time_and_a_due_date_are_slots(self) -> None:
        note = {"kind": "note", "text": "Clear until [[fact:13]] at [[fact:13.time]]."}

        assert _problems(note) == []
        assert _problems({"kind": "note", "text": "Then [[fact:1.time]]."}) == [
            "the block 1 (note) text: [[fact:1.time]]: fact 1 has no time"
        ]

    def test_a_figure_typed_into_a_takeaway_or_a_note_is_refused(self) -> None:
        assert _problems(_chart("meetings", takeaway="Today holds 7 hours.")) == [
            "the block 1 (chart) takeaway types '7' itself; every count, time and date is a slot, "
            "and any other figure is said in words"
        ]
        assert _problems({"kind": "note", "text": "You closed 4 threads."}) == [
            "the block 1 (note) text types '4' itself; every count, time and date is a slot, "
            "and any other figure is said in words"
        ]

    def test_a_slot_on_a_series_the_pool_does_not_hold_or_a_field_it_lacks_is_refused(self) -> None:
        assert _problems({"kind": "note", "text": "Up to [[series:ghost.peak]]."}) == [
            "the block 1 (note) text: [[series:ghost.peak]]: ghost is no series shown today"
        ]
        assert _problems({"kind": "note", "text": "Latest [[series:invoices.latest]]."}) == [
            "the block 1 (note) text: [[series:invoices.latest]]: series invoices offers "
            "total, peak, peak_at, low, as [[series:invoices.field]]"
        ]
