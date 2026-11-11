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
