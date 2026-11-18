"""Repairing a composition: what code decides alone is enforced, and what still breaks is dropped or rebuilt."""

from datetime import UTC, date, datetime

import pytest
from tests.helpers import user_clock

from app.constants.briefing import BriefAction, BriefOutcome
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_composition_models import (
    BriefComposition,
    ChartKind,
    ComposedBlock,
    ComposedChart,
    ComposedItem,
    ComposedItems,
    ComposedLead,
    ComposedNote,
)
from app.models.brief_item_models import GroupState, ItemState
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.services.briefing.composition.compose import pool_values
from app.services.briefing.composition.repair import pool_composition, repaired, salvaged
from app.services.briefing.fact_pool.pool import FactPool, PoolContext

_CONTEXT = PoolContext(
    reader="Ada",
    clock=user_clock("Asia/Kolkata", date(2026, 11, 11)),
    calendar=0,
    calendar_span="today",
    done_since=datetime(2026, 11, 10, tzinfo=UTC),
    recent_openings=[],
)
_MEETINGS = DataSeries(
    id="meetings",
    label="Meeting hours",
    unit="hours",
    source="googlecalendar",
    app="Google Calendar",
    shape=SeriesShape.TIME_SERIES,
    points=[SeriesPoint(x=f"2026-11-{d:02d}", y=d % 3) for d in range(5, 12)],
)
NOTE = ComposedNote(kind="note", text="A light day.")


def _candidate(title: str, **fields: object) -> BriefCandidate:
    return BriefCandidate.model_validate(
        {
            "origin": CandidateOrigin.TRACKED,
            "source": "gaia",
            "app": "GAIA",
            "state": "you",
            "title": title,
            "gaia_acts": True,
        }
        | fields
    )


def _pool(*candidates: BriefCandidate) -> FactPool:
    return FactPool(
        items=dict(enumerate(candidates, start=1)),
        series=[_MEETINGS],
        quotes=[],
        goals=[],
        context=_CONTEXT,
        criteria={},
    )


def _item(
    item_id: int,
    *,
    action: BriefAction | None = BriefAction.REVIEW,
    outcome: BriefOutcome | None = None,
    title: str | None = None,
) -> ComposedItem:
    return ComposedItem(
        id=item_id, action=action, outcome=outcome, title=title or f"Ask {item_id}", detail=None
    )


def _group(*items: ComposedItem, state: GroupState = GroupState.NEEDS_YOU) -> ComposedItems:
    return ComposedItems(kind="items", state=state, heading="Waiting on you", items=list(items))


def _lead(item: ComposedItem) -> ComposedLead:
    return ComposedLead(kind="lead", item=item)


def _chart(title: str) -> ComposedChart:
    return ComposedChart(
        kind="chart",
        chart=ChartKind.LINE,
        series_ids=["meetings"],
        title=title,
        takeaway="Busy week.",
    )


def _of(*blocks: ComposedBlock) -> BriefComposition:
    return BriefComposition(blocks=list(blocks))


#: Fifteen plain asks, more than one brief can place.
MANY = _pool(*(_candidate(f"Ask {n}") for n in range(1, 16)))


