"""Browser task orchestration, the agent layer.

Run one browser task against an already-created browser-host session through
injected seams: emit (card snapshots to UI and bots), request_handoff (pause
for the human in live-view) and is_cancelled (cooperative cancellation).
Deciding and executing steps is the agent run's job; the runner owns progress,
handoff, cancellation, budgets, metering and the replay link, and never judges
whether a step is sensitive: the agent calls the takeover hook itself.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.constants.browser import (
    BROWSER_RUN_HANDOFF_TIMED_OUT,
    BROWSER_TASK_FAILED_PREFIX,
    MAX_HANDOFFS_PER_TASK,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserCardSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.browser.agent_run import BrowserAgentRun
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.replay import create_replay_link
from app.services.browser.run_contract import (
    ActionResultsFn,
    BrowserRunConfig,
    RunHooks,
    RunOutcome,
    RunUsage,
    StepFrame,
)
from app.services.browser.screenshots import publish_step_screenshot
from app.services.browser.session import BrowserHostSession
from app.services.llm_metering import LLMCallContext, TokenUsage, record_llm_call
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel

EmitFn = Callable[[BrowserCardSnapshot], Awaitable[None]]
RequestHandoffFn = Callable[[HandoffRequest], Awaitable[HandoffOutcome]]
IsCancelledFn = Callable[[], Awaitable[bool]]

__all__ = [
    "ActionResultsFn",
    "BrowserRunConfig",
    "BrowserRunnerCallbacks",
    "BrowserTaskRunner",
]


@dataclass(frozen=True)
class BrowserRunnerCallbacks:
    """The runner's injected seams — how it streams progress, pauses for the human, checks cancellation, and mirrors per-action results into the thread."""

    emit: EmitFn
    request_handoff: RequestHandoffFn
    is_cancelled: IsCancelledFn
    action_results: ActionResultsFn | None = None


