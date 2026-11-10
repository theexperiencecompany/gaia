"""Each source of the daily brief turned into candidates, against the documents its store holds.

Faked seams: the repository reads each reading producer makes.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id

from app.constants.briefing import BriefItemSource
from app.constants.todos import (
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    NEEDS_REPLY_LABEL,
    WAITING_FOR_APPROVAL_LABEL,
)
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import CandidateKind
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import BriefingEvent
from app.models.hil_models import ApprovalLedgerDocument, HILApprovalRecord
from app.models.reminder_models import AgentType, ReminderDocument
from app.models.scout_models import (
    RememberedSignal,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from app.services.briefing.candidates.app_signals import app_signal_candidates
from app.services.briefing.candidates.approvals import approval_candidates
from app.services.briefing.candidates.calendar import calendar_candidates
from app.services.briefing.candidates.failed_runs import failed_run_candidates
from app.services.briefing.candidates.held import held_candidates
from app.services.briefing.candidates.reminders import reminder_candidates
from app.services.briefing.candidates.tracked import (
    gaia_work_candidates,
    user_done_candidates,
    waiting_candidates,
)
from app.services.briefing.context import TrackedWork

USER_ID = make_user_id()
NOW = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)
DESK_ID = "desk-1"


def _todo(todo_id: str, title: str, *labels: str, **fields: Any) -> TodoDocument:
    return TodoDocument(
        id=todo_id, user_id=USER_ID, title=title, labels=[GAIA_TRACKED_LABEL, *labels], **fields
    )


class TestTrackedTodos:
    def test_what_waits_on_the_user_comes_first_then_what_failed(self) -> None:
        work = TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply", WAITING_FOR_APPROVAL_LABEL)],
            failed=[_todo("f1", "Book the Lisbon flights", FAILED_LABEL)],
        )

        found = waiting_candidates(work)

        assert [(c.title, c.kind, c.state, c.todo_id, c.app) for c in found] == [
            ("Approve the Priya reply", CandidateKind.NEEDS_YOU, "you", "b1", "GAIA"),
            ("Book the Lisbon flights", CandidateKind.NEEDS_YOU, "failed", "f1", "GAIA"),
        ]

    def test_an_inbox_desk_thread_is_a_gmail_item_and_one_subject_counts_its_todos(self) -> None:
        thread = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f")
        work = TrackedWork(
            blocked=[
                _todo("t1", "Reply to Dan about the lease", NEEDS_REPLY_LABEL, external_ref=thread),
                _todo("t2", "Reply to Dan again", NEEDS_REPLY_LABEL, external_ref=thread),
            ]
        )

        [found] = waiting_candidates(work)

        assert (found.app, found.source, found.count, found.todo_id) == ("Gmail", "gmail", 2, "t1")

    def test_gaias_finished_work_then_its_running_work(self) -> None:
        work = TrackedWork(
            completed=[_todo("c1", "Investor update")], running=[_todo("r1", "Vet the Q4 leads")]
        )

        found = gaia_work_candidates(work)

        assert [(c.title, c.kind, c.state) for c in found] == [
            ("Investor update", CandidateKind.GAIA_DID, "lookback"),
            ("Vet the Q4 leads", CandidateKind.GAIA_DID, "gaia"),
        ]

    def test_what_the_user_finished_is_an_update_one_per_subject(self) -> None:
        done = [
            _todo("u1", "Send the deck to Priya"),
            _todo("u2", "send the  deck to priya"),
            _todo("u3", "File the VAT return"),
        ]

        found = user_done_candidates(done)

        assert [(c.title, c.kind, c.state, c.todo_id, c.count) for c in found] == [
            ("Send the deck to Priya", CandidateKind.UPDATE, "lookback", "u1", 2),
            ("File the VAT return", CandidateKind.UPDATE, "lookback", "u3", 1),
        ]


def _held(
    item_id: str, source: BriefItemSource, source_id: str, title: str, text: str
) -> PendingBriefItemDocument:
    return PendingBriefItemDocument(
        id=item_id,
        user_id=USER_ID,
        source=source,
        source_id=source_id,
        source_title=title,
        conversation_id=f"conv-{item_id}",
        text=text,
    )


class TestHeldResults:
    async def test_the_desks_findings_are_gmail_updates_and_the_rest_gaias_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        desk = _todo(DESK_ID, "Inbox desk")
        find_desk = AsyncMock(return_value=desk)
        monkeypatch.setattr(todo_repository, "find_latest_by_external_ref", find_desk)
        held = [
            _held(
                "h1", BriefItemSource.TODO, DESK_ID, "Inbox desk", "Stripe payout of $2,400 landed"
            ),
            _held(
                "h2",
                BriefItemSource.WORKFLOW,
                "wf-1",
                "Research digest",
                "3 new papers on retrieval\nThe longest is 40 pages.",
            ),
        ]

        found = await held_candidates(USER_ID, held)

        assert [(c.app, c.kind, c.title, c.held_id) for c in found] == [
            ("Gmail", CandidateKind.UPDATE, "Stripe payout of $2,400 landed", "h1"),
            ("GAIA", CandidateKind.GAIA_DID, "Research digest: 3 new papers on retrieval", "h2"),
        ]
        assert found[1].detail is None
        assert find_desk.await_args.args[0] == USER_ID

    async def test_with_nothing_held_nothing_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        find_desk = AsyncMock()
        monkeypatch.setattr(todo_repository, "find_latest_by_external_ref", find_desk)

        assert await held_candidates(USER_ID, []) == []
        find_desk.assert_not_awaited()


class TestAppSignals:
    def test_a_signal_carries_its_app_people_link_and_what_briefs_remember(self) -> None:
        signal = Signal(
            integration_id="linear",
            app="Linear",
            external_id="ENG-42",
            kind="issue assigned to you",
            title="Fix the login redirect",
            why="due tomorrow",
            importance=SignalImportance.HIGH,
            due_at=NOW + timedelta(days=1),
            people=["Priya"],
            url="https://linear.app/acme/issue/ENG-42",
            state="In Progress",
        )
        memory = SignalMemoryDocument(
            user_id=USER_ID,
            integration_id="linear",
            external_id="ENG-42",
            first_seen=NOW - timedelta(days=2),
            times_shown=1,
            last_shown=NOW - timedelta(days=1),
            last_state="Todo",
        )

        [found] = app_signal_candidates(
            [RememberedSignal(signal=signal, memory=memory, previous_state="Todo")], NOW
        )

        assert (found.app, found.source, found.kind, found.importance) == (
            "Linear",
            "linear",
            CandidateKind.NEEDS_YOU,
            SignalImportance.HIGH,
        )
        assert (found.url, found.people, found.signal) == (signal.url, ["Priya"], signal)
        assert found.detail == (
            "issue assigned to you | state: In Progress | why: due tomorrow | first seen "
            "2 days ago, mentioned 1 time(s), last yesterday, moved from Todo to In Progress"
        )


class TestCalendar:
    def test_an_event_is_only_ever_an_event_timed_on_the_users_clock(self) -> None:
        events = [
            BriefingEvent(date="2026-11-10", start="11:00", title="Sequoia", location="Zoom"),
            BriefingEvent(date="2026-11-10", title="Diwali"),
        ]

        found = calendar_candidates(events)

        assert [(c.app, c.kind, c.title, c.detail) for c in found] == [
            ("Google Calendar", CandidateKind.EVENT, "Sequoia", "at 11:00 | Zoom"),
            ("Google Calendar", CandidateKind.EVENT, "Diwali", "all day"),
        ]


def _ledger(approval_id: str, **fields: Any) -> ApprovalLedgerDocument:
    defaults: dict[str, Any] = {
        "approval_id": approval_id,
        "conversation_id": "conv-1",
        "user_id": USER_ID,
        "fingerprint": f"fp-{approval_id}",
        "tool_name": "GMAIL_SEND_EMAIL",
        "summary": "Send the invoice to Acme",
    }
    return ApprovalLedgerDocument(**{**defaults, **fields})


class TestApprovals:
    async def test_both_stores_pending_approvals_wait_on_the_user_except_a_todos_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ledger = AsyncMock(
            return_value=[
                _ledger("ap_1"),
                _ledger(
                    "ap_2", summary="Post the launch tweet", owner_run_type="todo", owner_id="b1"
                ),
                _ledger("ap_3", tool_name="create_reminder", summary=""),
            ]
        )
        gate = AsyncMock(
            return_value=[
                HILApprovalRecord(
                    approval_id="appr-1",
                    user_id=USER_ID,
                    conversation_id="conv-2",
                    stream_id="s-1",
                    tool_name="SLACK_SEND_MESSAGE",
                    summary="Message #launch on Slack",
                    integration_name="Slack",
                    expires_at=NOW + timedelta(minutes=15),
                )
            ]
        )
        monkeypatch.setattr(approval_ledger_repository, "list_pending_for_user", ledger)
        monkeypatch.setattr(hil_approval_repository, "list_pending_for_user", gate)

        found = await approval_candidates(USER_ID, NOW, {"b1"})

        assert [(c.app, c.title, c.kind, c.state) for c in found] == [
            ("Gmail", "Send the invoice to Acme", CandidateKind.NEEDS_YOU, "you"),
            ("GAIA", "Approve create_reminder", CandidateKind.NEEDS_YOU, "you"),
            ("Slack", "Message #launch on Slack", CandidateKind.NEEDS_YOU, "you"),
        ]
        assert ledger.await_args.args == (USER_ID,)
        assert gate.await_args.args == (USER_ID, NOW)


class TestReminders:
    async def test_todays_reminders_are_read_for_the_users_local_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start, end = NOW - timedelta(hours=2), NOW + timedelta(hours=22)
        due = ReminderDocument(
            id="rem-1",
            user_id=USER_ID,
            agent=AgentType.STATIC,
            payload={"title": "Call the dentist", "body": "Six-month cleaning appointment"},
            scheduled_at=NOW + timedelta(hours=5),
        )
        read = AsyncMock(return_value=[due])
        monkeypatch.setattr(reminder_repository, "find_scheduled_between", read)

        [found] = await reminder_candidates(USER_ID, start, end)

        assert (found.title, found.detail, found.due_at, found.kind) == (
            "Call the dentist",
            "Six-month cleaning appointment",
            due.scheduled_at,
            CandidateKind.NEEDS_YOU,
        )
        assert read.await_args.args == (USER_ID, start, end)


def _run(
    execution_id: str, workflow_id: str, hours_ago: int, error: str
) -> WorkflowExecutionDocument:
    return WorkflowExecutionDocument(
        execution_id=execution_id,
        workflow_id=workflow_id,
        user_id=USER_ID,
        status="failed",
        started_at=NOW - timedelta(hours=hours_ago),
        error_message=error,
    )


def _workflow(workflow_id: str, title: str) -> WorkflowDocument:
    return WorkflowDocument(
        delivery=WorkflowDelivery.NOW,
        id=workflow_id,
        user_id=USER_ID,
        title=title,
        prompt="-",
        steps=[],
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE, enabled=True),
    )


class TestFailedRuns:
    async def test_one_item_per_failed_workflow_naming_its_latest_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        since = NOW - timedelta(days=1)
        runs = [
            _run("e3", "wf-sync", 1, "HubSpot token expired"),
            _run("e2", "wf-digest", 3, "Timed out"),
            _run("e1", "wf-sync", 6, "Rate limited"),
        ]
        list_since = AsyncMock(return_value=runs)
        monkeypatch.setattr(workflow_executions_repository, "list_since", list_since)
        monkeypatch.setattr(
            workflow_repository,
            "find_system_workflows",
            AsyncMock(return_value=[_workflow("wf-brief", "Daily briefing")]),
        )
        monkeypatch.setattr(
            workflow_repository,
            "find_by_ids_for_user",
            AsyncMock(
                return_value=[_workflow("wf-sync", "CRM sync"), _workflow("wf-digest", "Digest")]
            ),
        )

        found = await failed_run_candidates(USER_ID, since)

        assert [(c.title, c.detail, c.state) for c in found] == [
            ("CRM sync failed", "HubSpot token expired", "failed"),
            ("Digest failed", "Timed out", "failed"),
        ]
        assert list_since.await_args.kwargs["status"] == "failed"
        assert list_since.await_args.kwargs["exclude_workflow_ids"] == ["wf-brief"]
        assert list_since.await_args.args == (USER_ID, since)
