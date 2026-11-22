"""keep_proving: a holder is proven alive while it runs, and stopped once its liveness is gone."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from app.utils.liveness import keep_proving
from tests.helpers import captured_wide_event


async def _hold(prove: Callable[[], Awaitable[bool]]) -> asyncio.Task[None]:
    """Run a holder that proves itself alive and then waits until it is stopped."""

    async def holder() -> None:
        keep_proving(
            prove,
            every=0.001,
            give_up_after=10.0,
            name="test-liveness",
            what="the step",
            context={"conversation_id": "c1"},
        )
        await asyncio.Event().wait()

    return asyncio.create_task(holder())


async def test_a_lapsed_liveness_stops_its_holder_and_says_so() -> None:
    async def lapsed() -> bool:
        return False

    async with captured_wide_event() as event:
        task = await _hold(lapsed)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)

    [error] = event["errors"]
    assert error["msg"] == "A holder's liveness lapsed; stopping it"
    assert (error["what"], error["conversation_id"]) == ("the step", "c1")


async def test_the_beat_stops_once_its_holder_ends() -> None:
    async def alive() -> bool:
        return True

    beats: list[asyncio.Task[None]] = []

    async def holder() -> None:
        beats.append(
            keep_proving(
                alive,
                every=0.001,
                give_up_after=10.0,
                name="test-liveness",
                what="the step",
                context={},
            )
        )
        await asyncio.sleep(0.01)

    await asyncio.create_task(holder())
    (beat,) = beats
    await asyncio.wait({beat}, timeout=5)

    assert beat.cancelled()
