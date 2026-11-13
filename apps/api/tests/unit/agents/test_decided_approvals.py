"""A run's report carries what became of the approvals it asked for, read from the stores that hold the decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background.decided_approvals import decided_approvals_of
from app.agents.core.background.session import ExecutorRun, RunKind
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.hil_models import ApprovalLedgerDocument, HILApprovalStatus, LedgerState
from app.models.user_models import AuthenticatedUser
from app.services.outbox.models import ApprovalOutcome, DecidedApproval

MODULE = "app.agents.core.background.decided_approvals"
USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011")


def _run(bot_message_id: str | None = "bot-1") -> ExecutorRun:
    return ExecutorRun(
        stream_id="stream-1",
        conversation_id="conv-1",
        user=USER,
        kind=RunKind.QUEUED,
        task_id="task-1",
        user_message_id=None,
        bot_message_id=bot_message_id,
    )


def _card(approval_id: str) -> dict[str, object]:
    return {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": {"approval_id": approval_id}}


def _ledger(approval_id: str, state: LedgerState) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id="conv-1",
        user_id=USER.user_id,
        fingerprint=f"fp-{approval_id}",
        tool_name="GMAIL_SEND_EMAIL",
        summary=f"Send the deck ({approval_id})",
        state=state,
    )


@pytest.fixture
def stores():
    ledger: dict[str, ApprovalLedgerDocument] = {}
    barrier: dict[str, SimpleNamespace] = {}
    message = SimpleNamespace(tool_data=[])

    async def get_ledger(approval_id: str) -> ApprovalLedgerDocument | None:
        return ledger.get(approval_id)

    async def get_barrier(approval_id: str) -> SimpleNamespace | None:
        return barrier.get(approval_id)

    with (
        patch(f"{MODULE}.approval_ledger_repository.get_by_approval_id", new=get_ledger),
        patch(f"{MODULE}.get_approval", new=get_barrier),
        patch(f"{MODULE}.conversation_repository.get_message", new=AsyncMock(return_value=message)),
    ):
        yield {"ledger": ledger, "barrier": barrier, "message": message}


class TestDecidedApprovalsOfARun:
    async def test_each_settled_approval_is_told_by_what_it_was_and_how_it_ended(
        self, stores
    ) -> None:
        stores["message"].tool_data = [_card("ap_1"), _card("ap_2"), _card("ap_3")]
        stores["ledger"].update(
            {
                "ap_1": _ledger("ap_1", LedgerState.EXECUTED),
                "ap_2": _ledger("ap_2", LedgerState.DENIED),
                "ap_3": _ledger("ap_3", LedgerState.EXPIRED),
            }
        )

        decided = await decided_approvals_of(_run())

        assert decided == [
            DecidedApproval(summary="Send the deck (ap_1)", outcome=ApprovalOutcome.APPROVED),
            DecidedApproval(summary="Send the deck (ap_2)", outcome=ApprovalOutcome.DENIED),
            DecidedApproval(summary="Send the deck (ap_3)", outcome=ApprovalOutcome.EXPIRED),
        ]

    async def test_an_approval_still_waiting_is_not_a_decision(self, stores) -> None:
        stores["message"].tool_data = [_card("ap_1")]
        stores["ledger"]["ap_1"] = _ledger("ap_1", LedgerState.PENDING)

        assert await decided_approvals_of(_run()) == []

    async def test_a_parked_runs_timeout_reads_as_expired(self, stores) -> None:
        stores["message"].tool_data = [_card("ap_1")]
        stores["barrier"]["ap_1"] = SimpleNamespace(
            summary="Post the update", status=HILApprovalStatus.TIMEOUT
        )

        decided = await decided_approvals_of(_run())

        assert decided == [
            DecidedApproval(summary="Post the update", outcome=ApprovalOutcome.EXPIRED)
        ]

    async def test_the_tool_behind_an_approval_is_never_named(self, stores) -> None:
        stores["message"].tool_data = [_card("ap_1")]
        stores["ledger"]["ap_1"] = _ledger("ap_1", LedgerState.DENIED)

        decided = await decided_approvals_of(_run())

        assert "GMAIL_SEND_EMAIL" not in decided[0].model_dump_json()

    async def test_a_run_with_no_reply_message_has_no_decisions(self, stores) -> None:
        assert await decided_approvals_of(_run(bot_message_id=None)) == []

    async def test_other_cards_are_not_approvals(self, stores) -> None:
        stores["message"].tool_data = [{"tool_name": "web_search", "data": {}}]

        assert await decided_approvals_of(_run()) == []
