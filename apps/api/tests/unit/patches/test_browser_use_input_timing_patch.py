"""Tests for the keystroke-rhythm patch.

Browser-Use types on two fixed timers (a 5ms key-hold and a 1ms inter-key gap),
so every keystroke is identical to the microsecond — a zero-variance metronome
no hand produces. The patch scales those two delays by a log-normal draw.

The scope is the delicate part and is what these tests mostly guard: the jitter
must reach the per-keystroke timers and nothing else. The same module uses
comparable float literals for scroll-settle and readback waits, which are
load-bearing page timing, and asyncio.sleep itself must stay untouched
process-wide.
"""

from __future__ import annotations

import asyncio
import statistics

from browser_use.browser.watchdogs import default_action_watchdog as watchdog_module
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
import pytest

import app.patches.browser_use_input_timing_patch as patch_module
from app.services.browser.fingerprint import reset_fingerprint_seed, set_fingerprint_seed

HOLD_SECONDS = 0.005
GAP_SECONDS = 0.001
SETTLE_SECONDS = 0.05


async def _record(delays: list[float], requested: list[float]) -> None:
    """Run delays through the patched module sleep, capturing what it asks for."""
    real_sleep = asyncio.sleep

    async def spy(delay: float, result: object = None) -> object:
        requested.append(delay)
        return await real_sleep(0)

    asyncio.sleep = spy  # type: ignore[assignment]  # swaps asyncio.sleep for a spy to capture requested delays
    try:
        for delay in delays:
            await watchdog_module.asyncio.sleep(delay)
    finally:
        asyncio.sleep = real_sleep  # type: ignore[assignment]  # restores the real asyncio.sleep after the spy


async def _armed_record(delays: list[float]) -> list[float]:
    requested: list[float] = []

    async def body() -> None:
        await _record(delays, requested)

    await patch_module._arm_typing_rhythm(body)()
    return requested


@pytest.mark.unit
class TestInputTimingPatch:
    def test_global_asyncio_sleep_is_not_patched(self) -> None:
        # Assigning to asyncio.sleep would perturb every coroutine in the process.
        assert asyncio.sleep is not patch_module._sleep
        assert watchdog_module.asyncio.sleep is patch_module._sleep

    def test_both_typing_methods_are_wrapped(self) -> None:
        for name in ("_input_text_element_node_impl", "_type_to_page"):
            assert getattr(DefaultActionWatchdog, name).__name__ == "wrapper"

    async def test_delays_pass_through_untouched_outside_typing(self) -> None:
        requested: list[float] = []
        await _record([HOLD_SECONDS, GAP_SECONDS], requested)
        assert requested == [HOLD_SECONDS, GAP_SECONDS]

    async def test_page_timing_sleeps_are_untouched_while_typing(self) -> None:
        # 50ms readback/scroll settles share the module with the keystroke timers.
        assert await _armed_record([SETTLE_SECONDS]) == [SETTLE_SECONDS]

    async def test_keystroke_delays_gain_variance(self) -> None:
        requested = await _armed_record([HOLD_SECONDS] * 60)
        assert len(set(requested)) > 1, "key-hold is still a constant"
        assert statistics.stdev(requested) > 0.001

    async def test_stays_close_to_the_library_pace(self) -> None:
        # A "realistic" ~60ms/char would cost a second per field; the variance is
        # what defeats the check, so the mean must stay in the same order.
        requested = await _armed_record([HOLD_SECONDS, GAP_SECONDS] * 100)
        baseline = 100 * (HOLD_SECONDS + GAP_SECONDS)
        assert baseline < sum(requested) < baseline * 3

    async def test_ceiling_delay_is_jittered_and_anything_slower_is_not(self) -> None:
        # The ceiling separates keystroke rhythm from page timing: a delay *at* it
        # is still a keystroke, the next float up is a load-bearing page wait.
        ceiling = patch_module._KEYSTROKE_DELAY_CEILING_SECONDS
        just_above = ceiling * 1.01

        assert len(set(await _armed_record([ceiling] * 40))) > 1
        assert await _armed_record([just_above] * 3) == [just_above] * 3

    async def test_sleep_returns_the_result_it_was_given(self) -> None:
        # asyncio.sleep's second argument is the awaited value; the proxy must not
        # swallow it, or a caller relying on `await sleep(d, x)` silently gets None.
        assert await patch_module._sleep(0, "page-ready") == "page-ready"

    async def test_wrapper_forwards_positional_and_keyword_arguments(self) -> None:
        received: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def method(*args: object, **kwargs: object) -> str:
            received.append((args, kwargs))
            return "typed"

        result = await patch_module._arm_typing_rhythm(method)("element", text="hello")

        assert result == "typed"
        assert received == [(("element",), {"text": "hello"})]

    async def test_rhythm_is_stable_per_user_and_differs_across_users(self) -> None:
        async def rhythm(user: str) -> list[float]:
            token = set_fingerprint_seed(user)
            try:
                return await _armed_record([GAP_SECONDS] * 20)
            finally:
                reset_fingerprint_seed(token)

        # A fingerprint that changes every run is itself a bot signal.
        assert await rhythm("user-a") == await rhythm("user-a")
        assert await rhythm("user-a") != await rhythm("user-b")
