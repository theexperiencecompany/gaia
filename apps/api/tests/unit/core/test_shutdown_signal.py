"""A real SIGTERM sets the shutdown signal and still reaches the server's own handler."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import os
import signal
from types import FrameType

import pytest

from app.core.shutdown_signal import (
    install_shutdown_signal,
    remove_shutdown_signal,
    shutdown_requested,
)


@pytest.fixture
def server_handler() -> Iterator[list[int]]:
    """Stand in for uvicorn's handle_exit on SIGTERM, recording what it was sent."""
    received: list[int] = []

    def handle_exit(signum: int, frame: FrameType | None) -> None:
        # uvicorn's handler takes the interrupted frame; the chain must hand on the real one.
        assert frame is not None
        received.append(signum)

    original = signal.signal(signal.SIGTERM, handle_exit)
    try:
        yield received
    finally:
        remove_shutdown_signal()
        signal.signal(signal.SIGTERM, original)


async def test_a_sigterm_sets_shutdown_requested_and_reaches_the_server(
    server_handler: list[int],
) -> None:
    install_shutdown_signal()
    requested = shutdown_requested()
    assert not requested.is_set()

    os.kill(os.getpid(), signal.SIGTERM)

    async with asyncio.timeout(1):
        await requested.wait()
    assert server_handler == [signal.SIGTERM]


async def test_removing_it_hands_sigterm_back_to_the_server(server_handler: list[int]) -> None:
    install_shutdown_signal()
    chained = signal.getsignal(signal.SIGTERM)

    remove_shutdown_signal()

    assert chained is not signal.getsignal(signal.SIGTERM)
    assert not shutdown_requested().is_set()
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.sleep(0)
    assert server_handler == [signal.SIGTERM]
