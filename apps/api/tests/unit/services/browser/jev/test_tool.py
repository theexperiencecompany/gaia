"""The agent's jev action: a goal that went nowhere is never re-sent, and the report carries what Jev saw."""

from __future__ import annotations

from typing import Any

import pytest

from app.constants.browser import JevOperation, JevStop
from app.services.browser.jev.loop import BurstResult, JevStep, OpenedPage
from app.services.browser.jev.tool import JevDelegate, JevParams, report

pytestmark = pytest.mark.unit


def _step(page_changed: bool) -> JevStep:
    return JevStep(
        operation=JevOperation.CLICK,
        label="Next",
        ident="next-btn",
        href="https://site.test/b",
        text=None,
        url="https://site.test/a",
        page_changed=page_changed,
        decision_ms=5,
    )


def _burst(stop: JevStop, *steps: JevStep) -> BurstResult:
    return BurstResult(
        goal="g",
        stop=stop,
        detail="why",
        steps=list(steps),
        url="https://site.test/b",
        title="B",
        text="visible text of B",
        opened=[OpenedPage(url="https://site.test/a", title="A", text="start of A")],
        hidden_frames=[],
    )


class _Runner:
    def __init__(self, *results: BurstResult) -> None:
        self._results = list(results)
        self.goals: list[str] = []

    async def burst(self, goal: str, start_url: str | None) -> BurstResult:
        self.goals.append(goal)
        return self._results.pop(0)


def _delegate(runner: _Runner) -> tuple[JevDelegate, list[Any]]:
    emitted: list[Any] = []

    async def _emit(actions: Any, url: str, title: str) -> None:
        emitted.append((actions, url))

    return JevDelegate(runner_for=lambda: runner, emit=_emit), emitted  # type: ignore[arg-type,return-value]  # a scripted runner


async def test_a_goal_jev_made_no_progress_on_is_refused_the_second_time() -> None:
    runner = _Runner(_burst(JevStop.NO_PROGRESS, _step(page_changed=False)))
    delegate, _ = _delegate(runner)

    await delegate.run(JevParams(goal="Open the Pricing page"))
    again = await delegate.run(JevParams(goal="  open the pricing   PAGE "))

    assert again.error is not None
    assert runner.goals == ["Open the Pricing page"]


async def test_a_goal_the_site_failed_may_be_sent_again() -> None:
    runner = _Runner(_burst(JevStop.LOAD_STALLED), _burst(JevStop.DONE, _step(page_changed=True)))
    delegate, _ = _delegate(runner)

    await delegate.run(JevParams(goal="open the pricing page"))
    second = await delegate.run(JevParams(goal="open the pricing page"))

    assert second.error is None
    assert len(runner.goals) == 2


async def test_a_burst_that_acted_gets_one_card_with_its_actions() -> None:
    delegate, emitted = _delegate(_Runner(_burst(JevStop.DONE, _step(page_changed=True))))

    await delegate.run(JevParams(goal="go next"))

    [(actions, url)] = emitted
    assert (len(actions), url) == (1, "https://site.test/b")


def test_the_report_names_each_action_its_target_and_the_pages_jev_read() -> None:
    text = report(_burst(JevStop.DONE, _step(page_changed=True)))

    assert "Stopped: done. why" in text
    assert "1. CLICK Next [#next-btn] -> https://site.test/b (page changed)" in text
    assert "start of A" in text
    assert "Now on: B (https://site.test/b)" in text
    assert "visible text of B" in text
