"""A browser run's event handlers never wait on another run's, and within a run bubus keeps its order."""

from __future__ import annotations

import asyncio

from bubus import BaseEvent, EventBus
import pytest

import app.patches.browser_use_run_lock_patch as patch_module
from app.patches.browser_use_run_lock_patch import isolate_run_events

#: Far above what two trivial handlers take; reached only when one run waits on the other.
_DEADLOCK_SECONDS = 5


class SlowEvent(BaseEvent[None]):
    pass


class QuickEvent(BaseEvent[None]):
    pass


class OuterEvent(BaseEvent[None]):
    pass


class InnerEvent(BaseEvent[None]):
    pass


@pytest.mark.unit
class TestRunLockPatch:
    async def test_a_handler_busy_in_one_run_does_not_hold_up_another_run(self) -> None:
        # The first run's handler holds its lock until the second run's event is
        # handled: with one lock for the process that never happens.
        busy = asyncio.Event()
        other_handled = asyncio.Event()

        async def busy_run() -> None:
            isolate_run_events()
            bus = EventBus(name="BusyRun")

            async def hold(event: SlowEvent) -> None:
                busy.set()
                await other_handled.wait()

            bus.on(SlowEvent, hold)
            await bus.dispatch(SlowEvent())
            await bus.stop()

        async def other_run() -> None:
            isolate_run_events()
            bus = EventBus(name="OtherRun")
            bus.on(QuickEvent, lambda event: None)
            await busy.wait()
            await bus.dispatch(QuickEvent())
            other_handled.set()
            await bus.stop()

        await asyncio.wait_for(asyncio.gather(busy_run(), other_run()), timeout=_DEADLOCK_SECONDS)

    async def test_nested_events_across_one_runs_buses_keep_order_and_reenter(self) -> None:
        isolate_run_events()
        agent_bus = EventBus(name="AgentBus")
        browser_bus = EventBus(name="BrowserBus")
        order: list[str] = []

        async def inner(event: InnerEvent) -> None:
            order.append("inner")

        async def outer(event: OuterEvent) -> None:
            order.append("outer:start")
            # A handler awaiting an event on the run's other bus re-enters the run's lock.
            await browser_bus.dispatch(InnerEvent())
            order.append("outer:end")

        browser_bus.on(InnerEvent, inner)
        agent_bus.on(OuterEvent, outer)
        await asyncio.wait_for(agent_bus.dispatch(OuterEvent()), timeout=5)
        await agent_bus.stop()
        await browser_bus.stop()

        assert order == ["outer:start", "inner", "outer:end"]

    def test_outside_a_run_the_process_wide_lock_is_used(self) -> None:
        assert patch_module._get_run_lock() is patch_module._original_get_global_lock()
