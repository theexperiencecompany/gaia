"""Gathering every producer into one pool: one item per outside thing, whichever sources found it.

Faked seams: the repository reads the reading producers make.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.constants.briefing import BriefAction
from app.constants.todos import GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL, WaitingOn
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.signal_memory import signal_memory_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.briefing_models import BriefingEvent
from app.models.scout_models import (
    RememberedSignal,
    ScoutOutcome,
    ScoutResult,
    Sighting,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.services.briefing.candidates import pool as candidates_pool
from app.services.briefing.candidates.pool import (
    CandidateSources,
    GatheredCandidates,
    _one_per_thing,
    gather_candidates,
)
from app.services.briefing.context import TrackedWork, UserClock
from app.services.briefing.scouts.service import ScoutSignals

USER_ID = make_user_id()
NOW = datetime(2026, 11, 11, 2, 30, tzinfo=UTC)
TZ = ZoneInfo("Asia/Kolkata")
CLOCK = UserClock(tz=TZ, now_local=NOW.astimezone(TZ), date_str="2026-11-11", day_of_year=315)


@pytest.fixture(autouse=True)
def memory(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Signal memory as Mongo holds it: nothing seen before unless a test says so."""
    seams = {"find_for": AsyncMock(return_value=[]), "record_seen": AsyncMock()}
    for name, mock in seams.items():
        monkeypatch.setattr(signal_memory_repository, name, mock)
    return seams


@pytest.fixture(autouse=True)
def quiet_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    for owner, name in (
        (approval_ledger_repository, "list_pending_for_user"),
        (hil_approval_repository, "list_pending_for_user"),
        (reminder_repository, "find_scheduled_between"),
        (workflow_executions_repository, "list_since"),
        (workflow_repository, "find_system_workflows"),
    ):
        monkeypatch.setattr(owner, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(
        todo_repository, "find_latest_by_external_ref", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(todo_repository, "list_open_user_todos", AsyncMock(return_value=[]))
    monkeypatch.setattr(todo_repository, "list_undated_user_todos", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        candidates_pool, "get_connected_integration_ids", AsyncMock(return_value=[])
    )


def _thread_todo(thread_id: str, title: str) -> TodoDocument:
    return TodoDocument(
        id=f"todo-{thread_id}",
        user_id=USER_ID,
        title=title,
        description="Maya asked for sign-off on the revised preference",
        labels=[GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL],
        external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=thread_id),
    )


def _gmail_signal(external_id: str, title: str) -> RememberedSignal:
    return RememberedSignal(
        signal=Signal(
            integration_id="gmail",
            app="Gmail",
            external_id=external_id,
            kind="email waiting on your reply",
            title=title,
            people=["Maya Chen"],
            importance=SignalImportance.HIGH,
            url="https://mail.google.com/mail/u/0/#inbox/t-maya",
            text="Can you confirm the preference by Friday? Our partners meet Monday.",
        )
    )


def _scouts(*remembered: RememberedSignal) -> ScoutSignals:
    return ScoutSignals(
        results=[ScoutResult(integration_id="gmail", app="Gmail", outcome=ScoutOutcome.REPLAYED)],
        remembered=list(remembered),
        criteria={},
    )


async def _gathered(work: TrackedWork, scouts: ScoutSignals) -> GatheredCandidates:
    return await gather_candidates(USER_ID, CLOCK, NOW, NOW, CandidateSources(work, scouts, []))


def _found(
    title: str,
    *,
    detail: str | None = None,
    due_at: datetime | None = None,
    todo_id: str | None = None,
    held_id: str | None = None,
) -> BriefCandidate:
    return BriefCandidate(
        source="gmail",
        app="Gmail",
        state="you",
        title=title,
        ref="gmail:t1",
        detail=detail,
        due_at=due_at,
        todo_id=todo_id,
        held_id=held_id,
    )


class TestFoldingTwoFindsOfOneThing:
    def test_what_only_the_second_find_knew_is_kept(self) -> None:
        first = _found("Reply to Maya")
        again = _found(
            "Re: term sheet",
            detail="needs sign-off",
            due_at=NOW,
            todo_id="todo-1",
            held_id="held-1",
        )

        [merged] = _one_per_thing([first, again])

        assert (merged.title, merged.detail, merged.due_at, merged.todo_id, merged.held_id) == (
            "Reply to Maya",
            "needs sign-off",
            NOW,
            "todo-1",
            "held-1",
        )

    def test_what_the_first_find_knew_wins_over_the_second(self) -> None:
        first = _found(
            "Reply to Maya", detail="first", due_at=NOW, todo_id="todo-1", held_id="held-1"
        )
        again = _found(
            "Re: term sheet",
            detail="second",
            due_at=datetime(2026, 11, 20, tzinfo=UTC),
            todo_id="todo-2",
            held_id="held-2",
        )

        [merged] = _one_per_thing([first, again])

        assert (merged.detail, merged.due_at, merged.todo_id, merged.held_id) == (
            "first",
            NOW,
            "todo-1",
            "held-1",
        )

    def test_a_repeat_does_not_end_the_folding_of_what_follows(self) -> None:
        other = BriefCandidate(source="gmail", app="Gmail", state="you", title="Offsite")

        kept = _one_per_thing([_found("a"), _found("b"), other])

        assert [c.title for c in kept] == ["a", "Offsite"]


class TestTheCalendarJoinsThePool:
    async def test_todays_events_are_timed_in_the_users_own_clock(self) -> None:
        events = [BriefingEvent(date="2026-11-11", start="15:00", title="Board call")]
        sources = CandidateSources(TrackedWork(), _scouts(), events)

        gathered = await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)

        [event] = gathered.pool.values()
        assert (event.title, event.is_event, event.time) == ("Board call", True, "3:00 PM")