class TestTheProducersSide:
    def test_an_action_the_producer_named_replaces_what_the_model_said(self) -> None:
        pool = _pool(_candidate("Expense report", action=BriefAction.APPROVE))
        said = _item(1, action=None, outcome=BriefOutcome.FINISHED)

        assert repaired(_of(_group(said)), pool) == _of(
            _group(_item(1, action=BriefAction.APPROVE, outcome=None))
        )

    def test_an_outcome_the_producer_named_replaces_what_the_model_said(self) -> None:
        pool = _pool(
            _candidate("Weekly update", state=ItemState.LOOKBACK, outcome=BriefOutcome.SENT)
        )
        said = _item(1, action=BriefAction.REPLY)

        assert repaired(_of(_group(said, state=GroupState.DONE)), pool) == _of(
            _group(_item(1, action=None, outcome=BriefOutcome.SENT), state=GroupState.DONE)
        )

    def test_a_lead_takes_its_producers_action(self) -> None:
        pool = _pool(_candidate("Expense report", action=BriefAction.APPROVE))

        assert repaired(_of(_lead(_item(1, action=BriefAction.REPLY))), pool) == _of(
            _lead(_item(1, action=BriefAction.APPROVE))
        )

    def test_a_group_takes_the_state_its_items_now_share(self) -> None:
        pool = _pool(_candidate("Expense report", action=BriefAction.APPROVE))
        said = _item(1, action=None, outcome=BriefOutcome.FINISHED)

        (group,) = repaired(_of(_group(said, state=GroupState.DONE)), pool).blocks

        assert isinstance(group, ComposedItems)
        assert group.state is GroupState.NEEDS_YOU

    def test_a_group_whose_items_differ_keeps_its_declared_state(self) -> None:
        pool = _pool(_candidate("Ask"), _candidate("Done", state=ItemState.LOOKBACK))
        mixed = _group(
            _item(1), _item(2, action=None, outcome=BriefOutcome.FINISHED), state=GroupState.DONE
        )

        assert repaired(_of(mixed), pool) == _of(mixed)


class TestTheLead:
    def test_a_lead_after_another_block_is_dropped_and_what_follows_is_kept(self) -> None:
        composition = _of(NOTE, _lead(_item(1)), _group(_item(2)))

        assert repaired(composition, MANY) == _of(NOTE, _group(_item(2)))

    def test_a_lead_on_an_item_the_pool_lacks_is_dropped(self) -> None:
        assert repaired(_of(_lead(_item(99)), _group(_item(1))), MANY) == _of(_group(_item(1)))

    def test_an_item_placed_in_two_groups_stays_in_the_first(self) -> None:
        composition = _of(_group(_item(1), _item(2)), _group(_item(2), _item(3)))

        assert repaired(composition, MANY) == _of(_group(_item(1), _item(2)), _group(_item(3)))

    def test_a_leads_item_is_not_placed_again(self) -> None:
        composition = _of(_lead(_item(1)), _group(_item(1), _item(2)))

        assert repaired(composition, MANY) == _of(_lead(_item(1)), _group(_item(2)))

    @pytest.mark.regression
    def test_a_second_item_the_composer_titles_as_an_earlier_one_is_dropped(self) -> None:
        """Replay: two todos from Mercury's repeated email both read "Mercury application questions"."""
        mercury = "Mercury application questions"
        composition = _of(
            _lead(_item(1, title=mercury)),
            _group(_item(2), _item(3, title=f" {mercury.upper()} ")),
        )

        assert repaired(composition, MANY) == _of(_lead(_item(1, title=mercury)), _group(_item(2)))


class TestThePageBudget:
    def test_items_past_the_brief_cap_are_cut_in_reading_order(self) -> None:
        composition = _of(
            _lead(_item(1)),
            _group(*(_item(n) for n in range(2, 7))),
            _group(*(_item(n) for n in range(7, 12))),
        )

        assert repaired(composition, MANY) == _of(
            _lead(_item(1)),
            _group(*(_item(n) for n in range(2, 7))),
            _group(*(_item(n) for n in range(7, 11))),
        )

    def test_a_group_left_with_nothing_is_dropped_and_what_follows_is_kept(self) -> None:
        composition = _of(_group(_item(98), _item(99)), NOTE)

        assert repaired(composition, MANY) == _of(NOTE)

    def test_charts_past_the_cap_are_dropped_and_other_blocks_are_not_counted(self) -> None:
        composition = _of(_chart("First"), NOTE, _chart("Second"), _chart("Third"), NOTE)

        assert repaired(composition, MANY) == _of(_chart("First"), NOTE, _chart("Second"), NOTE)


