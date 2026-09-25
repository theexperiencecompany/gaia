"""The engine watchdog: strikes only on consecutive unanswered reads, a bounded unwind, and a trail on the wide event.

Driven directly against run_watched with a scripted host, so each read and each
pause is under the test's control; the runner-level journeys (a frozen engine
moving the run to the fallback) live in test_runner.py.
"""

import asyncio
from collections.abc import Callable, Iterator
from itertools import chain, repeat
from typing import Any

import pytest

from app.constants.browser import BROWSER_ENGINE_WATCH_STRIKES, EngineFailure
from app.services.browser import engine_watchdog
from app.services.browser.engine_watchdog import run_watched
from app.services.browser.run_contract import RunOutcome
from app.services.browser.session import BrowserHostSession
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

STRIKES = BROWSER_ENGINE_WATCH_STRIKES
GONE = EngineFailure.SESSION_GONE
_SESSION = BrowserHostSession(
    session_id="s-1",
    cdp_url="ws://host/cdp",
    live_view_url="https://host/live",
    context_id="ctx",
    host_url="http://host",
)
_WATCH = {"session_id": "s-1", "operation": "engine_watch"}


@pytest.fixture(autouse=True)
def fast_beat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_CANCEL_GRACE_SECONDS", 0.2)


class _Host:
    """The host's liveness answers, one per read, in order."""

    def __init__(self, answers: Iterator[EngineFailure | None]) -> None:
        self.reads = 0
        self._answers = answers

    async def __call__(self, session: BrowserHostSession) -> EngineFailure | None:
        self.reads += 1
        return next(self._answers)


def _host(monkeypatch: pytest.MonkeyPatch, *answers: EngineFailure | None) -> _Host:
    """Stand in for a host giving these answers, then reporting the engine gone for good."""
    host = _Host(chain(answers, repeat(GONE)))
    monkeypatch.setattr(engine_watchdog, "engine_failure", host)
    return host


class _Paused:
    """The runner's paused() read: True on the listed calls (0-based), False otherwise."""

    def __init__(self, *paused_calls: int) -> None:
        self._paused_calls = set(paused_calls)
        self._calls = 0

    def __call__(self) -> bool:
        call = self._calls
        self._calls += 1
        return call in self._paused_calls


class _StuckRun:
    """A step that never finishes, whose teardown takes a few loop turns once cancelled."""

    def __init__(self, *, ignores_cancel: bool = False) -> None:
        self.started = asyncio.Event()
        self.cancels_seen = 0
        self.unwound = False
        self.abandoned = False
        self._ignores_cancel = ignores_cancel
        self.release = asyncio.Event()
        #: Whether the run's own CDP connection answers the watchdog's probe.
        self.answers = True
        self.probes = 0

    async def execute(self, task: str) -> RunOutcome:
        self.started.set()
        while True:
            try:
                await self.release.wait()
                return RunOutcome(success=True, summary="released")
            except asyncio.CancelledError:
                self.cancels_seen += 1
                if self._ignores_cancel:
                    continue
                for _ in range(5):
                    await asyncio.sleep(0)
                self.unwound = True
                raise

    async def abandon(self) -> None:
        self.abandoned = True

    async def connection_answers(self) -> bool:
        self.probes += 1
        return self.answers


class _QuickRun(_StuckRun):
    async def execute(self, task: str) -> RunOutcome:
        return RunOutcome(success=True, summary="done")


async def _watched(
    run: _StuckRun, paused: Callable[[], bool] = lambda: False
) -> RunOutcome | EngineFailure:
    return await run_watched(run, "t", _SESSION, paused=paused)  # type: ignore[arg-type]  # a duck-typed BrowserAgentRun stand-in


def _strike_warnings(event: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in event.get("warnings", []) if "strikes" in w]


async def test_a_run_that_finishes_returns_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _host(monkeypatch)

    ended = await _watched(_QuickRun())

    assert ended == RunOutcome(success=True, summary="done")


async def test_consecutive_unanswered_reads_cut_the_run_and_say_how_the_engine_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _host(monkeypatch)
    run = _StuckRun()

    async with captured_wide_event() as event:
        ended = await _watched(run)

    assert ended is GONE
    assert host.reads == STRIKES
    assert run.abandoned is True
    # Cut once and waited on: Browser-Use's teardown finished before the switch went ahead.
    assert (run.cancels_seen, run.unwound) == (1, True)
    assert [(w["strikes"], w["engine_failure"], w["browser"]) for w in _strike_warnings(event)] == [
        (n, GONE.value, _WATCH) for n in range(1, STRIKES + 1)
    ]
    assert all(w["msg"] for w in _strike_warnings(event))
    # A run that unwound inside its grace leaves no complaint about it.
    assert len(event["warnings"]) == STRIKES


async def test_a_run_whose_own_connection_stops_answering_is_cut_while_the_host_says_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Obscura serves each CDP connection on its own thread: a page wedging the run's
    # connection leaves the engine answering the host, and the run must still move.
    host = _host(monkeypatch, *[None] * 10)
    run = _StuckRun()
    run.answers = False

    ended = await asyncio.wait_for(_watched(run), timeout=2)

    assert ended is EngineFailure.UNRESPONSIVE
    assert (host.reads, run.probes) == (STRIKES, STRIKES)
    assert run.abandoned is True


async def test_an_answered_read_between_misses_starts_the_count_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _host(monkeypatch, *[GONE] * (STRIKES - 1), None)

    ended = await _watched(_StuckRun())

    assert ended is GONE
    assert host.reads == (STRIKES - 1) + 1 + STRIKES


async def test_a_pause_between_misses_starts_the_count_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _host(monkeypatch)
    # Each unpaused beat reads paused() twice (before and after the host read);
    # the beat after STRIKES - 1 misses finds the run waiting on someone.
    paused = _Paused(2 * (STRIKES - 1))

    ended = await _watched(_StuckRun(), paused)

    assert ended is GONE
    assert host.reads == (STRIKES - 1) + STRIKES


async def test_a_miss_read_while_a_handoff_began_does_not_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _host(monkeypatch)
    # The after-read paused() of the STRIKES-th beat: the handoff began mid-read.
    paused = _Paused(2 * (STRIKES - 1) + 1)

    ended = await _watched(_StuckRun(), paused)

    assert ended is GONE
    assert host.reads == STRIKES + STRIKES


async def test_a_caller_that_gives_up_cancels_the_run_and_waits_for_it_to_unwind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_watchdog, "engine_failure", _Host(repeat(None)))
    run = _StuckRun()
    watched = asyncio.create_task(_watched(run))
    await run.started.wait()

    watched.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watched

    assert (run.cancels_seen, run.unwound) == (1, True)


async def test_a_run_that_will_not_unwind_is_left_after_its_grace_and_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _host(monkeypatch)
    run = _StuckRun(ignores_cancel=True)

    try:
        async with captured_wide_event() as event:
            ended = await asyncio.wait_for(
                _watched(run),
                timeout=2,
            )
    finally:
        run.release.set()

    assert ended is GONE
    outlived = [w for w in event["warnings"] if "strikes" not in w]
    assert len(outlived) == 1
    assert outlived[0]["msg"]
    assert outlived[0]["browser"] == _WATCH
