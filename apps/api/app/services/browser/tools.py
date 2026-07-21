"""Custom Browser-Use actions the agent can call mid-run.

Two seams the agent reaches for itself:

* ``request_human_takeover`` — the agent's *own* way to pause for the human at a
  sensitive step (payment / credentials / irreversible). Because it is a normal
  action that blocks and returns a result string, Browser-Use resumes its loop
  natively afterwards with full task memory — no dispose/recreate. The per-step
  classifier in the runner remains as a safety net for a model that acts without
  asking.
* ``wait_for_captcha_solution`` — wait for Steel's automatic solver; if it can't
  solve in time, escalate to the same human takeover so the user solves it in
  live-view.

Imports of ``browser_use`` are local so the module loads without the package.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.constants.log_tags import LogTag
from app.services.browser.session import build_steel_client
from shared.py.wide_events import log

_CAPTCHA_POLL_INTERVAL_SECONDS = 1.0
_CAPTCHA_MAX_WAIT_SECONDS = 60

TakeoverFn = Callable[[str, str], Awaitable[str]]


def build_browser_tools(
    *,
    session_id: str,
    solve_captcha: bool,
    handle_takeover: TakeoverFn,
) -> Any:
    """Build the Browser-Use ``Tools`` the agent can call during a run.

    ``handle_takeover(reason, category)`` performs the live-view handoff and
    returns a result string to feed back to the agent (or raises to stop the run
    when the user cancels).
    """
    from browser_use import Tools  # noqa: PLC0415

    tools: Any = Tools()

    @tools.action(
        description=(
            "Hand control to the human for a step you must NOT do yourself: "
            "entering a payment, a password / OTP / 2FA, or confirming an "
            "irreversible action. Call this BEFORE such a step. The user completes "
            "it in the live browser; you then continue. Pass a short reason and a "
            "category of payment | credentials | irreversible."
        )
    )
    async def request_human_takeover(reason: str, category: str = "irreversible") -> str:
        return await handle_takeover(reason, category)

    if solve_captcha:
        steel_client = build_steel_client()

        @tools.action(
            description=(
                "Wait for Steel to automatically solve a CAPTCHA on the page. Call "
                "this when you see a CAPTCHA/reCAPTCHA/hCaptcha challenge, then continue."
            )
        )
        async def wait_for_captcha_solution() -> str:
            loop = asyncio.get_event_loop()
            deadline = loop.time() + _CAPTCHA_MAX_WAIT_SECONDS
            while loop.time() < deadline:
                try:
                    statuses = await steel_client.sessions.captchas.status(session_id)
                except Exception as exc:  # noqa: BLE001 — solver status is best-effort
                    log.warning(f"{LogTag.AGENT} CAPTCHA status check failed: {exc}")
                    return "Could not check CAPTCHA status; proceeding."
                if not any(getattr(item, "is_solving_captcha", False) for item in statuses):
                    return "CAPTCHA solved (or none present)."
                await asyncio.sleep(_CAPTCHA_POLL_INTERVAL_SECONDS)
            # Auto-solve timed out — let the human solve it in live-view.
            return await handle_takeover("A CAPTCHA needs you to solve it in the browser.", "none")

    return tools
