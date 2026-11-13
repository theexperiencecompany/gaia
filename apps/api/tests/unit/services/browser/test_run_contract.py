"""The step clock that stamps each step frame with how long the agent took since the last one."""

import pytest

from app.services.browser import run_contract
from app.services.browser.run_contract import StepClock

pytestmark = pytest.mark.unit


def test_each_tick_reports_the_milliseconds_since_the_previous_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter([10.0, 12.0, 13.5])
    monkeypatch.setattr(run_contract, "perf_counter", lambda: next(readings))
    clock = StepClock()

    ticks = [clock.tick(), clock.tick(), clock.tick()]

    assert ticks == [0, 2000, 1500]