class TestOwnTodosJoinThePool:
    async def test_the_users_own_todos_due_by_their_next_local_midnight_wait_on_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        own = TodoDocument(id="own-1", user_id=USER_ID, title="File the VAT return", due_date=NOW)
        listing = AsyncMock(return_value=[own])
        monkeypatch.setattr(todo_repository, "list_open_user_todos", listing)

        gathered = await _gathered(TrackedWork(), _scouts())

        [item] = gathered.pool.values()
        assert (item.title, item.todo_id, item.state, item.action) == (
            "File the VAT return",
            "own-1",
            "you",
            BriefAction.ATTEND,
        )
        assert listing.await_args.kwargs["due_before"] == datetime(2026, 11, 11, 18, 30, tzinfo=UTC)

    async def test_an_undated_own_todo_is_offered_with_no_due_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        undated = TodoDocument(id="own-2", user_id=USER_ID, title="Sort the garage")
        monkeypatch.setattr(
            todo_repository, "list_undated_user_todos", AsyncMock(return_value=[undated])
        )

        gathered = await _gathered(TrackedWork(), _scouts())

        [item] = gathered.pool.values()
        assert (item.todo_id, item.due_at, item.state, item.action) == (
            "own-2",
            None,
            "you",
            BriefAction.ATTEND,
        )


def _tracked(todo_id: str, title: str, label: str) -> TodoDocument:
    return TodoDocument(
        id=todo_id, user_id=USER_ID, title=title, labels=[GAIA_TRACKED_LABEL, label]
    )


def _shown(external_id: str, state: str, times: int) -> SignalMemoryDocument:
    return SignalMemoryDocument(
        user_id=USER_ID,
        integration_id="gaia",
        external_id=external_id,
        first_seen=datetime(2026, 11, 8, 2, 30, tzinfo=UTC),
        times_shown=times,
        last_shown=datetime(2026, 11, 10, 2, 30, tzinfo=UTC),
        last_state=state,
    )


class TestWhatEarlierBriefsShowedIsNotNews:
    """Regression: the same stale approval and overdue todo came back every day as news."""

    async def test_a_thing_shown_before_as_it_stands_is_a_repeat_and_no_news(
        self, memory: dict[str, AsyncMock]
    ) -> None:
        approve = _tracked("t1", "Approve the MSA", NEEDS_REPLY_LABEL)
        memory["find_for"].return_value = [_shown("todo:t1", "you", times=2)]

        gathered = await _gathered(TrackedWork(blocked=[approve]), _scouts())

        (candidate,) = gathered.pool.values()
        assert candidate.is_repeat
        assert not gathered.has_news
        memory["find_for"].assert_awaited_once_with(USER_ID, [Sighting("gaia", "todo:t1", "you")])
        memory["record_seen"].assert_awaited_once_with(
            USER_ID, [Sighting("gaia", "todo:t1", "you")], NOW
        )

    async def test_a_thing_that_moved_since_is_news_again(
        self, memory: dict[str, AsyncMock]
    ) -> None:
        memory["find_for"].return_value = [_shown("todo:t1", "gaia", times=3)]

        gathered = await _gathered(
            TrackedWork(blocked=[_tracked("t1", "Approve", NEEDS_REPLY_LABEL)]), _scouts()
        )

        (candidate,) = gathered.pool.values()
        assert candidate.moved and not candidate.is_repeat
        assert gathered.has_news

    async def test_an_undated_own_todo_alone_is_no_news(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            todo_repository,
            "list_undated_user_todos",
            AsyncMock(return_value=[TodoDocument(id="u1", user_id=USER_ID, title="Plan Q1")]),
        )

        gathered = await _gathered(TrackedWork(), _scouts())

        (candidate,) = gathered.pool.values()
        assert candidate.backlog
        assert not gathered.has_news


