"""A slow call gets one spare; the first answer wins, errors are not retried, and the deadline holds."""

from __future__ import annotations

import asyncio

import pytest

from app.services.browser.hedge import first_answer

pytestmark = pytest.mark.unit


class _Calls:
    """Each call waits its scripted delay, then answers or raises."""

    def __init__(self, *script: tuple[float, object]) -> None:
        self._script = list(script)
        self.started = 0

    async def __call__(self) -> object:
        delay, outcome = self._script[self.started]
        self.started += 1
        await asyncio.sleep(delay)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


async def test_a_fast_call_is_never_hedged() -> None:
    calls = _Calls((0, "first"))

    assert await first_answer(calls, hedge_after=0.05, deadline=1) == "first"
    assert calls.started == 1


async def test_a_slow_call_gets_one_spare_and_the_spares_answer_wins() -> None:
    calls = _Calls((10, "stalled"), (0, "spare"))

    assert await first_answer(calls, hedge_after=0.01, deadline=1) == "spare"
    assert calls.started == 2


async def test_an_error_is_not_hedged_and_is_raised() -> None:
    calls = _Calls((0, ValueError("refused")))

    with pytest.raises(ValueError, match="refused"):
        await first_answer(calls, hedge_after=0.05, deadline=1)
    assert calls.started == 1


async def test_a_spare_that_fails_leaves_the_slow_call_to_answer() -> None:
    calls = _Calls((0.05, "slow"), (0, ValueError("spare failed")))

    assert await first_answer(calls, hedge_after=0.01, deadline=1) == "slow"


async def test_no_answer_within_the_deadline_times_out() -> None:
    calls = _Calls((10, "late"), (10, "late too"))

    with pytest.raises(TimeoutError):
        await first_answer(calls, hedge_after=0.01, deadline=0.05)
    assert calls.started == 2
