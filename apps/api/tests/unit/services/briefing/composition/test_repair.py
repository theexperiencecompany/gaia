"""Repairing a composition: what code decides alone is enforced, and what still breaks is dropped or rebuilt."""

from datetime import UTC, date, datetime

import pytest
from tests.briefing_helpers import user_clock

from app.constants.briefing import MAX_BRIEF_ITEMS, BriefAction, BriefOutcome
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
    placed_items,
)
from app.models.brief_item_models import GroupState, ItemState
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.models.scout_models import SignalMemoryDocument
from app.services.briefing.composition.compose import pool_values
from app.services.briefing.composition.repair import (
    derived_heading,
    pool_composition,
    repaired,
    salvaged,
)
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


def _group(
    *items: ComposedItem,
    state: GroupState = GroupState.NEEDS_YOU,
    heading: str = "Waiting on you",
) -> ComposedItems:
    return ComposedItems(kind="items", state=state, heading=heading, items=list(items))


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
        composition = _of(_group(_item(1), _item(2)), _group(_item(2), _item(3), heading="Money"))

        assert repaired(composition, MANY) == _of(
            _group(_item(1), _item(2)), _group(_item(3), heading="Money")
        )

    def test_a_leads_item_is_not_placed_again(self) -> None:
        composition = _of(_lead(_item(1)), _group(_item(1), _item(2)))

        assert repaired(composition, MANY) == _of(_lead(_item(1)), _group(_item(2)))

    def test_an_item_placed_twice_in_one_group_under_another_title_stays_once(self) -> None:
        composition = _of(_group(_item(1), _item(1, title="Ask one again")))

        assert repaired(composition, MANY) == _of(_group(_item(1)))

    def test_an_item_the_pool_lacks_is_dropped_and_the_rest_of_its_group_kept(self) -> None:
        assert repaired(_of(_group(_item(99), _item(1))), MANY) == _of(_group(_item(1)))

    def test_a_second_item_the_composer_titles_as_an_earlier_one_is_dropped(self) -> None:
        """Replay: two todos from Mercury's repeated email both read "Mercury application questions"."""
        mercury = "Mercury application questions"
        composition = _of(
            _lead(_item(1, title=mercury)),
            _group(_item(2), _item(3, title=f" {mercury.upper()} ")),
        )

        assert repaired(composition, MANY) == _of(_lead(_item(1, title=mercury)), _group(_item(2)))


class TestOneHeading:
    def test_two_groups_of_one_state_under_one_heading_are_one_group_where_the_first_stood(
        self,
    ) -> None:
        """Dhruv 11-03/04: two needs-you groups both read "Replies waiting on you"."""
        composition = _of(
            _group(_item(1)), _group(_item(2), heading="Money"), _group(_item(3), _item(4))
        )

        assert repaired(composition, MANY) == _of(
            _group(_item(1), _item(3), _item(4)), _group(_item(2), heading="Money")
        )

    def test_groups_of_two_states_or_past_what_a_group_holds_stay_apart(self) -> None:
        done = _item(4, action=None, outcome=BriefOutcome.FINISHED)
        composition = _of(
            _group(_item(1), _item(2), _item(3)),
            _group(done, state=GroupState.DONE),
            _group(_item(5), _item(6), _item(7)),
        )

        assert repaired(composition, MANY) == composition

    def test_two_groups_under_one_heading_that_just_fill_a_group_are_one_group(self) -> None:
        composition = _of(_group(_item(1), _item(2), _item(3)), _group(_item(4), _item(5)))

        assert repaired(composition, MANY) == _of(
            _group(_item(1), _item(2), _item(3), _item(4), _item(5))
        )


APPROVAL = _candidate(
    "Connect integration", origin=CandidateOrigin.APPROVAL, action=BriefAction.APPROVE
)
PLACED_APPROVAL = ComposedItems(
    kind="items",
    state=GroupState.NEEDS_YOU,
    heading="To approve",
    items=[_item(2, action=BriefAction.APPROVE, title="Connect integration")],
)


