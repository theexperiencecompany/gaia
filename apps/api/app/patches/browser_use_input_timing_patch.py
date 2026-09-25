"""Give keystrokes human variance without making the agent slower in any noticeable way.

Browser-Use types character by character on two fixed timers: a 5ms hold
between keyDown and keyUp, then a 1ms gap before the next character. Every
keystroke is identical to the microsecond, and that zero-variance metronome
is the tell behavioural checks read, not the speed.

Only the distribution changes, not the pace: each delay is scaled by a draw
averaging ~1.9x, costing ~100ms on a 20-character field. The RNG is seeded
per user so one person's typing rhythm stays consistent across tasks.

The shim is armed only while a typing method is on the stack, and it rebinds the
watchdog module's asyncio name to a proxy rather than patching asyncio.sleep.
Pinned to browser-use==0.11.13; the imports fail loudly if the methods move.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextvars
import random
from typing import Any, ParamSpec, TypeVar

from browser_use.browser.watchdogs import default_action_watchdog as watchdog_module
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

from app.services.browser.fingerprint import current_fingerprint_seed

# Only the per-keystroke timers are this short; every other wait in the module
# is 50ms or longer, so this threshold separates rhythm from page timing.
_KEYSTROKE_DELAY_CEILING_SECONDS = 0.010
# Log-normal draw: mostly clustered with an occasional long pause, the shape
# human inter-key intervals actually take. mu/sigma give a mean scale of
# ~1.9x; the cap keeps a tail draw from stalling.
_SCALE_MU = 0.49
_SCALE_SIGMA = 0.55
_MAX_SCALE = 6.0

P = ParamSpec("P")
R = TypeVar("R")

_rng: contextvars.ContextVar[random.Random | None] = contextvars.ContextVar(
    "browser_typing_rng", default=None
)


async def _sleep(delay: float, result: object = None) -> object:
    rng = _rng.get()
    if rng is not None and delay <= _KEYSTROKE_DELAY_CEILING_SECONDS:
        delay *= min(rng.lognormvariate(_SCALE_MU, _SCALE_SIGMA), _MAX_SCALE)
    return await asyncio.sleep(delay, result)


class _AsyncioProxy:
    """The stdlib asyncio module with only sleep swapped, for one module's use."""

    sleep = staticmethod(_sleep)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- delegates to an arbitrary asyncio module attribute, so Any is the honest return type
        return getattr(asyncio, name)


def _arm_typing_rhythm(
    method: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Enable the jitter for the duration of one typing action."""

    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # A private Random, not the global module RNG: seeded per user and scoped
        # to this call, so nothing else in the process has its randomness moved.
        token = _rng.set(random.Random(current_fingerprint_seed()))
        try:
            return await method(*args, **kwargs)
        finally:
            _rng.reset(token)

    return wrapper


watchdog_module.asyncio = _AsyncioProxy()  # type: ignore[assignment, attr-defined]  # inject an asyncio proxy into browser-use's watchdog module so its sleeps carry the typing rhythm
DefaultActionWatchdog._input_text_element_node_impl = _arm_typing_rhythm(  # type: ignore[method-assign, assignment]  # rebind browser-use's watchdog method with the rhythm-armed wrapper
    DefaultActionWatchdog._input_text_element_node_impl
)
DefaultActionWatchdog._type_to_page = _arm_typing_rhythm(  # type: ignore[method-assign, assignment]  # rebind browser-use's watchdog method with the rhythm-armed wrapper
    DefaultActionWatchdog._type_to_page
)
