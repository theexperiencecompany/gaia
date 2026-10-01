"""A slow call gets one spare; the first answer wins, the loser's answer is still handed over, errors are not retried, and the deadline holds.

Every ordering a test asserts is set by an event it opens, never by how long
something takes: a call that must not answer waits on an event nobody sets.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.browser.hedge import first_answer

pytestmark = pytest.mark.unit

#: Long enough that no test ever reaches it: the spare is started only by the
#: tests that set a short one, and a deadline only ends the tests about it.
_NEVER = 60.0


class _Calls:
    """Each call waits for its gate (None answers at once), then answers or raises."""

    def __init__(self, *script: tuple[asyncio.Event | None, object]) -> None:
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
        gate, outcome = self._script[self.started - 1]
        try:
            if gate is not None:
                await gate.wait()
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


async def _loser_settled(calls: _Calls) -> None:
    await asyncio.wait_for(calls.all_ended.wait(), timeout=_NEVER)
    await asyncio.sleep(0)  # the loser's done-callback runs on the next turn of the loop


async def test_a_call_that_answers_is_never_hedged() -> None:
    calls = _Calls((None, "first"))

    assert await first_answer(calls, hedge_after=_NEVER, deadline=_NEVER, on_late=_unexpected) == (
        "first"
    )
    assert calls.started == 1


async def test_a_slow_call_gets_one_spare_and_the_spares_answer_wins() -> None:
    calls = _Calls((asyncio.Event(), "stalled"), (None, "spare"))

    assert await first_answer(calls, hedge_after=0, deadline=_NEVER, on_late=_unexpected) == (
        "spare"
    )
    assert calls.started == 2


async def test_an_error_is_not_hedged_and_is_raised() -> None:
    calls = _Calls((None, ValueError("refused")))

    with pytest.raises(ValueError, match="refused"):
        await first_answer(calls, hedge_after=_NEVER, deadline=_NEVER, on_late=_unexpected)
    assert calls.started == 1


async def test_a_spare_that_fails_leaves_the_slow_call_to_answer() -> None:
    release = asyncio.Event()
    started = 0

    async def _call() -> object:
        nonlocal started
        started += 1
        if started == 1:
            await release.wait()
            return "slow"
        release.set()
        raise ValueError("spare failed")

    assert await first_answer(_call, hedge_after=0, deadline=_NEVER, on_late=_unexpected) == "slow"


async def test_no_answer_within_the_deadline_times_out() -> None:
    calls = _Calls((asyncio.Event(), "late"), (asyncio.Event(), "late too"))

    with pytest.raises(TimeoutError, match="no answer within"):
        await first_answer(calls, hedge_after=0, deadline=0.05, on_late=_unexpected)
    assert calls.started == 2


async def test_the_losing_call_runs_to_its_end_and_its_answer_is_handed_over() -> None:
    release = asyncio.Event()
    calls = _Calls((release, "slow"), (None, "spare"))
    late: list[object] = []

    assert await first_answer(calls, hedge_after=0, deadline=_NEVER, on_late=late.append) == (
        "spare"
    )
    release.set()
    await _loser_settled(calls)

    assert late == ["slow"]


async def test_a_losing_call_that_never_answers_is_cut_off_at_the_deadline() -> None:
    calls = _Calls((asyncio.Event(), "stalled"), (None, "spare"))

    assert await first_answer(calls, hedge_after=0, deadline=0.1, on_late=_unexpected) == "spare"

    await asyncio.wait_for(calls.cut_off.wait(), timeout=_NEVER)


async def test_a_losing_call_that_fails_is_never_handed_over_or_left_unhandled() -> None:
    release = asyncio.Event()
    calls = _Calls((release, ValueError("late failure")), (None, "spare"))
    unhandled: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda loop, context: unhandled.append(context)
    )

    assert await first_answer(calls, hedge_after=0, deadline=_NEVER, on_late=_unexpected) == (
        "spare"
    )
    release.set()
    await _loser_settled(calls)

    assert unhandled == []