class BrowserTaskRunner:
    """Orchestrates one browser task: session, agent run, handoffs, delivery."""

    def __init__(
        self,
        *,
        session: BrowserHostSession,
        llm: BaseChatModel | None,
        callbacks: BrowserRunnerCallbacks,
        config: BrowserRunConfig,
        user_id: str | None = None,
        root_request_id: str | None = None,
    ) -> None:
        self._session = session
        self._llm = llm
        self._emit = callbacks.emit
        self._request_handoff = callbacks.request_handoff
        self._is_cancelled = callbacks.is_cancelled
        self._action_results = callbacks.action_results
        self._config = config
        self._task_timeout = config.task_timeout_seconds
        # A step that hands off waits on the human, so its budget is active work
        # plus one full handoff; the wall clock allows every permitted handoff on
        # top of the active-work budget so takeovers are never starved by a timeout.
        self._step_timeout = config.step_timeout_seconds + config.handoff_timeout_seconds
        self._wall_clock_timeout = (
            config.task_timeout_seconds + MAX_HANDOFFS_PER_TASK * config.handoff_timeout_seconds
        )
        self._user_id = user_id
        self._root_request_id = root_request_id
        self._stopped = False
        self._handed_off = False
        self._handoff_timed_out = False
        self._handoffs = 0
        self._last_step = 0
        # CDN URLs that really uploaded, in step order — the recap's frames.
        self._shots: list[str] = []
        # Step emits run off the agent's loop; the lock keeps them ordered and the
        # set lets _finish() flush them before the result (see _record_step / _finish).
        self._emit_lock = asyncio.Lock()
        self._emit_tasks: set[asyncio.Task[Any]] = set()
        self._agent_run = self._build_agent_run()

    def _build_agent_run(self) -> BrowserAgentRun:
        hooks = RunHooks(
            step=self._record_step,
            takeover=self._handle_takeover,
            should_stop=self._should_stop,
            action_results=self._action_results,
        )
        return BrowserAgentRun(
            session=self._session,
            llm=self._llm,
            config=self._config,
            hooks=hooks,
            step_timeout=self._step_timeout,
        )

    async def run(self, task: str) -> BrowserResultSnapshot:
        """Run the task to completion and return the final result snapshot."""
        await self._emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self._session.session_id,
                live_view_url=self._session.live_view_url,
            )
        )

        try:
            outcome = await asyncio.wait_for(
                self._agent_run.execute(task), timeout=self._wall_clock_timeout
            )
        except (BrowserHandoffCancelled, InterruptedError):
            return await self._finish_from_handoff()
        except TimeoutError:
            self._agent_run.stop()
            return await self._finish(
                BrowserSessionStatus.FAILED,
                False,
                f"Browser task timed out after {self._task_timeout}s.",
            )
        except (ConnectionError, OSError) as exc:
            # The host created the session but the agent couldn't attach over CDP —
            # almost always the host's CDP proxy websocket isn't reachable from here.
            raise BrowserUnavailableError(
                f"Could not attach to the browser over CDP at {self._session.cdp_url}: {exc}. "
                "Check that the browser host is reachable from the API at BROWSER_HOST_URL."
            ) from exc
        except Exception as exc:
            # Any unexpected agent/runtime failure must not leave the card stuck in
            # RUNNING: emit a terminal FAILED result with an honest reason.
            # CancelledError is BaseException, so it is never caught here.
            log.error(
                f"{LogTag.BROWSER} Browser agent failed unexpectedly",
                error_type=type(exc).__name__,
                browser={"session_id": self._session.session_id},
            )
            return await self._finish(
                BrowserSessionStatus.FAILED,
                False,
                f"{BROWSER_TASK_FAILED_PREFIX}{exc}",
            )

        return await self._finish_after_execute(outcome)

    async def _finish_from_handoff(self) -> BrowserResultSnapshot:
        """Judge a run the handoff ended: expired, completed by the user, or stopped."""
        if self._handoff_timed_out:
            return await self._finish(
                BrowserSessionStatus.FAILED, False, BROWSER_RUN_HANDOFF_TIMED_OUT
            )
        if self._handed_off:
            return await self._finish(
                BrowserSessionStatus.COMPLETED,
                True,
                "You completed the sensitive step in the live browser.",
            )
        return await self._finish(
            BrowserSessionStatus.CANCELLED, False, "Browser task was stopped."
        )

    async def _finish_after_execute(self, outcome: RunOutcome) -> BrowserResultSnapshot:
        """Judge a run whose agent loop returned, cancellation and handoff first.

        Browser-Use catches BrowserHandoffCancelled inside the registered action
        and turns it into an action error, so on a timeout the loop returns
        normally and only the flag the takeover hook set still knows.
        """
        if self._handoff_timed_out:
            return await self._finish(
                BrowserSessionStatus.FAILED, False, BROWSER_RUN_HANDOFF_TIMED_OUT
            )
        if self._stopped:
            status = (
                BrowserSessionStatus.COMPLETED
                if self._handed_off
                else BrowserSessionStatus.CANCELLED
            )
            return await self._finish(status, self._handed_off, "Browser task stopped.")
        if await self._is_cancelled():
            return await self._finish(
                BrowserSessionStatus.CANCELLED, False, "Browser task was cancelled."
            )
        return await self._finish_from_outcome(outcome)

    async def _should_stop(self) -> bool:
        return self._stopped or await self._is_cancelled()

    async def _handle_takeover(self, reason: str, category: str) -> str | None:
        """Pause for the human (the agent's takeover hook) and return the note they left, if any.

        Raises to stop the run on cancel."""
        self._handoffs += 1
        if self._handoffs > MAX_HANDOFFS_PER_TASK:
            self._stopped = True
            raise BrowserHandoffCancelled("max-handoffs")
        try:
            cat = SensitiveCategory(category)
        except ValueError:
            cat = SensitiveCategory.IRREVERSIBLE

        outcome = await self._request_handoff(HandoffRequest(category=cat, reason=reason))
        if outcome.status == HandoffStatus.COMPLETED:
            self._handed_off = True
            log.info(f"{LogTag.BROWSER} Browser takeover completed by user; agent continuing.")
            return (outcome.message or "").strip() or None
        self._stopped = True
        self._handoff_timed_out = outcome.status == HandoffStatus.TIMEOUT
        log.info(f"{LogTag.BROWSER} Browser takeover ended", status=outcome.status.value)
        raise BrowserHandoffCancelled(outcome.status.value)

    def _record_step(self, frame: StepFrame) -> None:
        """Emit one executed step off the agent loop's critical path.

        The screenshot upload is a ~1s CDN round-trip that Browser-Use awaits
        before the step's actions run, so it is spawned; the per-runner lock
        keeps emits ordered and _finish() flushes them before the result.
        """
        self._last_step = frame.index
        task = spawn_background_task(self._emit_step(frame), name="browser_step_emit")
        self._emit_tasks.add(task)
        task.add_done_callback(self._emit_tasks.discard)

    async def _emit_step(self, frame: StepFrame) -> None:
        async with self._emit_lock:
            shot_t0 = perf_counter()
            screenshot = await self._render_screenshot(frame)
            if screenshot and screenshot.startswith("http"):
                self._shots.append(screenshot)
            screenshot_ms = round((perf_counter() - shot_t0) * 1000)
            emit_t0 = perf_counter()
            await self._emit(
                BrowserStepSnapshot(
                    index=frame.index,
                    goal=frame.goal,
                    actions=frame.actions,
                    url=frame.url,
                    title=frame.title,
                    screenshot=screenshot,
                    elapsed_ms=frame.since_prev_ms or None,
                )
            )
            log.info(
                f"{LogTag.BROWSER} step timing",
                step=frame.index,
                since_prev_ms=frame.since_prev_ms,
                screenshot_ms=screenshot_ms,
                emit_ms=round((perf_counter() - emit_t0) * 1000),
            )

    async def _render_screenshot(self, frame: StepFrame) -> str | None:
        """Return a step frame as a signed CDN URL, or an inline data URL when the CDN is unconfigured.

        Return None when screenshots are off or the frame has none.
        """
        raw_b64 = frame.raw_screenshot
        if not raw_b64 or not self._config.stream_screenshots:
            return None
        try:
            image = base64.b64decode(raw_b64)
        except (ValueError, TypeError):
            return None
        # Keyed by session id (not conversation) so each run is its own replay folder.
        url = await publish_step_screenshot(image, self._session.session_id, frame.index)
        return url or f"data:image/png;base64,{raw_b64}"

    async def _finish(
        self, status: BrowserSessionStatus, success: bool, summary: str
    ) -> BrowserResultSnapshot:
        # Flush any in-flight step emits before the result so their photos land in
        # order and the SSE writer is still open when they do.
        if self._emit_tasks:
            await asyncio.gather(*self._emit_tasks, return_exceptions=True)
        # A recap slideshow of every step — surfaced whether the task succeeded or not.
        replay_url = await create_replay_link(self._session.session_id, self._shots)
        result = BrowserResultSnapshot(
            status=status,
            success=success,
            summary=summary,
            steps=self._last_step,
            replay_url=replay_url,
        )
        await self._emit(result)
        return result

    async def _finish_from_outcome(self, outcome: RunOutcome) -> BrowserResultSnapshot:
        status = BrowserSessionStatus.COMPLETED if outcome.success else BrowserSessionStatus.FAILED
        await self._record_usage(outcome.usage)
        return await self._finish(status, outcome.success, outcome.summary)

    async def _record_usage(self, usage: list[RunUsage]) -> None:
        """Price and record the run's LLM spend into GAIA's usage pipeline.

        One record_llm_call per billed model, re-priced through GAIA's own
        catalog rather than Browser-Use's pricing data, so the Jev spend is
        charged to the budget like any other tool-driven model call.
        """
        for entry in usage:
            await record_llm_call(
                user_id=self._user_id,
                model_name=entry.model_name,
                usage=TokenUsage(
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    cached_tokens=0,
                    reasoning_tokens=0,
                ),
                root_request_id=self._root_request_id,
                context=LLMCallContext(
                    agent_name="browser_task",
                    background=False,
                    charge_to_budget=True,
                ),
            )
