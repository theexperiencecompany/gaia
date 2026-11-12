"""Unit tests for hil/notify (approval-pending wake channels).

Every channel is best-effort by contract: a failure inside any channel must
never propagate into the HIL gate. Expo pushes batch at 100 and deactivate
tokens Expo reports as DeviceNotRegistered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.services.hil.notify import (
    _dead_tokens_from_receipts,
    _format_expiry,
    _send_expo_push,
    bot_approval_prompt,
    notify_approval_pending,
)

_MOD = "app.services.hil.notify"
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
    with (
        patch(f"{_MOD}.websocket_manager") as m_ws,
        patch(f"{_MOD}.get_device_token_service", return_value=device_service) as m_dts,
        patch(
            f"{_MOD}.conversation_repository.get_source",
            new=AsyncMock(return_value=ConversationSource.WEB),
        ) as m_source,
        patch(
            f"{_MOD}.deliver_message_to_platform", new=AsyncMock(return_value=True)
        ) as m_platform,
    ):
        m_ws.broadcast_to_user = AsyncMock()
        yield SimpleNamespace(
            ws=m_ws, dts=m_dts, device=device_service, source=m_source, platform=m_platform
        )


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
        mock_channels.device.get_active_tokens.return_value = ["token-1"]

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


class TestPromptOnBotPlatform:
    """A bot turn ends with its reply, so a bot user learns of an approval only through this channel."""

    @pytest.mark.parametrize("source", [ConversationSource.TELEGRAM, ConversationSource.WHATSAPP])
    async def test_a_bot_conversation_gets_the_prompt_once_on_its_platform(
        self, mock_channels, mock_expo, source
    ):
        mock_channels.source.return_value = source

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_channels.source.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID)
        mock_channels.platform.assert_awaited_once_with(
            source, USER_ID, bot_approval_prompt(SUMMARY), conversation_id=CONVERSATION_ID
        )

    @pytest.mark.parametrize("source", [ConversationSource.WEB, None])
    async def test_a_web_conversation_gets_no_platform_message(
        self, mock_channels, mock_expo, source
    ):
        mock_channels.source.return_value = source

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_channels.platform.assert_not_awaited()

    async def test_a_platform_failure_never_reaches_the_gate(self, mock_channels, mock_expo):
        mock_channels.source.return_value = ConversationSource.TELEGRAM
        mock_channels.platform.side_effect = RuntimeError("queue down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_channels.ws.broadcast_to_user.assert_awaited_once()

    async def test_an_undelivered_prompt_is_logged_with_its_approval(
        self, mock_channels, mock_expo
    ):
        mock_channels.source.return_value = ConversationSource.TELEGRAM
        mock_channels.platform.return_value = False

        with patch(f"{_MOD}.log") as m_log:
            await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        m_log.warning.assert_called_once_with(
            f"{LogTag.HIL} HIL notify: bot approval prompt not delivered",
            platform=str(ConversationSource.TELEGRAM),
            approval_id=APPROVAL_ID,
            conversation_id=CONVERSATION_ID,
        )

    async def test_a_delivered_prompt_logs_nothing(self, mock_channels, mock_expo):
        mock_channels.source.return_value = ConversationSource.TELEGRAM

        with patch(f"{_MOD}.log") as m_log:
            await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        m_log.warning.assert_not_called()

    async def test_a_platform_failure_is_logged_with_its_cause(self, mock_channels, mock_expo):
        mock_channels.source.return_value = ConversationSource.TELEGRAM
        mock_channels.platform.side_effect = RuntimeError("queue down")

        with patch(f"{_MOD}.log") as m_log:
            await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        m_log.warning.assert_called_once_with(
            f"{LogTag.HIL} HIL notify: bot approval prompt failed",
            error="queue down",
            error_type="RuntimeError",
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
        )

    def test_the_prompt_asks_for_yes_or_no_and_says_when_it_expires(self):
        assert bot_approval_prompt(SUMMARY) == (
            f"**Approval needed:** {SUMMARY}\n"
            "Reply **yes** to approve or **no** to decline. This expires in 6 hours."
        )

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "1 minute"),
            (60, "1 minute"),
            (120, "2 minutes"),
            (3540, "59 minutes"),
            (3600, "1 hour"),
            (5400, "2 hours"),
            (7200, "2 hours"),
        ],
    )
    def test_the_expiry_reads_in_minutes_under_an_hour_and_hours_after(self, seconds, expected):
        assert _format_expiry(seconds) == expected


class TestBroadcastInApp:
    async def test_broadcast_failure_is_swallowed(self, mock_channels, mock_expo):
        mock_channels.ws.broadcast_to_user.side_effect = RuntimeError("ws down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)


class TestPushToDevices:
    async def test_no_push_without_tokens(self, mock_channels, mock_expo):
        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)

        mock_expo.post.assert_not_awaited()
        mock_channels.device.deactivate_tokens.assert_not_awaited()

    async def test_token_fetch_failure_is_swallowed(self, mock_channels, mock_expo):
        mock_channels.device.get_active_tokens.side_effect = RuntimeError("db down")

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
        mock_channels.device.get_active_tokens.return_value = ["token-1", "token-2"]

        await _send_expo_push(
            ["token-1", "token-2"],
            conversation_id=CONVERSATION_ID,
            approval_id=APPROVAL_ID,
            summary=SUMMARY,
        )

        mock_channels.device.deactivate_tokens.assert_awaited_once_with(["token-2"])

    async def test_post_failure_is_swallowed(self, mock_channels, mock_expo):
        """The swallow happens in _push_to_devices — notify must never raise."""
        mock_channels.device.get_active_tokens.return_value = ["token-1"]
        mock_expo.post.side_effect = RuntimeError("expo down")

        await notify_approval_pending(USER_ID, CONVERSATION_ID, APPROVAL_ID, SUMMARY)


class TestDeadTokensFromReceipts:
    def _response(self, data: object) -> MagicMock:
        response = MagicMock()
        response.json.return_value = data
        return response

    def test_returns_device_not_registered_tokens(self):
        response = self._response(
            {
                "data": [
                    {"status": "ok"},
                    {"status": "error", "details": {"error": "DeviceNotRegistered"}},
                    {"status": "error", "details": {"error": "SomeOtherError"}},
                ]
            }
        )

        assert _dead_tokens_from_receipts(["a", "b", "c"], response) == ["b"]

    def test_empty_data(self):
        assert _dead_tokens_from_receipts(["a"], self._response({})) == []

    def test_non_json_body(self):
        response = MagicMock()
        response.json.side_effect = ValueError("not json")

        assert _dead_tokens_from_receipts(["a"], response) == []