class TestSalvage:
    def test_a_lead_gaia_cannot_act_on_becomes_a_group_of_its_item(self) -> None:
        pool = _pool(_candidate("Re: contract", app="Gmail", source="gmail", gaia_acts=False))

        kept = salvaged(_of(_lead(_item(1)), NOTE), pool, pool_values(pool))

        assert kept == _of(
            ComposedItems(
                kind="items", state=GroupState.NEEDS_YOU, heading="Needs you", items=[_item(1)]
            ),
            NOTE,
        )

    def test_an_item_that_breaks_its_contract_is_dropped_and_the_rest_kept(self) -> None:
        long = _item(2, title="A title far longer than any brief item may carry on a page")

        kept = salvaged(_of(_group(_item(1), long), NOTE), MANY, pool_values(MANY))

        assert kept == _of(
            ComposedItems(
                kind="items", state=GroupState.NEEDS_YOU, heading="Needs you", items=[_item(1)]
            ),
            NOTE,
        )

    def test_a_composition_with_nothing_that_holds_is_built_from_the_pool(self) -> None:
        pool = _pool(_candidate("Sync job"))

        kept = salvaged(_of(_group(_item(9))), pool, pool_values(pool))

        assert kept == _of(
            ComposedItems(
                kind="items",
                state=GroupState.NEEDS_YOU,
                heading="Needs you",
                items=[_item(1, title="Sync job")],
            )
        )


class TestThePoolsOwnBrief:
    def test_its_news_is_grouped_by_state_with_each_items_own_side(self) -> None:
        pool = _pool(
            _candidate("Reply to Maya"),
            _candidate("Board deck", state=ItemState.LOOKBACK),
            _candidate("Weekly update", state=ItemState.LOOKBACK, outcome=BriefOutcome.SENT),
            _candidate("Inbox triage", state=ItemState.GAIA),
            _candidate("Standup", state=ItemState.NOTE, origin=CandidateOrigin.EVENT),
        )

        assert pool_composition(pool, pool_values(pool)) == _of(
            ComposedItems(
                kind="items",
                state=GroupState.NEEDS_YOU,
                heading="Needs you",
                items=[_item(1, title="Reply to Maya")],
            ),
            ComposedItems(
                kind="items",
                state=GroupState.DONE,
                heading="Done",
                items=[
                    _item(2, action=None, outcome=BriefOutcome.FINISHED, title="Board deck"),
                    _item(3, action=None, outcome=BriefOutcome.SENT, title="Weekly update"),
                ],
            ),
            ComposedItems(
                kind="items",
                state=GroupState.IN_PROGRESS,
                heading="Still in progress",
                items=[_item(4, action=None, outcome=BriefOutcome.STARTED, title="Inbox triage")],
            ),
        )

    def test_a_failed_item_asks_the_user_to_look(self) -> None:
        pool = _pool(_candidate("Sync job", state=ItemState.FAILED))

        assert pool_composition(pool, pool_values(pool)) == _of(
            ComposedItems(
                kind="items",
                state=GroupState.NEEDS_YOU,
                heading="Needs you",
                items=[_item(1, title="Sync job")],
            )
        )

    @pytest.mark.parametrize(
        ("title", "shown"),
        [
            ("Quarterly planning review for the Series A pitches", None),
            (
                "Quarterly planning review for the Series A pitch and the board call",
                "Quarterly planning review for the Series A pitch…",
            ),
            (
                "Quarterly planning review for the Series A pitches and the call",
                "Quarterly planning review for the Series A…",
            ),
        ],
    )
    def test_a_long_title_is_cut_at_a_word_under_the_cap(
        self, title: str, shown: str | None
    ) -> None:
        pool = _pool(_candidate(title))

        (group,) = pool_composition(pool, pool_values(pool)).blocks

        assert isinstance(group, ComposedItems)
        assert group.items[0].title == (shown or title)
