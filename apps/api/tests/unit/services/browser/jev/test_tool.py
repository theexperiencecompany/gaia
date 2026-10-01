"""The agent's jev action: one card per burst that acted, and a report of what Jev did and saw."""

from __future__ import annotations

from dataclasses import replace
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

    return JevDelegate(runner_for=lambda: runner, emit=_emit), emitted


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
        (JevStep(JevOperation.CLICK, "Next", "", "", None, "u", True), "click", {}, "Next"),
        (
            JevStep(JevOperation.TYPE_TEXT, "Name", "", "", "Ada", "u", True),
            "input",
            {"text": "Ada"},
            "Name",
        ),
        (JevStep(JevOperation.TYPE_TEXT, "Name", "", "", None, "u", True), "input", {}, "Name"),
        (
            JevStep(JevOperation.SELECT, "Route", "", "", None, "u", True, option="LHR → JFK"),
            "select_dropdown",
            {"text": "LHR → JFK"},
            None,
        ),
        (
            JevStep(
                JevOperation.NAVIGATE,
                "Open https://b.test/",
                "",
                "",
                None,
                "u",
                True,
                opened="https://b.test/",
            ),
            "navigate",
            {"url": "https://b.test/"},
            None,
        ),
        (
            JevStep(JevOperation.PRESS_ENTER, "Press Enter", "", "", None, "u", True),
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


def test_each_action_line_says_what_it_targeted_set_typed_and_whether_the_page_changed() -> None:
    steps = [
        JevStep(JevOperation.CLICK, "Next", "next-btn", "https://site.test/b", None, "u", True),
        JevStep(JevOperation.TYPE_TEXT, "Phone", "", "", "5551234", "u", False, held='"5551"'),
        JevStep(JevOperation.SELECT, "Size", "", "", None, "u", True, option="Large"),
        JevStep(JevOperation.SCROLL_DOWN, "Scroll down", "", "", None, "u", None),
    ]
    result = replace(_burst(JevStop.DONE, *steps), opened=[], text="", omitted_controls=12)

    lines = report(result).split("\n")

    assert lines[2:7] == [
        "Actions (4):",
        "  1. CLICK Next [#next-btn] -> https://site.test/b (page changed)",
        '  2. TYPE_TEXT Phone = "5551234" (the field holds "5551") (no change)',
        '  3. SELECT Size -> "Large" (page changed)',
        "  4. SCROLL_DOWN Scroll down",
    ]
    assert lines[7] == "Now on: B (https://site.test/b)"
    assert lines[8] == (
        "This page has 12 more controls than Jev reads; it saw only the first ones in the "
        "page's order."
    )
