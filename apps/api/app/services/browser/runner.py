"""Browser-Use agent execution — the *agent* layer.

Drives a Browser-Use ``Agent`` against an already-created browser-host session and
turns its lifecycle into injected, swappable seams:

  * ``emit`` — stream a card snapshot (session/step/handoff/result) to UI + bots
  * ``request_handoff`` — pause for the human at a sensitive step (live-view)
  * ``is_cancelled`` — cooperative cancellation (wired to the chat stream)

The runner does NOT judge whether a step is sensitive. The agent decides for
itself when it cannot proceed — a CAPTCHA it can't solve, a login/2FA/payment it
must not do — and calls its takeover action, which pauses for the human in
live-view (``_handle_takeover``). The runner knows nothing about SSE, Redis, or bots.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.constants.browser import (
    BROWSER_TAKEOVER_PREAMBLE,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    MAX_HANDOFFS_PER_TASK,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserAction,
    BrowserCardSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.browser.captions import caption_from_actions
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.replay import create_replay_link
from app.services.browser.screenshots import upload_step_screenshot
from app.services.browser.session import BrowserHostSession
from app.services.browser.tools import build_browser_tools
from app.services.llm_metering import record_llm_call
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.agent.views import AgentHistoryList, AgentOutput
    from browser_use.browser.views import BrowserStateSummary
    from browser_use.llm.base import BaseChatModel
    from pydantic import BaseModel

EmitFn = Callable[[BrowserCardSnapshot], Awaitable[None]]
RequestHandoffFn = Callable[[HandoffRequest], Awaitable[HandoffOutcome]]
IsCancelledFn = Callable[[], Awaitable[bool]]


def _element_label(state: BrowserStateSummary, index: object) -> str | None:
    """The on-page text of the element an action targets, by its DOM index.

    Browser-Use addresses elements by index, which is meaningless to a reader.
    The same step state the agent saw carries the DOM, so the index resolves to
    the element's own text — that is what makes a caption say what was clicked.
    """
    if not isinstance(index, int):
        return None
    selector_map = getattr(getattr(state, "dom_state", None), "selector_map", None) or {}
    node = selector_map.get(index)
    if node is None:
        return None
    try:
        return (node.get_meaningful_text_for_llm() or "").strip() or None
    except Exception:  # a DOM node shape we don't recognise must not kill the step
        return None


def _extract_actions(
    agent_output: AgentOutput, state: BrowserStateSummary | None = None
) -> list[BrowserAction]:
    """The step's actions as the agent's own tool calls — name, arguments, and
    the on-page text of whatever each one targets."""
    actions: list[BrowserAction] = []
    for action in getattr(agent_output, "action", None) or []:
        dumped = action.model_dump(exclude_none=True) if hasattr(action, "model_dump") else {}
        for action_name, params in dumped.items():
            inputs = params if isinstance(params, dict) else {}
            target = _element_label(state, inputs.get("index")) if state is not None else None
            actions.append(BrowserAction(name=action_name, inputs=inputs, target=target))
    return actions


class BrowserTaskRunner:
    """Orchestrates one browser task: session, agent loop, handoffs, delivery."""

    def __init__(
        self,
        *,
        session: BrowserHostSession,
        conversation_id: str,
        llm: BaseChatModel,
        emit: EmitFn,
        request_handoff: RequestHandoffFn,
        is_cancelled: IsCancelledFn,
        max_steps: int,
        max_actions_per_step: int,
        task_timeout_seconds: int,
        step_timeout_seconds: int,
        handoff_timeout_seconds: int,
        stream_screenshots: bool,
        use_vision: bool,
        solve_captcha: bool,
        flash_mode: bool = True,
        user_id: str | None = None,
        root_request_id: str | None = None,
    ) -> None:
        self._session = session
        self._conversation_id = conversation_id
        self._llm = llm
        self._emit = emit
        self._request_handoff = request_handoff
        self._is_cancelled = is_cancelled
        self._max_steps = max_steps
        self._max_actions_per_step = max_actions_per_step
        self._task_timeout = task_timeout_seconds
        # A step that hands off waits on the human for up to the handoff timeout, so
        # its budget is active-work time PLUS a full handoff; the overall wall-clock
        # likewise allows every permitted handoff to run its full duration on top of
        # the active-work budget, so live-view takeovers are never starved by a timeout.
        self._step_timeout = step_timeout_seconds + handoff_timeout_seconds
        self._wall_clock_timeout = (
            task_timeout_seconds + MAX_HANDOFFS_PER_TASK * handoff_timeout_seconds
        )
        self._stream_screenshots = stream_screenshots
        self._use_vision = use_vision
        self._solve_captcha = solve_captcha
        self._flash_mode = flash_mode
        self._user_id = user_id
        self._root_request_id = root_request_id
        self._agent: Any = None
        self._stopped = False
        self._handed_off = False
        self._handoffs = 0
        self._last_step = 0
        # CDN URLs that really uploaded, in step order — the recap's frames.
        self._shots: list[str] = []
        self._last_step_at = 0.0
        # Step emits run off Browser-Use's loop; the lock keeps them ordered and the
        # set lets _finish() flush them before the result (see _on_step / _finish).
        self._emit_lock = asyncio.Lock()
        self._emit_tasks: set[asyncio.Task[Any]] = set()

    async def run(self, task: str) -> BrowserResultSnapshot:
        """Run the task to completion and return the final result snapshot."""
        from browser_use import Agent, Browser  # noqa: PLC0415

        await self._emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self._session.session_id,
                live_view_url=self._session.live_view_url,
            )
        )

        browser = Browser(
            cdp_url=self._session.cdp_url,
            viewport={"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
            # The live-view surface DPR is set host-side (screencast.py); Browser-Use
            # ignores device_scale_factor when connecting over CDP, so leave it at 1 here.
            device_scale_factor=1,
            no_viewport=False,
        )
        # Stealth fingerprinting is injected on every page by browser_use_stealth_patch
        # (app/patches), which hooks Browser-Use's per-target CDP session accessor so
        # new tabs are covered too — no per-run registration needed here.

        agent_kwargs: dict[str, Any] = {
            "task": task + BROWSER_TAKEOVER_PREAMBLE,
            "llm": self._llm,
            "browser": browser,
            # Browser-Use's prompt suggests todo.md for long tasks, but small
            # models write it even for 3-step forms — a measured ~7s and one
            # whole step of pure bookkeeping. Steer it to act directly.
            "extend_system_message": (
                "Do NOT create or update todo.md (or any planning file) unless the task "
                "genuinely needs more than 10 steps. For short tasks, act on the page "
                "directly from the first step."
            ),
            "register_new_step_callback": self._on_step,
            "register_should_stop_callback": self._should_stop,
            "use_vision": self._use_vision,
            "flash_mode": self._flash_mode,
            "max_actions_per_step": self._max_actions_per_step,
            "step_timeout": self._step_timeout,
            "tools": build_browser_tools(
                solve_captcha=self._solve_captcha,
                handle_takeover=self._handle_takeover,
            ),
        }
        self._agent = Agent(**agent_kwargs)

        try:
            history = await asyncio.wait_for(
                self._agent.run(max_steps=self._max_steps), timeout=self._wall_clock_timeout
            )
        except (BrowserHandoffCancelled, InterruptedError):
            if self._handed_off:
                return await self._finish(
                    BrowserSessionStatus.COMPLETED,
                    True,
                    "You completed the sensitive step in the live browser.",
                )
            return await self._finish(
                BrowserSessionStatus.CANCELLED, False, "Browser task was stopped."
            )
        except TimeoutError:
            self._agent.stop()
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
            # Any other unexpected agent/runtime failure (an LLM-provider error, a
            # browser_use internal crash, a malformed tool output, a failed handoff
            # persistence write) must not leave the card stuck in RUNNING — emit a
            # terminal FAILED result so the UI resolves and the user gets an honest
            # reason. CancelledError is BaseException, so it is never caught here.
            log.error(
                f"{LogTag.BROWSER} Browser agent failed unexpectedly",
                error_type=type(exc).__name__,
                browser={"session_id": self._session.session_id},
            )
            return await self._finish(
                BrowserSessionStatus.FAILED,
                False,
                f"Browser task failed: {exc}",
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
        return await self._finish_from_history(history)

    async def _should_stop(self) -> bool:
        return self._stopped or await self._is_cancelled()

    async def _handle_takeover(self, reason: str, category: str) -> str:
        """The ``request_human_takeover`` action: pause for the human, then let the
        agent resume natively with the returned result. Raises to stop on cancel."""
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
            note = (outcome.message or "").strip()
            # A note is a direct instruction from the user (e.g. "just grab the photo,
            # skip the login") — it overrides the default verify-and-continue posture.
            preface = (
                f'The user handed control back with this instruction: "{note}". Follow it.\n\n'
                if note
                else "The user says they finished that step in the live browser. "
            )
            return (
                f"{preface}Do NOT assume the page is in the state you expect. Look at the "
                "CURRENT page now and VERIFY before doing anything else — e.g. a solved CAPTCHA "
                "shows a green checkmark and no 'please verify that you are not a robot' error "
                "remains; a login lands on the signed-in page. If the step is NOT actually "
                "complete, call the takeover / solve_captcha_with_help action again instead of "
                "proceeding. Only continue toward the goal once you have confirmed the page state "
                "yourself, and never report success you cannot see on the page."
            )
        self._stopped = True
        log.info(f"{LogTag.BROWSER} Browser takeover ended", status=outcome.status.value)
        raise BrowserHandoffCancelled(outcome.status.value)

    async def _on_step(
        self, browser_state_summary: BrowserStateSummary, agent_output: AgentOutput, n_steps: int
    ) -> None:
        """Fires after the model picks actions, before they execute."""
        self._last_step = n_steps
        goal = (
            getattr(agent_output, "next_goal", None)
            or getattr(agent_output, "thinking", "")
            or caption_from_actions(agent_output)
        )
        step_actions = _extract_actions(agent_output, browser_state_summary)
        raw_screenshot = getattr(browser_state_summary, "screenshot", None)

        # Per-step profiling: `since_prev_ms` is the wall-clock the agent spent on the
        # previous step's LLM think + action execution (the dominant per-step cost);
        # `screenshot_ms` is how long the screenshot upload blocks this callback (and
        # therefore Browser-Use's loop). Both are the levers when the run "feels slow".
        now = perf_counter()
        since_prev_ms = round((now - self._last_step_at) * 1000) if self._last_step_at else 0
        self._last_step_at = now

        # Emit OFF Browser-Use's critical path: the screenshot upload is a ~1s CDN
        # round-trip and this callback is awaited *before the step's actions run*, so
        # uploading inline taxed every step. Spawn it — the per-runner lock keeps the
        # step emits ordered, and _finish() flushes them before the result so the SSE
        # writer is still open. The runner does not judge sensitivity; the agent hands
        # off for itself (see _handle_takeover). This callback only streams progress.
        task = spawn_background_task(
            self._emit_step(
                n_steps,
                goal,
                step_actions,
                getattr(browser_state_summary, "url", None),
                getattr(browser_state_summary, "title", None),
                raw_screenshot,
                since_prev_ms,
            ),
            name="browser_step_emit",
        )
        self._emit_tasks.add(task)
        task.add_done_callback(self._emit_tasks.discard)

    async def _emit_step(
        self,
        n_steps: int,
        goal: str,
        actions: list[BrowserAction],
        url: str | None,
        title: str | None,
        raw_screenshot: str | None,
        since_prev_ms: int,
    ) -> None:
        async with self._emit_lock:
            shot_t0 = perf_counter()
            screenshot = await self._render_screenshot(raw_screenshot, n_steps)
            if screenshot and screenshot.startswith("http"):
                self._shots.append(screenshot)
            screenshot_ms = round((perf_counter() - shot_t0) * 1000)
            emit_t0 = perf_counter()
            await self._emit(
                BrowserStepSnapshot(
                    index=n_steps,
                    goal=goal,
                    actions=actions,
                    url=url,
                    title=title,
                    screenshot=screenshot,
                    elapsed_ms=since_prev_ms or None,
                )
            )
            log.info(
                f"{LogTag.BROWSER} step timing",
                step=n_steps,
                since_prev_ms=since_prev_ms,
                screenshot_ms=screenshot_ms,
                emit_ms=round((perf_counter() - emit_t0) * 1000),
            )

    async def _render_screenshot(self, raw_b64: str | None, index: int) -> str | None:
        """A step frame as a signed CDN URL (persisted), or an inline data URL as
        a dev fallback when the CDN is unconfigured. ``None`` when off/absent."""
        if not raw_b64 or not self._stream_screenshots:
            return None
        try:
            png = base64.b64decode(raw_b64)
        except (ValueError, TypeError):
            return None
        # Keyed by session id (not conversation) so each run is its own replay folder.
        url = await upload_step_screenshot(png, self._session.session_id, index)
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

    async def _finish_from_history(
        self, history: AgentHistoryList[BaseModel]
    ) -> BrowserResultSnapshot:
        # The three fallbacks the try leaves in place if reading history fails.
        # pragma-exempt below: every consumer collapses falsy values to one answer
        # (`final or ...`, `bool(is_done and ...)`, `is_successful is not False`),
        # so swapping any of them for another falsy value cannot change the
        # snapshot — verified against both the total-failure and partial-read
        # paths. Restructuring to an early return WAS tried and rejected: it
        # discards a final_result() that was read before the failure, which
        # test_a_history_that_breaks_midway_still_reports_what_it_read catches.
        final = None  # pragma: no mutate
        is_done = False  # pragma: no mutate
        is_successful: bool | None = None  # pragma: no mutate
        try:
            final = history.final_result()
            is_done = history.is_done()
            is_successful = history.is_successful()
        except Exception as exc:
            log.warning(
                f"{LogTag.BROWSER} Could not read browser history result",
                error_type=type(exc).__name__,
            )

        success = bool(is_done and is_successful is not False)
        status = BrowserSessionStatus.COMPLETED if success else BrowserSessionStatus.FAILED
        summary = final or (
            "Completed the browser task." if success else "Could not complete the browser task."
        )
        await self._record_usage(history)
        return await self._finish(status, success, str(summary))

    async def _record_usage(self, history: AgentHistoryList[BaseModel]) -> None:
        """Price and record the run's LLM spend into GAIA's usage pipeline.

        Browser-Use tracks its own per-model token totals on
        ``history.usage.by_model`` (populated whenever ``Agent.run`` returns
        normally — not on the timeout/cancellation/CDP-failure paths above,
        which return before a history exists). One :func:`record_llm_call`
        per model matches how ``LLMAccountingMiddleware`` records the chat
        graph's own multi-model runs; token counts are re-priced through
        GAIA's own catalog rather than trusting Browser-Use's bundled pricing
        data. This is agent-graph work the user asked for (the ``browser_task``
        tool), so it charges the budget like any other tool-driven model call.
        """
        usage = history.usage
        if usage is None:
            return
        for model_name, stats in usage.by_model.items():
            await record_llm_call(
                user_id=self._user_id,
                model_name=model_name,
                input_tokens=stats.prompt_tokens,
                output_tokens=stats.completion_tokens,
                root_request_id=self._root_request_id,
                charge_to_budget=True,
            )
