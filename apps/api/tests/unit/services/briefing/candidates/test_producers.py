"""Each source of the daily brief turned into candidates, against the documents its store holds.

Faked seams: the repository reads each reading producer makes.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from tests.factories import make_user_id

from app.constants.briefing import (
    BRIEFING_RHYTHM_WORKFLOW_KEYS,
    DUE_TODO_CANDIDATES_LIMIT,
    UNDATED_TODO_CANDIDATES_LIMIT,
    BriefAction,
    BriefItemSource,
    BriefOutcome,
)
from app.constants.todos import (
    BLOCKING_LABEL,
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    NEEDS_REPLY_LABEL,
    WAITING_FOR_APPROVAL_LABEL,
    WAITING_FOR_REPLY_LABEL,
    TodoCompleter,
    WaitingOn,
)
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.hil import hil_approval_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_candidate_models import CandidateOrigin, OutsideRef
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import BriefingEvent
from app.models.calendar_models import CalendarResponse
from app.models.hil_models import ApprovalLedgerDocument, HILApprovalRecord
from app.models.reminder_models import AgentType, ReminderDocument
from app.models.scheduler_models import DeactivationReason
from app.models.scout_models import (
    RememberedSignal,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from app.services.briefing.candidates.app_names import integration_name
from app.services.briefing.candidates.app_signals import app_signal_candidates
from app.services.briefing.candidates.approvals import approval_candidates
from app.services.briefing.candidates.calendar import calendar_candidates
from app.services.briefing.candidates.failed_runs import failed_run_candidates
from app.services.briefing.candidates.held import held_candidates
from app.services.briefing.candidates.reminders import reminder_candidates
from app.services.briefing.candidates.tracked import (
    gaia_work_candidates,
    own_todo_candidates,
    user_done_candidates,
    waiting_candidates,
)
from app.services.briefing.clock import UserClock
from app.services.briefing.work import TrackedWork
from app.services.hil.tool_key import MCPToolIdentity, mcp_tool_key
from app.services.todos.inbox_desk import INBOX_DESK_REF

USER_ID = make_user_id()
NOW = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)
CLOCK = UserClock(tz=ZoneInfo("UTC"), now_local=NOW, date_str="2026-11-10", day_of_year=314)
DESK_ID = "desk-1"


def _todo(todo_id: str, title: str, *labels: str, **fields: Any) -> TodoDocument:
    return TodoDocument(
        id=todo_id, user_id=USER_ID, title=title, labels=[GAIA_TRACKED_LABEL, *labels], **fields
    )


class TestTrackedTodos:
    def test_a_todos_due_date_travels_with_its_candidate_and_its_description_never_does(
        self,
    ) -> None:
        """Replay of Dhruv's set: GAIA's own instructions on a todo were voiced to the user."""
        due = NOW + timedelta(days=2)
        rule = "Do not make a payment without explicit approval."
        work = TrackedWork(
            blocked=[_todo("d1", "Pay the invoice", description=rule, due_date=due)],
            running=[_todo("d2", "Draft the memo", description=rule)],
        )

        [waiting] = waiting_candidates(work)
        [running] = gaia_work_candidates(work, CLOCK)

        assert (waiting.detail, waiting.due_at) == (None, due)
        assert (running.detail, running.due_at) == (None, None)

    def test_what_waits_on_the_user_comes_first_then_what_failed(self) -> None:
        work = TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply", WAITING_FOR_APPROVAL_LABEL)],
            failed=[_todo("f1", "Book the Lisbon flights", FAILED_LABEL)],
        )

        found = waiting_candidates(work)

        assert [(c.title, c.state, c.todo_id, c.app, c.action) for c in found] == [
            (
                "Approve the Priya reply",
                "you",
                "b1",
                "GAIA",
                BriefAction.APPROVE,
            ),
            (
                "Book the Lisbon flights",
                "failed",
                "f1",
                "GAIA",
                BriefAction.RETRY,
            ),
        ]
        assert all(c.outcome is None for c in found)

    @pytest.mark.parametrize(
        ("label", "action"),
        [
            (WAITING_FOR_APPROVAL_LABEL, BriefAction.APPROVE),
            (NEEDS_REPLY_LABEL, BriefAction.REPLY),
            (BLOCKING_LABEL, BriefAction.REVIEW),
        ],
    )
    def test_a_waiting_todo_asks_what_its_label_says(self, label: str, action: BriefAction) -> None:
        """Live brief: an approval read as "review", so "To approve" over it was refused."""
        [found] = waiting_candidates(TrackedWork(blocked=[_todo("b1", "Priya's venues", label)]))

        assert found.action is action

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

    def test_only_a_gmail_todo_carries_a_ref_to_its_thread(self) -> None:
        thread = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f")
        desk = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="int-9")
        work = TrackedWork(
            blocked=[
                _todo("t1", "Reply to Dan", external_ref=thread),
                _todo("t2", "Triage the mailbox", external_ref=desk),
                _todo("t3", "Plain todo"),
            ]
        )

        found = waiting_candidates(work)

        assert [(c.todo_id, c.ref) for c in found] == [
            ("t1", OutsideRef(integration_id="gmail", external_id="18c2f")),
            ("t2", None),
            ("t3", None),
        ]

    def test_gaias_finished_work_then_its_running_work(self) -> None:
        work = TrackedWork(
            completed=[
                _todo("c1", "Investor update", completed=True, completed_by=TodoCompleter.GAIA),
                _todo(
                    "c2", "Wait for Sam's yes", completed=True, completed_by=TodoCompleter.TRIGGER
                ),
            ],
            running=[_todo("r1", "Vet the Q4 leads")],
        )

        found = gaia_work_candidates(work, CLOCK)

        assert [(c.title, c.state, c.outcome, c.finished_by) for c in found] == [
            ("Investor update", "lookback", BriefOutcome.FINISHED, TodoCompleter.GAIA),
            ("Wait for Sam's yes", "lookback", BriefOutcome.FINISHED, TodoCompleter.TRIGGER),
            ("Vet the Q4 leads", "gaia", BriefOutcome.STARTED, None),
        ]
        assert all(c.action is None for c in found)

    @pytest.mark.parametrize(
        ("fields", "stands", "outcome"),
        [
            (
                {"labels": [GAIA_TRACKED_LABEL, WAITING_FOR_REPLY_LABEL]},
                "waiting on someone else's reply, not the user's",
                BriefOutcome.STARTED,
            ),
            (
                {"pause_reason": DeactivationReason.INTEGRATION_EXPIRED},
                "paused: its app's connection expired",
                None,
            ),
            (
                {"waiting_on": WaitingOn.UNPLANNED, "scheduled_at": NOW + timedelta(days=2)},
                "captured, not started: GAIA plans it Thu Nov 12",
                None,
            ),
            (
                {"waiting_on": WaitingOn.UNPLANNED},
                "captured, not started: GAIA plans it",
                None,
            ),
            (
                {"waiting_on": WaitingOn.TIME, "scheduled_at": NOW},
                "GAIA looks at it again today",
                BriefOutcome.STARTED,
            ),
            (
                {"waiting_on": WaitingOn.TIME},
                "GAIA looks at it again",
                BriefOutcome.STARTED,
            ),
            (
                {"waiting_on": WaitingOn.EVENT},
                "waiting on an event it watches",
                BriefOutcome.STARTED,
            ),
            (
                {"waiting_on": WaitingOn.SUB_TODOS},
                "its sub-todos are doing the work",
                BriefOutcome.STARTED,
            ),
        ],
    )
    def test_open_work_gaia_is_not_running_says_where_it_stands(
        self, fields: dict[str, Any], stands: str, outcome: BriefOutcome | None
    ) -> None:
        """Audit: work waiting on a reply, paused or never planned read as "in progress | started"."""
        doc = TodoDocument(
            id="r1",
            user_id=USER_ID,
            title="Chase the venue",
            **{"labels": [GAIA_TRACKED_LABEL], **fields},
        )

        [found] = gaia_work_candidates(TrackedWork(running=[doc]), CLOCK)

        assert (found.standing, found.outcome) == (stands, outcome)

    def test_a_question_gaia_asked_waits_on_the_user_as_a_reply(self) -> None:
        asked = _todo(
            "q1",
            "Pick the venue",
            waiting_on=WaitingOn.USER,
            question="Lisbon or Porto?",
            description="Book only after the user picks.",
        )

        [found] = waiting_candidates(TrackedWork(blocked=[asked]))

        assert (found.state, found.action, found.detail) == (
            "you",
            BriefAction.REPLY,
            "Lisbon or Porto?",
        )

    def test_what_the_user_finished_is_an_update_one_per_subject(self) -> None:
        done = [
            _own_todo("u1", "Send the deck to Priya", completed=True),
            _own_todo("u2", "send the  deck to priya", completed=True),
            _own_todo("u3", "File the VAT return", completed=True),
        ]

        found = user_done_candidates(done)

        # Audit: the user's own finished todos read as GAIA's; they are the user's.
        assert {c.finished_by for c in found} == {TodoCompleter.USER}

        assert [(c.title, c.state, c.todo_id, c.count) for c in found] == [
            ("Send the deck to Priya", "lookback", "u1", 2),
            ("File the VAT return", "lookback", "u3", 1),
        ]
        assert {c.outcome for c in found} == {BriefOutcome.FINISHED}


def _own_todo(todo_id: str, title: str, **fields: Any) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=USER_ID, title=title, **fields)


class TestOwnTodos:
    def test_the_users_own_todos_due_by_the_cutoff_are_theirs_to_attend_to_most_overdue_first(
        self,
    ) -> None:
        overdue = NOW - timedelta(days=3)
        open_own = [
            _own_todo("o2", "Renew the passport", due_date=NOW),
            _own_todo("o1", "File the VAT return", description="Q3", due_date=overdue),
            _own_todo("late", "Book the dentist", due_date=NOW + timedelta(days=2)),
        ]

        found = own_todo_candidates(open_own, NOW + timedelta(hours=20), TrackedWork())

        assert [(c.title, c.detail, c.due_at, c.todo_id, c.origin) for c in found] == [
            ("File the VAT return", None, overdue, "o1", CandidateOrigin.OWN_TODO),
            ("Renew the passport", None, NOW, "o2", CandidateOrigin.OWN_TODO),
        ]
        assert {(c.state, c.action, c.app) for c in found} == {("you", BriefAction.ATTEND, "GAIA")}

    def test_a_todo_due_exactly_at_the_cutoff_is_not_the_briefs(self) -> None:
        open_own = [_own_todo("o1", "File the VAT return", due_date=NOW)]

        assert own_todo_candidates(open_own, NOW, TrackedWork()) == []

    def test_a_naive_due_date_is_read_as_utc(self) -> None:
        naive = (NOW - timedelta(minutes=1)).replace(tzinfo=None)
        open_own = [_own_todo("o1", "File the VAT return", due_date=naive)]

        assert [c.todo_id for c in own_todo_candidates(open_own, NOW, TrackedWork())] == ["o1"]

    def test_only_the_most_overdue_are_offered_and_ties_keep_creation_order(self) -> None:
        open_own = [
            _own_todo(f"o{n:02d}", f"Errand {n}", due_date=NOW - timedelta(days=n % 3))
            for n in reversed(range(DUE_TODO_CANDIDATES_LIMIT + 5))
        ]

        found = own_todo_candidates(open_own, NOW + timedelta(hours=1), TrackedWork())

        ordered = sorted(open_own, key=lambda d: (d.due_date, d.id))[:DUE_TODO_CANDIDATES_LIMIT]
        assert [c.todo_id for c in found] == [d.id for d in ordered]

    def test_the_oldest_undated_todos_follow_the_due_ones_as_backlog(self) -> None:
        open_own = [
            _own_todo(f"n{n}", f"Someday {n}", created_at=NOW - timedelta(days=n))
            for n in range(UNDATED_TODO_CANDIDATES_LIMIT + 2)
        ] + [_own_todo("o1", "File the VAT return", due_date=NOW)]

        found = own_todo_candidates(open_own, NOW + timedelta(hours=1), TrackedWork())

        oldest = [f"n{n}" for n in reversed(range(2, UNDATED_TODO_CANDIDATES_LIMIT + 2))]
        assert [(c.todo_id, c.backlog) for c in found] == [
            ("o1", False),
            *((todo_id, True) for todo_id in oldest),
        ]
        assert {(c.state, c.action) for c in found} == {("you", BriefAction.ATTEND)}

    def test_a_todo_already_tracked_by_id_or_subject_is_left_to_its_tracked_candidate(
        self,
    ) -> None:
        open_own = [
            _own_todo("b1", "Approve the Priya reply", due_date=NOW),
            _own_todo("u9", "draft the  MEMO", due_date=NOW),
            _own_todo("u1", "Call the bank", due_date=NOW),
            _own_todo("n9", "Draft the memo"),
            _own_todo("n1", "Sort the garage"),
        ]
        work = TrackedWork(
            blocked=[_todo("b1", "Approve the Priya reply", WAITING_FOR_APPROVAL_LABEL)],
            running=[_todo("r1", "Draft the memo")],
        )

        found = own_todo_candidates(open_own, NOW + timedelta(hours=1), work)

        assert [c.todo_id for c in found] == ["u1", "n1"]

    def test_an_undated_todo_on_a_due_ones_subject_is_counted_into_it(self) -> None:
        open_own = [
            _own_todo("n1", "call the  BANK"),
            _own_todo("o1", "Call the bank", due_date=NOW),
        ]

        found = own_todo_candidates(open_own, NOW + timedelta(hours=1), TrackedWork())

        assert [(c.todo_id, c.count, c.backlog) for c in found] == [("o1", 2, False)]


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

        assert [(c.app, c.title, c.held_id, c.outcome) for c in found] == [
            ("Gmail", "Stripe payout of $2,400 landed", "h1", None),
            (
                "GAIA",
                "Research digest: 3 new papers on retrieval",
                "h2",
                BriefOutcome.FINISHED,
            ),
        ]
        assert found[1].detail is None
        assert find_desk.await_args.args == (USER_ID, INBOX_DESK_REF)

    async def test_a_todo_runs_held_report_is_not_called_finished(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            todo_repository, "find_latest_by_external_ref", AsyncMock(return_value=None)
        )
        held = [
            _held("h1", BriefItemSource.TODO, "t-1", "Book the venue", "Could not reach the venue")
        ]

        (found,) = await held_candidates(USER_ID, held)

        assert (found.title, found.outcome) == ("Book the venue: Could not reach the venue", None)

    async def test_only_a_todo_result_of_the_desk_itself_is_a_gmail_finding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            todo_repository,
            "find_latest_by_external_ref",
            AsyncMock(return_value=_todo(DESK_ID, "Inbox desk")),
        )
        held = [
            _held("h1", BriefItemSource.TODO, "other-todo", "Weekly review", "Wrote the summary"),
            _held("h2", BriefItemSource.WORKFLOW, DESK_ID, "Research digest", "Three new papers"),
        ]

        found = await held_candidates(USER_ID, held)

        assert [(c.app, c.title) for c in found] == [
            ("GAIA", "Weekly review: Wrote the summary"),
            ("GAIA", "Research digest: Three new papers"),
        ]

    async def test_a_result_is_carried_by_its_first_non_blank_line_or_its_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            todo_repository,
            "find_latest_by_external_ref",
            AsyncMock(return_value=_todo(DESK_ID, "Inbox desk")),
        )
        held = [
            _held(
                "h1", BriefItemSource.WORKFLOW, "wf-1", "Research digest", "\n  \n  Papers  \nmore"
            ),
            _held("h2", BriefItemSource.WORKFLOW, "wf-2", "Backup", "  \n "),
            _held("h3", BriefItemSource.TODO, DESK_ID, "Inbox desk", "   "),
        ]

        found = await held_candidates(USER_ID, held)

        assert [c.title for c in found] == ["Research digest: Papers", "Backup", "Inbox desk"]

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
            [RememberedSignal(signal=signal, memory=memory, previous_state="Todo")], CLOCK
        )

        assert (found.app, found.source, found.importance) == (
            "Linear",
            "linear",
            SignalImportance.HIGH,
        )
        assert (found.url, found.people, found.signal) == (signal.url, ["Priya"], signal)
        assert found.due_at == signal.due_at
        assert (found.action, found.outcome) == (None, None)
        assert (found.moved, found.is_repeat) == (True, False)
        assert found.detail == (
            "issue assigned to you | state: In Progress | why: due tomorrow | first seen "
            "2 days ago, mentioned 1 time(s), last yesterday, moved from Todo to In Progress"
        )

    def test_a_signal_shown_before_in_the_same_state_has_not_moved_and_is_a_repeat(self) -> None:
        signal = Signal(
            integration_id="linear",
            app="Linear",
            external_id="ENG-42",
            kind="issue assigned to you",
            title="Fix the login redirect",
            state="Todo",
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

        [found] = app_signal_candidates([RememberedSignal(signal=signal, memory=memory)], CLOCK)

        assert (found.moved, found.is_repeat) == (False, True)


class TestIntegrationName:
    def test_an_id_the_catalog_does_not_hold_names_itself_in_the_error(self) -> None:
        with pytest.raises(KeyError) as raised:
            integration_name("nope")

        assert raised.value.args == ("no integration 'nope' in the catalog",)


class TestCalendar:
    def test_an_event_is_only_ever_an_event_timed_on_the_users_clock(self) -> None:
        events = [
            BriefingEvent(date="2026-11-10", start="11:00", title="Sequoia", location="Zoom"),
            BriefingEvent(date="2026-11-10", title="Diwali"),
            BriefingEvent(date="2026-11-13", start="15:00", title="Pitch to Accel"),
        ]

        found = calendar_candidates(events, "2026-11-10")

        assert [(c.is_event, c.title, c.time, c.detail, c.action) for c in found] == [
            (True, "Sequoia", "11:00 AM", "Zoom", BriefAction.ATTEND),
            (True, "Diwali", None, "all day", BriefAction.ATTEND),
            (True, "Pitch to Accel", "Fri 3:00 PM", None, BriefAction.ATTEND),
        ]
        assert {c.app for c in found} == {"Google Calendar"}

    @pytest.mark.parametrize(
        ("response", "answer"),
        [
            (CalendarResponse.TENTATIVE, "the user answered tentative"),
            (CalendarResponse.NEEDS_ACTION, "the user has not answered the invite"),
        ],
    )
    def test_an_events_line_says_its_end_place_calendar_people_and_the_users_answer(
        self, response: CalendarResponse, answer: str
    ) -> None:
        event = BriefingEvent(
            date="2026-11-10",
            start="11:00",
            end="12:30",
            title="Sequoia",
            location="Zoom",
            calendar="Work",
            organizer="Priya",
            guests=3,
            response=response,
        )

        [found] = calendar_candidates([event], "2026-11-10")

        assert found.detail == (
            "until 12:30 PM | Zoom | on the Work calendar | organized by Priya"
            f" | 3 other(s) invited | {answer}"
        )


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

        assert [(c.app, c.title, c.state) for c in found] == [
            ("Gmail", "Send the invoice to Acme", "you"),
            ("GAIA", "Approve create_reminder", "you"),
            ("Slack", "Message #launch on Slack", "you"),
        ]
        assert [c.source for c in found] == ["gmail", "gaia", "Slack"]
        assert [str(c.seen_as) for c in found] == [
            "approval:ap_1",
            "approval:ap_3",
            "approval:appr-1",
        ]
        assert {c.action for c in found} == {BriefAction.APPROVE}
        assert {c.detail for c in found} == {"waiting for your approval"}
        assert ledger.await_args.args == (USER_ID,)
        assert gate.await_args.args == (USER_ID, NOW)

    async def test_a_ledger_row_names_the_app_its_mcp_tool_key_points_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row = _ledger(
            "ap_1",
            tool_key=mcp_tool_key(MCPToolIdentity(integration_id="linear", server_name="linear")),
        )
        monkeypatch.setattr(
            approval_ledger_repository, "list_pending_for_user", AsyncMock(return_value=[row])
        )
        monkeypatch.setattr(
            hil_approval_repository, "list_pending_for_user", AsyncMock(return_value=[])
        )

        [found] = await approval_candidates(USER_ID, NOW, set())

        assert (found.source, found.app) == ("linear", "Linear")

    async def test_a_gate_approval_without_an_integration_is_gaias_and_a_blank_summary_names_the_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = HILApprovalRecord(
            approval_id="appr-1",
            user_id=USER_ID,
            conversation_id="conv-2",
            stream_id="s-1",
            tool_name="delete_file",
            expires_at=NOW + timedelta(minutes=15),
        )
        monkeypatch.setattr(
            approval_ledger_repository, "list_pending_for_user", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            hil_approval_repository, "list_pending_for_user", AsyncMock(return_value=[record])
        )

        [found] = await approval_candidates(USER_ID, NOW, set())

        assert (found.source, found.app, found.title) == ("gaia", "GAIA", "Approve delete_file")

    async def test_a_row_owned_by_an_uncovered_todo_still_waits_on_the_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            _ledger("ap_1", owner_run_type="todo", owner_id="b1"),
            _ledger("ap_2", owner_run_type="todo", owner_id="b2"),
        ]
        monkeypatch.setattr(
            approval_ledger_repository, "list_pending_for_user", AsyncMock(return_value=rows)
        )
        monkeypatch.setattr(
            hil_approval_repository, "list_pending_for_user", AsyncMock(return_value=[])
        )

        found = await approval_candidates(USER_ID, NOW, {"b1"})

        assert len(found) == 1


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

        assert (found.title, found.detail, found.due_at, found.action) == (
            "Call the dentist",
            "Six-month cleaning appointment",
            due.scheduled_at,
            BriefAction.ATTEND,
        )
        assert read.await_args.args == (USER_ID, start, end)


def _run(
    execution_id: str, workflow_id: str, hours_ago: int, error: str | None = None
) -> WorkflowExecutionDocument:
    """Return a run that failed with error, or succeeded without one."""
    return WorkflowExecutionDocument(
        execution_id=execution_id,
        workflow_id=workflow_id,
        user_id=USER_ID,
        status="success" if error is None else "failed",
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
    async def test_a_workflow_that_ran_fine_after_failing_reads_as_recovered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runs = [
            _run("e4", "wf-sync", 1),
            _run("e3", "wf-sync", 2, "Rate limited"),
            _run("e2", "wf-sync", 3, "Rate limited"),
            _run("e1", "wf-sync", 4, "Rate limited"),
        ]
        monkeypatch.setattr(
            workflow_executions_repository, "list_since", AsyncMock(return_value=runs)
        )
        monkeypatch.setattr(
            workflow_repository, "find_system_workflows", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            workflow_repository,
            "find_by_ids_for_user",
            AsyncMock(return_value=[_workflow("wf-sync", "CRM sync")]),
        )

        (found,) = await failed_run_candidates(USER_ID, NOW - timedelta(days=1))

        assert (found.title, found.detail, found.state, found.action) == (
            "CRM sync recovered",
            "failed 3 time(s) since the last brief, then its latest run succeeded",
            "note",
            None,
        )

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
        find_system = AsyncMock(return_value=[_workflow("wf-brief", "Daily briefing")])
        find_titles = AsyncMock(
            return_value=[_workflow("wf-sync", "CRM sync"), _workflow("wf-digest", "Digest")]
        )
        monkeypatch.setattr(workflow_repository, "find_system_workflows", find_system)
        monkeypatch.setattr(workflow_repository, "find_by_ids_for_user", find_titles)

        found = await failed_run_candidates(USER_ID, since)

        assert [(c.title, c.detail, c.state, c.action) for c in found] == [
            (
                "CRM sync failed",
                "HubSpot token expired | failed 2 time(s) since the last brief",
                "failed",
                BriefAction.RETRY,
            ),
            (
                "Digest failed",
                "Timed out | failed 1 time(s) since the last brief",
                "failed",
                BriefAction.RETRY,
            ),
        ]
        assert list_since.await_args.kwargs == {"exclude_workflow_ids": ["wf-brief"], "limit": 200}
        assert list_since.await_args.args == (USER_ID, since)
        assert find_system.await_args.args == (USER_ID, BRIEFING_RHYTHM_WORKFLOW_KEYS)
        assert find_titles.await_args.args == (["wf-sync", "wf-digest"], USER_ID)
