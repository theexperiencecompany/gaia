"""What the briefing run sees: clocks, goals, tracked work, look-back, winback.

Repositories and the memory engine are the faked seams; every assertion is on
the block or state the run would hand the agent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.helpers import captured_wide_event, local_timezone

from app.constants.briefing import (
    WEEK_LIST_LIMIT,
    WINBACK_THRESHOLD,
    BriefingKind,
    BriefOutcome,
    EditionFamily,
)
from app.constants.memory import MemoryEntityType, MemoryKind
from app.constants.todos import (
    ACTION_NEEDED_LABEL,
    BLOCKING_LABEL,
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    NEEDS_REPLY_LABEL,
    WAITING_FOR_APPROVAL_LABEL,
    WAITING_FOR_REPLY_LABEL,
    TodoCompleter,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_document_models import BriefingModel
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
)
from app.models.brief_pool_models import GoalOrigin
from app.models.calendar_models import CalendarEventsResponse, GoogleCalendarEventResource
from app.models.memory_models import MemoryEntityRef, MemoryEntry, MemorySearchResult
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services import calendar_service
from app.services.briefing import calendar_read, goals as goals_module, wind_down
from app.services.briefing.calendar_read import CalendarGap, CalendarRead, read_calendar
from app.services.briefing.clock import UserClock, due_on, resolve_clock
from app.services.briefing.fact_pool.pool import PoolContext
from app.services.briefing.fact_pool.render import context_block
from app.services.briefing.goals import (
    StatedGoal,
    format_goal_block,
    has_meaningful_focus,
    stated_goals,
)
from app.services.briefing.lookback import (
    Lookback,
    compute_winback_state,
    format_lookback_block,
    lookback_since,
)
from app.services.briefing.work import (
    CompletedWork,
    Finish,
    OpenSubjects,
    TrackedWork,
    count_week,
    is_gaia_tracked,
    read_work,
)
from app.utils.errors import AppError, IntegrationNotConnectedError

_USER = "user-1"


@pytest.fixture(autouse=True)
def nothing_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read read_work makes answers empty unless a test says otherwise."""
    for name in ("list_completed_since", "list_active_tracked", "list_open_user_todos"):
        monkeypatch.setattr(todo_repository, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(workflow_repository, "find_system_workflows", AsyncMock(return_value=[]))


async def _tracked(since: datetime) -> TrackedWork:
    return (await read_work(_USER, since)).tracked_work(since)


async def _calendar(clock: UserClock, days: int, starts_in: int = 0) -> CalendarRead:
    span = clock.days(clock.today + timedelta(days=starts_in), days)
    return await read_calendar(_USER, span, span)


async def _lookback(last: BriefingModel | None, since: datetime) -> str:
    reads = await read_work(_USER, since)
    return await format_lookback_block(_USER, reads, Lookback(last, since), _CLOCK)


def _todo(todo_id: str, title: str, *labels: str, by: TodoCompleter | None = None) -> TodoDocument:
    return TodoDocument(
        id=todo_id,
        user_id=_USER,
        title=title,
        labels=list(labels),
        completed=by is not None,
        completed_by=by,
    )


def _finished_at_cutoff(*docs: TodoDocument) -> AsyncMock:
    """Stand in for list_completed_since: each todo completed right at the cutoff it was read from."""
    return AsyncMock(
        side_effect=lambda _user_id, since: [
            d.model_copy(update={"completed": True, "completed_at": since}) for d in docs
        ]
    )


def _brief(mood: BriefingMood, *, items: list[str] | None = None) -> BriefingModel:
    return BriefingModel(
        user_id=_USER,
        date="2026-10-12",
        payload=BriefingPayload(
            kicker="K",
            template_family=EditionFamily.SWISS,
            date="2026-10-12",
            headline="H",
            lede="L",
            mood=mood,
            caption="C",
            sections=[
                BriefingSection(
                    numeral="I",
                    title="T",
                    items=[
                        BriefingItem(text=t, outcome=BriefOutcome.CHANGED) for t in (items or [])
                    ],
                )
            ],
        ),
        created_at=datetime(2026, 10, 12, 8, tzinfo=UTC),
    )


class TestClock:
    def test_missing_timezone_is_utc(self) -> None:
        assert resolve_clock(None).tz is UTC

    def test_unknown_timezone_reads_as_utc_like_every_other_clock(self) -> None:
        assert resolve_clock("Nowhere/City").tz is UTC

    def test_a_stored_utc_offset_is_the_users_clock(self) -> None:
        clock = resolve_clock("+05:30")

        assert clock.now_local.utcoffset() == timedelta(hours=5, minutes=30)
        assert (
            context_block(
                PoolContext(
                    reader="Ada",
                    clock=clock,
                    calendar=0,
                    calendar_span="today",
                    done_since=clock.day_start(),
                )
            )
            .splitlines()[0]
            .endswith(", +05:30.")
        )

    def test_day_start_is_local_midnight_in_utc(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")
        clock = UserClock(
            tz=tz,
            now_local=datetime(2026, 10, 13, 9, 30, tzinfo=tz),
            date_str="2026-10-13",
            day_of_year=286,
        )

        assert clock.day_start() == datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
        assert clock.day_start(days_ago=1) == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)


def _user_with_focus(focus: str) -> UserDocument:
    return UserDocument(onboarding=OnboardingSubdocument(focus=focus))


def _memory(note: str, *entities: str, kind: MemoryKind = MemoryKind.FACT) -> MemoryEntry:
    """Return a recalled memory: its content and the names it is about."""
    return MemoryEntry(
        content=note,
        kind=kind,
        entities=[
            MemoryEntityRef(id=e, name=e, entity_type=MemoryEntityType.PROJECT) for e in entities
        ],
    )


def _recalled(*memories: MemoryEntry, confident: bool = True) -> MemorySearchResult:
    return MemorySearchResult(memories=list(memories), has_confident_match=confident)


class TestGoalBlock:
    @pytest.fixture
    def recall(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        recall = AsyncMock(return_value=_recalled())
        monkeypatch.setattr(goals_module, "memory_engine", SimpleNamespace(recall=recall))
        monkeypatch.setattr(goals_module, "entry_to_note", lambda entry: entry.content)
        return recall

    @pytest.mark.parametrize("focus", ["", "  ", "nothing", "N/A", "idk"])
    async def test_junk_focus_and_no_memories_is_no_goal(
        self, recall: AsyncMock, focus: str
    ) -> None:
        goals = await stated_goals(_USER, _user_with_focus(focus))
        block, has_goal = format_goal_block(goals), bool(goals)

        assert goals == []
        assert has_goal is False
        assert "No stated goal" in block

    async def test_stated_focus_and_recalled_memories_are_both_shown(
        self, recall: AsyncMock
    ) -> None:
        recall.return_value = _recalled(
            _memory("Raising a seed round", "Accel"), _memory("Raising a seed round", "Accel")
        )

        goals = await stated_goals(_USER, _user_with_focus("Close 10 customers"))
        block, has_goal = format_goal_block(goals), bool(goals)

        assert goals == [
            StatedGoal("Close 10 customers", GoalOrigin.ONBOARDING),
            StatedGoal("Raising a seed round", GoalOrigin.MEMORY, ("Accel",)),
        ]
        assert has_goal is True
        assert block.splitlines() == ["Stated goal: Close 10 customers", "- Raising a seed round"]

    async def test_a_recall_failure_fails_the_run(self, recall: AsyncMock) -> None:
        """Goal knowledge gates the brief; a broken memory store must not read as no goal."""
        recall.side_effect = RuntimeError("vector store down")

        with pytest.raises(RuntimeError, match="vector store down"):
            await stated_goals(_USER, _user_with_focus("Ship v2"))


class TestTrackedWork:
    async def test_open_todos_are_sorted_by_state_and_only_gaia_completions_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            todo_repository,
            "list_completed_since",
            _finished_at_cutoff(
                _todo("c1", "Research", GAIA_TRACKED_LABEL),
                _todo("c2", "Groceries"),
                _todo("c3", "Book flights", GAIA_TRACKED_LABEL, by=TodoCompleter.USER),
            ),
        )
        monkeypatch.setattr(
            todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    _todo("f1", "Sync", GAIA_TRACKED_LABEL, FAILED_LABEL, BLOCKING_LABEL),
                    _todo("b1", "Reply", GAIA_TRACKED_LABEL, BLOCKING_LABEL),
                    _todo("r1", "Plan", GAIA_TRACKED_LABEL),
                ]
            ),
        )

        work = await _tracked(datetime.now(UTC))

        assert [d.id for d in work.completed] == ["c1"]
        assert [d.id for d in work.failed] == ["f1"]
        assert [d.id for d in work.blocked] == ["b1"]
        assert [d.id for d in work.running] == ["r1"]
        assert not work.is_empty

    async def test_a_thread_the_user_owes_needs_them_and_one_awaiting_others_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The inbox desk's thread todos are its findings: needs-reply and action-needed wait on the user."""
        monkeypatch.setattr(todo_repository, "list_completed_since", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    _todo("n1", "Priya · pitch deck", GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL),
                    _todo("a1", "Add Arjun call", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL),
                    _todo("k1", "Kotak · card declined", GAIA_TRACKED_LABEL, ACTION_NEEDED_LABEL),
                    _todo("w1", "Dhruv · offer", GAIA_TRACKED_LABEL, WAITING_FOR_REPLY_LABEL),
                ]
            ),
        )

        work = await _tracked(datetime.now(UTC))

        assert [d.id for d in work.blocked] == ["n1", "a1", "k1"]
        assert [d.id for d in work.running] == ["w1"]

    async def test_the_inbox_desk_is_reported_through_its_findings_not_as_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        desk = _todo("d1", "Inbox desk", GAIA_TRACKED_LABEL)
        desk.external_ref = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
        monkeypatch.setattr(todo_repository, "list_completed_since", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    desk,
                    _todo("n1", "Priya · pitch deck", GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL),
                ]
            ),
        )

        work = await _tracked(datetime.now(UTC))

        assert ([d.id for d in work.blocked], work.running) == (["n1"], [])