class TestAnApprovalNoBriefHasShown:
    """Replay of Dhruv's Nov 9: the composer left out an unseen approval, and the day went quiet."""

    def test_it_is_placed_after_the_asks_when_the_composer_leaves_it_out(self) -> None:
        pool = _pool(_candidate("Ask 1"), APPROVAL)
        done = _group(_item(1, action=None, outcome=BriefOutcome.FINISHED), state=GroupState.DONE)

        assert repaired(_of(_group(_item(1)), NOTE), pool) == _of(
            _group(_item(1)), PLACED_APPROVAL, NOTE
        )
        assert repaired(_of(done), pool) == _of(PLACED_APPROVAL, done)

    def test_one_shown_before_and_unchanged_is_the_composers_call(self) -> None:
        shown = APPROVAL.model_copy(
            update={
                "memory": SignalMemoryDocument(
                    user_id="u",
                    integration_id="gaia",
                    external_id="approval:1",
                    first_seen=datetime(2026, 11, 9, tzinfo=UTC),
                    times_shown=1,
                )
            }
        )

        assert repaired(_of(_group(_item(1))), _pool(_candidate("Ask 1"), shown)) == _of(
            _group(_item(1))
        )

    def test_one_titled_as_an_earlier_item_is_said_once_not_placed_again(self) -> None:
        pool = _pool(_candidate("Ask 1"), APPROVAL)
        composition = _of(
            _group(_item(1, title="Connect integration")),
            _group(_item(2, action=BriefAction.APPROVE, title="Connect integration")),
        )

        assert repaired(composition, pool) == _of(_group(_item(1, title="Connect integration")))

    def test_more_than_a_group_holds_are_placed_in_groups_of_at_most_five(self) -> None:
        approvals = [APPROVAL.model_copy(update={"title": f"Approve {n}"}) for n in range(1, 7)]
        owed = [_item(n, action=BriefAction.APPROVE, title=f"Approve {n}") for n in range(1, 7)]

        assert repaired(_of(NOTE), _pool(*approvals)) == _of(
            PLACED_APPROVAL.model_copy(update={"items": owed[:5]}),
            PLACED_APPROVAL.model_copy(update={"items": owed[5:]}),
            NOTE,
        )

    def test_one_the_composer_placed_stays_where_it_put_it(self) -> None:
        placed = ComposedItems(
            kind="items",
            state=GroupState.NEEDS_YOU,
            heading="Sign-offs",
            items=[_item(2, action=BriefAction.APPROVE, title="Connect integration")],
        )
        pool = _pool(_candidate("Ask 1"), APPROVAL)

        assert repaired(_of(placed, NOTE), pool) == _of(placed, NOTE)

    def test_one_the_composer_groups_costs_no_other_item_its_place(self) -> None:
        others = [_candidate(f"Ask {n}") for n in range(1, MAX_BRIEF_ITEMS)]
        pool = _pool(*others, APPROVAL)
        approval = _item(MAX_BRIEF_ITEMS, action=BriefAction.APPROVE, title="Connect")
        composition = _of(
            _group(*(_item(n) for n in range(1, 6))),
            _group(*(_item(n) for n in range(6, MAX_BRIEF_ITEMS)), approval),
        )

        assert repaired(composition, pool) == composition

    def test_one_the_composer_leads_with_costs_no_other_item_its_place(self) -> None:
        others = [_candidate(f"Ask {n}") for n in range(1, MAX_BRIEF_ITEMS)]
        pool = _pool(*others, APPROVAL)
        lead = _lead(_item(MAX_BRIEF_ITEMS, action=BriefAction.APPROVE, title="Connect"))
        composition = _of(
            lead,
            _group(*(_item(n) for n in range(1, 6))),
            _group(*(_item(n) for n in range(6, MAX_BRIEF_ITEMS))),
        )

        assert repaired(composition, pool) == composition

    def test_it_takes_its_place_inside_the_brief_cap(self) -> None:
        pool = _pool(*(_candidate(f"Ask {n}") for n in range(1, MAX_BRIEF_ITEMS + 1)), APPROVAL)
        full = _of(
            _group(*(_item(n) for n in range(1, 6))),
            _group(*(_item(n) for n in range(6, MAX_BRIEF_ITEMS + 1))),
        )

        placed = [i.id for b in repaired(full, pool).blocks for i in placed_items(b)]

        assert placed == [*range(1, MAX_BRIEF_ITEMS), MAX_BRIEF_ITEMS + 1]


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
                kind="items", state=GroupState.NEEDS_YOU, heading="To review", items=[_item(1)]
            ),
            NOTE,
        )

    def test_an_item_that_breaks_its_contract_is_dropped_and_the_rest_kept(self) -> None:
        long = _item(2, title="A title far longer than any brief item may carry on a page")

        kept = salvaged(_of(_group(_item(1), long), NOTE), MANY, pool_values(MANY))

        assert kept == _of(
            ComposedItems(
                kind="items", state=GroupState.NEEDS_YOU, heading="To review", items=[_item(1)]
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
                heading="To review",
                items=[_item(1, title="Sync job")],
            )
        )

    def test_groups_whose_broken_headings_give_way_to_one_are_one_group_and_the_rest_kept(
        self,
    ) -> None:
        composition = _of(
            _group(_item(1), heading="Everything that came in for you while you slept"),
            _group(_item(2), heading="And everything else that is waiting on you today"),
            NOTE,
        )

        kept = salvaged(composition, MANY, pool_values(MANY))

        assert kept == _of(_group(_item(1), _item(2), heading="To review"), NOTE)


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
                heading="To review",
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
                heading="To review",
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


