"""Pressing Stop settles the conversation's pending approvals as cancelled, through the real stop path.

The route, the stop service, the work cancel and the ledger settle are production code on
real (fake) Redis keys; only the Mongo-backed stores and the client broadcast are seams.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints.chat import cancel_stream_endpoint
from app.core.stream_manager import stream_manager
from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.services.browser import job_stop

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("fake_redis")]

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
CONVERSATION_ID = "conv-stop"
STREAM_ID = "turn-stream"


class _Ledger:
    """An in-memory approval_ledger: the reads and the CAS transition the stop path uses."""

    def __init__(self, rows: list[ApprovalLedgerDocument]) -> None:
        self.rows = {row.approval_id: row for row in rows}

    async def list_open(self, conversation_id: str) -> list[ApprovalLedgerDocument]:
        return [
            row
            for row in self.rows.values()
            if row.conversation_id == conversation_id
            and row.state in (LedgerState.PENDING, LedgerState.APPROVED)
        ]

    async def get_by_approval_id(self, approval_id: str) -> ApprovalLedgerDocument | None:
        return self.rows.get(approval_id)

    async def transition(
        self, approval_id: str, from_state: LedgerState, to_state: LedgerState, **_: object
    ) -> bool:
        row = self.rows.get(approval_id)
        if row is None or row.state is not from_state:
            return False
        self.rows[approval_id] = row.model_copy(update={"state": to_state, "v": row.v + 1})
        return True


def _pending_row() -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id="ap_pending",
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        fingerprint="fp",
        tool_name="GMAIL_SEND_EMAIL",
        summary="Send an email",
        proposing_run_id="an-earlier-run",
        created_at=datetime(2026, 11, 12, 9, 0, tzinfo=UTC),
    )


@dataclass(frozen=True)
class _Seams:
    ledger: _Ledger
    conversations: MagicMock
    broadcast: AsyncMock


@pytest.fixture
def seams() -> Iterator[_Seams]:
    ledger = _Ledger([_pending_row()])
    conversations = MagicMock()
    conversations.set_message_approval_status = AsyncMock(return_value=True)
    conversations.refresh_live_approval_flag = AsyncMock()
    broadcast = AsyncMock()
    with (
        patch("app.services.hil.ledger_decide.approval_ledger_repository", ledger),
        patch("app.services.hil.bridge.approval_ledger_repository", ledger),
        patch("app.services.hil.ledger_decide.conversation_repository", conversations),
        patch("app.services.hil.bridge.conversation_repository", conversations),
        patch("app.services.hil.ledger_decide.websocket_manager.broadcast_to_user", broadcast),
        patch.object(job_stop, "_abort_if_started", AsyncMock(return_value=True)),
        patch("app.services.hil.ledger_decide.capture"),
        patch("app.services.conversation_stop_service.capture"),
    ):
        yield _Seams(ledger=ledger, conversations=conversations, broadcast=broadcast)


async def test_stop_settles_a_pending_approval_as_cancelled_after_its_run_ended(
    seams: _Seams,
) -> None:
    """The ledger's run ends before its card shows, so Stop must close the card with no run alive."""
    await stream_manager.start_stream(STREAM_ID, CONVERSATION_ID, USER_ID)

    response = await cancel_stream_endpoint(STREAM_ID, user_id=USER_ID)

    assert response.success is True
    assert seams.ledger.rows["ap_pending"].state is LedgerState.CANCELLED
    seams.conversations.set_message_approval_status.assert_awaited_once_with(
        CONVERSATION_ID, user_id=USER_ID, approval_id="ap_pending", status="cancelled"
    )
    messages = [
        call.kwargs.get("message") or call.args[-1] for call in seams.broadcast.await_args_list
    ]
    decided = [m["data"]["status"] for m in messages if m["type"] == "hil_approval_decided"]
    assert decided == ["cancelled"]