# Tuesday 13 Oct 2026, 09:00 in Kolkata.
_CLOCK = UserClock(
    tz=ZoneInfo("Asia/Kolkata"),
    now_local=datetime(2026, 10, 13, 9, tzinfo=ZoneInfo("Asia/Kolkata")),
    date_str="2026-10-13",
    day_of_year=286,
)
_SINCE_BRIEF = datetime(2026, 10, 12, 8, tzinfo=UTC)


class TestLookback:
    @pytest.fixture(autouse=True)
    def no_briefing_workflows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            workflow_repository, "find_system_workflows", AsyncMock(return_value=[])
        )

    async def test_first_look_back_with_nothing_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(todo_repository, "list_completed_since", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            workflow_executions_repository, "list_since", AsyncMock(return_value=[])
        )

        block = await _lookback(None, datetime.now(UTC))

        assert "No prior briefing" in block
        assert "Nothing was completed" in block
        assert "Background workflow runs" not in block

    async def test_yesterdays_plan_is_compared_to_what_finished(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            todo_repository,
            "list_completed_since",
            _finished_at_cutoff(
                _todo("c1", "Deck", GAIA_TRACKED_LABEL, by=TodoCompleter.GAIA), _todo("c2", "Gym")
            ),
        )
        monkeypatch.setattr(
            workflow_executions_repository,
            "list_since",
            AsyncMock(return_value=[SimpleNamespace(status="success", summary="3 drafts")]),
        )

        block = await _lookback(_brief(BriefingMood.CLEAR, items=["Finish the deck"]), _SINCE_BRIEF)

        assert "- note: Finish the deck" in block
        assert "- GAIA finished: Deck" in block
        assert "- The user finished: Gym" in block
        assert "- Workflow [success]: 3 drafts" in block


