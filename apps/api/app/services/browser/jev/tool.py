"""Jev as a Browser-Use action: the agent hands it a goal, Jev drives, the agent reads what it did.

The run starts with this action as the Agent's initial action, so the first
burst costs no agent model call; the agent may call it again with a sharper
goal. The result the agent reads is written from
the burst's own record: every action, every line captured verbatim, where
Jev ended and why.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.constants.browser import JEV_REPORT_PAGE_TEXT_CHARS, JevOperation, JevStop
from app.schemas.browser import BrowserAction
from app.services.browser.jev.loop import BurstResult, JevRunner, JevStep

if TYPE_CHECKING:
    from browser_use import Tools
    from browser_use.agent.views import ActionResult

#: Emits one card for a finished burst: its caption source, and the page it ended on.
BurstEmitFn = Callable[[list[BrowserAction], str, str], Awaitable[None]]
#: Builds the burst runner, on the Agent's browser session, at the first burst.
RunnerFactory = Callable[[], JevRunner]

JEV_ACTION = "jev"

_DESCRIPTION = (
    "Hand a goal to Jev, the fast page operator: it clicks, types, selects, scrolls and "
    "navigates step by step (~1 s per step) until the goal is done or it is stuck, then "
    "reports every action, the page text lines it captured verbatim, and where it stopped. "
    "Use it for any multi-step on-page work. Give a concrete, self-contained goal naming the "
    "values to type (quote them) and what counts as done. Never give Jev the same goal again "
    "after it made no progress on it."
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
        "Jev judged the goal done. The current page is already in your browser state and the "
        "captures are below: if they answer the task, finish now."
    ),
    JevStop.BLOCKED: "Jev found nothing on this page that advances the goal.",
    JevStop.NEEDS_INPUT: "The goal gives no value for a field: ask the user, or hand the step over.",
    JevStop.NO_PROGRESS: "Jev's last actions changed nothing on the page.",
    JevStop.CYCLE: "Jev went back and forth without progress.",
    JevStop.MAX_ACTIONS: "Jev used its action budget for one burst; it may be partway.",
    JevStop.COVERED: "An overlay or hidden control blocks the target; deal with it yourself.",
    JevStop.STALE: "The page kept changing under Jev's decisions.",
    JevStop.CAPTCHA: "A CAPTCHA is on the page: hand it to the user with solve_captcha_with_help.",
    JevStop.UNRESPONSIVE: "The page stopped answering; an input sent just then may or may not have landed.",
    JevStop.USER_MESSAGE: "The user sent a message; read it (it is in your task) before going on.",
    JevStop.STOPPED: "The run is stopping.",
    JevStop.GATEWAY: "Jev could not decide; continue yourself.",
}


class JevParams(BaseModel):
    goal: str = Field(description="What Jev should achieve, self-contained, with every value quoted.")
    start_url: str | None = Field(default=None, description="Open this page first; omit to start where the browser is.")


def _normalized(goal: str) -> str:
    return " ".join(goal.lower().split())


def _step_action(step: JevStep) -> BrowserAction:
    name = _STEP_ACTION[step.operation]
    inputs: dict[str, object] = {}
    if step.operation is JevOperation.TYPE_TEXT and step.text is not None:
        inputs["text"] = step.text
    elif step.operation is JevOperation.SELECT:
        inputs["text"] = step.label.split(" → ")[-1]
    elif step.operation is JevOperation.NAVIGATE:
        inputs["url"] = step.label.removeprefix("Open ")
    elif step.operation is JevOperation.PRESS_ENTER:
        inputs["keys"] = "Enter"
    target = step.label if step.operation in (JevOperation.CLICK, JevOperation.TYPE_TEXT) else None
    return BrowserAction(name=name, inputs=inputs, target=target)


def report(result: BurstResult) -> str:
    """The burst as the agent reads it: why it stopped, what it did, what it captured, where it is."""
    lines = [f'Jev ran on: "{result.goal}"', f"Stopped: {result.stop.value}. {result.detail} {_STOP_MEANING[result.stop]}"]
    if result.steps:
        lines.append(f"Actions ({len(result.steps)}):")
        for n, step in enumerate(result.steps, 1):
            typed = f' = "{step.text}"' if step.text is not None else ""
            changed = "" if step.page_changed is None else (" (page changed)" if step.page_changed else " (no change)")
            ident = f" [#{step.ident}]" if step.ident else ""
            lines.append(f"  {n}. {step.operation.value} {step.label}{ident}{typed}{changed}")
    else:
        lines.append("Actions: none.")
    if result.captures:
        lines.append("Captured verbatim from the pages (evidence for the answer):")
        lines.extend(f'  - "{c.line}" [{c.title} | {c.url}]' for c in result.captures)
    lines.append(f"Now on: {result.title} ({result.url})")
    if result.text:
        visible = result.text[:JEV_REPORT_PAGE_TEXT_CHARS]
        lines.append(f"Visible text of this page, verbatim:\n{visible}")
    if result.hidden_frames:
        lines.append("Frames on this page Jev cannot see into: " + ", ".join(result.hidden_frames[:5]))
    return "\n".join(lines)


class JevDelegate:
    """The agent's handle on Jev for one run: bursts, and the goals that went nowhere."""

    def __init__(self, *, runner_for: RunnerFactory, emit: BurstEmitFn) -> None:
        self._runner_for = runner_for
        self._emit = emit
        self._runner: JevRunner | None = None
        self._fruitless: set[str] = set()
        self.bursts: list[BurstResult] = []

    async def run(self, params: JevParams) -> ActionResult:
        from browser_use.agent.views import ActionResult  # noqa: PLC0415 -- heavy optional dep

        goal = _normalized(params.goal)
        if goal in self._fruitless:
            return ActionResult(
                error=(
                    "Jev already made no progress on exactly this goal. Act yourself with "
                    "browser actions, or give Jev a different, sharper goal."
                )
            )
        if self._runner is None:
            self._runner = self._runner_for()
        result = await self._runner.burst(params.goal, params.start_url)
        self.bursts.append(result)
        if not result.progressed:
            self._fruitless.add(goal)
        if result.steps:
            await self._emit([_step_action(step) for step in result.steps], result.url, result.title)
        text = report(result)
        return ActionResult(extracted_content=text, long_term_memory=text)


def register_jev(tools: Tools[None], delegate: JevDelegate) -> None:
    """Register the jev action on the agent's tools."""

    @tools.action(_DESCRIPTION, param_model=JevParams)
    async def jev(params: JevParams) -> ActionResult:
        return await delegate.run(params)

    del jev
