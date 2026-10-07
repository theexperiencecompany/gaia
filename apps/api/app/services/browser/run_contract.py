"""The types the runner and the Browser-Use agent run exchange.

BrowserTaskRunner owns everything about a run that is not the stepping
itself: the progress card, the human handoff, cancellation, the budgets, the
metering, the replay link. The agent run owns only deciding and executing the
steps, and never learns about SSE, Redis, bots or live-view links: it reaches
back through RunHooks and returns a RunOutcome.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter

from app.config.settings import settings
from app.constants.browser import BrowserRunFailure, EngineSwitchReason, SensitiveCategory
from app.schemas.browser import BrowserAction, BrowserActionOutput, BrowserResultSnapshot

# Per-action results, keyed to the step whose rows the thread mirror emitted.
# Awaitable: the mirror publishes them, and a publish crosses a process boundary.
ActionResultsFn = Callable[[int, list[BrowserActionOutput]], Awaitable[None]]

#: Whether something is waiting (a stop, a user message); asked between Jev decisions.
FlagFn = Callable[[], Awaitable[bool]]
#: The messages the user sent since the last read, oldest first; reading takes them.
TakeMessagesFn = Callable[[], Awaitable[list[str]]]
#: Move the run to the full browser: why, and the page it was on; returns what the agent reads.
SwitchEngineFn = Callable[[EngineSwitchReason, str | None], Awaitable[str]]


@dataclass(frozen=True)
class BrowserRunConfig:
    """One browser run's settings: the BROWSER_USE_* knobs, and the page it starts on."""

    #: Browser-Use's step backstop; the run ends on the agent's own finish or a budget.
    max_steps: int
    max_actions_per_step: int
    task_timeout_seconds: int
    step_timeout_seconds: int
    handoff_timeout_seconds: int
    stream_screenshots: bool
    solve_captcha: bool
    #: Opened before the first decision; Browser-Use's own find of a URL in the
    #: task gives up when the task names more than one.
    start_url: str | None = None

    @classmethod
    def from_settings(cls, start_url: str | None) -> BrowserRunConfig:
        """Return the deployment's run settings for a run starting at start_url."""
        return cls(
            max_steps=settings.BROWSER_USE_MAX_STEPS,
            max_actions_per_step=settings.BROWSER_USE_MAX_ACTIONS_PER_STEP,
            task_timeout_seconds=settings.BROWSER_USE_TASK_TIMEOUT_SECONDS,
            step_timeout_seconds=settings.BROWSER_USE_STEP_TIMEOUT_SECONDS,
            handoff_timeout_seconds=settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS,
            stream_screenshots=settings.BROWSER_USE_STREAM_SCREENSHOTS,
            solve_captcha=settings.BROWSER_USE_SOLVE_CAPTCHA,
            start_url=start_url,
        )


@dataclass(frozen=True)
class StepFrame:
    """One executed step, captured off the agent's loop for a deferred emit."""

    index: int
    #: The session it was captured on; by the deferred emit the run may be on the fallback's.
    session_id: str
    goal: str
    actions: list[BrowserAction]
    url: str | None
    title: str | None
    #: The page's photo as base64 (PNG or JPEG), taken when its url and title were read; None when there is none.
    photo: str | None
    since_prev_ms: int


@dataclass(frozen=True)
class FinishedRun:
    """How a job's run ended, as the job records it: its result card, where, how much work, how long."""

    result: BrowserResultSnapshot
    session_id: str
    #: Browser actions executed, Jev's and the agent's.
    actions: int
    engine_fallback: bool
    run_ms: int
    #: Why the run did not succeed; None when it did.
    failure: BrowserRunFailure | None


@dataclass(frozen=True)
class RunOutcome:
    """What the agent run produced, before the runner judges cancellation."""

    success: bool
    summary: str
    #: Why the agent's own run did not succeed, as its history shows; None when it did.
    failure: BrowserRunFailure | None = None


@dataclass(frozen=True)
class RunHooks:
    """The runner's side of the contract, as the agent run sees it.

    step is deliberately synchronous: the runner schedules the emit (the
    screenshot upload is a CDN round-trip) so recording a step never taxes the
    agent's loop.
    """

    step: Callable[[StepFrame], None]
    takeover: Callable[[str, SensitiveCategory], Awaitable[str | None]]
    should_stop: FlagFn
    user_waiting: FlagFn
    take_user_messages: TakeMessagesFn
    action_results: ActionResultsFn | None = None
    #: Present only while the run is on Obscura with Chrome behind it.
    switch_engine: SwitchEngineFn | None = None


class StepClock:
    """Wall-clock between steps — the agent's think + execute time, per step."""

    def __init__(self) -> None:
        self._last = 0.0  # pragma: no mutate — None is read as falsy by tick() exactly like 0.0

    def tick(self) -> int:
        """Milliseconds since the previous step; 0 for the first one."""
        now = perf_counter()
        elapsed = round((now - self._last) * 1000) if self._last else 0
        self._last = now
        return elapsed
