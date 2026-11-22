"""The run pump: the next run event, tick or crash the step waits on, and closing it."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from app.models.conversation_log_models import (
    Verdict,
)
from app.services.conversation.ports import (
    Finished,
    RunEvent,
)


class RunEndedUnfinished(Exception):
    """A comms run's events ended without a Finished event."""


@dataclass(frozen=True)
class Tick:
    """The tick fired before the run's next event."""


@dataclass(frozen=True)
class Crashed:
    """The run raised."""

    error: Exception


@dataclass
class Pump:
    """The run's event stream with at most one pull in flight across ticks."""

    events: AsyncIterator[RunEvent]
    pending: asyncio.Task[RunEvent] | None = None


Ending = Verdict | Finished | Crashed
_Signal = RunEvent | Tick | Crashed


async def next_signal(pump: Pump, tick: Callable[[], Awaitable[None]]) -> _Signal:
    """Race the run's next event against the tick; the pull survives a tick, the tick never outlives the race."""
    if pump.pending is None:
        pump.pending = asyncio.ensure_future(_pull(pump.events))
    ticking = asyncio.ensure_future(tick())
    try:
        await asyncio.wait((pump.pending, ticking), return_when=asyncio.FIRST_COMPLETED)
    finally:
        await _end_task(ticking)
    if not pump.pending.done():
        return Tick()
    pulled, pump.pending = pump.pending, None
    error = pulled.exception()
    if error is None:
        return pulled.result()
    if isinstance(error, Exception):
        return Crashed(error=error)
    raise error


async def _pull(events: AsyncIterator[RunEvent]) -> RunEvent:
    try:
        return await anext(events)
    except StopAsyncIteration:
        raise RunEndedUnfinished from None


async def _end_task(task: asyncio.Future[None]) -> None:
    """Cancel task if still running, wait for it, and raise what it raised."""
    if not task.done():
        task.cancel()
    await asyncio.wait((task,))
    if not task.cancelled():
        task.result()


async def close_pump(pump: Pump) -> None:
    if pump.pending is not None:
        pump.pending.cancel()
        await asyncio.wait((pump.pending,))
        pump.pending = None