class TestADerivedHeading:
    """Founder's Nov 22: every salvaged group read "Needs you", the user's own list among them."""

    def test_the_users_own_undated_todos_are_still_on_their_list(self) -> None:
        pool = _pool(*(_candidate(f"Todo {n}", origin=CandidateOrigin.BACKLOG) for n in (1, 2)))

        assert derived_heading(_group(_item(1), _item(2)), pool) == "Still on your list"

    def test_items_asking_one_act_are_headed_by_it(self) -> None:
        pool = _pool(_candidate("PR"), _candidate("Thread", app="Gmail"))
        replies = _group(_item(1, action=BriefAction.REPLY), _item(2, action=BriefAction.REPLY))

        assert derived_heading(replies, pool) == "Replies to send"

    def test_items_of_one_app_asking_several_acts_are_headed_by_their_app(self) -> None:
        github = {"app": "GitHub", "source": "github"}
        pool = _pool(_candidate("PR", **github), _candidate("Issue", **github))
        mixed = _group(_item(1, action=BriefAction.READ), _item(2, action=BriefAction.REPLY))

        assert derived_heading(mixed, pool) == "Needs you in GitHub"

    def test_items_sharing_nothing_are_headed_by_their_state(self) -> None:
        pool = _pool(_candidate("PR", app="GitHub"), _candidate("Thread", app="Gmail"))
        mixed = _group(_item(1, action=BriefAction.READ), _item(2, action=BriefAction.REPLY))

        assert derived_heading(mixed, pool) == "Needs you"

    def test_a_lone_item_is_headed_by_its_state_not_its_app(self) -> None:
        pool = _pool(_candidate("PR", app="GitHub", source="github"))
        merged = _group(_item(1, action=None, outcome=BriefOutcome.FINISHED), state=GroupState.DONE)

        assert derived_heading(merged, pool) == "Done"

    @pytest.mark.parametrize(
        ("app", "heading"),
        [
            ("Northwind Field Service Hub", "Needs you in Northwind Field Service Hub"),
            ("Northwind Field Services Hub", "Needs you"),
        ],
    )
    def test_an_app_heading_is_kept_up_to_the_heading_cap_and_no_further(
        self, app: str, heading: str
    ) -> None:
        pool = _pool(_candidate("PR", app=app), _candidate("Issue", app=app))
        mixed = _group(_item(1, action=BriefAction.READ), _item(2, action=BriefAction.REPLY))

        assert derived_heading(mixed, pool) == heading
