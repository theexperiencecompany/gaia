"""Tests for with_heartbeat — the socket-level SSE keepalive.

subscribe_stream keeps the connection alive only while the Redis event log is
IDLE. That is not the same as the socket being idle: the bot translator drops
every web-only frame, so a busy turn can produce a long silence on the wire and
a reverse proxy will hang up on it (nginx's stock proxy_read_timeout is 60s —
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
    """A producer that yields nothing for several intervals is padded, since the bot translator swallows web-only frames."""

    # The producer stays silent until three keepalives have reached the socket,
    # so no wall-clock margin decides the outcome; a fixed 3.5-interval sleep
    # lost its third keepalive to timer drift on a loaded runner.
    spoke = asyncio.Event()

    async def silent_until_told() -> AsyncGenerator[str, None]:
        await spoke.wait()
        yield "data: real\n\n"

    frames: list[str] = []
    async with asyncio.timeout(5):
        async for frame in with_heartbeat(silent_until_told(), interval=INTERVAL):
            frames.append(frame)
            if frames.count(SSE_KEEPALIVE_FRAME) == 3:
                spoke.set()

    assert frames == [SSE_KEEPALIVE_FRAME] * 3 + ["data: real\n\n"], (
        f"the silence must be padded and the real frame arrive last and intact, got {frames!r}"
    )


@pytest.mark.asyncio
async def test_real_frames_are_forwarded_in_order_and_unmodified() -> None:
    """The wrapper is transparent: it adds frames, it never drops or reorders."""

    async def chatty() -> AsyncGenerator[str, None]:
        for index in range(5):
            yield f"data: {index}\n\n"

    frames = await _drain(with_heartbeat(chatty(), interval=INTERVAL))

    assert frames == [f"data: {index}\n\n" for index in range(5)]


@pytest.mark.asyncio
async def test_an_always_ready_producer_is_forwarded_verbatim() -> None:
    """The wrapper is transparent: real frames through, padding not asserted absent."""

    async def ready() -> AsyncGenerator[str, None]:
        for index in range(4):
            yield f"data: {index}\n\n"

    frames = await _drain(with_heartbeat(ready(), interval=INTERVAL))

    assert [frame for frame in frames if frame != SSE_KEEPALIVE_FRAME] == [
        f"data: {index}\n\n" for index in range(4)
    ]


@pytest.mark.asyncio
async def test_a_stall_longer_than_the_interval_is_padded_even_before_the_first_frame() -> None:
    """Padding is keyed to silence, not frame position — even before the first frame."""

    async def slow_first_frame() -> AsyncGenerator[str, None]:
        await asyncio.sleep(INTERVAL * 2)
        yield "data: late\n\n"

    async def occupy(seconds: float) -> None:
        # Block the loop thread the way a co-scheduled xdist worker does, so the
        # sleep above cannot be serviced on time.
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            pass

    staller = asyncio.ensure_future(occupy(INTERVAL * 2))
    frames = await _drain(with_heartbeat(slow_first_frame(), interval=INTERVAL))
    await staller

    assert frames[0] == SSE_KEEPALIVE_FRAME
    assert "data: late\n\n" in frames


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
