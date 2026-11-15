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
from tests.helpers import user_clock

from app.constants.briefing import (
    BRIEFING_RHYTHM_WORKFLOW_KEYS,
    CALENDAR_UNAVAILABLE,
    NO_CALENDAR_CONNECTED,
    BriefAction,
    BriefOutcome,
)
from app.constants.desk_buckets import DeskBucket
from app.constants.todos import GAIA_TRACKED_LABEL, TodoCompleter
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
from app.models.briefing_models import UnreadSource
from app.models.calendar_models import GoogleCalendarEventDateTime, GoogleCalendarEventResource
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.scout_models import (
    PeopleRole,
    ScoutSkipReason,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.workflow_execution_models import RunMoment
from app.services.briefing.context import CalendarGap, StatedGoal
from app.services.briefing.fact_pool.pool import FactPool, PoolContext, PoolReads, build_fact_pool
from app.services.briefing.fact_pool.render import (
    context_block,
    goal_line,
    item_line,
    pool_block,
    series_line,
)
from app.services.briefing.fact_pool.window import SeriesWindow

USER_ID = make_user_id()
KOLKATA = ZoneInfo("Asia/Kolkata")
WINDOW = SeriesWindow(first_day=date(2026, 11, 5), days=7, tz=KOLKATA)
NOW = datetime(2026, 11, 11, 2, 30, tzinfo=UTC)
CONTEXT = PoolContext(
    reader="Ada",
    clock=user_clock("Asia/Kolkata", date(2026, 11, 11)),
    calendar=2,
    calendar_span="today",
    done_since=datetime(2026, 11, 10, tzinfo=UTC),
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
    author="Maya Chen",
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
                    completed_by=TodoCompleter.GAIA,
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
        stores.rhythm.assert_awaited_once_with(USER_ID, BRIEFING_RHYTHM_WORKFLOW_KEYS)
        stores.open_todos.assert_awaited_once_with(USER_ID, limit=0)
        stores.tracked.assert_awaited_once_with(USER_ID, limit=0)

    async def test_a_goals_open_work_untouched_a_week_by_now_is_stuck(self, stores: Stores) -> None:
        stores.open_todos.return_value = [
            _todo("GAIA beta invite email", updated_at=_at(10, 9)),
            _todo("GAIA store listing", updated_at=_at(3, 9)),
        ]

        [goal] = (await _pool()).goals

        assert goal.stalled == ["GAIA store listing"]

    async def test_each_apps_criteria_ride_with_the_pool(self, stores: Stores) -> None:
        pool = await _pool()

        assert pool.criteria == {"Gmail": "a person waiting on a reply"}

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
        # Done means done in this brief's own window, never "overnight" whatever the window.
        assert block.startswith(
            "ITEMS (done by GAIA / done by the user / closed: finished since Tue 10 Nov, 5:30 AM,"
        )
        assert "overnight" not in block

        assert (
            "1. [Gmail] waiting on you: Re: Series A term sheet | names Maya Chen"
            " (the app does not say their part in it) | GAIA can only read Gmail: no offer on it"
        ) in block
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
            'g1 | "Launch the GAIA mobile app" (from memory) | linked todos: 1 finished since '
            "Thu 5 Nov (1 by GAIA), 1 open: GAIA privacy labels; GAIA beta invite email"
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


class TestTheContextBlock:
    def test_the_day_the_calendar_and_how_recent_briefs_opened_are_each_a_line(self) -> None:
        context = replace(
            CONTEXT,
            clock=user_clock("Asia/Kolkata", date(2026, 11, 5)),
            recent_openings=["Priya replied overnight.", "Big day for the raise."],
        )

        assert context_block(context).splitlines() == [
            "Thursday 5 November 2026, Asia/Kolkata.",
            "Calendar today: 2 event(s), every one listed below.",
            'Recent briefs opened on: "Priya replied overnight."; "Big day for the raise.". '
            "Lead somewhere new unless the same thing still matters most.",
        ]

    def test_an_empty_calendar_and_no_openings_say_just_that(self) -> None:
        assert context_block(replace(CONTEXT, calendar=0)).splitlines() == [
            "Wednesday 11 November 2026, Asia/Kolkata.",
            "Nothing on the calendar today.",
        ]

    def test_with_no_calendar_connected_it_never_says_the_calendar_is_empty(self) -> None:
        unconnected = replace(CONTEXT, calendar=CalendarGap.NOT_CONNECTED)

        assert context_block(unconnected).splitlines() == [
            "Wednesday 11 November 2026, Asia/Kolkata.",
            NO_CALENDAR_CONNECTED,
        ]

    def test_a_calendar_that_did_not_answer_is_never_called_empty(self) -> None:
        unread = replace(CONTEXT, calendar=CalendarGap.UNAVAILABLE)

        assert context_block(unread).splitlines() == [
            "Wednesday 11 November 2026, Asia/Kolkata.",
            CALENDAR_UNAVAILABLE,
        ]

    def test_each_app_that_went_unread_is_named_once(self) -> None:
        unread = replace(
            CONTEXT,
            unread=[
                UnreadSource(app="Slack", reason=ScoutSkipReason.FAILED),
                UnreadSource(app="Notion", reason=ScoutSkipReason.BUDGET),
                UnreadSource(app="Slack", reason=ScoutSkipReason.SOURCE_FAILED),
            ],
        )

        assert context_block(unread).splitlines() == [
            "Wednesday 11 November 2026, Asia/Kolkata.",
            "Calendar today: 2 event(s), every one listed below.",
            "Not read this time: Slack, Notion. Nothing is known about what they hold today:"
            " never say they hold nothing, or that nothing there needs the user.",
        ]

    def test_an_app_whose_sign_in_died_is_named_for_a_reconnect(self) -> None:
        unread = replace(
            CONTEXT,
            unread=[
                UnreadSource(app="GitHub", reason=ScoutSkipReason.SIGNED_OUT),
                UnreadSource(app="Slack", reason=ScoutSkipReason.FAILED),
                UnreadSource(app="GitHub", reason=ScoutSkipReason.SIGNED_OUT),
                UnreadSource(app="Linear", reason=ScoutSkipReason.SIGNED_OUT),
            ],
        )

        assert context_block(unread).splitlines()[2] == (
            "Not read this time: GitHub, Slack, Linear. Nothing is known about what they hold"
            " today: never say they hold nothing, or that nothing there needs the user. Signed"
            " out: GitHub, Linear. Their sign-in expired, so they stay unread until the user"
            " reconnects them in Settings, Integrations: say so in one short line."
        )


class TestAnItemLine:
    def test_a_due_date_is_the_users_own_day_not_utcs(self) -> None:
        """Regression: a todo due 1 AM in Kolkata read as due the day before, its UTC date."""
        item = BriefCandidate(
            source="gaia",
            app="GAIA",
            state="you",
            title="Rent",
            due_at=datetime(2026, 11, 11, 19, 30, tzinfo=UTC),
            gaia_acts=True,
        )

        assert (
            item_line(1, item, CONTEXT.clock)
            == "1. [GAIA] waiting on you: Rent | due 2026-11-12 | GAIA can act on it"
        )

    def test_an_undated_own_todo_reads_as_on_their_list_not_waiting(self) -> None:
        item = BriefCandidate(
            source="gaia", app="GAIA", state="you", title="Plan Q1", backlog=True, gaia_acts=True
        )

        assert item_line(4, item, CONTEXT.clock) == (
            "4. [GAIA] on their list, undated: Plan Q1 | GAIA can act on it"
        )

    def test_an_item_an_earlier_brief_showed_as_it_stands_is_marked_still_open(self) -> None:
        shown = SignalMemoryDocument(
            user_id="u1",
            integration_id="gaia",
            external_id="todo:t1",
            first_seen=datetime(2026, 11, 8, 3, tzinfo=UTC),
            times_shown=2,
            last_shown=datetime(2026, 11, 10, 3, tzinfo=UTC),
            last_state="you",
        )
        item = BriefCandidate(
            source="gaia",
            app="GAIA",
            state="you",
            title="Approve the MSA",
            memory=shown,
            gaia_acts=True,
        )

        assert item_line(2, item, CONTEXT.clock) == (
            "2. [GAIA] waiting on you: Approve the MSA | GAIA can act on it | already shown,"
            " still open (first seen 3 days ago, mentioned 2 time(s), last yesterday)"
        )
        assert item_line(2, item.model_copy(update={"moved": True}), CONTEXT.clock) == (
            "2. [GAIA] waiting on you: Approve the MSA | GAIA can act on it"
        )

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

        assert item_line(7, item, CONTEXT.clock) == (
            "7. [GitHub] failed, important: Deploy broke | CI red on main | at 4:00 PM"
            " | due 2026-11-12 | names Maya Chen, Ravi Rao (the app does not say their part in it)"
            " | 3 todos on this one subject | action retry | outcome drafted | linkable"
            " | GAIA can only read GitHub: no offer on it | also found by Slack, Linear"
        )

    @pytest.mark.parametrize(
        ("finished_by", "state"),
        [
            (TodoCompleter.GAIA, "done by GAIA"),
            (TodoCompleter.USER, "done by the user"),
            (None, "done, who finished it is not recorded"),
        ],
    )
    def test_a_done_todo_says_who_finished_it(
        self, finished_by: TodoCompleter | None, state: str
    ) -> None:
        item = BriefCandidate(
            source="gaia",
            app="GAIA",
            state="lookback",
            title="Investor update",
            todo_id="t1",
            finished_by=finished_by,
            gaia_acts=True,
        )

        assert item_line(1, item, CONTEXT.clock) == (
            f"1. [GAIA] {state}: Investor update | linkable | GAIA can act on it"
        )

    def test_a_done_item_that_is_no_todo_reads_as_done(self) -> None:
        item = BriefCandidate(source="github", app="GitHub", state="lookback", title="PR merged")

        assert item_line(1, item, CONTEXT.clock) == (
            "1. [GitHub] done: PR merged | GAIA can only read GitHub: no offer on it"
        )

    def test_gaias_work_not_being_worked_on_reads_open_and_says_where_it_stands(self) -> None:
        item = BriefCandidate(
            source="gaia",
            app="GAIA",
            state="gaia",
            title="Draft the deck",
            standing="paused: waiting on your notes",
            todo_id="t2",
            gaia_acts=True,
        )

        assert item_line(5, item, CONTEXT.clock) == (
            "5. [GAIA] open: Draft the deck | stands: paused: waiting on your notes"
            " | linkable | GAIA can act on it"
        )

    def test_the_people_take_the_part_their_app_names_only_when_they_are_its_people(
        self,
    ) -> None:
        review = Signal(
            integration_id="github",
            app="GitHub",
            external_id="pr-1",
            kind="pull request awaiting your review",
            title="Fix login",
            people=["Ravi Rao"],
            people_role=PeopleRole.REVIEWER,
        )
        item = BriefCandidate(
            source="github",
            app="GitHub",
            state="you",
            title="Fix login",
            people=["Ravi Rao"],
            signal=review,
        )
        folded = item.model_copy(update={"people": ["Ravi Rao", "Maya Chen"]})

        assert item_line(1, item, CONTEXT.clock) == (
            "1. [GitHub] waiting on you: Fix login | reviewer: Ravi Rao"
            " | GAIA can only read GitHub: no offer on it"
        )
        assert item_line(1, folded, CONTEXT.clock) == (
            "1. [GitHub] waiting on you: Fix login | names Ravi Rao, Maya Chen"
            " (the app does not say their part in it) | GAIA can only read GitHub: no offer on it"
        )

    def test_a_plain_item_is_only_its_head(self) -> None:
        item = BriefCandidate(source="stripe", app="Stripe", state="note", title="Payout sent")

        assert (
            item_line(2, item, CONTEXT.clock)
            == "2. [Stripe] note: Payout sent | GAIA can only read Stripe: no offer on it"
        )

    def test_one_request_is_not_called_a_group(self) -> None:
        item = BriefCandidate(source="stripe", app="Stripe", state="note", title="Payout", count=1)
        grouped = item.model_copy(update={"count": 2})

        assert item_line(1, item, CONTEXT.clock) == (
            "1. [Stripe] note: Payout | GAIA can only read Stripe: no offer on it"
        )
        assert "| 2 todos on this one subject |" in item_line(1, grouped, CONTEXT.clock)

    @pytest.mark.parametrize(("url", "todo_id"), [("https://x.test", None), (None, "t1")])
    def test_an_item_with_either_a_url_or_a_todo_is_linkable(
        self, url: str | None, todo_id: str | None
    ) -> None:
        item = BriefCandidate(
            source="gmail", app="Gmail", state="you", title="Reply", url=url, todo_id=todo_id
        )

        assert item_line(1, item, CONTEXT.clock) == (
            "1. [Gmail] waiting on you: Reply | linkable | GAIA can only read Gmail: no offer on it"
        )

    def test_a_calendar_event_is_not_named_by_its_state(self) -> None:
        item = BriefCandidate(
            source="googlecalendar",
            app="Google Calendar",
            state="note",
            title="Board call",
            is_event=True,
        )

        assert (
            item_line(3, item, CONTEXT.clock)
            == "3. [Google Calendar] calendar event: Board call | GAIA can only read Google Calendar: no offer on it"
        )


class TestAnEmptyPool:
    def test_the_pool_says_each_due_date_on_the_users_own_day(self) -> None:
        rent = BriefCandidate(
            source="gaia",
            app="GAIA",
            state="you",
            title="Rent",
            due_at=datetime(2026, 11, 11, 19, 30, tzinfo=UTC),
            gaia_acts=True,
        )
        pool = FactPool(
            items={1: rent}, series=[], quotes=[], goals=[], context=CONTEXT, criteria={}
        )

        assert (
            pool_block(pool).split("\n")[1]
            == "1. [GAIA] waiting on you: Rent | due 2026-11-12 | GAIA can act on it"
        )

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

    def test_the_items_part_opens_by_saying_what_each_state_means(self) -> None:
        pool = FactPool(items={}, series=[], quotes=[], goals=[], context=CONTEXT, criteria={})

        assert pool_block(pool).split("\n")[0] == (
            "ITEMS (done by GAIA / done by the user / closed: finished since Tue 10 Nov, 5:30 AM,"
            " by whoever its state names; in progress: GAIA is working on it; open: GAIA's work"
            " that is not being worked on now, its line says where it stands; waiting on you:"
            " needs the user; failed: broke and needs the user; note: news that needs nothing;"
            " on their list, undated: an undated todo of their own, never news and never the"
            " lead. An item marked already shown, still open was already shown, unchanged: not"
            " news, so it never leads)"
        )

    def test_several_items_each_take_a_line(self) -> None:
        reads = _reads()
        pool = FactPool(
            items=reads.items, series=[], quotes=[], goals=[], context=CONTEXT, criteria={}
        )

        lines = pool_block(pool).split("\n")

        assert lines[1:4] == [
            "1. [Gmail] waiting on you: Re: Series A term sheet | names Maya Chen"
            " (the app does not say their part in it) | GAIA can only read Gmail: no offer on it",
            "2. [Stripe] waiting on you: "
            + reads.items[2].title
            + " | GAIA can only read Stripe: no offer on it",
            "3. [Google Calendar] calendar event: Board call"
            " | GAIA can only read Google Calendar: no offer on it",
        ]


class TestSeriesAndGoalLines:
    def test_a_series_without_a_unit_names_none(self) -> None:
        series = DataSeries(
            id="s",
            label="Runs",
            unit=None,
            source="gaia",
            app="GAIA",
            shape=SeriesShape.CATEGORICAL,
            points=[SeriesPoint(x="Done", y=1)],
        )

        assert series_line(series, date(2026, 11, 11)).split(" | ")[1] == (
            "Runs (GAIA), categorical of 1 points"
        )

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

    def test_a_goal_says_who_finished_its_work_and_what_is_stuck(self) -> None:
        goal = GoalState(
            id="g2",
            statement="Close the Atlas round",
            origin=GoalOrigin.MEMORY,
            done=4,
            done_by_gaia=1,
            done_by_you=2,
            open=2,
            linked=["Atlas deck", "Atlas model", "Atlas memo", "Atlas data room", "Atlas pricing"],
            stalled=["Atlas pricing", "Atlas press"],
        )

        assert goal_line(goal) == (
            'g2 | "Close the Atlas round" (from memory) | linked todos: 4 finished (1 by GAIA,'
            " 2 by the user, 1 by an event, or no one recorded), 2 open: Atlas deck; Atlas model;"
            " Atlas memo; Atlas data room; Atlas pricing | stuck a week or more: Atlas pricing;"
            " Atlas press"
        )

    def test_a_goal_with_nothing_finished_names_no_one_and_says_since_when(self) -> None:
        goal = GoalState(
            id="g1",
            statement="Ship",
            origin=GoalOrigin.MEMORY,
            done=0,
            since="2026-11-05",
            open=1,
            linked=["Ship the beta"],
        )

        assert goal_line(goal) == (
            'g1 | "Ship" (from memory) | linked todos: 0 finished since Thu 5 Nov, 1 open:'
            " Ship the beta"
        )
