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
from tests.helpers import local_timezone

from app.constants.briefing import BRIEFING_KIND_DAILY, WEEK_LIST_LIMIT, WINBACK_THRESHOLD
from app.constants.todos import (
    BLOCKING_LABEL,
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    NEEDS_REPLY_LABEL,
    WAITING_FOR_APPROVAL_LABEL,
    WAITING_FOR_REPLY_LABEL,
)
from app.models.briefing_models import BriefingEvent, BriefingModel, BriefingPayload
from app.models.calendar_models import GoogleCalendarEventResource
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services.briefing import context

_USER = "user-1"


def _todo(todo_id: str, title: str, *labels: str) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=title, labels=list(labels))


def _brief(mood: str, *, opened: bool = False, items: list[str] | None = None) -> BriefingModel:
    return BriefingModel(
        user_id=_USER,
        date="2026-10-12",
        payload=BriefingPayload(
            kicker="K",
            date="2026-10-12",
            headline="H",
            lede="L",
            mood=mood,
            caption="C",
            sections=[
                {"numeral": "I", "title": "T", "items": [{"text": t} for t in (items or [])]}
            ],
        ),
        opened_at=datetime.now(UTC) if opened else None,
        created_at=datetime(2026, 10, 12, 8, tzinfo=UTC),
    )


