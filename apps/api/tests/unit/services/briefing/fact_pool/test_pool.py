"""The fact pool built for one user across every producer, and laid out as the composition reads it.

Faked seams: the repository reads the pool makes. Every producer runs for real.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.constants.briefing import BriefAction, BriefOutcome
from app.constants.desk_buckets import DeskBucket
from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.email_verdicts import email_verdict_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_pool_models import (
    DataSeries,
    GoalOrigin,
    GoalState,
    SeriesPoint,
    SeriesShape,
)
from app.models.calendar_models import GoogleCalendarEventDateTime, GoogleCalendarEventResource
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.scout_models import Signal, SignalImportance
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.workflow_execution_models import RunMoment
from app.services.briefing.context import StatedGoal
from app.services.briefing.fact_pool.pool import FactPool, PoolContext, PoolReads, build_fact_pool
from app.services.briefing.fact_pool.render import goal_line, item_line, pool_block, series_line
from app.services.briefing.fact_pool.window import SeriesWindow

USER_ID = make_user_id()
KOLKATA = ZoneInfo("Asia/Kolkata")
WINDOW = SeriesWindow(first_day=date(2026, 11, 5), days=7, tz=KOLKATA)
NOW = datetime(2026, 11, 11, 2, 30, tzinfo=UTC)
CONTEXT = PoolContext(
    reader="Ada",
    timezone="Asia/Kolkata",
    today=date(2026, 11, 11),
    calendar_events=2,
    calendar_span="today",
    recent_openings=[],
)


def _at(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=KOLKATA).astimezone(UTC)


def _todo(title: str, *labels: str, **fields: object) -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": title, "user_id": USER_ID, "title": title, "labels": list(labels), **fields}
    )


_MAYA = Signal(
    integration_id="gmail",
    app="Gmail",
    external_id="m-1",
    kind="email waiting on your reply",
    title="Re: Series A term sheet",
    people=["Maya Chen"],
    text="Can you confirm the preference by Friday? Our partners meet Monday.",
)
_INVOICE = Signal(
    integration_id="stripe",
    app="Stripe",
    external_id="in_1",
    kind="open invoice",
    title="INV-2207 Acme Corp",
    amount=4800,
    amount_unit="USD",
)


class Stores:
    """What each store holds for the user: a realistic week."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.completed = AsyncMock(
            return_value=[
                _todo(
                    "GAIA privacy labels",
                    GAIA_TRACKED_LABEL,
                    completed=True,
                    completed_at=_at(10, 9),
                ),
                _todo("Call the bank", completed=True, completed_at=_at(11, 7)),
            ]
        )
        self.threads = AsyncMock(
            return_value=[
                _todo(
                    "Re: offsite",
                    GAIA_TRACKED_LABEL,
                    created_at=_at(10, 8),
                    external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="t1"),
                )
            ]
        )
        self.verdicts = AsyncMock(
            return_value=[
                EmailVerdictDocument(
                    user_id=USER_ID, message_id=f"m{i}", answers={}, bucket=DeskBucket.JUNK
                )
                for i in range(3)
            ]
        )
        self.rhythm = AsyncMock(return_value=[SimpleNamespace(id="wf-daily-brief")])
        self.runs = AsyncMock(return_value=[RunMoment(started_at=_at(9, 6), status="failed")])
        self.open_todos = AsyncMock(return_value=[_todo("GAIA beta invite email")])
        self.tracked = AsyncMock(return_value=[])
        for owner, name, mock in (
            (todo_repository, "list_completed_since", self.completed),
            (todo_repository, "list_external_ref_activity_since", self.threads),
            (todo_repository, "list_open_user_todos", self.open_todos),
            (todo_repository, "list_active_tracked", self.tracked),
            (email_verdict_repository, "list_since", self.verdicts),
            (workflow_repository, "find_system_workflows", self.rhythm),
            (workflow_executions_repository, "list_run_moments_since", self.runs),
        ):
            monkeypatch.setattr(owner, name, mock)


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> Stores:
    return Stores(monkeypatch)


def _reads() -> PoolReads:
    items = {
        1: BriefCandidate(
            source="gmail",
            app="Gmail",
            state="you",
            title=_MAYA.title,
            people=["Maya Chen"],
            signal=_MAYA,
        ),
        2: BriefCandidate(source="stripe", app="Stripe", state="you", title=_INVOICE.title),
        3: BriefCandidate(
            source="googlecalendar",
            app="Google Calendar",
            state="note",
            title="Board call",
            is_event=True,
        ),
    }
    meeting = GoogleCalendarEventResource(
        summary="Board call",
        start=GoogleCalendarEventDateTime(dateTime="2026-11-11T15:00:00+05:30"),
        end=GoogleCalendarEventDateTime(dateTime="2026-11-11T16:30:00+05:30"),
    )
    return PoolReads(
        items=items,
        signals=[_MAYA, _INVOICE],
        calendar=[meeting],
        goals=[StatedGoal("Launch the GAIA mobile app", GoalOrigin.MEMORY, ("GAIA",))],
        criteria={"Gmail": "a person waiting on a reply"},
    )


