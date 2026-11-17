"""The open approvals a typed reply names: the screen's order, each under the number it was asked with."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.conversation_log_models import ConversationState, Entry, LoggedEntry, Transition
from app.models.conversation_screen_models import WorkItem
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.reducer import reduce, stamped
from app.services.conversation.screen import project_screen
from app.services.hil.errors import ApprovalRequestNotFoundError
from app.services.hil.pending import pending_approvals
from tests.factories import CONVERSATION_ID
from tests.helpers import TEST_FILE_LINKS
from tests.unit.services.conversation.log_helpers import EMPTY, asked, logged, started, user

MODULE = "app.services.hil.pending"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
# Task A starts first; B asks "pay" before A asks "email".
ENTRIES: tuple[Entry, ...] = (
    user("u1"),
    started("w1", "task_a", 1),
    started("w2", "task_b", 1),
    asked("approval:pay", "task_b", "pay"),
    asked("approval:email", "task_a", "email"),
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


def _appended() -> tuple[ConversationState, list[LoggedEntry]]:
    """Append ENTRIES as the log does, each request taking its number; the state after and what was stored."""
    state, stored = EMPTY, []
    for seq, entry in enumerate(ENTRIES, start=1):
        kept = logged(seq, stamped(state, entry))
        result = reduce(state, kept)
        assert isinstance(result, Transition)
        state = result.state
        stored.append(kept)
    return state, stored


@pytest.fixture
def log_state() -> AsyncMock:
    """Serve the conversation log's state read, folded from ENTRIES."""
    state, _ = _appended()
    return AsyncMock(return_value=state)


async def _read_log(conversation_id: str, *, user_id: str, ids: list[str]) -> list[LoggedEntry]:
    _, stored = _appended()
    return (
        [item for item in stored if item.entry.id in ids]
        if (conversation_id, user_id) == ("c1", "u1")
        else []
    )


@pytest.fixture
def ledger(log_state: AsyncMock) -> Iterator[dict[str, ApprovalLedgerDocument]]:
    rows = {approval_id: _row(approval_id) for approval_id in CREATED}
    ports = SimpleNamespace(log=SimpleNamespace(state=log_state))
    with (
        patch(f"{MODULE}.runtime_ports", return_value=ports),
        patch(
            f"{MODULE}.approval_ledger_repository.get_by_approval_id",
            new=AsyncMock(side_effect=rows.get),
        ),
        patch(
            f"{MODULE}.conversation_log_repository.read_log", new=AsyncMock(side_effect=_read_log)
        ),
    ):
        yield rows


def _screen_order() -> list[str]:
    screen = project_screen(
        CONVERSATION_ID,
        [logged(seq, entry) for seq, entry in enumerate(ENTRIES, start=1)],
        TEST_FILE_LINKS,
    )
    return [
        request.approval_id
        for item in screen
        if isinstance(item, WorkItem)
        for request in item.asking
    ]


async def test_pending_approvals_number_in_the_order_the_screen_asks_them(
    ledger: dict[str, ApprovalLedgerDocument], log_state: AsyncMock
) -> None:
    pending = await pending_approvals("c1", "u1")

    assert [item.row.approval_id for item in pending] == _screen_order() == ["email", "pay"]
    log_state.assert_awaited_once_with("c1", "u1")


async def test_each_pending_approval_keeps_the_number_it_was_asked_with(
    ledger: dict[str, ApprovalLedgerDocument],
) -> None:
    """Regression: the reply resolver numbered by screen place, so its "2" was not the prompt's "2"."""
    pending = await pending_approvals("c1", "u1")

    assert [(item.row.approval_id, item.number) for item in pending] == [("email", 2), ("pay", 1)]


async def test_a_pending_approval_without_a_ledger_row_fails_instead_of_shifting_the_numbers(
    ledger: dict[str, ApprovalLedgerDocument],
) -> None:
    del ledger["email"]

    with pytest.raises(ApprovalRequestNotFoundError):
        await pending_approvals("c1", "u1")
