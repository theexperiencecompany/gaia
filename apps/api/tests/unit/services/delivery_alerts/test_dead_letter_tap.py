"""Which broker dead-letters alert, and what they say."""

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import pytest

from app.constants.delivery_alerts import (
    DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS,
    DeliveryFailureKind,
)
from app.services.delivery_alerts import dead_letter_tap
from app.services.delivery_alerts.dead_letter_tap import dead_letter_failure

DIED_AT = datetime(2026, 10, 22, 15, 40, tzinfo=UTC)
ENVELOPE = json.dumps(
    {"id": "env-1", "platform": "telegram", "destination_id": "-100999", "is_channel": True}
).encode()


def _headers(reason: str, queue: str = "outbound.telegram") -> dict[str, object]:
    return {"x-death": [{"reason": reason, "queue": queue, "count": 1, "time": DIED_AT}]}


class TestDeadLetterFailure:
    def test_an_expired_message_alerts_with_its_envelope(self) -> None:
        failure = dead_letter_failure(_headers("expired"), ENVELOPE)

        assert failure is not None
        assert failure.kind is DeliveryFailureKind.EXPIRED
        assert failure.platform.value == "telegram"
        assert failure.reason == "expired"
        assert failure.envelope_id == "env-1"
        assert failure.destination_id == "-100999"
        assert failure.is_channel is True
        assert failure.occurred_at == DIED_AT

    def test_a_bot_rejection_is_left_to_the_bot_that_reported_it(self) -> None:
        assert dead_letter_failure(_headers("rejected"), ENVELOPE) is None

    def test_an_unreadable_message_still_alerts_without_a_recipient(self) -> None:
        failure = dead_letter_failure(_headers("maxlen"), b"{ not json")

        assert failure is not None
        assert failure.destination_id is None
        assert failure.reason == "maxlen"

    def test_a_message_from_another_queue_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="not an outbound work queue"):
            dead_letter_failure(_headers("expired", queue="websocket.events"), ENVELOPE)

    def test_a_message_without_x_death_is_an_error(self) -> None:
        with pytest.raises(ValidationError, match="x-death"):
            dead_letter_failure({}, ENVELOPE)


class FakeMessage:
    """The parts of an aio-pika incoming message the tap settles."""

    def __init__(self, headers: dict[str, object], body: bytes = ENVELOPE) -> None:
        self.headers = headers
        self.body = body
        self.routing_key = "outbound.telegram.dlq"
        self.ack = AsyncMock()
        self.nack = AsyncMock()
        self.reject = AsyncMock()


class TestHandle:
    async def test_a_queued_alert_acks_the_copy(self) -> None:
        message = FakeMessage(_headers("expired"))
        with patch.object(dead_letter_tap, "queue_delivery_failure", AsyncMock()) as queued:
            await dead_letter_tap._handle(message)

        queued.assert_awaited_once()
        message.ack.assert_awaited_once()

    async def test_a_bot_rejection_is_acked_without_an_alert(self) -> None:
        message = FakeMessage(_headers("rejected"))
        with patch.object(dead_letter_tap, "queue_delivery_failure", AsyncMock()) as queued:
            await dead_letter_tap._handle(message)

        queued.assert_not_awaited()
        message.ack.assert_awaited_once()

    async def test_unreadable_metadata_is_dropped_not_requeued(self) -> None:
        message = FakeMessage({})
        with patch.object(dead_letter_tap, "queue_delivery_failure", AsyncMock()) as queued:
            await dead_letter_tap._handle(message)

        queued.assert_not_awaited()
        message.reject.assert_awaited_once_with(requeue=False)

    async def test_an_alert_redis_could_not_take_is_requeued_after_a_pause(self) -> None:
        message = FakeMessage(_headers("expired"))
        pause = AsyncMock()
        with (
            patch.object(
                dead_letter_tap,
                "queue_delivery_failure",
                AsyncMock(side_effect=ConnectionError("redis down")),
            ),
            patch.object(dead_letter_tap.asyncio, "sleep", pause),
        ):
            await dead_letter_tap._handle(message)

        pause.assert_awaited_once_with(DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS)
        message.nack.assert_awaited_once_with(requeue=True)
        message.reject.assert_not_awaited()


class TestRun:
    async def test_a_failed_setup_closes_its_connection_and_retries(self) -> None:
        first, second = AsyncMock(name="first"), AsyncMock(name="second")
        holder = dead_letter_tap._TapConnection()
        with (
            patch.object(
                dead_letter_tap.aio_pika, "connect_robust", AsyncMock(side_effect=[first, second])
            ),
            patch.object(
                dead_letter_tap,
                "_consume",
                AsyncMock(side_effect=[RuntimeError("declare refused"), None]),
            ),
            patch.object(dead_letter_tap.asyncio, "sleep", AsyncMock()),
        ):
            await dead_letter_tap._run(holder)

        first.close.assert_awaited_once()
        second.close.assert_not_awaited()
        assert holder.connection is second
