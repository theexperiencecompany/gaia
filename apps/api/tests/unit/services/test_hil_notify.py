"""Unit tests for hil/notify (approval-pending wake channels).

Both channels are best-effort by contract: a failure inside any channel must
never propagate into the HIL gate. Expo pushes batch at 100 and deactivate
tokens Expo reports as DeviceNotRegistered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.hil.notify import (
    _dead_tokens_from_receipts,
    _send_expo_push,
    notify_approval_pending,
)

_MOD = "app.services.hil.notify"
USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"
APPROVAL_ID = "appr-1"
SUMMARY = "Send the deck to bob"


@pytest.fixture
def mock_channels():
    with (
        patch(f"{_MOD}.websocket_manager") as m_ws,
        patch(f"{_MOD}.device_token_repository") as m_devices,
    ):
        m_ws.broadcast_to_user = AsyncMock()
        m_devices.list_active_tokens = AsyncMock(return_value=[])
        m_devices.deactivate = AsyncMock()
        yield SimpleNamespace(ws=m_ws, device=m_devices)


@pytest.fixture
def mock_expo():
    client = AsyncMock()
    client.__aenter__.return_value = client
    response = MagicMock()
    response.json.return_value = {"data": []}
    client.post.return_value = response
    with patch(f"{_MOD}.httpx.AsyncClient") as m_client:
        m_client.return_value = client
        yield client


class TestNotifyApprovalPending:
    async def test_fires_both_channels(self, mock_channels, mock_expo):
        mock_channels.device.list_active_tokens.return_value = ["token-1"]

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
        mock_expo.post.assert_awaited_once()


class TestBroadcastInApp:
    async def test_broadcast_failure_is_swallowed(self, mock_channels, mock_expo):
        mock_channels.ws.broadcast_to_user.side_effect = RuntimeError("ws down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)


class TestPushToDevices:
    async def test_no_push_without_tokens(self, mock_channels, mock_expo):
        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_expo.post.assert_not_awaited()
        mock_channels.device.deactivate.assert_not_awaited()

    async def test_token_fetch_failure_is_swallowed(self, mock_channels, mock_expo):
        mock_channels.device.list_active_tokens.side_effect = RuntimeError("db down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_expo.post.assert_not_awaited()


class TestSendExpoPush:
    async def test_message_shape(self, mock_expo):
        await _send_expo_push(
            ["token-1"], conversation_id=CONVERSATION_ID, approval_id=APPROVAL_ID, summary=SUMMARY
        )

        payload = mock_expo.post.await_args.kwargs["json"]
        assert payload == [
            {
                "to": "token-1",
                "title": "GAIA needs your approval",
                "body": SUMMARY,
                "categoryId": "hil_approval",
                "data": {
                    "type": "hil_approval",
                    "conversation_id": CONVERSATION_ID,
                    "approval_id": APPROVAL_ID,
                },
            }
        ]
        assert mock_expo.post.await_args.args == ("https://exp.host/--/api/v2/push/send",)

    async def test_batches_at_100(self, mock_expo):
        tokens = [f"token-{i}" for i in range(150)]

        await _send_expo_push(
            tokens, conversation_id=CONVERSATION_ID, approval_id=APPROVAL_ID, summary=SUMMARY
        )

        assert mock_expo.post.await_count == 2
        first_batch = mock_expo.post.await_args_list[0].kwargs["json"]
        second_batch = mock_expo.post.await_args_list[1].kwargs["json"]
        assert len(first_batch) == 100
        assert len(second_batch) == 50

    async def test_dead_tokens_deactivated(self, mock_channels, mock_expo):
        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"status": "ok"},
                {"status": "error", "details": {"error": "DeviceNotRegistered"}},
            ]
        }
        mock_expo.post.return_value = response
        mock_channels.device.list_active_tokens.return_value = ["token-1", "token-2"]

        await _send_expo_push(
            ["token-1", "token-2"],
            conversation_id=CONVERSATION_ID,
            approval_id=APPROVAL_ID,
            summary=SUMMARY,
        )

        mock_channels.device.deactivate.assert_awaited_once_with(["token-2"])

    async def test_a_dead_token_in_a_later_batch_is_the_one_deactivated(
        self, mock_channels, mock_expo
    ):
        delivered, one_dead = MagicMock(), MagicMock()
        delivered.json.return_value = {"data": [{"status": "ok"}] * 100}
        one_dead.json.return_value = {
            "data": [{"status": "error", "details": {"error": "DeviceNotRegistered"}}]
        }
        mock_expo.post.side_effect = [delivered, one_dead]

        await _send_expo_push(
            [f"token-{i}" for i in range(150)],
            conversation_id=CONVERSATION_ID,
            approval_id=APPROVAL_ID,
            summary=SUMMARY,
        )

        mock_channels.device.deactivate.assert_awaited_once_with(["token-100"])

    async def test_post_failure_is_swallowed(self, mock_channels, mock_expo):
        """The swallow happens in _push_to_devices — notify must never raise."""
        mock_channels.device.list_active_tokens.return_value = ["token-1"]
        mock_expo.post.side_effect = RuntimeError("expo down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)


class TestDeadTokensFromReceipts:
    def _response(self, data: object) -> MagicMock:
        response = MagicMock()
        response.json.return_value = data
        return response

    def test_returns_device_not_registered_tokens(self):
        batch = ["a", "b", "c"]
        response = self._response(
            {
                "data": [
                    {"status": "ok"},
                    {"status": "error", "details": {"error": "DeviceNotRegistered"}},
                    {"status": "error", "details": {"error": "SomeOtherError"}},
                ]
            }
        )

        assert _dead_tokens_from_receipts(batch, response) == ["b"]

    def test_empty_data(self):
        assert _dead_tokens_from_receipts(["a"], self._response({})) == []

    def test_non_json_body(self):
        response = MagicMock()
        response.json.side_effect = ValueError("not json")

        assert _dead_tokens_from_receipts(["a"], response) == []

    def test_a_reply_that_is_not_ticket_shaped_reports_none(self):
        assert _dead_tokens_from_receipts(["a"], self._response({"data": "unavailable"})) == []

    def test_an_error_ticket_without_details_is_not_dead(self):
        response = self._response(
            {"data": [{"status": "error"}, {"status": "error", "details": None}]}
        )

        assert _dead_tokens_from_receipts(["a", "b"], response) == []
