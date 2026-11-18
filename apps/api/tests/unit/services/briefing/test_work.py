"""What GAIA is working on and what got done: the user's tracked work, and their week counted.

The todo and workflow repositories are the faked seams.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_todo, make_user_id
from tests.helpers import local_timezone, user_clock

from app.constants.briefing import WEEK_LIST_LIMIT
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
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_payload_models import BriefingEvent
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.services.briefing.work import (
    CompletedWork,
    Finish,
    OpenSubjects,
    TrackedWork,
    count_week,
    is_gaia_tracked,
    read_work,
)

USER_ID = make_user_id()
CLOCK = user_clock("Asia/Kolkata", date(2026, 10, 14), 7)


@pytest.fixture(autouse=True)
def nothing_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read read_work makes answers empty unless a test says otherwise."""
    for name in ("list_completed_since", "list_active_tracked", "list_open_user_todos"):
        monkeypatch.setattr(todo_repository, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(workflow_repository, "find_system_workflows", AsyncMock(return_value=[]))


async def _tracked(since: datetime) -> TrackedWork:
    return (await read_work(USER_ID, since)).tracked_work(since)


def _by_owner(docs: list[TodoDocument]) -> CompletedWork:
    """Credit each completion to GAIA when tracked, else to the user, keeping their order."""
    return CompletedWork(
        [Finish(d, TodoCompleter.GAIA if is_gaia_tracked(d) else TodoCompleter.USER) for d in docs]
    )


class TestReadWork:
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
        completed.assert_awaited_once_with(USER_ID, since=since)
        active.assert_awaited_once_with(USER_ID, limit=0)

    async def test_open_todos_are_sorted_by_state_and_only_gaia_completions_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        since = datetime.now(UTC)
        at_cutoff: dict[str, Any] = {"completed": True, "completed_at": since}
        monkeypatch.setattr(
            todo_repository,
            "list_completed_since",
            AsyncMock(
                return_value=[
                    make_todo("Research", GAIA_TRACKED_LABEL, id="c1", **at_cutoff),
                    make_todo("Groceries", id="c2", **at_cutoff),
                    make_todo(
                        "Book flights",
                        GAIA_TRACKED_LABEL,
                        id="c3",
                        completed_by=TodoCompleter.USER,
                        **at_cutoff,
                    ),
                ]
            ),
        )
        monkeypatch.setattr(
            todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    make_todo("Sync", GAIA_TRACKED_LABEL, FAILED_LABEL, BLOCKING_LABEL, id="f1"),
                    make_todo("Reply", GAIA_TRACKED_LABEL, BLOCKING_LABEL, id="b1"),
                    make_todo("Plan", GAIA_TRACKED_LABEL, id="r1"),
                ]
            ),
        )

        work = await _tracked(since)

        assert [d.id for d in work.completed] == ["c1"]
        assert [d.id for d in work.failed] == ["f1"]
        assert [d.id for d in work.blocked] == ["b1"]
        assert [d.id for d in work.running] == ["r1"]
        assert not work.is_empty

    async def test_a_thread_the_user_owes_needs_them_and_one_awaiting_others_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The inbox desk's thread todos are its findings: needs-reply and action-needed wait on the user."""
        monkeypatch.setattr(
            todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    make_todo("Priya · pitch deck", GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL, id="n1"),
                    make_todo(
                        "Add Arjun call", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL, id="a1"
                    ),
                    make_todo(
                        "Kotak · card declined", GAIA_TRACKED_LABEL, ACTION_NEEDED_LABEL, id="k1"
                    ),
                    make_todo(
                        "Dhruv · offer", GAIA_TRACKED_LABEL, WAITING_FOR_REPLY_LABEL, id="w1"
                    ),
                ]
            ),
        )

        work = await _tracked(datetime.now(UTC))

        assert [d.id for d in work.blocked] == ["n1", "a1", "k1"]
        assert [d.id for d in work.running] == ["w1"]

    async def test_the_inbox_desk_is_reported_through_its_findings_not_as_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        desk = make_todo(
            "Inbox desk",
            GAIA_TRACKED_LABEL,
            external_ref=ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail"),
        )
        monkeypatch.setattr(
            todo_repository,
            "list_active_tracked",
            AsyncMock(
                return_value=[
                    desk,
                    make_todo("Priya · pitch deck", GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL, id="n1"),
                ]
            ),
        )

        work = await _tracked(datetime.now(UTC))

        assert ([d.id for d in work.blocked], work.running) == (["n1"], [])

    async def test_the_open_totals_count_past_the_read_limit_each_subject_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: 35 running todos were voiced as 20, the read's limit."""
        running = [make_todo(f"Research {i}", GAIA_TRACKED_LABEL) for i in range(35)]
        waiting = [
            make_todo("Approve the MSA", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL, id="w1"),
            make_todo("Approve the MSA", GAIA_TRACKED_LABEL, WAITING_FOR_APPROVAL_LABEL, id="w2"),
        ]
        monkeypatch.setattr(
            todo_repository, "list_active_tracked", AsyncMock(return_value=[*running, *waiting])
        )

        work = await _tracked(datetime(2026, 10, 13, tzinfo=UTC))

        assert len(work.running) == 20
        assert work.open_subjects == OpenSubjects(running=35, blocked=1, failed=0)


