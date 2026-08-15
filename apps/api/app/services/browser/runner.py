"""Browser-Use agent execution — the *agent* layer.

Drives a Browser-Use ``Agent`` against an already-created Steel session and
turns its lifecycle into injected, swappable seams:

  * ``emit`` — stream a card snapshot (session/step/handoff/result) to UI + bots
  * ``request_handoff`` — pause for the human at a sensitive step (live-view)
  * ``is_cancelled`` — cooperative cancellation (wired to the chat stream)

Mid-run sensitivity is judged per step; a flexible policy decides whether to
hand off, proceed autonomously, or abort. The runner knows nothing about SSE,
Redis, or bots.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.constants.browser import (
    BROWSER_TAKEOVER_PREAMBLE,
    MAX_HANDOFFS_PER_TASK,
    BrowserSessionStatus,
    HandoffStatus,
    HandoffStrategy,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserCardSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffRequest,
)
from app.services.browser.classify import classify_step
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.policy import resolve_strategy
from app.services.browser.screenshots import upload_step_screenshot
from app.services.browser.session import SteelBrowserSession
from app.services.browser.tools import build_browser_tools
from app.services.llm_metering import record_llm_call
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.agent.views import AgentHistoryList, AgentOutput
    from browser_use.browser.views import BrowserStateSummary
    from browser_use.llm.base import BaseChatModel
    from pydantic import BaseModel

EmitFn = Callable[[BrowserCardSnapshot], Awaitable[None]]
RequestHandoffFn = Callable[[HandoffRequest], Awaitable[HandoffStatus]]
IsCancelledFn = Callable[[], Awaitable[bool]]


def _summarize_actions(agent_output: AgentOutput) -> tuple[list[str], str]:
    names: list[str] = []
    parts: list[str] = []
    for action in getattr(agent_output, "action", None) or []:
        dumped = action.model_dump(exclude_none=True) if hasattr(action, "model_dump") else {}
        for action_name, params in dumped.items():
            names.append(action_name)
            parts.append(f"{action_name}({params})" if params else action_name)
    return names, "; ".join(parts)


class BrowserTaskRunner:
    def __init__(
        self,
        *,
        session: SteelBrowserSession,
        conversation_id: str,
        llm: BaseChatModel,
        emit: EmitFn,
        request_handoff: RequestHandoffFn,
        is_cancelled: IsCancelledFn,
        max_steps: int,
        max_actions_per_step: int,
        task_timeout_seconds: int,
        stream_screenshots: bool,
        use_vision: bool,
        solve_captcha: bool,
        user_id: str | None = None,
        root_request_id: str | None = None,
        autonomous_override: bool | None = None,
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
        self._stream_screenshots = stream_screenshots
        self._use_vision = use_vision
        self._solve_captcha = solve_captcha
        self._user_id = user_id
        self._root_request_id = root_request_id
        self._autonomous = autonomous_override
        self._agent: Any = None
        self._stopped = False
        self._handed_off = False
        self._handoffs = 0
        self._last_step = 0

    async def run(self, task: str) -> BrowserResultSnapshot:
        from browser_use import Agent, Browser  # noqa: PLC0415

        await self._emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self._session.session_id,
                live_view_url=self._session.live_view_url,
            )
        )

        browser = Browser(cdp_url=self._session.cdp_url)

        agent_kwargs: dict[str, Any] = {
            "task": task + BROWSER_TAKEOVER_PREAMBLE,
            "llm": self._llm,
            "browser": browser,
            "register_new_step_callback": self._on_step,
            "register_should_stop_callback": self._should_stop,
            "use_vision": self._use_vision,
            "max_actions_per_step": self._max_actions_per_step,
            "tools": build_browser_tools(
                session_id=self._session.session_id,
                solve_captcha=self._solve_captcha,
                handle_takeover=self._handle_takeover,
            ),
        }
        self._agent = Agent(**agent_kwargs)

        try:
            history = await asyncio.wait_for(
                self._agent.run(max_steps=self._max_steps), timeout=self._task_timeout
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
            # Steel accepted the session but the agent couldn't attach over CDP —
            # almost always the advertised websocketUrl isn't reachable from here.
            raise BrowserUnavailableError(
                f"Could not attach to the browser over CDP at {self._session.cdp_url}: {exc}. "
                "If Steel is reachable, set STEEL_CDP_CONNECT_URL to a CDP endpoint that is "
                "reachable from the API."
            ) from exc

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

        status = await self._request_handoff(HandoffRequest(category=cat, reason=reason))
        if status == HandoffStatus.COMPLETED:
            self._handed_off = True
            log.info(f"{LogTag.BROWSER} Browser takeover completed by user; agent continuing.")
            return (
                "The user has completed that step in the browser. The page has advanced — "
                "continue toward the original goal."
            )
        self._stopped = True
        log.info(f"{LogTag.BROWSER} Browser takeover ended", status=status.value)
        raise BrowserHandoffCancelled(status.value)

    async def _on_step(
        self, browser_state_summary: BrowserStateSummary, agent_output: AgentOutput, n_steps: int
    ) -> None:
        """Fires after the model picks actions, before they execute."""
        self._last_step = n_steps
        goal = (
            getattr(agent_output, "next_goal", None) or getattr(agent_output, "thinking", "") or ""
        )
        action_names, action_detail = _summarize_actions(agent_output)
        url = getattr(browser_state_summary, "url", None)
        raw_screenshot = getattr(browser_state_summary, "screenshot", None)

        await self._emit(
            BrowserStepSnapshot(
                index=n_steps,
                goal=goal,
                action=action_detail or None,
                url=url,
                title=getattr(browser_state_summary, "title", None),
                screenshot=await self._render_screenshot(raw_screenshot, n_steps),
            )
        )

        verdict = await classify_step(
            goal=goal, action_names=action_names, actions_detail=action_detail, url=url or ""
        )
        if not verdict.requires_approval:
            return

        strategy = resolve_strategy(verdict.category, autonomous_override=self._autonomous)
        if strategy == HandoffStrategy.PROCEED:
            return  # user opted into autonomous sensitive actions

        if strategy == HandoffStrategy.ABORT:
            self._stopped = True
            self._agent.stop()
            raise BrowserHandoffCancelled("policy-abort")

        # HANDOFF: pause and let the human complete the sensitive step in live-view.
        status = await self._request_handoff(
            HandoffRequest(
                category=verdict.category,
                reason=verdict.reason or "This step needs you to take over in the browser.",
            )
        )
        self._stopped = True
        self._agent.stop()
        if status == HandoffStatus.COMPLETED:
            self._handed_off = True
            log.info(f"{LogTag.BROWSER} Browser step handed off to user; completed", step=n_steps)
        else:
            log.info(
                f"{LogTag.BROWSER} Browser step handoff ended", step=n_steps, status=status.value
            )
        raise BrowserHandoffCancelled(status.value)

    async def _render_screenshot(self, raw_b64: str | None, index: int) -> str | None:
        """A step frame as a signed CDN URL (persisted), or an inline data URL as
        a dev fallback when the CDN is unconfigured. ``None`` when off/absent."""
        if not raw_b64 or not self._stream_screenshots:
            return None
        try:
            png = base64.b64decode(raw_b64)
        except (ValueError, TypeError):
            return None
        url = await upload_step_screenshot(png, self._conversation_id, index)
        return url or f"data:image/png;base64,{raw_b64}"

    async def _finish(
        self, status: BrowserSessionStatus, success: bool, summary: str
    ) -> BrowserResultSnapshot:
        result = BrowserResultSnapshot(
            status=status, success=success, summary=summary, steps=self._last_step
        )
        await self._emit(result)
        return result

    async def _finish_from_history(
        self, history: AgentHistoryList[BaseModel]
    ) -> BrowserResultSnapshot:
        final = None
        is_done = False
        is_successful: bool | None = None
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
