"""Unit tests for hil/notify (approval-pending wake channels).

Both channels are best-effort by contract: a failure inside any channel must
never propagate into the HIL gate.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.hil.notify import notify_approval_pending

_MOD = "app.services.hil.notify"
USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"
APPROVAL_ID = "appr-1"
SUMMARY = "Send the deck to bob"


@pytest.fixture
def mock_channels():
    with (
        patch(f"{_MOD}.websocket_manager") as m_ws,
        patch(f"{_MOD}.push_approval_pending", new_callable=AsyncMock) as m_push,
    ):
        m_ws.broadcast_to_user = AsyncMock()
        yield SimpleNamespace(ws=m_ws, push=m_push)


class TestNotifyApprovalPending:
    async def test_fires_both_channels(self, mock_channels):
        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_channels.ws.broadcast_to_user.assert_awaited_once_with(
            user_id=USER_ID,
            message={
                "type": "hil_approval_pending",
                "data": {
                    "conversation_id": CONVERSATION_ID,
                    "approval_id": APPROVAL_ID,
                    "summary": SUMMARY,
                },
            },
        )
        mock_channels.push.assert_awaited_once_with(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)


class TestBroadcastInApp:
    async def test_broadcast_failure_is_swallowed(self, mock_channels):
        mock_channels.ws.broadcast_to_user.side_effect = RuntimeError("ws down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_channels.push.assert_awaited_once()