class TestCountWeek:
    def test_the_week_is_counted_monday_to_sunday_by_owner(self) -> None:
        tz = ZoneInfo("Asia/Kolkata")

        def done(title: str, local: str, *labels: str) -> TodoDocument:
            at = datetime.fromisoformat(local).replace(tzinfo=tz).astimezone(UTC)
            return make_todo(title, *labels, completed_at=at)

        # Newest completion first, as list_completed_since returns them.
        completed = _by_owner(
            [
                done("Memo", "2026-10-18T09:00", GAIA_TRACKED_LABEL),
                done("Deck", "2026-10-12T10:00", GAIA_TRACKED_LABEL),
                done("Gym", "2026-10-12T23:30"),
            ]
        )
        clock = user_clock("Asia/Kolkata", date(2026, 10, 18), 17)

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

    def test_each_completion_counts_on_its_local_day_and_odd_rows_are_skipped(self) -> None:
        tz = ZoneInfo("Pacific/Kiritimati")
        # Each skipped row comes before a counted one, so a skip that stopped the walk shows.
        closed = make_todo("Closed by an event", completed_at=datetime(2026, 10, 12, 9, tzinfo=tz))
        counted = _by_owner(
            [
                make_todo("Next week", completed_at=datetime(2026, 10, 19, 1, tzinfo=tz)),
                make_todo(
                    "Memo", GAIA_TRACKED_LABEL, completed_at=datetime(2026, 10, 13, 2, tzinfo=tz)
                ),
                make_todo("Never"),
                make_todo(
                    "Brief", GAIA_TRACKED_LABEL, completed_at=datetime(2026, 10, 12, 23, tzinfo=tz)
                ),
                make_todo("Gym", completed_at=datetime(2026, 10, 12, 20, tzinfo=tz)),
                make_todo("Run", completed_at=datetime(2026, 10, 12, 10)),
            ]
        )
        completed = CompletedWork([Finish(closed, TodoCompleter.TRIGGER), *counted.finished])
        clock = user_clock("Pacific/Kiritimati", date(2026, 10, 14), 12)

        # Mongo's naive "Run" is UTC whatever zone the server itself runs in.
        with local_timezone("Asia/Kolkata"):
            week = count_week(clock, completed, [])

        assert [(d.you, d.gaia) for d in week.days][:2] == [(1, 1), (1, 1)]
        assert clock.this_week().start.tzinfo is UTC

    def test_two_on_one_day_count_twice(self) -> None:
        at = datetime(2026, 10, 12, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
        docs = [
            make_todo("a", completed_at=at),
            make_todo("b", completed_at=at),
            make_todo("c", GAIA_TRACKED_LABEL, completed_at=at),
            make_todo("d", GAIA_TRACKED_LABEL, completed_at=at),
        ]
        week = count_week(CLOCK, _by_owner(docs), [])

        assert (week.days[0].you, week.days[0].gaia) == (2, 2)

    def test_the_week_ahead_is_the_next_seven_days_capped(self) -> None:
        events = [
            BriefingEvent(date="2026-10-15", title=f"E{i}") for i in range(WEEK_LIST_LIMIT + 1)
        ]
        week = count_week(CLOCK, CompletedWork(), events)

        assert week.ahead == events[:WEEK_LIST_LIMIT]
