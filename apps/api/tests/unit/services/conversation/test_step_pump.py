"""The run pump: the next event, tick or crash the step waits on, and closing it."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.services.conversation.ports import RunEvent
from app.services.conversation.step_pump import (
    Crashed,
    Pump,
    RunEndedUnfinished,
    Tick,
    close_pump,
    next_signal,
)


async def _no_tick() -> None:
    return None


async def _never() -> None:
    await asyncio.Event().wait()


async def _raising(error: BaseException) -> AsyncIterator[RunEvent]:
    raise error
    yield  # an async generator that raises on its first pull


async def _silent() -> AsyncIterator[RunEvent]:
    await asyncio.Event().wait()
    raise AssertionError("an event nothing sets was set")
    yield  # an async generator that streams nothing


async def test_a_run_whose_stream_raises_is_read_as_crashed_with_its_error() -> None:
    error = RuntimeError("provider down")
    signal = await next_signal(Pump(events=_raising(error)), _never)
    assert signal == Crashed(error=error)


async def test_a_run_whose_stream_ends_unanswered_is_crashed_as_unfinished() -> None:
    async def ended() -> AsyncIterator[RunEvent]:
        return
        yield

    signal = await next_signal(Pump(events=ended()), _never)
    assert isinstance(signal, Crashed)
    assert isinstance(signal.error, RunEndedUnfinished)


async def test_a_cancelled_pull_is_raised_not_read_as_a_crash() -> None:
    with pytest.raises(asyncio.CancelledError):
        await next_signal(Pump(events=_raising(asyncio.CancelledError())), _never)


async def test_a_tick_that_wins_keeps_the_pull_in_flight_and_closing_ends_it() -> None:
    pump = Pump(events=_silent())

    assert await next_signal(pump, _no_tick) == Tick()
    pending = pump.pending
    assert pending is not None and not pending.done()

    await close_pump(pump)

    assert pump.pending is None
    assert pending.cancelled()
