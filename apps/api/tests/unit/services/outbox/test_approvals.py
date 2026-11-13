"""An approval ask is facts for compose to word; whether it is still worth telling is read from the stores."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.hil_models import (
    ApprovalLedgerDocument,
    HILApprovalRecord,
    HILApprovalStatus,
    LedgerState,
)
from app.services.outbox.approvals import (
    ApprovalNoticeState,
    approval_id_of_report,
    is_approval_open,
    ledger_approval_notice,
)
from app.services.outbox.models import Initiative, NoticeOutcome, SubjectKind

MODULE = "app.services.outbox.approvals"
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _row(**overrides: object) -> ApprovalLedgerDocument:
    fields: dict[str, object] = {
        "approval_id": "ap_1",
        "conversation_id": "conv-1",
        "user_id": "6812f0b3c9a14e2b7d5a91cc",
        "fingerprint": "fp",
        "tool_name": "send_email",
        "summary": "Send the deck to Bob",
        "expires_at": NOW + timedelta(hours=24),
        **overrides,
    }
    return ApprovalLedgerDocument.model_validate(fields)


class TestApprovalNotice:
    def test_the_ask_is_a_needs_you_notice_on_its_own_subject_valid_until_it_lapses(self) -> None:
        report = ledger_approval_notice(_row(), ApprovalNoticeState.PENDING, now=NOW)

        assert report.outcome is NoticeOutcome.NEEDS_YOU
        assert report.report_id == "hil:ap_1:pending"
        assert (report.subject.kind, report.subject.id) == (SubjectKind.APPROVAL, "approval:ap_1")
        assert report.subject.owner_conversation_id == "conv-1"
        assert report.valid_until == NOW + timedelta(hours=24)
        assert "Send the deck to Bob" in report.facts[0]
        assert report.prerendered is None

    def test_a_reminder_is_a_second_report_that_says_they_were_already_asked(self) -> None:
        pending = ledger_approval_notice(_row(), ApprovalNoticeState.PENDING, now=NOW)
        reminder = ledger_approval_notice(_row(), ApprovalNoticeState.REMINDER, now=NOW)

        assert reminder.report_id != pending.report_id
        assert reminder.subject == pending.subject
        assert any("already asked" in fact for fact in reminder.facts)
        assert not any("already asked" in fact for fact in pending.facts)

    def test_an_ask_from_work_the_user_scheduled_is_an_answer_to_their_own_wish(self) -> None:
        asked = ledger_approval_notice(_row(), ApprovalNoticeState.PENDING, now=NOW)
        scheduled = ledger_approval_notice(
            _row(owner_run_type="workflow", owner_id="wf-1"), ApprovalNoticeState.PENDING, now=NOW
        )

        assert asked.initiative is Initiative.ASKED
        assert scheduled.initiative is Initiative.USER_SCHEDULED

    def test_an_ask_with_no_deadline_states_none(self) -> None:
        report = ledger_approval_notice(_row(expires_at=None), ApprovalNoticeState.PENDING, now=NOW)

        assert report.valid_until is None
        assert not any("lapses" in fact for fact in report.facts)


class TestApprovalIdOfReport:
    @pytest.mark.parametrize("state", list(ApprovalNoticeState))
    def test_the_id_comes_back_out_of_each_notice(self, state: ApprovalNoticeState) -> None:
        report = ledger_approval_notice(_row(approval_id="ap_9"), state, now=NOW)

        assert approval_id_of_report(report.report_id) == "ap_9"

    @pytest.mark.parametrize(
        "report_id", ["ask:t1:s1", "hil:ap_1", "hil::pending", "hil:ap_1:gone"]
    )
    def test_anything_else_names_no_approval(self, report_id: str) -> None:
        assert approval_id_of_report(report_id) is None


class TestIsApprovalOpen:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (LedgerState.PENDING, True),
            (LedgerState.APPROVED, False),
            (LedgerState.DENIED, False),
            (LedgerState.EXPIRED, False),
            (LedgerState.REVOKED, False),
        ],
    )
    async def test_only_a_pending_ledger_row_can_still_be_answered(
        self, state: LedgerState, expected: bool
    ) -> None:
        with patch(
            f"{MODULE}.approval_ledger_repository.get_by_approval_id",
            new=AsyncMock(return_value=_row(state=state)),
        ):
            assert await is_approval_open("ap_1") is expected

    async def test_a_parked_runs_approval_is_read_from_its_own_store(self) -> None:
        record = HILApprovalRecord(
            approval_id="ap_1",
            user_id="u",
            conversation_id="c",
            stream_id="s",
            tool_name="t",
            status=HILApprovalStatus.DENIED,
            expires_at=NOW,
        )
        with (
            patch(
                f"{MODULE}.approval_ledger_repository.get_by_approval_id",
                new=AsyncMock(return_value=None),
            ),
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
        ):
            assert await is_approval_open("ap_1") is False

    async def test_an_approval_nobody_holds_is_not_open(self) -> None:
        with (
            patch(
                f"{MODULE}.approval_ledger_repository.get_by_approval_id",
                new=AsyncMock(return_value=None),
            ),
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)),
        ):
            assert await is_approval_open("ap_gone") is False