class TestClock:
    def test_missing_timezone_is_utc(self) -> None:
        assert context.resolve_clock(None).tz == ZoneInfo("UTC")

    def test_unknown_timezone_fails_loud(self) -> None:
        with pytest.raises(Exception, match="Nowhere/City"):
            context.resolve_clock("Nowhere/City")

    def test_day_start_is_local_midnight_in_utc(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")
        clock = context.UserClock(
            tz=tz,
            now_local=datetime(2026, 10, 13, 9, 30, tzinfo=tz),
            date_str="2026-10-13",
            day_of_year=286,
        )

        assert context.day_start_utc(clock) == datetime(2026, 10, 12, 18, 30, tzinfo=UTC)
        assert context.day_start_utc(clock, days_ago=1) == datetime(
            2026, 10, 11, 18, 30, tzinfo=UTC
        )


def _user_with_focus(focus: str) -> UserDocument:
    return UserDocument(onboarding=OnboardingSubdocument(focus=focus))


class TestGoalBlock:
    @pytest.fixture
    def recall(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        recall = AsyncMock(return_value=SimpleNamespace(memories=[]))
        monkeypatch.setattr(context, "memory_engine", SimpleNamespace(recall=recall))
        monkeypatch.setattr(context, "entry_to_note", str)
        return recall

    @pytest.mark.parametrize("focus", ["", "  ", "nothing", "N/A", "idk"])
    async def test_junk_focus_and_no_memories_is_no_goal(
        self, recall: AsyncMock, focus: str
    ) -> None:
        block, has_goal = await context.format_goal_block(_USER, _user_with_focus(focus))

        assert has_goal is False
        assert "No stated goal" in block

    async def test_stated_focus_and_recalled_memories_are_both_shown(
        self, recall: AsyncMock
    ) -> None:
        recall.return_value = SimpleNamespace(
            memories=["Raising a seed round", "Raising a seed round"]
        )

        block, has_goal = await context.format_goal_block(
            _USER, _user_with_focus("Close 10 customers")
        )

        assert has_goal is True
        assert block.splitlines() == ["Stated goal: Close 10 customers", "- Raising a seed round"]

    async def test_a_recall_failure_fails_the_run(self, recall: AsyncMock) -> None:
        """Goal knowledge gates the brief; a broken memory store must not read as no goal."""
        recall.side_effect = RuntimeError("vector store down")

        with pytest.raises(RuntimeError, match="vector store down"):
            await context.format_goal_block(_USER, _user_with_focus("Ship v2"))


class TestTrackedWork:
    async def test_open_todos_are_sorted_by_state_and_only_gaia_completions_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            context.todo_repository,
            "list_completed_since",
            AsyncMock(
                return_value=[
                    _todo("c1", "Research", GAIA_TRACKED_LABEL),
                    _todo("c2", "Groceries"),
                ]
            ),
        )
        monkeypatch.setattr(
            context.todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    _todo("f1", "Sync", GAIA_TRACKED_LABEL, FAILED_LABEL, BLOCKING_LABEL),
                    _todo("b1", "Reply", GAIA_TRACKED_LABEL, BLOCKING_LABEL),
                    _todo("r1", "Plan", GAIA_TRACKED_LABEL),
                ]
            ),
        )

        work = await context.gather_tracked_work(_USER, datetime.now(UTC))

        assert [d.id for d in work.completed] == ["c1"]
        assert [d.id for d in work.failed] == ["f1"]
        assert [d.id for d in work.blocked] == ["b1"]
        assert [d.id for d in work.running] == ["r1"]
        assert not work.is_empty

    async def test_a_thread_the_user_owes_needs_them_and_one_awaiting_others_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The inbox desk's thread todos are its findings: needs-reply waits on the user."""
        monkeypatch.setattr(
            context.todo_repository, "list_completed_since", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            context.todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    _todo("n1", "Priya · pitch deck", GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL),
                    _todo("a1", "Add Arjun call", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL),
                    _todo("w1", "Dhruv · offer", GAIA_TRACKED_LABEL, WAITING_FOR_REPLY_LABEL),
                ]
            ),
        )

        work = await context.gather_tracked_work(_USER, datetime.now(UTC))

        assert [d.id for d in work.blocked] == ["n1", "a1"]
        assert [d.id for d in work.running] == ["w1"]

    async def test_the_inbox_desk_is_reported_through_its_findings_not_as_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        desk = _todo("d1", "Inbox desk", GAIA_TRACKED_LABEL)
        desk.external_ref = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
        monkeypatch.setattr(
            context.todo_repository, "list_completed_since", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            context.todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    desk,
                    _todo("n1", "Priya · pitch deck", GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL),
                ]
            ),
        )

        work = await context.gather_tracked_work(_USER, datetime.now(UTC))

        assert ([d.id for d in work.blocked], work.running) == (["n1"], [])

    async def test_open_todo_summary_counts_all_and_names_five(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [_todo(f"t{i}", f"Todo {i}") for i in range(7)]
        monkeypatch.setattr(
            context.todo_repository, "list_open_user_todos", AsyncMock(return_value=docs)
        )

        count, titles = await context.user_open_todo_summary(_USER)

        assert count == 7
        assert titles == [f"Todo {i}" for i in range(5)]


class TestLookback:
    @pytest.fixture(autouse=True)
    def no_briefing_workflows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            context.workflow_repository, "find_system_workflows", AsyncMock(return_value=[])
        )

    async def test_first_look_back_with_nothing_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            context.todo_repository, "list_completed_since", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            context.workflow_executions_repository, "list_since", AsyncMock(return_value=[])
        )

        block = await context.format_lookback_block(_USER, None, datetime.now(UTC))

        assert "No prior briefing" in block
        assert "Nothing was completed" in block
        assert "Background workflow runs" not in block

    async def test_yesterdays_plan_is_compared_to_what_finished(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            context.todo_repository,
            "list_completed_since",
            AsyncMock(return_value=[_todo("c1", "Deck", GAIA_TRACKED_LABEL), _todo("c2", "Gym")]),
        )
        monkeypatch.setattr(
            context.workflow_executions_repository,
            "list_since",
            AsyncMock(return_value=[SimpleNamespace(status="success", summary="3 drafts")]),
        )

        block = await context.format_lookback_block(
            _USER, _brief("clear", items=["Finish the deck"]).payload, datetime.now(UTC)
        )

        assert "- Finish the deck" in block
        assert "- GAIA finished: Deck" in block
        assert "- You finished: Gym" in block
        assert "- Workflow [success]: 3 drafts" in block


def _sent_days_ago(brief: BriefingModel, days: int) -> BriefingModel:
    brief.created_at = datetime(2026, 10, 12, 8, tzinfo=UTC) - timedelta(days=days)
    return brief


_WINBACK_USER = UserDocument(id=_USER)


