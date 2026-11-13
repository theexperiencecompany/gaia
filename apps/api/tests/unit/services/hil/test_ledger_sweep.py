"""The clock's part in ledger approvals: one reminder before an ask lapses, expiry when it does."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.services.hil.ledger_decide import LedgerDecision
from app.services.hil.ledger_sweep import sweep_ledger_approvals
from app.services.outbox.models import NoticeOutcome, NoticeReport

MODULE = "app.services.hil.ledger_sweep"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _row(approval_id: str, **overrides: object) -> ApprovalLedgerDocument:
    fields: dict[str, object] = {
        "approval_id": approval_id,
        "conversation_id": "conv-1",
        "user_id": USER_ID,
        "fingerprint": f"fp-{approval_id}",
        "tool_name": "send_email",
        "summary": f"Send the deck ({approval_id})",
        "expires_at": NOW + timedelta(hours=6),
        **overrides,
    }
    return ApprovalLedgerDocument.model_validate(fields)


def _decision(approval_id: str, *, committed: bool = True) -> LedgerDecision:
    return LedgerDecision(
        committed=committed,
        approval_id=approval_id,
        prior_state=LedgerState.PENDING,
        state=LedgerState.EXPIRED if committed else LedgerState.APPROVED,
    )


@pytest.fixture
def world():
    with (
        patch(f"{MODULE}.clock.now", return_value=NOW),
        patch(f"{MODULE}.approval_ledger_repository") as repo,
        patch(f"{MODULE}.decide_ledger", new=AsyncMock()) as decide,
        patch(f"{MODULE}.submit", new=AsyncMock()) as submit,
    ):
        repo.list_pending_expired = AsyncMock(return_value=[])
        repo.list_pending_reminders_due = AsyncMock(return_value=[])
        repo.mark_reminded = AsyncMock(return_value=True)
        yield {"repo": repo, "decide": decide, "submit": submit}


@pytest.mark.unit
class TestExpiry:
    async def test_a_lapsed_ask_is_expired_through_the_decision_path(self, world) -> None:
        world["repo"].list_pending_expired.return_value = [_row("ap_1")]
        world["decide"].return_value = _decision("ap_1")

        counts = await sweep_ledger_approvals()

        world["decide"].assert_awaited_once_with(
            "ap_1", user_id=USER_ID, kind="expire", via="expiry"
        )
        assert counts == {"expired": 1, "reminded": 0}

    async def test_an_ask_answered_first_is_not_counted_as_expired(self, world) -> None:
        world["repo"].list_pending_expired.return_value = [_row("ap_1")]
        world["decide"].return_value = _decision("ap_1", committed=False)

        assert (await sweep_ledger_approvals())["expired"] == 0

    async def test_one_ask_that_cannot_expire_does_not_strand_the_rest(self, world) -> None:
        world["repo"].list_pending_expired.return_value = [_row("ap_bad"), _row("ap_ok")]
        world["decide"].side_effect = [RuntimeError("mongo down"), _decision("ap_ok")]

        counts = await sweep_ledger_approvals()

        assert counts["expired"] == 1
        assert world["decide"].await_count == 2


@pytest.mark.unit
class TestReminder:
    async def test_a_due_reminder_is_filed_once_as_a_reminder_notice(self, world) -> None:
        world["repo"].list_pending_reminders_due.return_value = [_row("ap_1")]

        counts = await sweep_ledger_approvals()

        report = world["submit"].await_args.args[0]
        assert isinstance(report, NoticeReport)
        assert report.report_id == "hil:ap_1:reminder"
        assert report.outcome is NoticeOutcome.NEEDS_YOU
        assert report.valid_until == NOW + timedelta(hours=6)
        world["repo"].mark_reminded.assert_awaited_once_with("ap_1")
        assert counts["reminded"] == 1

    async def test_a_reminder_the_outbox_refused_is_not_marked_sent_so_the_next_sweep_retries(
        self, world
    ) -> None:
        world["repo"].list_pending_reminders_due.return_value = [_row("ap_1")]
        world["submit"].side_effect = RuntimeError("redis down")

        counts = await sweep_ledger_approvals()

        world["repo"].mark_reminded.assert_not_awaited()
        assert counts["reminded"] == 0
