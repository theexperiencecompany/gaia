"""Give keystrokes human variance without making the agent slower in any way a user notices.

Browser-Use types character by character on two fixed timers: a 5ms hold between
keyDown and keyUp, then a 1ms gap before the next character
(``_input_text_element_node_impl``; the ``_type_to_page`` fallback uses a single
10ms gap). Every keystroke is therefore identical to the microsecond.

The uniformity is the tell, not the speed. Behavioural checks read
``event.timeStamp`` deltas, and a zero-variance metronome is a pattern no human
hand produces — a signal that survives every fingerprint defence we ship,
because it is emitted by our own input, not by the browser's identity.

Only the *distribution* changes, not the pace: each delay is scaled by a draw
averaging ~1.9x, which costs a ~20-character field on the order of 100ms.
Matching a real person's ~60ms/char would cost a full second per field, and that
is not what defeats the check — the variance is. The residual tell (still faster
than human hands) is accepted deliberately.

The RNG is seeded per user, so one person's typing rhythm stays consistent
across tasks — for the same reason the canvas fingerprint is seeded rather than
random (see services/browser/fingerprint.py).

Scope is deliberately narrow, in two ways. The shim is armed only while a typing
method is on the stack, so the module's scroll-settle, navigation and readback
waits — which use the same float literals — keep their load-bearing timing. And
it is installed by rebinding *the watchdog module's* ``asyncio`` name to a proxy,
never by assigning to ``asyncio.sleep``, which would patch every coroutine in the
process.

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
# Each delay is scaled by a log-normal draw, which is the shape human inter-key
# intervals actually take: mostly clustered, with an occasional long pause where
# the typist thinks. A uniform draw would need a bolt-on "sometimes pause" rule
# to produce that tail, and would wrongly apply it to the key-hold as well.
# mu/sigma give a mean scale of ~1.9x; the cap keeps a tail draw from stalling.
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
    """The stdlib asyncio module with only ``sleep`` swapped, for one module's use."""

    sleep = staticmethod(_sleep)

    # Delegating to an arbitrary module attribute — Any is the honest type here.
    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
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


watchdog_module.asyncio = _AsyncioProxy()  # type: ignore[assignment, attr-defined]
DefaultActionWatchdog._input_text_element_node_impl = _arm_typing_rhythm(  # type: ignore[method-assign, assignment]
    DefaultActionWatchdog._input_text_element_node_impl
)
DefaultActionWatchdog._type_to_page = _arm_typing_rhythm(  # type: ignore[method-assign, assignment]
    DefaultActionWatchdog._type_to_page
)
