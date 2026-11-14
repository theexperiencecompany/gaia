"""Each owner's oldest approval its conversation log still has pending; a log with none pending has none."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import time_machine

from app.constants.conversation import APPROVAL_EXPIRY_GRACE
from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.models.conversation_log_models import ConversationState, LiveWork
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.pending import pending_approvals, pending_approvals_by_owner

from .conftest import CONVERSATION_ID, USER_ID

MODULE = "app.services.hil.pending"
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _work(task_id: str, *approvals: str) -> LiveWork:
    return LiveWork(
        task_id=task_id, cause_through=1, answers=(), pending_approvals=frozenset(approvals)
    )


def _state(*work: LiveWork) -> ConversationState:
    return ConversationState.model_construct(work=work)


def _row(
    approval_id: str,
    created_at: datetime | None,
    *,
    conversation_id: str = CONVERSATION_ID,
    owner_id: str = "",
) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=conversation_id,
        user_id=USER_ID,
        fingerprint=f"fp-{approval_id}",
        tool_name="GMAIL_SEND_EMAIL",
        created_at=created_at,
        owner_run_type="todo" if owner_id else "",
        owner_id=owner_id,
    )


@dataclass
class Seams:
    state: AsyncMock
    ledger: MagicMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    ports = MagicMock()
    ports.log.state = AsyncMock()
    ledger = MagicMock()
    with (
        patch(f"{MODULE}.runtime_ports", return_value=ports),
        patch(f"{MODULE}.approval_ledger_repository", new=ledger),
    ):
        yield Seams(state=ports.log.state, ledger=ledger)


class TestPendingApprovals:
    async def test_a_conversation_with_nothing_logged_pending_has_none(self, seams: Seams) -> None:
        seams.state.return_value = _state(_work("t1"))
        seams.ledger.get_by_approval_id = AsyncMock()

        assert await pending_approvals(CONVERSATION_ID, USER_ID) == []
        seams.ledger.get_by_approval_id.assert_not_awaited()


class TestPendingApprovalsByOwner:
    @time_machine.travel(NOW, tick=False)
    async def test_each_owner_gets_its_oldest_approval_still_pending_in_its_log(
        self, seams: Seams
    ) -> None:
        older = _row("ap_1", NOW - timedelta(minutes=9), owner_id="todo-1")
        newer = _row("ap_2", NOW - timedelta(minutes=1), owner_id="todo-1")
        decided = _row("ap_3", NOW, conversation_id="conv-2", owner_id="todo-2")
        seams.ledger.list_by_owners = AsyncMock(return_value=[older, newer, decided])
        logs = {
            (CONVERSATION_ID, USER_ID): _state(_work("t1", "ap_1", "ap_2")),
            ("conv-2", USER_ID): _state(_work("t2", "ap_other")),
        }

        async def _log_state(conversation_id: str, user_id: str) -> ConversationState:
            return logs[(conversation_id, user_id)]

        seams.state.side_effect = _log_state

        oldest = await pending_approvals_by_owner("todo", ["todo-1", "todo-2"])

        assert oldest == {"todo-1": older}
        seams.ledger.list_by_owners.assert_awaited_once_with(
            "todo",
            ["todo-1", "todo-2"],
            created_since=NOW
            - (timedelta(seconds=HIL_APPROVAL_TIMEOUT_SECONDS) + APPROVAL_EXPIRY_GRACE),
        )
        assert sorted(call.args for call in seams.state.await_args_list) == [
            ("conv-1", USER_ID),
            ("conv-2", USER_ID),
        ]
