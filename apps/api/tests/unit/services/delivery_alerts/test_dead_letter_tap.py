"""Which broker dead-letters alert, and what they say."""

from datetime import UTC, datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import pytest
from tests.helpers import WideEventRecorder, captured_wide_event

from app.constants.chat import ConversationSource
from app.constants.delivery_alerts import (
    DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS,
    DeliveryFailureKind,
)
from app.constants.outbound import RABBITMQ_CONNECT_TIMEOUT_SECONDS, RABBITMQ_HEARTBEAT_SECONDS
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts import dead_letter_tap
from app.services.delivery_alerts.dead_letter_tap import dead_letter_failure

DIED_AT = datetime(2026, 10, 22, 15, 40, tzinfo=UTC)
EXPIRED_FAILURE = DeliveryFailure(
    platform=ConversationSource.TELEGRAM,
    kind=DeliveryFailureKind.EXPIRED,
    reason="expired",
    destination_id="-100999",
    is_channel=True,
    envelope_id="env-1",
    occurred_at=DIED_AT,
    reporter="dead-letter-tap",
)
ENVELOPE = json.dumps(
    {"id": "env-1", "platform": "telegram", "destination_id": "-100999", "is_channel": True}
).encode()


def _headers(
    reason: str, queue: str = "outbound.telegram", died_at: datetime | None = DIED_AT
) -> dict[str, object]:
    death: dict[str, object] = {"reason": reason, "queue": queue, "count": 1}
    if died_at is not None:
        death["time"] = died_at
    return {"x-death": [death]}


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

    def test_a_death_time_in_another_zone_is_stored_in_utc(self) -> None:
        failure = dead_letter_failure(
            _headers("expired", died_at=DIED_AT.astimezone(timezone(timedelta(hours=5)))), ENVELOPE
        )

        assert failure is not None
        assert failure.occurred_at == DIED_AT
        assert failure.occurred_at.tzinfo is UTC

    def test_a_death_without_a_time_is_stamped_now_in_utc(self) -> None:
        before = datetime.now(UTC)
        failure = dead_letter_failure(_headers("expired", died_at=None), ENVELOPE)

        assert failure is not None
        assert failure.occurred_at.tzinfo is UTC
        assert before <= failure.occurred_at <= datetime.now(UTC)

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

    def test_a_platform_without_an_outbound_queue_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="not an outbound work queue"):
            dead_letter_failure(_headers("expired", queue="outbound.web"), ENVELOPE)

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
        recorder = WideEventRecorder()
        with (
            patch("shared.py.wide_events._loguru", recorder),
            patch.object(dead_letter_tap, "queue_delivery_failure", AsyncMock()) as queued,
        ):
            await dead_letter_tap._handle(message)

        queued.assert_awaited_once_with(EXPIRED_FAILURE)
        message.ack.assert_awaited_once()
        event = recorder.event("dead_letter_tap")
        assert event["component"] == "delivery_alerts"
        assert event["delivery_failure"] == {"platform": "telegram", "reason": "expired"}

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

    async def test_unreadable_metadata_is_logged_as_an_error(self) -> None:
        message = FakeMessage(_headers("expired", queue="websocket.events"))
        recorder = WideEventRecorder()
        with patch("shared.py.wide_events._loguru", recorder):
            await dead_letter_tap._handle(message)

        assert recorder.event("dead_letter_tap")["errors"] == [
            {
                "msg": "dead-lettered message could not be read",
                "routing_key": "outbound.telegram.dlq",
                "error": "dead-lettered from 'websocket.events', which is not an outbound work queue",
                "error_type": "ValueError",
            }
        ]

    async def test_an_alert_redis_could_not_take_is_requeued_after_a_pause(self) -> None:
        message = FakeMessage(_headers("expired"))
        pause = AsyncMock()
        recorder = WideEventRecorder()
        with (
            patch("shared.py.wide_events._loguru", recorder),
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
        assert recorder.event("dead_letter_tap")["warnings"] == [
            {
                "msg": "dead-letter alert could not be queued, requeueing",
                "routing_key": "outbound.telegram.dlq",
                "wait_s": DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS,
                "error": "redis down",
                "error_type": "ConnectionError",
            }
        ]


RABBITMQ_URL = "amqp://tap.test"


class TestRun:
    async def test_connects_to_the_configured_broker(self) -> None:
        connection = AsyncMock()
        holder = dead_letter_tap._TapConnection()
        with (
            patch.object(dead_letter_tap.settings, "RABBITMQ_URL", RABBITMQ_URL),
            patch.object(
                dead_letter_tap.aio_pika, "connect_robust", AsyncMock(return_value=connection)
            ) as connect,
            patch.object(dead_letter_tap, "_consume", AsyncMock()) as consume,
        ):
            await dead_letter_tap._run(holder)

        connect.assert_awaited_once_with(
            RABBITMQ_URL,
            timeout=RABBITMQ_CONNECT_TIMEOUT_SECONDS,
            heartbeat=RABBITMQ_HEARTBEAT_SECONDS,
        )
        consume.assert_awaited_once_with(connection)
        assert holder.connection is connection

    async def test_a_failed_setup_closes_its_connection_and_retries(self) -> None:
        first, second = AsyncMock(name="first"), AsyncMock(name="second")
        holder = dead_letter_tap._TapConnection()
        held_while_waiting: list[object] = []

        async def _pause(_delay: float) -> None:
            held_while_waiting.append(holder.connection)

        with (
            patch.object(
                dead_letter_tap.aio_pika, "connect_robust", AsyncMock(side_effect=[first, second])
            ),
            patch.object(
                dead_letter_tap,
                "_consume",
                AsyncMock(side_effect=[RuntimeError("declare refused"), None]),
            ) as consume,
            patch.object(dead_letter_tap.asyncio, "sleep", _pause),
        ):
            await dead_letter_tap._run(holder)

        first.close.assert_awaited_once()
        second.close.assert_not_awaited()
        assert held_while_waiting == [None]
        assert consume.await_args_list[-1].args == (second,)
        assert holder.connection is second

    async def test_a_failed_connect_backs_off_doubling_up_to_the_cap(self) -> None:
        connection = AsyncMock()
        holder = dead_letter_tap._TapConnection()
        pause = AsyncMock()
        refused = ConnectionError("broker down")
        async with captured_wide_event() as event:
            with (
                patch.object(dead_letter_tap, "DEAD_LETTER_TAP_RECONNECT_MAX_SECONDS", 3.0),
                patch.object(
                    dead_letter_tap.aio_pika,
                    "connect_robust",
                    AsyncMock(side_effect=[refused, refused, refused, connection]),
                ),
                patch.object(dead_letter_tap, "_consume", AsyncMock()),
                patch.object(dead_letter_tap.asyncio, "sleep", pause),
            ):
                await dead_letter_tap._run(holder)

        assert [call.args for call in pause.await_args_list] == [(1.0,), (2.0,), (3.0,)]
        assert holder.connection is connection
        assert event["warnings"] == [
            {
                "msg": "dead-letter tap could not start, retrying",
                "wait_s": wait_s,
                "error": "broker down",
                "error_type": "ConnectionError",
            }
            for wait_s in (1.0, 2.0, 3.0)
        ]
