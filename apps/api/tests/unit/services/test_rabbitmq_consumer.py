"""How a background RabbitMQ consumer connects, retries and is stopped."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.constants.outbound import RABBITMQ_CONNECT_TIMEOUT_SECONDS, RABBITMQ_HEARTBEAT_SECONDS
from app.services import rabbitmq_consumer
from app.services.rabbitmq_consumer import (
    ConsumerConnection,
    RunningConsumer,
    connect_and_consume,
    start_consumer,
    stop_consumer,
)
from tests.helpers import captured_wide_event

RABBITMQ_URL = "amqp://consumer.test"
CTX_KEY = "test_consumer"


def _consume(setup: AsyncMock, holder: ConsumerConnection, max_seconds: float = 30.0):
    return connect_and_consume(
        holder, setup, name="test_consumer", queue="q", reconnect_max_seconds=max_seconds
    )


class TestConnectAndConsume:
    async def test_connects_to_the_configured_broker(self) -> None:
        connection = AsyncMock()
        holder = ConsumerConnection()
        setup = AsyncMock()
        with (
            patch.object(rabbitmq_consumer.settings, "RABBITMQ_URL", RABBITMQ_URL),
            patch.object(
                rabbitmq_consumer.aio_pika, "connect_robust", AsyncMock(return_value=connection)
            ) as connect,
        ):
            await _consume(setup, holder)

        connect.assert_awaited_once_with(
            RABBITMQ_URL,
            timeout=RABBITMQ_CONNECT_TIMEOUT_SECONDS,
            heartbeat=RABBITMQ_HEARTBEAT_SECONDS,
        )
        setup.assert_awaited_once_with(connection)
        assert holder.connection is connection

    async def test_a_failed_setup_closes_its_connection_and_retries(self) -> None:
        first, second = AsyncMock(name="first"), AsyncMock(name="second")
        holder = ConsumerConnection()
        held_while_waiting: list[object] = []

        async def _pause(_delay: float) -> None:
            held_while_waiting.append(holder.connection)

        setup = AsyncMock(side_effect=[RuntimeError("declare refused"), None])
        with (
            patch.object(
                rabbitmq_consumer.aio_pika, "connect_robust", AsyncMock(side_effect=[first, second])
            ),
            patch.object(rabbitmq_consumer.asyncio, "sleep", _pause),
        ):
            await _consume(setup, holder)

        first.close.assert_awaited_once()
        second.close.assert_not_awaited()
        assert held_while_waiting == [None]
        assert setup.await_args_list[-1].args == (second,)
        assert holder.connection is second

    async def test_a_failed_connect_backs_off_doubling_up_to_the_cap(self) -> None:
        connection = AsyncMock()
        holder = ConsumerConnection()
        pause = AsyncMock()
        refused = ConnectionError("broker down")
        async with captured_wide_event() as event:
            with (
                patch.object(
                    rabbitmq_consumer.aio_pika,
                    "connect_robust",
                    AsyncMock(side_effect=[refused, refused, refused, connection]),
                ),
                patch.object(rabbitmq_consumer.asyncio, "sleep", pause),
            ):
                await _consume(AsyncMock(), holder, max_seconds=3.0)

        assert [call.args for call in pause.await_args_list] == [(1.0,), (2.0,), (3.0,)]
        assert holder.connection is connection
        assert event["warnings"] == [
            {
                "msg": "rabbitmq consumer could not start, retrying",
                "consumer": "test_consumer",
                "wait_s": wait_s,
                "error": "broker down",
                "error_type": "ConnectionError",
            }
            for wait_s in (1.0, 2.0, 3.0)
        ]


class TestStartAndStop:
    async def test_without_a_broker_url_nothing_starts(self) -> None:
        ctx: dict[str, object] = {}
        with patch.object(rabbitmq_consumer.settings, "RABBITMQ_URL", ""):
            start_consumer(
                ctx,
                CTX_KEY,
                AsyncMock(),
                name="test_consumer",
                queue="q",
                reconnect_max_seconds=1.0,
            )

        assert ctx == {}

    async def test_a_started_consumer_is_kept_in_ctx_and_stopped_from_it(self) -> None:
        connection = AsyncMock()
        ctx: dict[str, object] = {}
        with (
            patch.object(rabbitmq_consumer.settings, "RABBITMQ_URL", RABBITMQ_URL),
            patch.object(
                rabbitmq_consumer.aio_pika, "connect_robust", AsyncMock(return_value=connection)
            ),
        ):
            start_consumer(
                ctx,
                CTX_KEY,
                AsyncMock(),
                name="test_consumer",
                queue="q",
                reconnect_max_seconds=1.0,
            )
            running = ctx[CTX_KEY]
            assert isinstance(running, RunningConsumer)
            await asyncio.wait({running.task})

        await stop_consumer(ctx, CTX_KEY)

        connection.close.assert_awaited_once()
        assert CTX_KEY not in ctx

    async def test_stopping_what_never_started_is_a_no_op(self) -> None:
        await stop_consumer({}, CTX_KEY)
