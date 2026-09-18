"""The types the runner and the Browser-Use agent run exchange.

BrowserTaskRunner owns everything about a run that is not the stepping
itself: the progress card, the human handoff, cancellation, the budgets, the
metering, the replay link. The agent run owns only deciding and executing the
steps, and never learns about SSE, Redis, bots or live-view links: it reaches
back through RunHooks and returns a RunOutcome.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter

from app.schemas.browser import BrowserAction, BrowserActionOutput

# Per-action results, keyed to the step whose rows the thread mirror emitted.
# Awaitable: the mirror publishes them, and a publish crosses a process boundary.
ActionResultsFn = Callable[[int, list[BrowserActionOutput]], Awaitable[None]]


@dataclass(frozen=True)
class BrowserRunConfig:
    """One browser run's tuning knobs; every field is a BROWSER_USE_* setting."""

    max_steps: int
    max_actions_per_step: int
    task_timeout_seconds: int
    step_timeout_seconds: int
    handoff_timeout_seconds: int
    stream_screenshots: bool
    solve_captcha: bool
    flash_mode: bool = True


@dataclass(frozen=True)
class StepFrame:
    """One executed step, captured off the agent's loop for a deferred emit."""

    index: int
    goal: str
    actions: list[BrowserAction]
    url: str | None
    title: str | None
    raw_screenshot: str | None
    since_prev_ms: int


@dataclass(frozen=True)
class RunUsage:
    """One model's token spend over a run, under the name it is billed as."""

    model_name: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RunOutcome:
    """What the agent run produced, before the runner judges cancellation."""

    success: bool
    summary: str
    usage: list[RunUsage] = field(default_factory=list)


@dataclass(frozen=True)
class RunHooks:
    """The runner's side of the contract, as the agent run sees it.

    step is deliberately synchronous: the runner schedules the emit (the
    screenshot upload is a CDN round-trip) so recording a step never taxes the
    agent's loop.
    """

    step: Callable[[StepFrame], None]
    takeover: Callable[[str, str], Awaitable[str | None]]
    should_stop: Callable[[], Awaitable[bool]]
    action_results: ActionResultsFn | None = None


class StepClock:
    """Wall-clock between steps — the agent's think + execute time, per step."""

    def __init__(self) -> None:
        self._last = 0.0

    def tick(self) -> int:
        """Milliseconds since the previous step; 0 for the first one."""
        now = perf_counter()
        elapsed = round((now - self._last) * 1000) if self._last else 0
        self._last = now
        return elapsed
