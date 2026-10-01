"""Jev as a Browser-Use action: the agent hands it a goal, Jev drives, the agent reads what it did.

The run starts with this action as the Agent's initial action, so the first
burst costs no agent model call; the agent may call it again with a sharper
goal. The result the agent reads is written from
the burst's own record: every action, where Jev ended and why, and that
page's text.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from browser_use import Tools
from browser_use.agent.views import ActionResult
from pydantic import BaseModel, Field

from app.constants.browser import (
    JEV_REPORT_OPENED_PAGE_CHARS,
    JEV_REPORT_OPENED_PAGES,
    JEV_REPORT_PAGE_TEXT_CHARS,
    JevOperation,
    JevStop,
)
from app.schemas.browser import BrowserAction
from app.services.browser.jev.loop import BurstResult, JevStep

#: Emits one card for a finished burst: its caption source, and the page it ended on.
BurstEmitFn = Callable[[list[BrowserAction], str, str], Awaitable[None]]


class Bursts(Protocol):
    """What the agent's jev action runs: one burst per goal, on the run's tab."""

    async def burst(self, goal: str, start_url: str | None) -> BurstResult: ...


#: Builds the burst runner, on the Agent's browser session, at the first burst.
RunnerFactory = Callable[[], Bursts]

JEV_ACTION = "jev"

_DESCRIPTION = (
    "Hand a goal to Jev, the fast page operator: it clicks, types, selects, scrolls and "
    "navigates step by step (~1 s per step) until the goal is done or it is stuck, then "
    "reports every action (with each clicked link's URL), where it stopped and why, and the "
    "text of the pages it opened. Use it for sequences of interactions: filling forms, "
    "searching and choosing, clicking through pages. Jev only operates controls: it cannot "
    "read, summarise, count or compare content, so never ask it to; open the page and use "
    "extract yourself for that. Give a concrete, self-contained goal naming the values to "
    "type (quote them) and what counts as done. When the browser is on a blank tab, pass "
    "start_url with the page to start on. Never give Jev the same goal again after it made no "
    "progress on it."
)

# Jev's steps as the Browser-Use actions the card and the thread already know how to name.
_STEP_ACTION = {
    JevOperation.CLICK: "click",
    JevOperation.TYPE_TEXT: "input",
    JevOperation.SELECT: "select_dropdown",
    JevOperation.PRESS_ENTER: "send_keys",
    JevOperation.SCROLL_DOWN: "scroll",
    JevOperation.SCROLL_UP: "scroll",
    JevOperation.WAIT: "wait",
    JevOperation.NAVIGATE: "navigate",
    JevOperation.GO_BACK: "go_back",
}

_STOP_MEANING = {
    JevStop.DONE: (
        "Jev judged the goal done. The page it ended on is already in your browser state and "
        "its text is below: if they answer the task, finish now."
    ),
    JevStop.BLOCKED: "Jev found nothing on this page that advances the goal.",
    JevStop.NEEDS_INPUT: "The goal gives no value for a field: ask the user, or hand the step over.",
    JevStop.SECRET_WITHHELD: (
        "A secret is typed only on the site it was given for, and this page is on another; "
        "nothing was typed."
    ),
    JevStop.NO_PROGRESS: "Jev's last actions changed nothing on the page.",
    JevStop.CYCLE: "Jev went back and forth without progress.",
    JevStop.MAX_ACTIONS: "Jev used its action budget for one burst; it may be partway.",
    JevStop.MAX_DECISIONS: "Jev used its decision budget for one burst without settling on the page.",
    JevStop.COVERED: "An overlay or hidden control blocks the target; deal with it yourself.",
    JevStop.STALE: "The page kept changing under Jev's decisions.",
    JevStop.UNRESPONSIVE: "The page stopped answering; an input sent just then may or may not have landed.",
    JevStop.LOADING: "The page had not finished loading, so Jev could not read it; nothing was done on it.",
    JevStop.NO_PAGE: "Pass start_url with the page to start on, or open the page yourself.",
    JevStop.USER_MESSAGE: "The user sent a message; read it (it is in your task) before going on.",
    JevStop.STOPPED: "The run is stopping.",
    JevStop.GATEWAY: "Jev could not decide; continue yourself.",
    JevStop.LOAD_STALLED: "The site did not answer in time; the tab stayed on the page before it.",
    JevStop.NAVIGATION_FAILED: "The page could not be opened; the tab stayed where it was.",
    JevStop.FIELD_UNFOCUSED: "Clicking the field did not focus it, so nothing was typed.",
    JevStop.TAB_UNAVAILABLE: "The tab Jev was driving is gone or refused it; check which tab is open.",
    JevStop.PAGE_SCRIPT_ERROR: "Jev could not read this page (its script failed here); continue yourself.",
}


#: Whether an action changed the page, as its report line says.
_CHANGED = {True: " (page changed)", False: " (no change)"}


class JevParams(BaseModel):
    goal: str = Field(
        description="What Jev should achieve, self-contained, with every value quoted."
    )
    start_url: str | None = Field(
        default=None,
        description="Open this page first; omit to start where the browser is (never a blank tab).",
    )


def _step_action(step: JevStep) -> BrowserAction:
    name = _STEP_ACTION[step.operation]
    inputs: dict[str, object] = {}
    if step.operation is JevOperation.TYPE_TEXT and step.text is not None:
        inputs["text"] = step.text
    elif step.option is not None:
        inputs["text"] = step.option
    elif step.opened is not None:
        inputs["url"] = step.opened
    elif step.operation is JevOperation.PRESS_ENTER:
        inputs["keys"] = "Enter"
    target = step.label if step.operation in (JevOperation.CLICK, JevOperation.TYPE_TEXT) else None
    return BrowserAction(name=name, inputs=inputs, target=target)


def _step_line(n: int, step: JevStep) -> str:
    """Return one action as the report lists it: what it targeted, set or typed, and what changed."""
    ident = f" [#{step.ident}]" if step.ident else ""
    link = f" -> {step.href}" if step.href else ""
    chosen = f' -> "{step.option}"' if step.option is not None else ""
    typed = f' = "{step.text}"' if step.text is not None else ""
    held = f" (the field holds {step.held})" if step.held is not None else ""
    changed = "" if step.page_changed is None else _CHANGED[step.page_changed]
    return f"  {n}. {step.operation.value} {step.label}{ident}{link}{chosen}{typed}{held}{changed}"


def _page_lines(result: BurstResult) -> list[str]:
    """Return what the report says of the page Jev ended on: its text, controls left out and hidden frames."""
    lines = [f"Now on: {result.title} ({result.url})"]
    if result.text:
        lines.append(
            f"Visible text of this page, verbatim:\n{result.text[:JEV_REPORT_PAGE_TEXT_CHARS]}"
        )
    if result.omitted_controls:
        lines.append(
            f"This page has {result.omitted_controls} more controls than Jev reads; it saw "
            "only the first ones in the page's order."
        )
    if result.hidden_frames:
        lines.append(
            "Frames on this page Jev cannot see into: " + ", ".join(result.hidden_frames[:5])
        )
    return lines


def report(result: BurstResult) -> str:
    """Return the burst as the agent reads it: why it stopped, what it did, and the page it ended on."""
    lines = [
        f'Jev ran on: "{result.goal}"',
        f"Stopped: {result.stop.value}. {result.detail} {_STOP_MEANING[result.stop]}",
    ]
    if result.steps:
        lines.append(f"Actions ({len(result.steps)}):")
        lines.extend(_step_line(n, step) for n, step in enumerate(result.steps, 1))
    else:
        lines.append("Actions: none.")
    earlier = result.opened[-JEV_REPORT_OPENED_PAGES:]
    if earlier:
        lines.append("Other pages Jev opened in this burst, with the start of their text:")
        lines.extend(
            f"--- {page.title} ({page.url})\n{page.text[:JEV_REPORT_OPENED_PAGE_CHARS]}"
            for page in earlier
        )
    return "\n".join([*lines, *_page_lines(result)])


class JevDelegate:
    """The agent's handle on Jev for one run: one runner, built at the first burst."""

    def __init__(self, *, runner_for: RunnerFactory, emit: BurstEmitFn) -> None:
        self._runner_for = runner_for
        self._emit = emit
        self._runner: Bursts | None = None

    async def run(self, params: JevParams) -> ActionResult:
        if self._runner is None:
            self._runner = self._runner_for()
        result = await self._runner.burst(params.goal, params.start_url)
        if result.steps:
            await self._emit(
                [_step_action(step) for step in result.steps], result.url, result.title
            )
        text = report(result)
        return ActionResult(extracted_content=text, long_term_memory=text)


def register_jev(tools: Tools[None], delegate: JevDelegate) -> None:
    """Register the jev action on the agent's tools."""

    @tools.action(_DESCRIPTION, param_model=JevParams)
    async def jev(params: JevParams) -> ActionResult:
        return await delegate.run(params)

    del jev
