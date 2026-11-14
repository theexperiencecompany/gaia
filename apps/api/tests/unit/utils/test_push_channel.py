"""The push channel: only an approval wakes a phone, Expo gets every device in batches, gone devices retire."""

from collections.abc import Iterator
from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
import time_machine

from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
)
from app.utils.notification.channels.push import PushChannelAdapter, PushMessage

EXPO_URL = "https://exp.host/--/api/v2/push/send"
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
MESSAGE = PushMessage(
    title="GAIA needs your approval",
    body="Send the deck",
    category_id="hil_approval",
    data={"notification_id": "n1", "approval_id": "ap_1"},
)


def _request(source: NotificationSourceEnum) -> NotificationRequest:
    return NotificationRequest(
        id="n1",
        user_id="u1",
        source=source,
        content=NotificationContent(title="GAIA needs your approval", body="Send the deck"),
        metadata={"approval_id": "ap_1"},
    )


@pytest.fixture
def tokens() -> Iterator[MagicMock]:
    """Serve the user's registered Expo tokens; records which ones were retired."""
    service = MagicMock()
    service.get_active_tokens = AsyncMock(return_value=[])
    service.deactivate_tokens = AsyncMock()
    with patch(
        "app.utils.notification.channels.push.get_device_token_service", return_value=service
    ):
        yield service


def _sent(route: respx.Route) -> list[list[dict[str, object]]]:
    return [json.loads(call.request.content) for call in route.calls]


@pytest.mark.parametrize(
    ("source", "handled"),
    [(NotificationSourceEnum.APPROVAL, True), (NotificationSourceEnum.AI_AGENT, False)],
)
def test_only_an_approval_wakes_the_phone(source: NotificationSourceEnum, handled: bool) -> None:
    assert PushChannelAdapter().can_handle(_request(source)) is handled


async def test_the_message_carries_the_notification_id_and_its_metadata() -> None:
    message = await PushChannelAdapter().transform(_request(NotificationSourceEnum.APPROVAL))

    assert message == MESSAGE


async def test_a_user_with_no_device_is_skipped(tokens: MagicMock) -> None:
    with respx.mock(assert_all_called=False) as expo:
        route = expo.post(EXPO_URL)
        status = await PushChannelAdapter().deliver(MESSAGE, "u1")

    assert status == ChannelDeliveryStatus(
        channel_type="push",
        status=NotificationStatus.FAILED,
        skipped=True,
        error_message="push: no registered device",
    )
    tokens.get_active_tokens.assert_awaited_once_with("u1")
    assert not route.called


@time_machine.travel(NOW, tick=False)
async def test_every_device_is_sent_in_batches_and_gone_ones_are_retired(
    tokens: MagicMock,
) -> None:
    devices = [f"ExponentPushToken[{n}]" for n in range(101)]
    tokens.get_active_tokens.return_value = devices
    first_batch = [{"status": "ok"}] * 100
    first_batch[3] = {"status": "error", "details": {"error": "DeviceNotRegistered"}}
    first_batch[4] = {"status": "error", "details": {"error": "MessageTooBig"}}
    first_batch[5] = {"status": "error"}
    replies = [
        httpx.Response(200, json={"data": first_batch}),
        httpx.Response(
            200, json={"data": [{"status": "error", "details": {"error": "DeviceNotRegistered"}}]}
        ),
    ]
    with respx.mock() as expo:
        route = expo.post(EXPO_URL).mock(side_effect=replies)
        status = await PushChannelAdapter().deliver(MESSAGE, "u1")

    assert status == ChannelDeliveryStatus(
        channel_type="push", status=NotificationStatus.DELIVERED, delivered_at=NOW
    )
    sent = _sent(route)
    assert [len(batch) for batch in sent] == [100, 1]
    assert sent[1] == [
        {
            "to": "ExponentPushToken[100]",
            "title": "GAIA needs your approval",
            "body": "Send the deck",
            "categoryId": "hil_approval",
            "data": {"notification_id": "n1", "approval_id": "ap_1"},
        }
    ]
    assert [message["to"] for message in sent[0]] == devices[:100]
    tokens.deactivate_tokens.assert_awaited_once_with(
        ["ExponentPushToken[3]", "ExponentPushToken[100]"]
    )


async def test_a_batch_with_no_gone_device_retires_nothing(tokens: MagicMock) -> None:
    tokens.get_active_tokens.return_value = ["ExponentPushToken[a]"]
    with respx.mock() as expo:
        expo.post(EXPO_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"status": "ok"}]})
        )
        status = await PushChannelAdapter().deliver(MESSAGE, "u1")

    assert status.status is NotificationStatus.DELIVERED
    tokens.deactivate_tokens.assert_not_awaited()


async def test_an_expo_failure_is_raised_for_the_orchestrator(tokens: MagicMock) -> None:
    tokens.get_active_tokens.return_value = ["ExponentPushToken[a]"]
    with respx.mock() as expo:
        expo.post(EXPO_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(httpx.HTTPStatusError):
            await PushChannelAdapter().deliver(MESSAGE, "u1")

    tokens.deactivate_tokens.assert_not_awaited()
