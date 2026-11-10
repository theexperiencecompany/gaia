"""A background RabbitMQ consumer that connects with retry and is stopped through the worker's ctx."""

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.config.settings import settings
from app.constants.outbound import RABBITMQ_CONNECT_TIMEOUT_SECONDS, RABBITMQ_HEARTBEAT_SECONDS
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

ConsumerSetup = Callable[[AbstractRobustConnection], Awaitable[None]]


@dataclass
class ConsumerConnection:
    """Filled in by the consumer's task once it connects, so shutdown can close it."""

    connection: AbstractRobustConnection | None = None


@dataclass(frozen=True)
class RunningConsumer:
    task: asyncio.Task[None]
    holder: ConsumerConnection


async def connect_and_consume(
    holder: ConsumerConnection,
    setup: ConsumerSetup,
    *,
    name: str,
    queue: str,
    reconnect_max_seconds: float,
) -> None:
    """Connect and run setup on the connection, retrying both with doubling backoff until they succeed.

    connect_robust only restores a connection whose setup once succeeded, so the first
    connect AND the setup on it are retried here.
    """
    delay = 1.0
    while True:
        connection: AbstractRobustConnection | None = None
        try:
            connection = await aio_pika.connect_robust(
                settings.RABBITMQ_URL,
                timeout=RABBITMQ_CONNECT_TIMEOUT_SECONDS,
                heartbeat=RABBITMQ_HEARTBEAT_SECONDS,
            )
            holder.connection = connection
            await setup(connection)
        except Exception as e:
            log.warning(
                "rabbitmq consumer could not start, retrying",
                consumer=name,
                wait_s=delay,
                error=str(e),
                error_type=type(e).__name__,
            )
            holder.connection = None
            if connection is not None:
                await connection.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, reconnect_max_seconds)
            continue
        log.info("rabbitmq consumer consuming", consumer=name, queue=queue)
        return


def start_consumer(
    ctx: MutableMapping[str, object],
    ctx_key: str,
    setup: ConsumerSetup,
    *,
    name: str,
    queue: str,
    reconnect_max_seconds: float,
) -> None:
    """Start consuming in the background and keep it in ctx under ctx_key; a no-op without RabbitMQ."""
    if not settings.RABBITMQ_URL:
        log.warning("rabbitmq consumer not started: RABBITMQ_URL is not configured", consumer=name)
        return
    holder = ConsumerConnection()
    task = spawn_background_task(
        connect_and_consume(
            holder,
            setup,
            name=name,
            queue=queue,
            reconnect_max_seconds=reconnect_max_seconds,
        ),
        name=name,
    )
    ctx[ctx_key] = RunningConsumer(task=task, holder=holder)


async def stop_consumer(ctx: MutableMapping[str, object], ctx_key: str) -> None:
    """Stop connecting (if still trying) and close the consumer's connection."""
    running = ctx.pop(ctx_key, None)
    if not isinstance(running, RunningConsumer):
        return
    running.task.cancel()
    await asyncio.wait({running.task})
    if running.holder.connection is not None:
        await running.holder.connection.close()