def _sent_days_ago(brief: BriefingModel, days: int) -> BriefingModel:
    brief.created_at = datetime(2026, 10, 12, 8, tzinfo=UTC) - timedelta(days=days)
    return brief


_WINBACK_USER = UserDocument(id=_USER)


class TestWinback:
    @pytest.fixture
    def briefs(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        listing = AsyncMock(return_value=[])
        monkeypatch.setattr(briefing_repository, "list_recent", listing)
        return listing

    @pytest.fixture
    def last_active(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        read = AsyncMock(return_value=None)
        monkeypatch.setattr(wind_down, "latest_activity_since", read)
        return read

    async def test_no_briefs_is_not_winback(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        state = await compute_winback_state(_WINBACK_USER)

        assert (state.unacknowledged, state.is_winback, state.should_back_off) == (0, False, False)
        last_active.assert_not_awaited()

    async def test_ignored_briefs_up_to_the_threshold_flip_to_winback(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [
            _sent_days_ago(_brief(BriefingMood.CLEAR), d) for d in range(WINBACK_THRESHOLD)
        ]

        state = await compute_winback_state(_WINBACK_USER)

        assert state.unacknowledged == WINBACK_THRESHOLD
        assert state.is_winback
        assert not state.should_back_off

    async def test_activity_after_a_brief_acknowledges_it(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [
            _sent_days_ago(_brief(BriefingMood.CLEAR), d) for d in range(WINBACK_THRESHOLD + 1)
        ]
        # Active between the second-newest brief and the newest one.
        last_active.return_value = datetime(2026, 10, 11, 9, tzinfo=UTC)

        state = await compute_winback_state(_WINBACK_USER)

        assert state.unacknowledged == 1
        assert not state.is_winback

    async def test_last_activity_is_read_once_from_the_oldest_brief(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_sent_days_ago(_brief(BriefingMood.CLEAR), d) for d in range(5)]

        await compute_winback_state(_WINBACK_USER)

        last_active.assert_awaited_once_with(_USER, datetime(2026, 10, 8, 8, tzinfo=UTC))

    async def test_a_sent_winback_that_is_still_ignored_backs_off(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_brief(BriefingMood.WINBACK)] + [
            _sent_days_ago(_brief(BriefingMood.CLEAR), d + 1) for d in range(WINBACK_THRESHOLD)
        ]

        state = await compute_winback_state(_WINBACK_USER)

        assert state.should_back_off

    async def test_naive_created_at_is_read_as_utc(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        brief = _brief(BriefingMood.CLEAR)
        brief.created_at = datetime(2026, 10, 12, 8)
        briefs.return_value = [brief]
        last_active.return_value = datetime(2026, 10, 12, 8, tzinfo=UTC)

        state = await compute_winback_state(_WINBACK_USER)

        assert last_active.await_args.args[1] == datetime(2026, 10, 12, 8, tzinfo=UTC)
        assert state.unacknowledged == 0


def _clock(iso: str = "2026-10-14T07:00:00", tz: str = "Asia/Kolkata") -> UserClock:
    zone = ZoneInfo(tz)
    now = datetime.fromisoformat(iso).replace(tzinfo=zone)
    return UserClock(
        tz=zone, now_local=now, date_str=now.date().isoformat(), day_of_year=now.timetuple().tm_yday
    )


def _event(
    summary: str, start: dict[str, str], location: str | None = None
) -> GoogleCalendarEventResource:
    data: dict[str, object] = {"summary": summary, "start": start}
    if location:
        data["location"] = location
    return GoogleCalendarEventResource.model_validate(data)


def _response(
    events: list[GoogleCalendarEventResource], failed: list[str] | None = None
) -> CalendarEventsResponse:
    return CalendarEventsResponse(
        events=events,
        selected_calendars=["primary"],
        has_more=False,
        calendars_truncated=[],
        calendars_failed=failed or [],
    )


class TestCalendar:
    @pytest.fixture
    def connected(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        ids = AsyncMock(return_value={"googlecalendar"})
        monkeypatch.setattr(calendar_read, "get_connected_integration_ids", ids)
        return ids

    async def test_no_calendar_connected_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        connected.return_value = {"gmail"}
        fetch = AsyncMock()
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        assert (await _calendar(_clock(), 1)).gap is CalendarGap.NOT_CONNECTED
        fetch.assert_not_awaited()

    async def test_events_land_on_the_users_clock_in_start_order(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        fetch = AsyncMock(
            return_value=_response(
                events=[
                    _event(
                        "Sequoia partner meeting",
                        {"dateTime": "2026-10-14T05:30:00Z"},
                        "Menlo Park",
                    ),
                    _event("Offsite", {"date": "2026-10-14"}),
                    _event("Standup", {"dateTime": "2026-10-14T03:30:00Z"}),
                ]
            )
        )
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        events = (await _calendar(_clock(), 1)).events

        assert [(e.date, e.start, e.title, e.location) for e in events] == [
            ("2026-10-14", None, "Offsite", None),
            ("2026-10-14", "09:00", "Standup", None),
            ("2026-10-14", "11:00", "Sequoia partner meeting", "Menlo Park"),
        ]
        window = fetch.await_args.kwargs
        assert window["time_min"] == "2026-10-13T18:30:00+00:00"
        assert window["time_max"] == "2026-10-14T18:30:00+00:00"

    async def test_a_calendar_failure_the_read_cannot_name_still_fails_it(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(side_effect=RuntimeError("proxy down"))
        )

        with pytest.raises(RuntimeError, match="proxy down"):
            await _calendar(_clock(), 1)

    @pytest.mark.parametrize(
        "failure",
        [
            IntegrationNotConnectedError(
                integration_id="googlecalendar",
                integration_name="Google Calendar",
                why="the token expired",
                grant_died=True,
            ),
            AppError(message="Invalid Credentials", status_code=401),
        ],
    )
    async def test_an_expired_calendar_is_unavailable_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock, failure: AppError
    ) -> None:
        """Regression: an expired token on the calendar list failed the whole daily brief."""
        monkeypatch.setattr(calendar_service, "proxy_request", AsyncMock(side_effect=failure))

        assert (await _calendar(_clock(), 1)).gap is CalendarGap.UNAVAILABLE

    async def test_a_calendar_that_failed_to_answer_is_unavailable_not_empty(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        """Regression: a calendar whose events failed to load read as a free day."""
        listing = {"items": [{"id": "primary", "summary": "Ada"}]}
        monkeypatch.setattr(
            calendar_service,
            "proxy_request",
            AsyncMock(side_effect=[listing, AppError(message="Backend Error", status_code=503)]),
        )
        monkeypatch.setattr(
            calendar_service,
            "_resolve_selected_calendars",
            AsyncMock(return_value=["primary"]),
        )

        assert (await _calendar(_clock(), 1)).gap is CalendarGap.UNAVAILABLE

    async def test_an_unavailable_calendar_is_a_warning_on_the_runs_event(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        monkeypatch.setattr(
            calendar_read,
            "get_calendar_events",
            AsyncMock(return_value=_response([], failed=["primary"])),
        )

        async with captured_wide_event() as event:
            await _calendar(_clock(), 1)

        assert [w["msg"] for w in event["warnings"]] == ["briefing.calendar_unavailable"]
        assert event["warnings"][0]["calendars_failed"] == 1

    async def test_a_failed_calendar_list_is_a_warning_naming_the_error(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        failure = AppError(message="Invalid Credentials", status_code=401)
        monkeypatch.setattr(calendar_service, "proxy_request", AsyncMock(side_effect=failure))

        async with captured_wide_event() as event:
            await _calendar(_clock(), 1)

        warning = event["warnings"][0]
        assert (warning["msg"], warning["error_type"], warning["error"]) == (
            "briefing.calendar_unavailable",
            "HTTPException",
            "401: Invalid Credentials",
        )

    async def test_the_week_ahead_holds_only_its_own_days(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        """Google answers for any event overlapping the window; the days are the brief's."""
        events = [
            _event("Today", {"date": "2026-10-14"}),
            _event("Tomorrow", {"date": "2026-10-15"}),
            _event("Last day", {"date": "2026-10-21"}),
            _event("Past the week", {"date": "2026-10-22"}),
            GoogleCalendarEventResource.model_validate({"summary": "No start"}),
        ]
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(return_value=_response(events))
        )

        ahead = (await _calendar(_clock(), 7, starts_in=1)).events

        assert [e.title for e in ahead] == ["Tomorrow", "Last day"]

    async def test_the_days_read_holds_today_and_keeps_the_whole_window(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        raw = [
            _event("Standup", {"dateTime": "2026-10-14T03:30:00Z"}),
            _event("Offsite", {"date": "2026-10-15"}),
        ]
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(return_value=_response(raw))
        )
        clock = _clock()

        day = await read_calendar(_USER, clock.days(clock.today, 7), clock.days(clock.today, 1))

        assert day.events == [BriefingEvent(date="2026-10-14", start="09:00", title="Standup")]
        assert day.raw == raw

    async def test_an_event_the_user_declined_is_not_on_their_day(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        declined = GoogleCalendarEventResource.model_validate(
            {
                "summary": "Vendor pitch",
                "start": {"dateTime": "2026-10-14T05:30:00Z"},
                "attendees": [
                    {"email": "ada@x.test", "self": True, "responseStatus": "declined"},
                    {"email": "vendor@y.test", "responseStatus": "accepted"},
                ],
            }
        )
        kept = _event("Standup", {"dateTime": "2026-10-14T03:30:00Z"})
        monkeypatch.setattr(
            calendar_read,
            "get_calendar_events",
            AsyncMock(return_value=_response([declined, kept])),
        )

        events = (await _calendar(_clock(), 1)).events

        assert [e.title for e in events] == ["Standup"]


class TestWeek:
    async def test_the_week_is_counted_monday_to_sunday_by_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tz = ZoneInfo("Asia/Kolkata")

        def done(title: str, local: str, *labels: str) -> TodoDocument:
            doc = _todo(title, title, *labels)
            doc.completed_at = datetime.fromisoformat(local).replace(tzinfo=tz).astimezone(UTC)
            return doc

        # Newest completion first, as list_completed_since returns them.
        completed = _by_owner(
            [
                done("Memo", "2026-10-18T09:00", GAIA_TRACKED_LABEL),
                done("Deck", "2026-10-12T10:00", GAIA_TRACKED_LABEL),
                done("Gym", "2026-10-12T23:30"),
            ]
        )
        clock = _clock("2026-10-18T17:00:00")

        week = count_week(clock, completed, [])

        assert [(d.you, d.gaia) for d in week.days] == [
            (1, 1),
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 1),
        ]
        assert clock.this_week().start == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)


class TestClockIsTheUsers:
    def test_the_clock_reads_now_on_the_users_zone(self) -> None:
        clock = resolve_clock("Pacific/Kiritimati")

        assert clock.now_local.tzinfo == ZoneInfo("Pacific/Kiritimati")
        assert clock.date_str == clock.now_local.date().isoformat()
        assert clock.day_of_year == clock.now_local.timetuple().tm_yday

    def test_day_start_is_expressed_in_utc(self) -> None:
        assert _clock().day_start().tzinfo is UTC

    @pytest.mark.parametrize(
        ("due_at", "said"),
        [
            (datetime(2026, 10, 14, 17, 0, tzinfo=UTC), "today"),
            (datetime(2026, 10, 14, 19, 0, tzinfo=UTC), "Thu Oct 15"),
        ],
        ids=["late-on-the-users-day", "past-the-users-midnight"],
    )
    def test_a_due_date_is_said_on_the_users_own_day(self, due_at: datetime, said: str) -> None:
        assert due_on(due_at, _clock()) == said


class TestGoalBlockEdges:
    @pytest.fixture
    def recall(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        recall = AsyncMock(return_value=_recalled())
        monkeypatch.setattr(goals_module, "memory_engine", SimpleNamespace(recall=recall))
        monkeypatch.setattr(goals_module, "entry_to_note", lambda entry: entry.content)
        return recall

    async def test_a_weak_fallback_recall_is_no_goal(self, recall: AsyncMock) -> None:
        """Regression: the top five nearest memories became goals however weakly they matched."""
        recall.return_value = _recalled(_memory("Likes oat milk"), confident=False)

        assert await stated_goals(_USER, UserDocument()) == []

    async def test_something_that_happened_is_no_goal(self, recall: AsyncMock) -> None:
        recall.return_value = _recalled(
            _memory("Had a call with Priya", kind=MemoryKind.EXPERIENCE),
            _memory("Shipping the v2 launch"),
        )

        goals = await stated_goals(_USER, UserDocument())

        assert [g.statement for g in goals] == ["Shipping the v2 launch"]

    def test_a_missing_focus_is_not_a_goal(self) -> None:
        assert has_meaningful_focus(None) is False

    async def test_no_onboarding_and_no_memories_asks_for_goal_discovery(
        self, recall: AsyncMock
    ) -> None:
        goals = await stated_goals(_USER, UserDocument())

        assert goals == []
        assert format_goal_block(goals) == (
            "No stated goal on record yet — treat goal discovery as part of today's job."
        )

    async def test_memory_is_asked_what_the_user_is_working_on(self, recall: AsyncMock) -> None:
        await stated_goals(_USER, UserDocument())

        recall.assert_awaited_once_with(
            _USER, "what is the user currently working on and their goals", limit=5
        )

    async def test_a_blank_memory_is_not_a_goal(self, recall: AsyncMock) -> None:
        recall.return_value = _recalled(_memory("   "), _memory("Hiring a designer"))

        goals = await stated_goals(_USER, UserDocument())

        assert format_goal_block(goals) == "- Hiring a designer"


class TestReadsAreScopedToTheUser:
    async def test_tracked_work_reads_this_users_completions_and_open_todos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = AsyncMock(return_value=[])
        active = AsyncMock(return_value=[])
        monkeypatch.setattr(todo_repository, "list_completed_since", completed)
        monkeypatch.setattr(todo_repository, "list_active_tracked", active)
        since = datetime(2026, 10, 13, tzinfo=UTC)

        work = await _tracked(since)

        assert work.is_empty
        completed.assert_awaited_once_with(_USER, since=since)
        active.assert_awaited_once_with(_USER, limit=0)

    async def test_the_open_totals_count_past_the_read_limit_each_subject_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: 35 running todos were voiced as 20, the read's limit."""
        running = [_todo(f"r{i}", f"Research {i}", GAIA_TRACKED_LABEL) for i in range(35)]
        waiting = [
            _todo("w1", "Approve the MSA", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL),
            _todo("w2", "Approve the MSA", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL),
        ]
        monkeypatch.setattr(todo_repository, "list_completed_since", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            todo_repository, "list_active_tracked", AsyncMock(return_value=[*running, *waiting])
        )

        work = await _tracked(datetime(2026, 10, 13, tzinfo=UTC))

        assert len(work.running) == 20
        assert work.open_subjects == OpenSubjects(running=35, blocked=1, failed=0)

    async def test_completed_work_reads_this_users_completions_since_the_cutoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = AsyncMock(return_value=[])
        monkeypatch.setattr(todo_repository, "list_completed_since", completed)
        since = datetime(2026, 10, 13, tzinfo=UTC)

        await read_work(_USER, since)

        completed.assert_awaited_once_with(_USER, since=since)


def _execution(status: str, summary: str | None) -> WorkflowExecutionDocument:
    return WorkflowExecutionDocument.model_validate(
        {
            "execution_id": "e1",
            "workflow_id": "w1",
            "user_id": _USER,
            "status": status,
            "started_at": datetime(2026, 10, 13, tzinfo=UTC),
            "summary": summary,
        }
    )


def _untitled(todo_id: str, *labels: str) -> TodoDocument:
    doc = _todo(todo_id, "x", *labels)
    doc.title = ""
    return doc


class TestLookbackBlock:
    @pytest.fixture
    def reads(self, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        reads = SimpleNamespace(
            completed=AsyncMock(return_value=[]),
            executions=AsyncMock(return_value=[]),
            briefing_workflows=AsyncMock(
                return_value=[SimpleNamespace(id="wf-daily"), SimpleNamespace(id="wf-weekly")]
            ),
        )
        monkeypatch.setattr(todo_repository, "list_completed_since", reads.completed)
        monkeypatch.setattr(workflow_executions_repository, "list_since", reads.executions)
        monkeypatch.setattr(workflow_repository, "find_system_workflows", reads.briefing_workflows)
        return reads

    async def test_the_whole_block_reads_plan_then_done_then_runs(
        self, reads: SimpleNamespace
    ) -> None:
        reads.completed.side_effect = _finished_at_cutoff(
            _todo("c1", "Deck", GAIA_TRACKED_LABEL, by=TodoCompleter.GAIA),
            _untitled("c2", GAIA_TRACKED_LABEL),
            _todo("c3", "Gym"),
            _untitled("c4"),
            # Audit: GAIA's tracked work the user closed, or an event closed, read "GAIA finished".
            _todo("c5", "Pay Acme", GAIA_TRACKED_LABEL, by=TodoCompleter.USER),
            _todo("c6", "Sam's yes", GAIA_TRACKED_LABEL, by=TodoCompleter.TRIGGER),
            _todo("c7", "Old lead", GAIA_TRACKED_LABEL, by=TodoCompleter.SYSTEM),
        ).side_effect
        reads.executions.return_value = [
            _execution("success", "3 drafts"),
            _execution("failed", None),
        ]
        since = datetime(2026, 10, 13, tzinfo=UTC)
        yesterday = _brief(BriefingMood.CLEAR, items=["Finish the deck", "Book flights"])
        yesterday.created_at = since

        block = await _lookback(yesterday, since)

        assert block == (
            # Audit: it said the user was told GAIA would "focus on" every item, done or not.
            "Your last brief, yesterday, told the user about:\n"
            "- note: Finish the deck\n"
            "- note: Book flights\n\n"
            "Actually completed since then:\n"
            "- GAIA finished: Deck\n"
            "- The user finished: Gym\n"
            "- The user finished: untitled\n"
            "- The user finished: Pay Acme\n"
            "- Closed (who closed it is not recorded): untitled\n"
            "- Closed when an event it watched fired: Sam's yes\n\n"
            "Background workflow runs since then:\n"
            "- Workflow [success]: 3 drafts\n"
            "- Workflow [failed]"
        )
        reads.completed.assert_awaited_once_with(_USER, since=since)
        # The briefing workflows' own runs are not background work to report.
        reads.briefing_workflows.assert_awaited_once_with(
            _USER, ("daily_briefing", "weekly_digest")
        )
        reads.executions.assert_awaited_once_with(
            _USER, since, exclude_workflow_ids=["wf-daily", "wf-weekly"], limit=20
        )

    async def test_a_first_look_back_with_nothing_done_says_both_plainly(
        self, reads: SimpleNamespace
    ) -> None:
        block = await _lookback(None, datetime.now(UTC))

        assert block == (
            "No prior briefing — this is the first look-back.\n\n"
            "Nothing was completed since the last briefing."
        )

    async def test_only_the_users_own_completions_still_count_as_done(
        self, reads: SimpleNamespace
    ) -> None:
        reads.completed.side_effect = _finished_at_cutoff(_todo("c1", "Gym")).side_effect

        block = await _lookback(None, datetime.now(UTC))

        assert block.endswith("Actually completed since then:\n- The user finished: Gym")

    async def test_a_brief_days_ago_is_named_by_its_day_not_as_yesterday(
        self, reads: SimpleNamespace
    ) -> None:
        friday = _brief(BriefingMood.CLEAR, items=["Finish the deck"])
        friday.date = "2026-10-09"

        block = await _lookback(friday, friday.created_at)

        assert block.startswith(
            "Your last brief, on Friday Oct 9, told the user about:\n- note: Finish the deck"
        )
        assert "Yesterday" not in block

    async def test_a_brief_older_than_the_look_back_is_named_but_not_quoted(
        self, reads: SimpleNamespace
    ) -> None:
        old = _brief(BriefingMood.CLEAR, items=["Finish the deck"])
        old.date = "2026-09-20"
        old.created_at = datetime(2026, 9, 20, 2, tzinfo=UTC)
        since = lookback_since(_CLOCK, old)

        block = await _lookback(old, since)

        assert since == _CLOCK.day_start(days_ago=7)
        assert block.startswith("The last brief went out on Sunday Sep 20, over 7 days ago")
        assert "Finish the deck" not in block


class TestLookbackSince:
    def test_with_no_brief_before_it_starts_at_yesterdays_midnight(self) -> None:
        assert lookback_since(_CLOCK, None) == _CLOCK.day_start(days_ago=1)

    def test_it_starts_when_the_last_brief_went_out(self) -> None:
        friday = _brief(BriefingMood.CLEAR)
        friday.created_at = datetime(2026, 10, 9, 2, 30, tzinfo=UTC)

        assert lookback_since(_CLOCK, friday) == friday.created_at


class TestWinbackReads:
    async def test_the_last_ten_daily_briefs_are_read_and_each_ack_checked_for_this_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listing = AsyncMock(return_value=[_brief(BriefingMood.CLEAR)])
        signal = AsyncMock(return_value=None)
        monkeypatch.setattr(briefing_repository, "list_recent", listing)
        monkeypatch.setattr(wind_down, "latest_activity_since", signal)

        await compute_winback_state(_WINBACK_USER)

        listing.assert_awaited_once_with(_USER, limit=10, kind=BriefingKind.DAILY)
        assert signal.await_args.args[0] == _USER

    async def test_no_briefs_means_no_winback_went_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(briefing_repository, "list_recent", AsyncMock(return_value=[]))

        state = await compute_winback_state(_WINBACK_USER)

        assert state.last_was_winback is False


class TestCalendarEdges:
    @pytest.fixture
    def connected(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        ids = AsyncMock(return_value={"googlecalendar"})
        monkeypatch.setattr(calendar_read, "get_connected_integration_ids", ids)
        return ids

    async def test_untitled_and_all_day_events_keep_their_place(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        untitled = GoogleCalendarEventResource.model_validate(
            {"start": {"dateTime": "2026-10-14T03:30:00Z"}}
        )
        fetch = AsyncMock(
            return_value=_response(events=[untitled, _event("   ", {"date": "2026-10-14"}, "Goa")])
        )
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        events = (await _calendar(_clock(), 1)).events

        assert events == [
            BriefingEvent(date="2026-10-14", title="Untitled event", location="Goa"),
            BriefingEvent(date="2026-10-14", start="09:00", title="Untitled event"),
        ]
        connected.assert_awaited_once_with(_USER)
        assert fetch.await_args.args == (_USER,)
        assert fetch.await_args.kwargs["fetch_all"] is True

    async def test_days_ahead_shifts_the_window_forward(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        fetch = AsyncMock(return_value=_response(events=[]))
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        await _calendar(_clock(), 7, starts_in=1)

        window = fetch.await_args.kwargs
        assert window["time_min"] == "2026-10-14T18:30:00+00:00"
        assert window["time_max"] == "2026-10-21T18:30:00+00:00"


def _done(title: str, completed_at: datetime | None, *labels: str) -> TodoDocument:
    doc = _todo(title, title, *labels)
    doc.completed_at = completed_at
    return doc


def _by_owner(docs: list[TodoDocument]) -> CompletedWork:
    """Credit each completion to GAIA when tracked, else to the user, keeping their order."""
    return CompletedWork(
        [Finish(d, TodoCompleter.GAIA if is_gaia_tracked(d) else TodoCompleter.USER) for d in docs]
    )


class TestWeekEdges:
    async def test_each_completion_counts_on_its_local_day_and_odd_rows_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tz = ZoneInfo("Pacific/Kiritimati")
        # Each skipped row comes before a counted one, so a skip that stopped the walk shows.
        closed = _done("Closed by an event", datetime(2026, 10, 12, 9, tzinfo=tz))
        counted = _by_owner(
            [
                _done("Next week", datetime(2026, 10, 19, 1, tzinfo=tz)),
                _done("Memo", datetime(2026, 10, 13, 2, tzinfo=tz), GAIA_TRACKED_LABEL),
                _done("Never", None),
                _done("Brief", datetime(2026, 10, 12, 23, tzinfo=tz), GAIA_TRACKED_LABEL),
                _done("Gym", datetime(2026, 10, 12, 20, tzinfo=tz)),
                _done("Run", datetime(2026, 10, 12, 10)),
            ]
        )
        completed = CompletedWork([Finish(closed, TodoCompleter.TRIGGER), *counted.finished])
        clock = _clock("2026-10-14T12:00:00", "Pacific/Kiritimati")

        # Mongo's naive "Run" is UTC whatever zone the server itself runs in.
        with local_timezone("Asia/Kolkata"):
            week = count_week(clock, completed, [])

        assert [(d.you, d.gaia) for d in week.days][:2] == [(1, 1), (1, 1)]
        assert clock.this_week().start.tzinfo is UTC

    async def test_two_on_one_day_count_twice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        at = datetime(2026, 10, 12, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
        docs = [
            _done("a", at),
            _done("b", at),
            _done("c", at, GAIA_TRACKED_LABEL),
            _done("d", at, GAIA_TRACKED_LABEL),
        ]
        week = count_week(_clock(), _by_owner(docs), [])

        assert (week.days[0].you, week.days[0].gaia) == (2, 2)

    async def test_the_week_ahead_is_the_next_seven_days_capped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events = [
            BriefingEvent(date="2026-10-15", title=f"E{i}") for i in range(WEEK_LIST_LIMIT + 1)
        ]
        week = count_week(_clock(), CompletedWork(), events)

        assert week.ahead == events[:WEEK_LIST_LIMIT]

    def test_an_unread_calendar_holds_no_events_and_names_itself_unread(self) -> None:
        unread = CalendarRead(gap=CalendarGap.UNAVAILABLE)

        assert count_week(_clock(), CompletedWork(), unread.events).ahead == []
        assert [s.app for s in unread.unread] == ["Google Calendar"]
