"""Each owner's oldest approval its conversation log still has pending; a log with none pending has none."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.conversation_log_models import ConversationState, LiveWork
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.pending import pending_approvals

from .conftest import CONVERSATION_ID, USER_ID

MODULE = "app.services.hil.pending"
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _work(task_id: str, *approvals: str) -> LiveWork:
    return LiveWork(
        task_id=task_id, cause_through=1, answers=(), pending_approvals=tuple(approvals)
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
