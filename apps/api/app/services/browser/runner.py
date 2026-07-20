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

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.constants.browser import (
    BrowserSessionStatus,
    HandoffStatus,
    HandoffStrategy,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserCardSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffRequest,
)
from app.services.browser.captcha import build_tools
from app.services.browser.classify import classify_step
from app.services.browser.exceptions import BrowserHandoffCancelled
from app.services.browser.policy import resolve_strategy
from app.services.browser.session import SteelBrowserSession
from shared.py.wide_events import log

EmitFn = Callable[[BrowserCardSnapshot], Awaitable[None]]
RequestHandoffFn = Callable[[HandoffRequest], Awaitable[HandoffStatus]]
IsCancelledFn = Callable[[], Awaitable[bool]]


def _summarize_actions(agent_output: Any) -> tuple[list[str], str]:
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
        llm: Any,
        emit: EmitFn,
        request_handoff: RequestHandoffFn,
        is_cancelled: IsCancelledFn,
        max_steps: int,
        max_actions_per_step: int,
        task_timeout_seconds: int,
        stream_screenshots: bool,
        use_vision: bool,
        solve_captcha: bool,
        autonomous_override: bool | None = None,
    ) -> None:
        self._session = session
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
        self._autonomous = autonomous_override
        self._agent: Any = None
        self._stopped = False
        self._handed_off = False
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
            "task": task,
            "llm": self._llm,
            "browser": browser,
            "register_new_step_callback": self._on_step,
            "register_should_stop_callback": self._should_stop,
            "use_vision": self._use_vision,
            "max_actions_per_step": self._max_actions_per_step,
        }
        if self._solve_captcha:
            agent_kwargs["tools"] = build_tools(self._session.session_id)
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

    async def _on_step(self, browser_state_summary: Any, agent_output: Any, n_steps: int) -> None:
        """Fires after the model picks actions, before they execute."""
        self._last_step = n_steps
        goal = (
            getattr(agent_output, "next_goal", None) or getattr(agent_output, "thinking", "") or ""
        )
        action_names, action_detail = _summarize_actions(agent_output)
        url = getattr(browser_state_summary, "url", None)
        screenshot = getattr(browser_state_summary, "screenshot", None)

        await self._emit(
            BrowserStepSnapshot(
                index=n_steps,
                goal=goal,
                action=action_detail or None,
                url=url,
                title=getattr(browser_state_summary, "title", None),
                screenshot=(
                    f"data:image/png;base64,{screenshot}"
                    if screenshot and self._stream_screenshots
                    else None
                ),
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
            log.info(f"{LogTag.AGENT} Browser step {n_steps} handed off to user; completed.")
        else:
            log.info(f"{LogTag.AGENT} Browser step {n_steps} handoff ended: {status.value}.")
        raise BrowserHandoffCancelled(status.value)

    async def _finish(
        self, status: BrowserSessionStatus, success: bool, summary: str
    ) -> BrowserResultSnapshot:
        result = BrowserResultSnapshot(
            status=status, success=success, summary=summary, steps=self._last_step
        )
        await self._emit(result)
        return result

    async def _finish_from_history(self, history: Any) -> BrowserResultSnapshot:
        final = None
        is_done = False
        is_successful: bool | None = None
        try:
            final = history.final_result()
            is_done = history.is_done()
            is_successful = history.is_successful()
        except Exception as exc:  # noqa: BLE001 — history shape is version-sensitive
            log.warning(f"{LogTag.AGENT} Could not read browser history result: {exc}")

        success = bool(is_done and is_successful is not False)
        status = BrowserSessionStatus.COMPLETED if success else BrowserSessionStatus.FAILED
        summary = final or (
            "Completed the browser task." if success else "Could not complete the browser task."
        )
        return await self._finish(status, success, str(summary))
