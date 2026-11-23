"""ARQ's connection to real Redis from a process whose event loop is busy booting.

Regression for the sim stack's worker dying at boot: its reminder and workflow
schedulers gave up connecting after arq's one-second deadline while the rest of
startup kept the loop busy, so no job ran for the whole e2e suite.
"""

from __future__ import annotations

import asyncio
import time

from arq import create_pool
import pytest

from app.config.arq_redis import arq_redis_settings
from app.config.settings import settings

# Each turn the loop gives away is held this long: a booting process's sync work, in miniature.
_BUSY_TURN_SECONDS = 0.6


def _hold_the_loop(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    time.sleep(_BUSY_TURN_SECONDS)
    if not stop.is_set():
        loop.call_soon(_hold_the_loop, loop, stop)


@pytest.mark.service
async def test_the_arq_pool_connects_while_the_loop_is_busy_booting(
    redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "REDIS_URL", redis_url)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_soon(_hold_the_loop, asyncio.get_running_loop(), stop)
    try:
        pool = await create_pool(arq_redis_settings())
    finally:
        stop.set()
    try:
        assert await pool.ping()
    finally:
        await pool.aclose()
