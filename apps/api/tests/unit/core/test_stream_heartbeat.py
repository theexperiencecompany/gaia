"""Tests for with_heartbeat — the socket-level SSE keepalive.

subscribe_stream keeps the connection alive only while the Redis event log is
IDLE. That is not the same as the socket being idle: the bot translator drops
every web-only frame, so a busy turn can produce a long silence on the wire and
a reverse proxy will hang up on it (nginx's stock proxy_read_timeout is 60s —
this is what killed the Discord turns on 2026-08-18). These tests pin the
guarantee that no silence longer than the interval can reach the socket.
"""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
import selectors

import pytest

from app.constants.streaming import SSE_KEEPALIVE_FRAME
from app.core.stream_manager import with_heartbeat

INTERVAL = 0.05


class _VirtualClockSelector(selectors.DefaultSelector):
    """A selector that never waits: it advances the clock by the timeout it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.now = 0.0

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        if timeout is None:
            raise RuntimeError("virtual-time loop would block forever: nothing is scheduled")
        self.now += max(timeout, 0.0)
        return super().select(0)


class _VirtualTimeLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock jumps to the next timer instead of waiting for it.

    Every sleep and wait_for timeout resolves in exact virtual time, so a test of
    interval arithmetic is deterministic however loaded the machine is.
    """

    def __init__(self) -> None:
        self._clock = _VirtualClockSelector()
        super().__init__(self._clock)

    def time(self) -> float:
        return self._clock.now


def _run_on_virtual_time(coro: Coroutine[object, object, list[str]]) -> list[str]:
    loop = _VirtualTimeLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _drain(frames: AsyncGenerator[str, None]) -> list[str]:
    return [frame async for frame in frames]


def test_silent_producer_still_writes_to_the_socket() -> None:
    """A producer that yields nothing for several intervals is padded, since the bot translator swallows web-only frames."""

    async def silent_then_speak() -> AsyncGenerator[str, None]:
        await asyncio.sleep(INTERVAL * 5.5)
        yield "data: real\n\n"

    frames = _run_on_virtual_time(_drain(with_heartbeat(silent_then_speak(), interval=INTERVAL)))

    # One keepalive per elapsed interval of silence, then the real frame, intact.
    assert frames == [SSE_KEEPALIVE_FRAME] * 5 + ["data: real\n\n"]


@pytest.mark.asyncio
async def test_real_frames_are_forwarded_in_order_and_unmodified() -> None:
    """The wrapper is transparent: it adds frames, it never drops or reorders."""

    async def chatty() -> AsyncGenerator[str, None]:
        for index in range(5):
            yield f"data: {index}\n\n"

    frames = await _drain(with_heartbeat(chatty(), interval=INTERVAL))

    assert frames == [f"data: {index}\n\n" for index in range(5)]


def test_no_keepalive_when_the_producer_keeps_talking() -> None:
    """Frames spaced just under the interval, across many intervals, are never padded: each frame restarts the wait."""

    async def steady() -> AsyncGenerator[str, None]:
        for index in range(10):
            await asyncio.sleep(INTERVAL * 0.9)
            yield f"data: {index}\n\n"

    frames = _run_on_virtual_time(_drain(with_heartbeat(steady(), interval=INTERVAL)))

    assert frames == [f"data: {index}\n\n" for index in range(10)]


@pytest.mark.asyncio
async def test_producer_errors_propagate() -> None:
    """A failure inside the stream must surface, not be swallowed into silence."""

    async def explodes() -> AsyncGenerator[str, None]:
        yield "data: first\n\n"
        raise RuntimeError("redis died")

    with pytest.raises(RuntimeError, match="redis died"):
        await _drain(with_heartbeat(explodes(), interval=INTERVAL))


@pytest.mark.asyncio
async def test_closing_mid_heartbeat_closes_the_wrapped_producer() -> None:
    """A disconnect while a read is in flight must still tear the read down, or aclose() raises "already running" and leaks to GC."""
    closed = asyncio.Event()

    async def never_speaks() -> AsyncGenerator[str, None]:
        try:
            await asyncio.sleep(10)
            yield "data: unreachable\n\n"
        finally:
            closed.set()

    stream = with_heartbeat(never_speaks(), interval=INTERVAL)
    # Padding around a pull that has not returned — the racy state.
    assert await stream.__anext__() == SSE_KEEPALIVE_FRAME

    await stream.aclose()

    await asyncio.wait_for(closed.wait(), timeout=1)


@pytest.mark.asyncio
async def test_closing_early_closes_the_wrapped_producer() -> None:
    """A client disconnect must tear the event-log read down, not leak it."""
    closed = asyncio.Event()

    async def tracked() -> AsyncGenerator[str, None]:
        try:
            while True:
                yield "data: tick\n\n"
                await asyncio.sleep(INTERVAL / 4)
        finally:
            closed.set()

    stream = with_heartbeat(tracked(), interval=INTERVAL)
    assert await stream.__anext__() == "data: tick\n\n"
    await stream.aclose()

    await asyncio.wait_for(closed.wait(), timeout=1)