async def _pool() -> FactPool:
    return await build_fact_pool(USER_ID, WINDOW, _reads(), CONTEXT, NOW)


class TestTheFactPool:
    async def test_every_source_adds_its_series_quotes_and_goals_beside_the_items(
        self, stores: Stores
    ) -> None:
        pool = await _pool()

        assert [s.id for s in pool.series] == [
            "gaia_finished",
            "you_finished",
            "calendar_meeting_hours",
            "gmail_threads_taken",
            "gmail_sorted",
            "workflows_failed",
            "stripe_open_invoice_usd",
        ]
        assert [(q.id, q.author, q.item_id) for q in pool.quotes] == [("q1", "Maya Chen", 1)]
        [goal] = pool.goals
        assert (goal.done, goal.open, goal.linked) == (
            1,
            1,
            ["GAIA privacy labels", "GAIA beta invite email"],
        )
        assert pool.composable

    async def test_each_store_is_read_for_this_user_over_the_window(self, stores: Stores) -> None:
        await _pool()

        stores.completed.assert_awaited_once_with(USER_ID, since=WINDOW.start)
        stores.threads.assert_awaited_once_with(
            USER_ID, ExternalRefSource.GMAIL_THREAD, since=WINDOW.start
        )
        stores.verdicts.assert_awaited_once_with(
            USER_ID, since=datetime(2026, 11, 10, 2, 30, tzinfo=UTC)
        )
        stores.runs.assert_awaited_once_with(
            USER_ID, WINDOW.start, exclude_workflow_ids=["wf-daily-brief"]
        )

    async def test_a_pool_of_only_the_calendar_has_nothing_to_compose(
        self, stores: Stores, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for mock in (stores.completed, stores.threads, stores.verdicts, stores.runs):
            mock.return_value = []
        reads = _reads()
        only_event = PoolReads(
            items={3: reads.items[3]}, signals=[], calendar=[], goals=[], criteria={}
        )

        pool = await build_fact_pool(USER_ID, WINDOW, only_event, CONTEXT, NOW)

        assert not pool.composable


class TestThePoolAsTheComposerReadsIt:
    async def test_every_item_series_quote_and_goal_is_laid_out_by_id(self, stores: Stores) -> None:
        block = pool_block(await _pool())

        # Every reader of the pool, the composer and its checkers, reads the states alike.
        assert block.startswith("ITEMS (done: finished since the last brief, overnight;")

        assert "1. [Gmail] waiting on you: Re: Series A term sheet | with Maya Chen" in block
        assert "3. [Google Calendar] calendar event: Board call" in block
        assert (
            "calendar_meeting_hours | Meeting hours, in hours (Google Calendar), time_series of 7 "
            "points | per day: Thu 5 Nov 0 · Fri 6 Nov 0 · Sat 7 Nov 0 · Sun 8 Nov 0 · Mon 9 Nov 0 "
            "· Tue 10 Nov 0 · Wed 11 Nov (today) 1.5 | figures: total 1.5, peak 1.5, "
            "peak_at Wednesday, low 0, latest 1.5"
        ) in block
        assert (
            "gmail_sorted | Mail sorted since yesterday, in emails (Gmail), categorical of 1 "
            "points | by category: Junk 3 | figures: total 3, peak 3, peak_at Junk, low 3"
        ) in block
        assert 'q1 | Maya Chen, in Gmail, on item 1: "Can you confirm the preference' in block
        assert (
            'g1 | "Launch the GAIA mobile app" (from memory) | linked todos: 1 finished in the '
            "window, 1 open: GAIA privacy labels; GAIA beta invite email"
        ) in block


class TestSeveralOfEachPart:
    async def test_series_quotes_and_goals_each_take_a_line(self, stores: Stores) -> None:
        pool = await _pool()
        crowded = replace(
            pool,
            quotes=[pool.quotes[0], pool.quotes[0].model_copy(update={"id": "q2"})],
            goals=[pool.goals[0], pool.goals[0].model_copy(update={"id": "g2"})],
        )

        lines = pool_block(crowded).splitlines()

        assert [
            line.split(" | ")[0]
            for line in lines[lines.index("SERIES") + 1 : lines.index("QUOTES")]
        ] == [s.id for s in pool.series]
        assert [
            line.split(" | ")[0] for line in lines[lines.index("QUOTES") + 1 : lines.index("GOALS")]
        ] == ["q1", "q2"]
        assert [line.split(" | ")[0] for line in lines[lines.index("GOALS") + 1 :]] == ["g1", "g2"]


class TestAnItemLine:
    def test_an_item_says_every_fact_its_producer_knows_in_order(self) -> None:
        item = BriefCandidate(
            source="github",
            app="GitHub",
            state="failed",
            title="Deploy broke",
            detail="CI red on main",
            time="4:00 PM",
            due_at=datetime(2026, 11, 12, 9, tzinfo=UTC),
            people=["Maya Chen", "Ravi Rao"],
            count=3,
            action=BriefAction.RETRY,
            outcome=BriefOutcome.DRAFTED,
            url="https://example.com/pr/1",
            importance=SignalImportance.HIGH,
            also_in=["Slack", "Linear"],
        )

        assert item_line(7, item) == (
            "7. [GitHub] failed, important: Deploy broke | CI red on main | at 4:00 PM"
            " | due 2026-11-12 | with Maya Chen, Ravi Rao | 3 requests, one item"
            " | action retry | outcome drafted | linkable | also found by Slack, Linear"
        )

    def test_a_plain_item_is_only_its_head(self) -> None:
        item = BriefCandidate(source="stripe", app="Stripe", state="note", title="Payout sent")

        assert item_line(2, item) == "2. [Stripe] note: Payout sent"

    def test_one_request_is_not_called_a_group(self) -> None:
        item = BriefCandidate(source="stripe", app="Stripe", state="note", title="Payout", count=1)
        grouped = item.model_copy(update={"count": 2})

        assert item_line(1, item) == "1. [Stripe] note: Payout"
        assert item_line(1, grouped).endswith("| 2 requests, one item")

    @pytest.mark.parametrize("link", [{"url": "https://x.test"}, {"todo_id": "t1"}])
    def test_an_item_with_either_a_url_or_a_todo_is_linkable(self, link: dict[str, str]) -> None:
        item = BriefCandidate(source="gmail", app="Gmail", state="you", title="Reply", **link)

        assert item_line(1, item) == "1. [Gmail] waiting on you: Reply | linkable"

    def test_a_calendar_event_is_not_named_by_its_state(self) -> None:
        item = BriefCandidate(
            source="googlecalendar",
            app="Google Calendar",
            state="note",
            title="Board call",
            is_event=True,
        )

        assert item_line(3, item) == "3. [Google Calendar] calendar event: Board call"


class TestAnEmptyPool:
    def test_each_part_with_nothing_in_it_says_none(self) -> None:
        pool = FactPool(items={}, series=[], quotes=[], goals=[], context=CONTEXT, criteria={})

        assert pool_block(pool).split("\n")[1:] == [
            "(none)",
            "SERIES",
            "(none)",
            "QUOTES",
            "(none)",
            "GOALS",
            "(none)",
        ]

    def test_several_items_each_take_a_line(self) -> None:
        reads = _reads()
        pool = FactPool(
            items=reads.items, series=[], quotes=[], goals=[], context=CONTEXT, criteria={}
        )

        lines = pool_block(pool).split("\n")

        assert lines[1:4] == [
            "1. [Gmail] waiting on you: Re: Series A term sheet | with Maya Chen",
            "2. [Stripe] waiting on you: " + reads.items[2].title,
            "3. [Google Calendar] calendar event: Board call",
        ]


class TestSeriesAndGoalLines:
    def test_a_categorical_series_joins_its_points_with_a_middle_dot(self) -> None:
        series = DataSeries(
            id="s",
            label="Mail",
            unit="emails",
            source="gmail",
            app="Gmail",
            shape=SeriesShape.CATEGORICAL,
            points=[SeriesPoint(x="Junk", y=3), SeriesPoint(x="News", y=2)],
        )

        assert series_line(series, date(2026, 11, 11)).split(" | ")[2] == (
            "by category: Junk 3 · News 2"
        )

    def test_a_time_series_joins_its_days_with_a_middle_dot(self) -> None:
        series = DataSeries(
            id="s",
            label="Hours",
            unit="hours",
            source="googlecalendar",
            app="Google Calendar",
            shape=SeriesShape.TIME_SERIES,
            points=[SeriesPoint(x="2026-11-10", y=1), SeriesPoint(x="2026-11-11", y=2)],
        )

        assert series_line(series, date(2026, 11, 11)).split(" | ")[2] == (
            "per day: Tue 10 Nov 1 · Wed 11 Nov (today) 2"
        )

    def test_a_goal_with_no_linked_todo_says_so(self) -> None:
        goal = GoalState(id="g1", statement="Ship", origin=GoalOrigin.MEMORY, done=0, open=0)

        assert goal_line(goal) == 'g1 | "Ship" (from memory) | no todo names what it is about'
