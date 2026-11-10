"""What the API does with a delivery receipt a bot publishes."""

import json
from unittest.mock import AsyncMock, patch

from app.constants.outbound import OUTBOUND_RECEIPTS_REQUEUE_DELAY_SECONDS
from app.services.outbox import receipt_consumer
from tests.helpers import WideEventRecorder


def _receipt_body(**overrides: object) -> bytes:
    return json.dumps(
        {
            "envelope_id": "env-1",
            "outbox_message_id": "ob-1",
            "part_index": 0,
            "platform": "telegram",
            "platform_message_ids": ["m1"],
            "status": "sent",
            "error": None,
            "occurred_at": "2026-11-10T11:00:00.000Z",
        }
        | overrides
    ).encode()


class FakeMessage:
    """The parts of an aio-pika incoming message the consumer settles."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.routing_key = "outbound.receipts"
        self.ack = AsyncMock()
        self.nack = AsyncMock()
        self.reject = AsyncMock()


class TestHandle:
    async def test_a_receipt_is_filed_and_acked(self) -> None:
        message = FakeMessage(_receipt_body(status="failed", error="destination_blocked"))
        with patch.object(
            receipt_consumer.outbound_receipts_repository, "record", AsyncMock(return_value=True)
        ) as record:
            await receipt_consumer.handle_receipt(message)

        (filed,) = record.await_args.args
        assert (filed.envelope_id, filed.status.value, filed.error) == (
            "env-1",
            "failed",
            "destination_blocked",
        )
        assert filed.platform_message_ids == ["m1"]
        message.ack.assert_awaited_once()

    async def test_a_redelivered_receipt_is_acked_not_filed_twice(self) -> None:
        message = FakeMessage(_receipt_body())
        recorder = WideEventRecorder()
        with (
            patch("shared.py.wide_events._loguru", recorder),
            patch.object(
                receipt_consumer.outbound_receipts_repository,
                "record",
                AsyncMock(return_value=False),
            ),
        ):
            await receipt_consumer.handle_receipt(message)

        message.ack.assert_awaited_once()
        assert recorder.event("outbound_receipt")["receipt_duplicate"] is True

    async def test_an_unreadable_receipt_is_dropped_loudly_not_requeued(self) -> None:
        message = FakeMessage(_receipt_body(status="delivered"))
        recorder = WideEventRecorder()
        with (
            patch("shared.py.wide_events._loguru", recorder),
            patch.object(
                receipt_consumer.outbound_receipts_repository, "record", AsyncMock()
            ) as record,
        ):
            await receipt_consumer.handle_receipt(message)

        record.assert_not_awaited()
        message.reject.assert_awaited_once_with(requeue=False)
        (error,) = recorder.event("outbound_receipt")["errors"]
        assert error["msg"] == "outbound receipt could not be read"

    async def test_a_store_failure_requeues_the_receipt_after_a_pause(self) -> None:
        message = FakeMessage(_receipt_body())
        pause = AsyncMock()
        with (
            patch.object(
                receipt_consumer.outbound_receipts_repository,
                "record",
                AsyncMock(side_effect=ConnectionError("mongo down")),
            ),
            patch.object(receipt_consumer.asyncio, "sleep", pause),
        ):
            await receipt_consumer.handle_receipt(message)

        pause.assert_awaited_once_with(OUTBOUND_RECEIPTS_REQUEUE_DELAY_SECONDS)
        message.nack.assert_awaited_once_with(requeue=True)
        message.ack.assert_not_awaited()
