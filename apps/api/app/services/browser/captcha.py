"""Browser-Use tools for Steel's automatic CAPTCHA solving.

Steel solves reCAPTCHA/hCaptcha under CDP when a session is created with
``solve_captcha=True``. The agent needs a way to *wait* for the solver to
finish, so we register a ``wait_for_captcha_solution`` action that polls Steel's
captcha status until no tab is still solving (bounded by a timeout).
"""

import asyncio
from typing import Any

from app.constants.log_tags import LogTag
from app.services.browser.session import build_steel_client
from shared.py.wide_events import log

_POLL_INTERVAL_SECONDS = 1.0
_MAX_WAIT_SECONDS = 60


def build_tools(session_id: str) -> Any:
    """Build a Browser-Use ``Tools`` with the CAPTCHA-wait action registered."""
    from browser_use import Tools  # noqa: PLC0415

    steel_client = build_steel_client()
    tools: Any = Tools()

    @tools.action(
        description=(
            "Wait for Steel to automatically solve a CAPTCHA on the page. Call this "
            "when you see a CAPTCHA/reCAPTCHA/hCaptcha challenge, then continue."
        )
    )
    async def wait_for_captcha_solution() -> str:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _MAX_WAIT_SECONDS
        while loop.time() < deadline:
            try:
                statuses = await steel_client.sessions.captchas.status(session_id)
            except Exception as exc:  # noqa: BLE001 — solver status is best-effort
                log.warning(f"{LogTag.AGENT} CAPTCHA status check failed: {exc}")
                return "Could not check CAPTCHA status; proceeding."
            solving = any(getattr(item, "is_solving_captcha", False) for item in statuses)
            if not solving:
                return "CAPTCHA solved (or none present)."
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        return "Timed out waiting for CAPTCHA to be solved."

    return tools
