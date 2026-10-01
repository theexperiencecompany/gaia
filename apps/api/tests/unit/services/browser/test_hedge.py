"""A slow call gets one spare; the first answer wins, the loser's answer is still handed over, errors are not retried, and the deadline holds."""

from __future__ import annotations

import asyncio

import pytest

from app.services.browser.hedge import first_answer

pytestmark = pytest.mark.unit


class _Calls:
    """Each call waits its scripted delay, or until its gate opens, then answers or raises."""

    def __init__(self, *script: tuple[float | asyncio.Event, object]) -> None:
        self._script = list(script)
        self.started = 0
        #: Set when a call is cut off before it answered.
        self.cut_off = asyncio.Event()
        #: Set when every call started has ended, however it ended.
        self.all_ended = asyncio.Event()
        self._running = 0

    async def __call__(self) -> object:
        self.started += 1
        self._running += 1
        wait, outcome = self._script[self.started - 1]
        try:
            if isinstance(wait, asyncio.Event):
                await wait.wait()
            else:
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            self.cut_off.set()
            raise
        finally:
            self._running -= 1
            if self._running == 0:
                self.all_ended.set()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _unexpected(late: object) -> None:
    raise AssertionError(f"no call should lose and answer: {late}")


async def test_a_fast_call_is_never_hedged() -> None:
    calls = _Calls((0, "first"))

    assert await first_answer(calls, hedge_after=0.05, deadline=1, on_late=_unexpected) == "first"
    assert calls.started == 1


async def test_a_slow_call_gets_one_spare_and_the_spares_answer_wins() -> None:
    calls = _Calls((3600, "stalled"), (0, "spare"))

    assert await first_answer(calls, hedge_after=0.01, deadline=30, on_late=_unexpected) == "spare"
    assert calls.started == 2


async def test_an_error_is_not_hedged_and_is_raised() -> None:
    calls = _Calls((0, ValueError("refused")))

    with pytest.raises(ValueError, match="refused"):
        await first_answer(calls, hedge_after=0.05, deadline=1, on_late=_unexpected)
    assert calls.started == 1


async def test_a_spare_that_fails_leaves_the_slow_call_to_answer() -> None:
    calls = _Calls((0.05, "slow"), (0, ValueError("spare failed")))

    assert await first_answer(calls, hedge_after=0.01, deadline=1, on_late=_unexpected) == "slow"


async def test_no_answer_within_the_deadline_times_out() -> None:
    calls = _Calls((10, "late"), (10, "late too"))

    with pytest.raises(TimeoutError, match="no answer within"):
        await first_answer(calls, hedge_after=0.01, deadline=0.05, on_late=_unexpected)
    assert calls.started == 2


async def test_the_losing_call_runs_to_its_end_and_its_answer_is_handed_over() -> None:
    release = asyncio.Event()
    calls = _Calls((release, "slow"), (0, "spare"))
    late: list[object] = []

    assert await first_answer(calls, hedge_after=0.01, deadline=5, on_late=late.append) == "spare"
    release.set()
    await asyncio.wait_for(calls.all_ended.wait(), timeout=5)
    await asyncio.sleep(0)  # the loser's done-callback runs on the next turn of the loop

    assert late == ["slow"]


async def test_a_losing_call_that_never_answers_is_cut_off_at_the_deadline() -> None:
    calls = _Calls((asyncio.Event(), "stalled"), (0, "spare"))

    assert await first_answer(calls, hedge_after=0.01, deadline=0.1, on_late=_unexpected) == "spare"

    await asyncio.wait_for(calls.cut_off.wait(), timeout=5)


async def test_a_losing_call_that_fails_is_never_handed_over_or_left_unhandled() -> None:
    release = asyncio.Event()
    calls = _Calls((release, ValueError("late failure")), (0, "spare"))
    unhandled: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda loop, context: unhandled.append(context)
    )

    assert await first_answer(calls, hedge_after=0.01, deadline=5, on_late=_unexpected) == "spare"
    release.set()
    await asyncio.wait_for(calls.all_ended.wait(), timeout=5)
    await asyncio.sleep(0)  # the loser's done-callback runs on the next turn of the loop

    assert unhandled == []
