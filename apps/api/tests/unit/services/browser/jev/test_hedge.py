"""The hedged writer call: a slow first answer is beaten by a spare, failures fall through."""

import asyncio

import pytest

from app.services.browser.jev.hedge import first_answer

pytestmark = pytest.mark.unit


def _calls(*behaviours):
    """Each call runs the next behaviour: (seconds to wait, value or exception)."""
    started: list[int] = []

    async def call():
        index = len(started)
        started.append(index)
        delay, outcome = behaviours[index]
        await asyncio.sleep(delay)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return call, started


async def test_a_fast_answer_starts_no_spare() -> None:
    call, started = _calls((0.0, "first"))

    assert await first_answer(call, hedge_after=0.05, deadline=1) == "first"
    assert started == [0]


async def test_a_slow_first_call_is_beaten_by_the_spare() -> None:
    call, started = _calls((1.0, "slow"), (0.0, "spare"))

    assert await first_answer(call, hedge_after=0.05, deadline=2) == "spare"
    assert started == [0, 1]


async def test_a_failure_is_raised_not_retried() -> None:
    call, started = _calls((0.0, RuntimeError("boom")), (0.0, "spare"))

    with pytest.raises(RuntimeError, match="boom"):
        await first_answer(call, hedge_after=10, deadline=20)
    assert started == [0]


async def test_the_spare_still_answers_when_the_slow_first_call_fails() -> None:
    call, _ = _calls((0.2, RuntimeError("boom")), (0.3, "spare"))

    assert await first_answer(call, hedge_after=0.05, deadline=2) == "spare"


async def test_no_answer_within_the_deadline_times_out() -> None:
    call, _ = _calls((5.0, "late"), (5.0, "late"))

    with pytest.raises(TimeoutError):
        await first_answer(call, hedge_after=0.05, deadline=0.2)


async def test_the_spare_wins_while_the_first_call_never_returns_and_the_first_is_cancelled() -> (
    None
):
    first_cancelled = asyncio.Event()
    started: list[str] = []

    async def call() -> str:
        started.append("call")
        if len(started) == 1:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                first_cancelled.set()
                raise
        return "spare"

    assert await first_answer(call, hedge_after=0.01, deadline=5) == "spare"
    await asyncio.sleep(0)
    assert first_cancelled.is_set()


async def test_only_one_spare_is_started_however_slow_both_calls_are() -> None:
    call, started = _calls((0.3, "first"), (0.3, "spare"))

    assert await first_answer(call, hedge_after=0.01, deadline=2) == "first"
    assert started == [0, 1]


async def test_every_call_failing_raises_the_last_failure() -> None:
    call, started = _calls((0.1, RuntimeError("first")), (0.0, ValueError("spare")))

    with pytest.raises(RuntimeError, match="first"):
        await first_answer(call, hedge_after=0.01, deadline=2)
    assert started == [0, 1]


async def test_the_timeout_names_the_deadline() -> None:
    call, _ = _calls((5.0, "late"), (5.0, "late"))

    with pytest.raises(TimeoutError, match="no answer within 0s"):
        await first_answer(call, hedge_after=0.05, deadline=0.2)


async def test_a_deadline_already_spent_times_out_without_starting_a_spare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio.get_running_loop(), "time", lambda: 100.0)
    call, started = _calls((0.0, "instant"))

    with pytest.raises(TimeoutError):
        await first_answer(call, hedge_after=0.05, deadline=0)
    assert 1 not in started
