"""Unit tests for the Expo push transport (approval prompts to backgrounded mobile clients).

The push is best-effort by contract: a failure must never propagate into the HIL gate.
Expo pushes batch at 100 and deactivate tokens Expo reports as DeviceNotRegistered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.outbox.transport.push import (
    _dead_tokens_from_receipts,
    _send_expo_push,
    push_approval_pending,
)

_MOD = "app.services.outbox.transport.push"
USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"
APPROVAL_ID = "appr-1"
SUMMARY = "Send the deck to bob"


@pytest.fixture
def mock_channels():
    device_service = SimpleNamespace(
        get_active_tokens=AsyncMock(return_value=[]),
        deactivate_tokens=AsyncMock(),
    )
    with patch(f"{_MOD}.get_device_token_service", return_value=device_service):
        yield SimpleNamespace(device=device_service)


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


class TestPushToDevices:
    async def test_no_push_without_tokens(self, mock_channels, mock_expo):
        await push_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_expo.post.assert_not_awaited()
        mock_channels.device.deactivate_tokens.assert_not_awaited()

    async def test_token_fetch_failure_is_swallowed(self, mock_channels, mock_expo):
        mock_channels.device.get_active_tokens.side_effect = RuntimeError("db down")

        await push_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

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
        mock_channels.device.get_active_tokens.return_value = ["token-1", "token-2"]

        await _send_expo_push(
            ["token-1", "token-2"],
            conversation_id=CONVERSATION_ID,
            approval_id=APPROVAL_ID,
            summary=SUMMARY,
        )

        mock_channels.device.deactivate_tokens.assert_awaited_once_with(["token-2"])

    async def test_post_failure_is_swallowed(self, mock_channels, mock_expo):
        """The swallow happens in push_approval_pending — notify must never raise."""
        mock_channels.device.get_active_tokens.return_value = ["token-1"]
        mock_expo.post.side_effect = RuntimeError("expo down")

        await push_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)


class TestDeadTokensFromReceipts:
    def _response(self, data: object) -> MagicMock:
        response = MagicMock()
        response.json.return_value = data
        return response

    def test_returns_device_not_registered_tokens(self):
        batch = [{"to": "a"}, {"to": "b"}, {"to": "c"}]
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
        assert _dead_tokens_from_receipts([{"to": "a"}], self._response({})) == []

    def test_non_json_body(self):
        response = MagicMock()
        response.json.side_effect = ValueError("not json")

        assert _dead_tokens_from_receipts([{"to": "a"}], response) == []
