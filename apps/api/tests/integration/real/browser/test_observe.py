"""The outbound observer against a real RabbitMQ.

pytest-randomly reseeds random identically for a test's rerun, and aiormq's default
consumer tag comes from random: a flake-gate rerun's watch collided with the failed
attempt's consumer, so no browser scenario could ever pass on its rerun.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import random
import uuid

import aio_pika
import pytest
import pytest_asyncio

from app.config.settings import settings
from app.constants.chat import ConversationSource
from app.constants.outbound import OUTBOUND_QUEUES
from tests.integration.real.browser._stack.observe import OutboundObserver
from tests.integration.real.browser._stack.progress import Progress

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _outbound_is_consumed() -> bool:
    connection = await aio_pika.connect(settings.RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(
            OUTBOUND_QUEUES[ConversationSource.TELEGRAM], passive=True
        )
        return bool(queue.declaration_result.consumer_count)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def observer(progress: Progress) -> AsyncIterator[OutboundObserver]:
    outbound = OutboundObserver(settings.RABBITMQ_URL, progress)
    await outbound.start()
    try:
        # The relay draws its own consumer tag; once it holds the queue it draws no more.
        async with asyncio.timeout(30):
            while True:
                if await _outbound_is_consumed():
                    break
                await asyncio.sleep(0.2)
        yield outbound
    finally:
        await outbound.stop()


@pytest.mark.regression
async def test_a_rerun_scenario_can_watch_its_new_chat(observer: OutboundObserver) -> None:
    random.seed(0)
    await observer.watch(f"first-attempt-{uuid.uuid4().hex}")
    random.seed(0)

    rerun = await observer.watch(f"rerun-{uuid.uuid4().hex}")

    assert rerun.deliveries == []