class TestWinback:
    @pytest.fixture
    def briefs(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        listing = AsyncMock(return_value=[])
        monkeypatch.setattr(context.briefing_repository, "list_recent", listing)
        return listing

    @pytest.fixture
    def last_active(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        read = AsyncMock(return_value=None)
        monkeypatch.setattr(context.dormancy, "latest_activity_since", read)
        return read

    async def test_no_briefs_is_not_winback(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        state = await context.compute_winback_state(_WINBACK_USER)

        assert (state.unacknowledged, state.is_winback, state.should_back_off) == (0, False, False)
        last_active.assert_not_awaited()

    async def test_ignored_briefs_up_to_the_threshold_flip_to_winback(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [
            _sent_days_ago(_brief("clear"), d) for d in range(WINBACK_THRESHOLD)
        ] + [_sent_days_ago(_brief("clear", opened=True), WINBACK_THRESHOLD)]

        state = await context.compute_winback_state(_WINBACK_USER)

        assert state.unacknowledged == WINBACK_THRESHOLD
        assert state.is_winback
        assert not state.should_back_off

    async def test_activity_after_a_brief_acknowledges_it(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [
            _sent_days_ago(_brief("clear"), d) for d in range(WINBACK_THRESHOLD + 1)
        ]
        # Active between the second-newest brief and the newest one.
        last_active.return_value = datetime(2026, 10, 11, 9, tzinfo=UTC)

        state = await context.compute_winback_state(_WINBACK_USER)

        assert state.unacknowledged == 1
        assert not state.is_winback

    async def test_last_activity_is_read_once_from_the_oldest_brief(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_sent_days_ago(_brief("clear"), d) for d in range(5)]

        await context.compute_winback_state(_WINBACK_USER)

        last_active.assert_awaited_once_with(_WINBACK_USER, datetime(2026, 10, 8, 8, tzinfo=UTC))

    async def test_a_sent_winback_that_is_still_ignored_backs_off(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        briefs.return_value = [_brief("winback")] + [
            _sent_days_ago(_brief("clear"), d + 1) for d in range(WINBACK_THRESHOLD)
        ]

        state = await context.compute_winback_state(_WINBACK_USER)

        assert state.should_back_off

    async def test_naive_created_at_is_read_as_utc(
        self, briefs: AsyncMock, last_active: AsyncMock
    ) -> None:
        brief = _brief("clear")
        brief.created_at = datetime(2026, 10, 12, 8)
        briefs.return_value = [brief]
        last_active.return_value = datetime(2026, 10, 12, 8, tzinfo=UTC)

        state = await context.compute_winback_state(_WINBACK_USER)

        assert last_active.await_args.args[1] == datetime(2026, 10, 12, 8, tzinfo=UTC)
        assert state.unacknowledged == 0


def _clock(iso: str = "2026-10-14T07:00:00", tz: str = "Asia/Kolkata") -> context.UserClock:
    zone = ZoneInfo(tz)
    now = datetime.fromisoformat(iso).replace(tzinfo=zone)
    return context.UserClock(
        tz=zone, now_local=now, date_str=now.date().isoformat(), day_of_year=now.timetuple().tm_yday
    )


def _event(
    summary: str, start: dict[str, str], location: str | None = None
) -> GoogleCalendarEventResource:
    data: dict[str, object] = {"summary": summary, "start": start}
    if location:
        data["location"] = location
    return GoogleCalendarEventResource.model_validate(data)


class TestCalendar:
    @pytest.fixture
    def connected(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        ids = AsyncMock(return_value={"googlecalendar"})
        monkeypatch.setattr(context, "get_connected_integration_ids", ids)
        return ids

    async def test_no_calendar_connected_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        connected.return_value = {"gmail"}
        fetch = AsyncMock()
        monkeypatch.setattr(context, "get_calendar_events", fetch)

        assert await context.gather_calendar(_USER, _clock(), days=1) == []
        fetch.assert_not_awaited()

    async def test_events_land_on_the_users_clock_in_start_order(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        fetch = AsyncMock(
            return_value=SimpleNamespace(
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
        monkeypatch.setattr(context, "get_calendar_events", fetch)

        events = await context.gather_calendar(_USER, _clock(), days=1)

        assert [(e.date, e.start, e.title, e.location) for e in events] == [
            ("2026-10-14", None, "Offsite", None),
            ("2026-10-14", "09:00", "Standup", None),
            ("2026-10-14", "11:00", "Sequoia partner meeting", "Menlo Park"),
        ]
        window = fetch.await_args.kwargs
        assert window["time_min"] == "2026-10-13T18:30:00+00:00"
        assert window["time_max"] == "2026-10-14T18:30:00+00:00"

    async def test_a_calendar_failure_fails_the_read(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        monkeypatch.setattr(
            context, "get_calendar_events", AsyncMock(side_effect=RuntimeError("proxy down"))
        )

        with pytest.raises(RuntimeError, match="proxy down"):
            await context.gather_calendar(_USER, _clock(), days=1)


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
        completed = context.CompletedWork(
            gaia=[
                done("Memo", "2026-10-18T09:00", GAIA_TRACKED_LABEL),
                done("Deck", "2026-10-12T10:00", GAIA_TRACKED_LABEL),
            ],
            user=[done("Gym", "2026-10-12T23:30")],
        )
        monkeypatch.setattr(context, "gather_calendar", AsyncMock(return_value=[]))
        clock = _clock("2026-10-18T17:00:00")

        week = await context.gather_week(_USER, clock, completed)

        assert [(d.you, d.gaia) for d in week.days] == [
            (1, 1),
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 1),
        ]
        assert week.shipped == ["Gym"]
        assert week.handled == ["Deck", "Memo"]
        assert context.week_start_utc(clock) == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)


class TestClockIsTheUsers:
    def test_the_clock_reads_now_on_the_users_zone(self) -> None:
        clock = context.resolve_clock("Pacific/Kiritimati")

        assert clock.now_local.tzinfo == ZoneInfo("Pacific/Kiritimati")
        assert clock.date_str == clock.now_local.date().isoformat()
        assert clock.day_of_year == clock.now_local.timetuple().tm_yday

    def test_day_start_is_expressed_in_utc(self) -> None:
        assert context.day_start_utc(_clock()).tzinfo is UTC


class TestGoalBlockEdges:
    @pytest.fixture
    def recall(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        recall = AsyncMock(return_value=SimpleNamespace(memories=[]))
        monkeypatch.setattr(context, "memory_engine", SimpleNamespace(recall=recall))
        monkeypatch.setattr(context, "entry_to_note", str)
        return recall

    def test_a_missing_focus_is_not_a_goal(self) -> None:
        assert context.has_meaningful_focus(None) is False

    async def test_no_onboarding_and_no_memories_asks_for_goal_discovery(
        self, recall: AsyncMock
    ) -> None:
        assert await context.format_goal_block(_USER, UserDocument()) == (
            "No stated goal on record yet — treat goal discovery as part of today's job.",
            False,
        )

    async def test_memory_is_asked_what_the_user_is_working_on(self, recall: AsyncMock) -> None:
        await context.format_goal_block(_USER, UserDocument())

        recall.assert_awaited_once_with(
            _USER, "what is the user currently working on and their goals", limit=5
        )

    async def test_a_blank_memory_is_not_a_goal(self, recall: AsyncMock) -> None:
        recall.return_value = SimpleNamespace(memories=["   ", "Hiring a designer"])

        block, has_goal = await context.format_goal_block(_USER, UserDocument())

        assert (block, has_goal) == ("- Hiring a designer", True)


class TestReadsAreScopedToTheUser:
    async def test_tracked_work_reads_this_users_completions_and_open_todos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = AsyncMock(return_value=[])
        active = AsyncMock(return_value=[])
        monkeypatch.setattr(context.todo_repository, "list_completed_since", completed)
        monkeypatch.setattr(context.todo_repository, "list_active_tracked", active)
        since = datetime(2026, 10, 13, tzinfo=UTC)

        work = await context.gather_tracked_work(_USER, since)

        assert work.is_empty
        completed.assert_awaited_once_with(_USER, since=since)
        active.assert_awaited_once_with(_USER, limit=20)

    async def test_completed_work_reads_this_users_completions_since_the_cutoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completed = AsyncMock(return_value=[])
        monkeypatch.setattr(context.todo_repository, "list_completed_since", completed)
        since = datetime(2026, 10, 13, tzinfo=UTC)

        await context.gather_completed_since(_USER, since)

        completed.assert_awaited_once_with(_USER, since=since)

    async def test_the_open_todo_summary_reads_up_to_50_and_names_untitled_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        untitled = _todo("t2", "x")
        untitled.title = ""
        listing = AsyncMock(return_value=[_todo("t1", "Pay rent"), untitled])
        monkeypatch.setattr(context.todo_repository, "list_open_user_todos", listing)

        assert await context.user_open_todo_summary(_USER) == (2, ["Pay rent", "untitled"])
        listing.assert_awaited_once_with(_USER, limit=50)


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
        monkeypatch.setattr(context.todo_repository, "list_completed_since", reads.completed)
        monkeypatch.setattr(context.workflow_executions_repository, "list_since", reads.executions)
        monkeypatch.setattr(
            context.workflow_repository, "find_system_workflows", reads.briefing_workflows
        )
        return reads

    async def test_the_whole_block_reads_plan_then_done_then_runs(
        self, reads: SimpleNamespace
    ) -> None:
        reads.completed.return_value = [
            _todo("c1", "Deck", GAIA_TRACKED_LABEL),
            _untitled("c2", GAIA_TRACKED_LABEL),
            _todo("c3", "Gym"),
            _untitled("c4"),
        ]
        reads.executions.return_value = [
            _execution("success", "3 drafts"),
            _execution("failed", None),
        ]
        since = datetime(2026, 10, 13, tzinfo=UTC)
        yesterday = _brief("clear", items=["Finish the deck", "Book flights"]).payload

        block = await context.format_lookback_block(_USER, yesterday, since)

        assert block == (
            "Yesterday you told the user you'd focus on:\n"
            "- Finish the deck\n"
            "- Book flights\n\n"
            "Actually completed since then:\n"
            "- GAIA finished: Deck\n"
            "- GAIA finished: untitled\n"
            "- You finished: Gym\n"
            "- You finished: untitled\n\n"
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
        block = await context.format_lookback_block(_USER, None, datetime.now(UTC))

        assert block == (
            "No prior briefing — this is the first look-back.\n\n"
            "Nothing was completed since the last briefing."
        )

    async def test_only_the_users_own_completions_still_count_as_done(
        self, reads: SimpleNamespace
    ) -> None:
        reads.completed.return_value = [_todo("c1", "Gym")]

        block = await context.format_lookback_block(_USER, None, datetime.now(UTC))

        assert block.endswith("Actually completed since then:\n- You finished: Gym")


class TestWinbackReads:
    async def test_the_last_ten_daily_briefs_are_read_and_each_ack_checked_for_this_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listing = AsyncMock(return_value=[_brief("clear")])
        signal = AsyncMock(return_value=None)
        monkeypatch.setattr(context.briefing_repository, "list_recent", listing)
        monkeypatch.setattr(context.dormancy, "latest_activity_since", signal)

        await context.compute_winback_state(_WINBACK_USER)

        listing.assert_awaited_once_with(_USER, limit=10, kind=BRIEFING_KIND_DAILY)
        assert signal.await_args.args[0] is _WINBACK_USER

    async def test_no_briefs_means_no_winback_went_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(context.briefing_repository, "list_recent", AsyncMock(return_value=[]))

        state = await context.compute_winback_state(_WINBACK_USER)

        assert state.last_was_winback is False


class TestCalendarEdges:
    @pytest.fixture
    def connected(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        ids = AsyncMock(return_value={"googlecalendar"})
        monkeypatch.setattr(context, "get_connected_integration_ids", ids)
        return ids

    async def test_untitled_and_all_day_events_keep_their_place(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        untitled = GoogleCalendarEventResource.model_validate(
            {"start": {"dateTime": "2026-10-14T03:30:00Z"}}
        )
        fetch = AsyncMock(
            return_value=SimpleNamespace(
                events=[untitled, _event("   ", {"date": "2026-10-14"}, "Goa")]
            )
        )
        monkeypatch.setattr(context, "get_calendar_events", fetch)

        events = await context.gather_calendar(_USER, _clock(), days=1)

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
        fetch = AsyncMock(return_value=SimpleNamespace(events=[]))
        monkeypatch.setattr(context, "get_calendar_events", fetch)

        await context.gather_calendar(_USER, _clock(), days=7, days_ahead=1)

        window = fetch.await_args.kwargs
        assert window["time_min"] == "2026-10-14T18:30:00+00:00"
        assert window["time_max"] == "2026-10-21T18:30:00+00:00"


def _done(title: str, completed_at: datetime | None, *labels: str) -> TodoDocument:
    doc = _todo(title, title, *labels)
    doc.completed_at = completed_at
    return doc


def _by_owner(docs: list[TodoDocument]) -> context.CompletedWork:
    """Split completions the way gather_completed_since does, keeping their order."""
    return context.CompletedWork(
        gaia=[d for d in docs if context.is_gaia_tracked(d)],
        user=[d for d in docs if not context.is_gaia_tracked(d)],
    )


class TestWeekEdges:
    @pytest.fixture
    def ahead(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        calendar = AsyncMock(return_value=[])
        monkeypatch.setattr(context, "gather_calendar", calendar)
        return calendar

    async def test_each_completion_counts_on_its_local_day_and_odd_rows_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch, ahead: AsyncMock
    ) -> None:
        tz = ZoneInfo("Pacific/Kiritimati")
        # Newest first: the walk is oldest first, so the skipped rows come first.
        completed = _by_owner(
            [
                _done("Memo", datetime(2026, 10, 13, 2, tzinfo=tz), GAIA_TRACKED_LABEL),
                _done("Brief", datetime(2026, 10, 12, 23, tzinfo=tz), GAIA_TRACKED_LABEL),
                _done("Gym", datetime(2026, 10, 12, 20, tzinfo=tz)),
                _done("Run", datetime(2026, 10, 12, 10)),
                _done("Next week", datetime(2026, 10, 19, 1, tzinfo=tz)),
                _done("Never", None),
            ]
        )
        clock = _clock("2026-10-14T12:00:00", "Pacific/Kiritimati")

        # Mongo's naive "Run" is UTC whatever zone the server itself runs in.
        with local_timezone("Asia/Kolkata"):
            week = await context.gather_week(_USER, clock, completed)

        assert [(d.you, d.gaia) for d in week.days][:2] == [(1, 1), (1, 1)]
        assert week.shipped == ["Run", "Gym"]
        assert week.handled == ["Brief", "Memo"]
        assert context.week_start_utc(clock).tzinfo is UTC

    async def test_two_on_one_day_count_twice(
        self, monkeypatch: pytest.MonkeyPatch, ahead: AsyncMock
    ) -> None:
        at = datetime(2026, 10, 12, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
        docs = [
            _done("a", at),
            _done("b", at),
            _done("c", at, GAIA_TRACKED_LABEL),
            _done("d", at, GAIA_TRACKED_LABEL),
        ]
        week = await context.gather_week(_USER, _clock(), _by_owner(docs))

        assert (week.days[0].you, week.days[0].gaia) == (2, 2)

    async def test_the_week_ahead_is_the_next_seven_days_capped(
        self, monkeypatch: pytest.MonkeyPatch, ahead: AsyncMock
    ) -> None:
        events = [
            BriefingEvent(date="2026-10-15", title=f"E{i}") for i in range(WEEK_LIST_LIMIT + 1)
        ]
        ahead.return_value = events
        clock = _clock()

        week = await context.gather_week(_USER, clock, context.CompletedWork())

        assert week.ahead == events[:WEEK_LIST_LIMIT]
        ahead.assert_awaited_once_with(_USER, clock, days=7, days_ahead=1)
