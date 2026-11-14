"""The open approvals a typed reply numbers: the screen's order, and every one of them."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.conversation_log_models import Entry
from app.models.conversation_screen_models import WorkItem
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.screen import project_screen
from app.services.hil.errors import ApprovalRequestNotFoundError
from app.services.hil.pending import pending_approvals
from tests.unit.services.conversation.log_helpers import asked, fold, logged, started, user

MODULE = "app.services.hil.pending"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
# Task A starts first; B asks "pay" before A asks "email".
ENTRIES: tuple[Entry, ...] = (
    user("u1"),
    started("w1", "task_a", 1),
    started("w2", "task_b", 1),
    asked("q1", "task_b", "pay"),
    asked("q2", "task_a", "email"),
)
CREATED = {"pay": NOW, "email": NOW + timedelta(seconds=4)}


def _row(approval_id: str) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id="c1",
        user_id="u1",
        fingerprint=f"fp-{approval_id}",
        tool_name="GMAIL_SEND_EMAIL",
        args={},
        summary=approval_id,
        created_at=CREATED[approval_id],
    )


@pytest.fixture
def ledger() -> Iterator[dict[str, ApprovalLedgerDocument]]:
    rows = {approval_id: _row(approval_id) for approval_id in CREATED}
    state, _ = fold(ENTRIES)
    ports = SimpleNamespace(log=SimpleNamespace(state=AsyncMock(return_value=state)))
    with (
        patch(f"{MODULE}.runtime_ports", return_value=ports),
        patch(
            f"{MODULE}.approval_ledger_repository.get_by_approval_id",
            new=AsyncMock(side_effect=rows.get),
        ),
    ):
        yield rows


def _screen_order() -> list[str]:
    screen = project_screen([logged(seq, entry) for seq, entry in enumerate(ENTRIES, start=1)])
    return [
        request.approval_id
        for item in screen
        if isinstance(item, WorkItem)
        for request in item.asking
    ]


async def test_pending_approvals_number_in_the_order_the_screen_asks_them(
    ledger: dict[str, ApprovalLedgerDocument],
) -> None:
    pending = await pending_approvals("c1", "u1")

    assert [row.approval_id for row in pending] == _screen_order() == ["email", "pay"]


async def test_a_pending_approval_without_a_ledger_row_fails_instead_of_shifting_the_numbers(
    ledger: dict[str, ApprovalLedgerDocument],
) -> None:
    del ledger["email"]

    with pytest.raises(ApprovalRequestNotFoundError):
        await pending_approvals("c1", "u1")
