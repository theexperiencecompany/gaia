"""The composition contract: ids only and each once, charts that fit their series, the page budget, slots."""

from collections.abc import Mapping
from datetime import date

from pydantic import ValidationError
import pytest

from app.constants.briefing import (
    BRIEF_CHART_TITLE_MAX_CHARS,
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_NOTE_MAX_CHARS,
    BRIEF_OFFER_MAX_CHARS,
    BRIEF_TAKEAWAY_MAX_CHARS,
    MAX_BAR_CATEGORIES,
    MAX_BRIEF_BLOCKS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    MIN_TREND_POINTS,
    BriefAction,
    BriefOutcome,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition, ComposedItems
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
        15: _item("Board deck numbers", state="gaia", outcome=BriefOutcome.STARTED),
        16: _item("CRM sync", state="failed", action=BriefAction.RETRY),
    },
    series=[
        _series("meetings", [2, 1.5, 2, 0, 0, 2.5, 7]),
        _series("short", [1, 2, 3]),
        _series("five_days", [1, 2, 3, 4, 5]),
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


def _placed(item_id: int, **fields: object) -> dict[str, object]:
    """Place an item as a schema-held answer does: every field present, the unset ones null."""
    return {"id": item_id, "action": None, "outcome": None, "title": "", "detail": None, **fields}


def _ask(item_id: int) -> dict[str, object]:
    title = POOL.items[item_id].title if item_id in POOL.items else "Somebody's thread"
    return _placed(item_id, action="reply", title=title)


def _items(*ids: int, heading: str = "Waiting on you") -> dict[str, object]:
    return {
        "kind": "items",
        "state": "needs_you",
        "heading": heading,
        "items": [_ask(i) for i in ids],
    }


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
                {"kind": "lead", "item": _ask(13), "offer": "Prep the board call notes"},
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
        assert _problems(
            {
                "kind": "chart",
                "chart": "line",
                "series_ids": [],
                "title": "Week",
                "takeaway": "Busy.",
            }
        ) == ["block 1 (chart): no series_ids"]


class TestThePageBudget:
    def test_more_items_than_a_brief_holds_is_refused(self) -> None:
        groups = [
            _items(1, 2, 3, 4, 5),
            _items(6, 7, 8, 9, 10, heading="Also"),
            _items(11, heading="And"),
        ]

        assert _problems(*groups) == [
            f"{MAX_BRIEF_ITEMS + 1} items in all; a brief holds at most {MAX_BRIEF_ITEMS}"
        ]

    def test_a_third_chart_is_refused(self) -> None:
        charts = [_chart("meetings"), _chart("emails"), _chart("threads_closed")]

        assert _problems(*charts) == ["3 charts; a brief holds at most 2"]


class TestAGroupHoldsWhatItsStateSays:
    """Live brief: started work stood under "Landed overnight" through every retry."""

    @pytest.mark.parametrize(
        ("state", "item", "problem"),
        [
            (
                "done",
                _placed(15, outcome="started", title="Board deck numbers"),
                "block 1 (items), item 15 has outcome started, which a done group does not "
                "hold; move it to an in_progress group",
            ),
            (
                "in_progress",
                _placed(3, outcome="sent", title="Board deck numbers"),
                "block 1 (items), item 3 has outcome sent, which an in_progress group does not "
                "hold; move it to a done group",
            ),
            (
                "needs_you",
                _placed(4, outcome="finished", title="Lisbon flights"),
                "block 1 (items), item 4 has outcome finished, which a needs_you group does not "
                "hold; move it to a done group",
            ),
            (
                "done",
                _placed(6, outcome="failed", title="Hiring loop"),
                "block 1 (items), item 6 has outcome failed, which a done group does not hold; "
                "a failed item needs the user: give it action retry in a needs_you group",
            ),
            (
                "done",
                _placed(5, action="review", title="Checkout bug"),
                "block 1 (items), item 5 has action review, which a done group does not hold; "
                "move it to a needs_you group",
            ),
        ],
    )
    def test_an_item_its_groups_state_does_not_hold_is_named_with_where_it_belongs(
        self, state: str, item: dict[str, object], problem: str
    ) -> None:
        group = {"kind": "items", "state": state, "heading": "Overnight", "items": [item]}

        assert problem in _problems(group)

    @pytest.mark.parametrize(
        ("state", "item"),
        [
            ("needs_you", _placed(1, action="reply", title="Acme invoice")),
            ("done", _placed(2, outcome="booked", title="Offsite venues")),
            ("in_progress", _placed(3, outcome="started", title="Board deck numbers")),
        ],
    )
    def test_an_item_its_groups_state_holds_is_no_problem(
        self, state: str, item: dict[str, object]
    ) -> None:
        group = {"kind": "items", "state": state, "heading": "Today", "items": [item]}

        assert _problems(group) == []

    def test_a_group_without_a_state_is_no_composition(self) -> None:
        with pytest.raises(ValidationError):
            ComposedItems.model_validate({"kind": "items", "heading": "Today", "items": [_ask(1)]})


class TestEachBlockHasItsShape:
    def test_an_item_with_both_or_neither_of_action_and_outcome_is_refused(self) -> None:
        both = _placed(1, action="reply", outcome="sent", title="Acme invoice")
        neither = _placed(2, title="Offsite venues")

        group = {
            "kind": "items",
            "state": "needs_you",
            "heading": "Mixed",
            "items": [both, neither],
        }

        assert _problems(group) == [
            "block 1 (items), item 1: give exactly one of action (it needs the user) or outcome (it got somewhere)",
            "block 1 (items), item 2: give exactly one of action (it needs the user) or outcome (it got somewhere)",
        ]

    def test_an_item_goes_on_the_side_its_producer_gave_it(self) -> None:
        """Live brief: a running todo, outcome started, was placed as an ask to read."""
        asked = _placed(15, action="read", title="Board deck numbers")
        reported = _placed(16, outcome="finished", title="CRM sync")

        assert _problems(
            {"kind": "items", "state": "needs_you", "heading": "Worth a look", "items": [asked]},
            {"kind": "items", "state": "done", "heading": "Done overnight", "items": [reported]},
        ) == [
            "block 1 (items), item 15: its line gives outcome started, so it is placed as that outcome",
            "block 2 (items), item 16: its line gives action retry, so it is placed as that action",
        ]
        agrees = [_placed(15, outcome="started", title="Board deck numbers")]
        assert (
            _problems(
                {
                    "kind": "items",
                    "state": "in_progress",
                    "heading": "Still running",
                    "items": agrees,
                }
            )
            == []
        )

    def test_a_title_is_measured_as_the_brief_shows_it_with_its_slots_filled(self) -> None:
        long_title = _placed(14, action="reply", title="[[fact:14]]")

        assert _problems(
            {"kind": "items", "state": "needs_you", "heading": "Waiting", "items": [long_title]}
        ) == [
            f"block 1 (items), item 14: a title of 63 characters, over {BRIEF_ITEM_TITLE_MAX_CHARS}"
        ]

    def test_an_item_the_composition_left_untitled_is_named(self) -> None:
        untitled: dict[str, object] = {
            "kind": "items",
            "state": "needs_you",
            "heading": "Waiting",
            "items": [_placed(1, action="reply", title="  ")],
        }

        assert _problems(untitled) == ["block 1 (items), item 1: no title"]

    def test_a_lead_opens_the_brief_with_an_offer(self) -> None:
        assert _problems(_items(1), {"kind": "lead", "item": _ask(2), "offer": " "}) == [
            "block 2 (lead): a lead opens the brief, so it is block 1",
            "block 2 (lead): no offer",
        ]

    def test_a_lead_reports_nothing_it_asks(self) -> None:
        reported = _placed(1, outcome="failed", title="Acme invoice")

        assert _problems({"kind": "lead", "item": reported, "offer": "Retry it"}) == [
            "block 1 (lead): a lead is something to act on, so its item has an action"
        ]

    def test_two_leads_are_refused(self) -> None:
        lead: dict[str, object] = {"kind": "lead", "item": _ask(1), "offer": "Draft it"}

        assert "2 leads; a brief has at most one" in _problems(lead, {**lead, "item": _ask(2)})

    def test_a_heading_past_its_length_or_missing_is_refused(self) -> None:
        long = "h" * (BRIEF_HEADING_MAX_CHARS + 1)

        assert _problems(_items(1, heading=long)) == [
            f"block 1 (items): a heading of {BRIEF_HEADING_MAX_CHARS + 1} characters, over {BRIEF_HEADING_MAX_CHARS}"
        ]
        assert _problems(
            {"kind": "items", "state": "needs_you", "heading": "", "items": [_ask(1)]}
        ) == ["block 1 (items): no heading"]

    def test_a_block_missing_any_field_of_its_kind_is_no_composition(self) -> None:
        """Gemini flash-lite dropped title and kind; the schema the provider holds requires both."""
        with pytest.raises(ValidationError):
            BriefComposition.model_validate(
                {"blocks": [{"kind": "items", "heading": "Waiting", "items": [{"id": 1}]}]}
            )
        with pytest.raises(ValidationError):
            BriefComposition.model_validate({"blocks": [{"heading": "Waiting", "items": []}]})


class TestTheSchemaAProviderHolds:
    def test_the_page_budget_is_in_the_schema_so_the_provider_holds_it(self) -> None:
        """E2E busy day: a composition came back with 8 blocks against a budget of 7."""
        schema = BriefComposition.model_json_schema()
        group = schema["$defs"]["ComposedItems"]["properties"]["items"]

        assert schema["properties"]["blocks"]["maxItems"] == MAX_BRIEF_BLOCKS
        assert (group["minItems"], group["maxItems"]) == (1, MAX_ITEMS_PER_BLOCK)
        with pytest.raises(ValidationError):
            ComposedItems.model_validate(
                {"kind": "items", "state": "done", "heading": "Empty", "items": []}
            )
        notes = [{"kind": "note", "text": "A note."}] * (MAX_BRIEF_BLOCKS + 1)
        with pytest.raises(ValidationError):
            BriefComposition.model_validate({"blocks": notes})

    def test_every_field_of_every_object_is_required_and_every_kind_an_enum(self) -> None:
        schema = BriefComposition.model_json_schema()
        objects = [schema, *schema["$defs"].values()]

        for obj in (o for o in objects if o.get("type") == "object"):
            assert set(obj["required"]) == set(obj["properties"]), obj["title"]
        kinds = {
            d["properties"]["kind"]["const"]
            for d in schema["$defs"].values()
            if "kind" in d.get("properties", {})
        }
        assert kinds == {"lead", "items", "chart", "quote", "progress", "note"}


class TestNoFreeNumbers:
    def test_an_events_time_and_a_due_date_are_slots(self) -> None:
        note: dict[str, object] = {
            "kind": "note",
            "text": "Clear until [[fact:13]] at [[fact:13.time]].",
        }

        assert _problems(note) == []
        assert _problems({"kind": "note", "text": "Then [[fact:1.time]]."}) == [
            "the block 1 (note) text: [[fact:1.time]]: fact 1 has no time"
        ]

    def test_a_figure_no_fact_carries_is_refused_in_a_takeaway_or_a_note(self) -> None:
        assert _problems(_chart("meetings", takeaway="Today holds 7 hours.")) == []
        assert _problems({"kind": "note", "text": "You closed 41 threads."}) == [
            "the block 1 (note) text types '41', a figure no fact carries; say it in words, "
            "from the facts, or leave it out"
        ]

    def test_a_slot_on_a_series_the_pool_does_not_hold_or_a_field_it_lacks_is_refused(self) -> None:
        assert _problems({"kind": "note", "text": "Up to [[series:ghost.peak]]."}) == [
            "the block 1 (note) text: [[series:ghost.peak]]: ghost is no series shown today"
        ]
        assert _problems({"kind": "note", "text": "Latest [[series:invoices.latest]]."}) == [
            "the block 1 (note) text: [[series:invoices.latest]]: series invoices offers "
            "total, peak, peak_at, low, as [[series:invoices.field]]"
        ]


_LONG_FACT = "[[fact:14]]"
_LONG_FACT_CHARS = len(POOL.items[14].title)


def _filled_to(slots: int) -> tuple[str, int]:
    """Return text of that many long-fact slots and the characters it reads as once filled."""
    return " ".join([_LONG_FACT] * slots), slots * _LONG_FACT_CHARS + slots - 1


class TestTextIsMeasuredAsTheBriefShowsIt:
    def test_a_heading_whose_filled_slots_run_past_its_limit_is_named(self) -> None:
        text, chars = _filled_to(1)

        assert _problems(_items(1, heading=text)) == [
            f"block 1 (items): a heading of {chars} characters, over {BRIEF_HEADING_MAX_CHARS}"
        ]

    def test_a_chart_title_and_takeaway_are_measured_filled(self) -> None:
        title, title_chars = _filled_to(1)
        takeaway, takeaway_chars = _filled_to(3)
        chart = {**_chart("meetings"), "title": title, "takeaway": takeaway}

        assert _problems(chart) == [
            f"block 1 (chart): a title of {title_chars} characters, over {BRIEF_CHART_TITLE_MAX_CHARS}",
            f"block 1 (chart): a takeaway of {takeaway_chars} characters, over {BRIEF_TAKEAWAY_MAX_CHARS}",
        ]

    def test_a_note_is_measured_filled(self) -> None:
        text, chars = _filled_to(4)

        assert _problems({"kind": "note", "text": text}) == [
            f"block 1 (note): a text of {chars} characters, over {BRIEF_NOTE_MAX_CHARS}"
        ]

    def test_a_lead_offer_is_measured_filled(self) -> None:
        text, chars = _filled_to(2)

        assert _problems({"kind": "lead", "item": _ask(1), "offer": text}) == [
            f"block 1 (lead): a offer of {chars} characters, over {BRIEF_OFFER_MAX_CHARS}"
        ]

    def test_a_field_exactly_at_its_limit_holds(self) -> None:
        assert _problems(_items(1, heading="h" * BRIEF_HEADING_MAX_CHARS)) == []

    def test_an_item_detail_over_its_limit_is_named_and_at_it_holds(self) -> None:
        def detailed(detail: str) -> dict[str, object]:
            item = _placed(1, action="reply", title="Acme invoice", detail=detail)
            return {"kind": "items", "state": "needs_you", "heading": "Waiting", "items": [item]}

        assert _problems(detailed("d" * BRIEF_ITEM_DETAIL_MAX_CHARS)) == []
        assert _problems(detailed("d" * (BRIEF_ITEM_DETAIL_MAX_CHARS + 1))) == [
            f"block 1 (items), item 1: a detail over {BRIEF_ITEM_DETAIL_MAX_CHARS} characters"
        ]

    def test_a_linked_phrase_is_measured_as_its_phrase(self) -> None:
        linked = {"kind": "note", "text": "See [the board call](fact:13) soon."}

        assert _problems(linked) == []


class TestEveryProblemOfABlockIsReported:
    def test_a_chart_missing_title_and_takeaway_names_both(self) -> None:
        chart = {**_chart("meetings"), "title": " ", "takeaway": ""}

        assert _problems(chart) == ["block 1 (chart): no title", "block 1 (chart): no takeaway"]

    def test_a_chart_with_a_blank_title_still_names_the_series_it_cannot_draw(self) -> None:
        chart = {**_chart("short"), "title": ""}

        assert _problems(chart) == [
            "block 1 (chart): no title",
            f"block 1 (chart): a line needs a time series of at least {MIN_TREND_POINTS} days",
        ]

    def test_every_unknown_series_is_listed(self) -> None:
        assert _problems(_chart("nope", "ghost")) == [
            "block 1 (chart): no series nope, ghost in the pool"
        ]

    def test_a_trend_on_exactly_the_minimum_days_holds(self) -> None:
        assert len(POOL.series_by_id["five_days"].points) == MIN_TREND_POINTS
        assert _problems(_chart("five_days")) == []

    def test_a_brief_of_exactly_its_item_budget_holds(self) -> None:
        assert MAX_BRIEF_ITEMS == 10
        assert _problems(_items(1, 2, 3, 4, 5), _items(6, 7, 8, 9, 10, heading="Also")) == []

    def test_an_item_after_a_fitting_one_is_still_checked_against_its_group(self) -> None:
        group = {
            "kind": "items",
            "state": "done",
            "heading": "Overnight",
            "items": [
                _placed(2, outcome="booked", title="Offsite venues"),
                _placed(15, outcome="started", title="Board deck numbers"),
            ],
        }

        assert _problems(group) == [
            "block 1 (items), item 15 has outcome started, which a done group does not hold; "
            "move it to an in_progress group"
        ]

    def test_slot_problems_in_blocks_and_in_items_all_come_back_in_order(self) -> None:
        bad = "[[fact:1.time]]"
        first_note = {"kind": "note", "text": f"One {bad}."}
        item = _placed(1, action="reply", title=bad, detail=bad)
        group = {"kind": "items", "state": "needs_you", "heading": "Waiting", "items": [item]}
        second_note = {"kind": "note", "text": f"Two {bad}."}

        assert _problems(first_note, group, second_note) == [
            "the block 1 (note) text: [[fact:1.time]]: fact 1 has no time",
            "the block 2 (items) item 1 title: [[fact:1.time]]: fact 1 has no time",
            "the block 2 (items) item 1 detail: [[fact:1.time]]: fact 1 has no time",
            "the block 3 (note) text: [[fact:1.time]]: fact 1 has no time",
        ]

    def test_an_item_may_quote_a_figure_its_own_line_gives(self) -> None:
        item = _placed(1, action="reply", title="Pay 41 dollars", detail="Due in 3 days")
        group = {"kind": "items", "state": "needs_you", "heading": "Waiting", "items": [item]}

        assert _problems(group) == []


def test_every_id_placed_twice_is_listed_in_order() -> None:
    assert _problems(_items(1, 2), _items(2, 1, heading="Also")) == [
        "placed more than once: item 1, item 2"
    ]
