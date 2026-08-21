"""Tests for `with_heartbeat` — the socket-level SSE keepalive.

`subscribe_stream` keeps the connection alive only while the Redis event log is
IDLE. That is not the same as the socket being idle: the bot translator drops
every web-only frame, so a busy turn can produce a long silence on the wire and
a reverse proxy will hang up on it (nginx's stock `proxy_read_timeout` is 60s —
this is what killed the Discord turns on 2026-08-18). These tests pin the
guarantee that no silence longer than the interval can reach the socket.
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest

from app.constants.streaming import SSE_KEEPALIVE_FRAME
from app.core.stream_manager import with_heartbeat

INTERVAL = 0.05


async def _drain(frames: AsyncGenerator[str, None]) -> list[str]:
    return [frame async for frame in frames]


@pytest.mark.asyncio
async def test_silent_producer_still_writes_to_the_socket() -> None:
    """A producer that yields nothing for several intervals is padded.

    This is the regression: the bot translator swallows web-only frames, so the
    inner generator can be busy and silent at the same time.
    """

    async def silent_then_speak() -> AsyncGenerator[str, None]:
        await asyncio.sleep(INTERVAL * 3.5)
        yield "data: real\n\n"

    frames = await _drain(with_heartbeat(silent_then_speak(), interval=INTERVAL))

    assert frames.count(SSE_KEEPALIVE_FRAME) >= 3, (
        f"expected the gap to be padded with keepalives, got {frames!r}"
    )
    assert frames[-1] == "data: real\n\n", "the real frame must still arrive, last and intact"


@pytest.mark.asyncio
async def test_real_frames_are_forwarded_in_order_and_unmodified() -> None:
    """The wrapper is transparent: it adds frames, it never drops or reorders."""

    async def chatty() -> AsyncGenerator[str, None]:
        for index in range(5):
            yield f"data: {index}\n\n"

    frames = await _drain(with_heartbeat(chatty(), interval=INTERVAL))

    assert frames == [f"data: {index}\n\n" for index in range(5)]


@pytest.mark.asyncio
async def test_no_keepalive_when_the_producer_keeps_talking() -> None:
    """A stream that never goes quiet gets no padding — keepalives are for gaps."""

    async def steady() -> AsyncGenerator[str, None]:
        for index in range(4):
            await asyncio.sleep(INTERVAL / 4)
            yield f"data: {index}\n\n"

    frames = await _drain(with_heartbeat(steady(), interval=INTERVAL))

    assert SSE_KEEPALIVE_FRAME not in frames
    assert len(frames) == 4


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
    """A disconnect while a read is in flight must still tear the read down.

    This is the ordinary disconnect for the case the heartbeat exists to serve:
    the turn is quiet (busy with tool work), so a pull from the event log is
    always in flight when the client drops. Cancelling that pull without
    awaiting it leaves the wrapped generator running, and `aclose()` then
    raises "asynchronous generator is already running" — the subscription is
    left to GC instead of being closed here.
    """
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