class TestWhereGaiaCanAct:
    async def test_gaia_acts_in_its_own_work_its_connected_built_ins_and_apps_it_can_write_to(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connected = AsyncMock(return_value=["gmail", "notion"])
        monkeypatch.setattr(candidates_pool, "get_connected_integration_ids", connected)
        notion = _gmail_signal("n-1", "Roadmap page shared").signal.model_copy(
            update={"integration_id": "notion", "app": "Notion"}
        )
        linear = _gmail_signal("l-1", "Fix the login redirect").signal.model_copy(
            update={"integration_id": "linear", "app": "Linear"}
        )
        scouts = ScoutSignals(
            results=[
                ScoutResult(integration_id="notion", app="Notion", outcome=ScoutOutcome.REPLAYED),
                ScoutResult(
                    integration_id="linear",
                    app="Linear",
                    outcome=ScoutOutcome.REPLAYED,
                    can_write=True,
                ),
            ],
            remembered=[RememberedSignal(signal=notion), RememberedSignal(signal=linear)],
            criteria={},
        )
        work = TrackedWork(
            blocked=[
                _thread_todo("t-maya", "Reply to Maya on the term sheet"),
                _tracked("t1", "Approve the MSA", NEEDS_REPLY_LABEL),
            ]
        )
        events = [BriefingEvent(date="2026-11-11", start="15:00", title="Board call")]

        gathered = await gather_candidates(
            USER_ID, CLOCK, NOW, NOW, CandidateSources(work, scouts, events)
        )

        assert [(c.source, c.gaia_acts) for c in gathered.pool.values()] == [
            ("gmail", True),
            ("gaia", True),
            ("notion", False),
            ("linear", True),
            ("googlecalendar", False),
        ]
        connected.assert_awaited_once_with(USER_ID)


class TestGaiasOpenWorkJoinsThePool:
    async def test_when_gaia_looks_again_is_said_on_the_users_own_day(self) -> None:
        later = TodoDocument(
            id="r1",
            user_id=USER_ID,
            title="Chase the venue",
            labels=[GAIA_TRACKED_LABEL],
            waiting_on=WaitingOn.TIME,
            scheduled_at=datetime(2026, 11, 11, 20, 0, tzinfo=UTC),
        )

        gathered = await _gathered(TrackedWork(running=[later]), _scouts())

        [item] = gathered.pool.values()
        assert item.standing == "GAIA looks at it again Thu Nov 12"


class TestOneItemPerThing:
    async def test_a_tracked_thread_and_the_scouts_signal_on_it_are_one_item_noting_both(
        self,
    ) -> None:
        """Live brief: Maya's term sheet was placed twice, once from GAIA's tracking, once from Gmail."""
        work = TrackedWork(blocked=[_thread_todo("t-maya", "Reply to Maya on the term sheet")])
        scouts = _scouts(_gmail_signal("t-maya", "Re: Series A term sheet"))

        gathered = await _gathered(work, scouts)

        [item] = gathered.pool.values()
        assert (item.title, item.todo_id, item.action) == (
            "Reply to Maya on the term sheet",
            "todo-t-maya",
            BriefAction.REPLY,
        )
        assert item.signal is not None and item.signal.external_id == "t-maya"
        assert (item.people, item.importance, item.url) == (
            ["Maya Chen"],
            SignalImportance.HIGH,
            "https://mail.google.com/mail/u/0/#inbox/t-maya",
        )
        assert item.also_in == ["the Gmail scout"]

    async def test_things_with_different_ids_stay_apart(self) -> None:
        work = TrackedWork(blocked=[_thread_todo("t-maya", "Reply to Maya on the term sheet")])
        scouts = _scouts(_gmail_signal("t-priya", "Offsite venues"))

        gathered = await _gathered(work, scouts)

        assert [c.title for c in gathered.pool.values()] == [
            "Reply to Maya on the term sheet",
            "Offsite venues",
        ]
        assert all(c.also_in == [] for c in gathered.pool.values())

    async def test_the_same_id_in_another_app_is_another_thing(self) -> None:
        work = TrackedWork(blocked=[_thread_todo("42", "Reply to Maya on the term sheet")])
        slack = _gmail_signal("42", "Standup notes")
        slack.signal = slack.signal.model_copy(update={"integration_id": "slack", "app": "Slack"})

        gathered = await _gathered(work, _scouts(slack))

        assert len(gathered.pool) == 2
