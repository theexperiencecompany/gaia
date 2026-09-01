"""Custom Browser-Use actions the agent can call mid-run.

Two seams the agent reaches for itself:

* ``request_human_takeover`` — the agent's *own* way to pause for the human at a
  sensitive step (payment / credentials / irreversible). Because it is a normal
  action that blocks and returns a result string, Browser-Use resumes its loop
  natively afterwards with full task memory — no dispose/recreate. The per-step
  classifier in the runner remains as a safety net for a model that acts without
  asking.
* ``solve_captcha_with_help`` — there is no automatic solver, so a CAPTCHA is a
  human takeover: the user solves it in live-view and the agent then continues.

Imports of ``browser_use`` are local so the module loads without the package.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from browser_use import Tools

TakeoverFn = Callable[[str, str], Awaitable[str]]


def build_browser_tools(
    *,
    solve_captcha: bool,
    handle_takeover: TakeoverFn,
) -> Tools[None]:
    """Build the Browser-Use ``Tools`` the agent can call during a run.

    ``handle_takeover(reason, category)`` performs the live-view handoff and
    returns a result string to feed back to the agent (or raises to stop the run
    when the user cancels).
    """
    from browser_use import Tools  # noqa: PLC0415

    tools: Tools[None] = Tools()

    @tools.action(
        description=(
            "Hand control to the human for a step you must NOT do yourself: "
            "entering a payment, a password / OTP / 2FA, or confirming an "
            "irreversible action. Call this BEFORE such a step. The user completes "
            "it in the live browser; you then continue. `reason` is shown to the "
            "user verbatim as their instruction, so write ONE short second-person "
            "directive — 10 words or fewer, no restating what the field is for "
            "(e.g. 'Enter your password and sign in'), NOT a third-person explanation. `category` "
            "is one of payment | credentials | irreversible."
        )
    )
    async def request_human_takeover(reason: str, category: str = "irreversible") -> str:
        """Return the takeover tool that hands control to the user via live view."""
        return await handle_takeover(reason, category)

    if solve_captcha:

        @tools.action(
            description=(
                "Hand a CAPTCHA to the human to solve in the live browser. Call this "
                "when you see a CAPTCHA/reCAPTCHA/hCaptcha challenge; the user solves "
                "it and you then continue. `challenge` is shown to the user verbatim "
                "as their instruction, so write it as a short second-person directive "
                "describing exactly what to solve (e.g. 'Select all squares with "
                "motorcycles, then click Verify')."
            )
        )
        async def solve_captcha_with_help(challenge: str) -> str:
            """Return the CAPTCHA tool that asks the user to solve it in live view."""
            return await handle_takeover(challenge, "none")

    return tools
