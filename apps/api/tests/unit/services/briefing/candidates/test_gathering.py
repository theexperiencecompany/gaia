"""Gathering every producer into one pool: one item per outside thing, whichever sources found it.

Faked seams: the repository reads the reading producers make.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.constants.briefing import BriefAction
from app.constants.todos import GAIA_TRACKED_LABEL, NEEDS_REPLY_LABEL
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import BriefCandidate
from app.models.briefing_models import BriefingEvent
from app.models.scout_models import (
    RememberedSignal,
    ScoutOutcome,
    ScoutResult,
    Signal,
    SignalImportance,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
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
    return await gather_candidates(USER_ID, CLOCK, NOW, NOW, CandidateSources(work, [], scouts, []))


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
        sources = CandidateSources(TrackedWork(), [], _scouts(), events)

        gathered = await gather_candidates(USER_ID, CLOCK, NOW, NOW, sources)

        [event] = gathered.pool.values()
        assert (event.title, event.is_event, event.time) == ("Board call", True, "3:00 PM")


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
