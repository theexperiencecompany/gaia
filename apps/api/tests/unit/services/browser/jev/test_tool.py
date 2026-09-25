"""The agent's jev action: a goal that went nowhere is never re-sent, and the report carries what Jev saw."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.constants.browser import JEV_REPEATED_GOAL_REFUSAL, JevOperation, JevStop
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
        self.start_urls: list[str | None] = []

    async def burst(self, goal: str, start_url: str | None) -> BurstResult:
        self.goals.append(goal)
        self.start_urls.append(start_url)
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

    assert again.error == JEV_REPEATED_GOAL_REFUSAL
    assert runner.goals == ["Open the Pricing page"]


async def test_a_different_goal_after_a_fruitless_one_is_sent() -> None:
    runner = _Runner(
        _burst(JevStop.NO_PROGRESS, _step(page_changed=False)),
        _burst(JevStop.DONE, _step(page_changed=True)),
    )
    delegate, _ = _delegate(runner)

    await delegate.run(JevParams(goal="open the pricing page"))
    second = await delegate.run(JevParams(goal="open the plans page"))

    assert second.error is None
    assert runner.goals == ["open the pricing page", "open the plans page"]


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


async def test_the_agent_reads_the_report_now_and_keeps_it_for_later_steps() -> None:
    runner = _Runner(_burst(JevStop.DONE, _step(page_changed=True)))
    delegate, _ = _delegate(runner)

    result = await delegate.run(JevParams(goal="go next", start_url="https://site.test/a"))

    assert runner.start_urls == ["https://site.test/a"]
    expected = report(_burst(JevStop.DONE, _step(page_changed=True)))
    assert (result.extracted_content, result.long_term_memory) == (expected, expected)


@pytest.mark.parametrize(
    ("step", "name", "inputs", "target"),
    [
        (JevStep(JevOperation.CLICK, "Next", "", "", None, "u", True, 5), "click", {}, "Next"),
        (
            JevStep(JevOperation.TYPE_TEXT, "Name", "", "", "Ada", "u", True, 5),
            "input",
            {"text": "Ada"},
            "Name",
        ),
        (JevStep(JevOperation.TYPE_TEXT, "Name", "", "", None, "u", True, 5), "input", {}, "Name"),
        (
            JevStep(JevOperation.SELECT, "Route → LHR → JFK", "", "", None, "u", True, 5),
            "select_dropdown",
            {"text": "LHR → JFK"},
            None,
        ),
        (
            JevStep(JevOperation.NAVIGATE, "Open https://b.test/", "", "", None, "u", True, 5),
            "navigate",
            {"url": "https://b.test/"},
            None,
        ),
        (
            JevStep(JevOperation.PRESS_ENTER, "Press Enter", "", "", None, "u", True, 5),
            "send_keys",
            {"keys": "Enter"},
            None,
        ),
    ],
)
async def test_each_jev_step_is_shown_on_the_card_as_the_action_it_was(
    step: JevStep, name: str, inputs: dict[str, str], target: str | None
) -> None:
    delegate, emitted = _delegate(_Runner(_burst(JevStop.DONE, step)))

    await delegate.run(JevParams(goal="go"))

    [([action], _)] = emitted
    assert (action.name, action.inputs, action.target) == (name, inputs, target)


def test_a_burst_with_no_actions_reports_so_and_what_it_could_not_see() -> None:
    result = _burst(JevStop.BLOCKED)
    result.hidden_frames.extend(f"https://ads.test/{n}" for n in range(7))

    assert report(result) == (
        'Jev ran on: "g"\n'
        "Stopped: blocked. why Jev found nothing on this page that advances the goal.\n"
        "Actions: none.\n"
        "Other pages Jev opened in this burst, with the start of their text:\n"
        "--- A (https://site.test/a)\nstart of A\n"
        "Now on: B (https://site.test/b)\n"
        "Visible text of this page, verbatim:\nvisible text of B\n"
        "Frames on this page Jev cannot see into: "
        + ", ".join(f"https://ads.test/{n}" for n in range(5))
    )


def test_each_action_line_says_what_it_targeted_and_whether_the_page_changed() -> None:
    steps = [
        JevStep(JevOperation.CLICK, "Next", "next-btn", "https://site.test/b", None, "u", True, 5),
        JevStep(JevOperation.TYPE_TEXT, "Name", "", "", "Ada", "u", False, 5),
        JevStep(JevOperation.SCROLL_DOWN, "Scroll down", "", "", None, "u", None, 5),
    ]
    result = replace(_burst(JevStop.DONE, *steps), opened=[], text="")

    lines = report(result).split("\n")

    assert lines[2:6] == [
        "Actions (3):",
        "  1. CLICK Next [#next-btn] -> https://site.test/b (page changed)",
        '  2. TYPE_TEXT Name = "Ada" (no change)',
        "  3. SCROLL_DOWN Scroll down",
    ]
    assert lines[6:] == ["Now on: B (https://site.test/b)"]
