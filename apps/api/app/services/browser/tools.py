"""Custom Browser-Use actions the agent can call mid-run.

Three seams the agent reaches for itself: request_human_takeover is the agent's
own way to pause for the human at a sensitive step (payment, credentials,
irreversible); because it is a normal action that blocks and returns a result
string, Browser-Use resumes its loop natively afterwards with full task
memory, no dispose or recreate. solve_captcha_with_help hands a CAPTCHA to a
human takeover since there is no automatic solver. request_agent_guidance
pauses the same way but asks the agent that started the run, not the user.

Imports of browser_use are local so the module loads without the package.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.constants.browser import EngineSwitchReason

if TYPE_CHECKING:
    from browser_use import Tools

TakeoverFn = Callable[[str, str], Awaitable[str]]
AgentGuidanceFn = Callable[[str], Awaitable[str]]
EngineSwitchFn = Callable[[EngineSwitchReason], Awaitable[str]]


class EngineSwitchParams(BaseModel):
    """The continue_in_full_browser action's one argument: which engine-caused breakage it was."""

    category: EngineSwitchReason


def build_browser_tools(
    *,
    solve_captcha: bool,
    handle_takeover: TakeoverFn,
    handle_guidance: AgentGuidanceFn,
    handle_engine_switch: EngineSwitchFn | None = None,
) -> Tools[None]:
    """Build the Browser-Use Tools the agent can call during a run.

    handle_takeover(reason, category) performs the live-view handoff and
    returns a result string to feed back to the agent, or raises to stop the
    run when the user cancels. handle_guidance(reason) asks the agent that
    started the run instead, on the same contract. handle_engine_switch, given
    only on the fast engine, moves the run to the full browser.
    """
    from browser_use import Tools  # noqa: PLC0415 -- heavy optional dep

    tools: Tools[None] = Tools()

    # Registered by function name; BrowserHandoffAction.REQUEST_AGENT_GUIDANCE must spell it the same.
    @tools.action(
        description=(
            "Ask the assistant that gave you this task what to do, when no action on "
            "this page moves the task forward and no human step is what is missing. "
            "It answers with ONE concrete instruction and you then continue. `reason` "
            "says what you tried and what the page does instead; it is read by an "
            "assistant, not by the user, so write it as a plain statement of fact."
        )
    )
    async def request_agent_guidance(reason: str) -> str:
        """Return the guidance tool that asks the agent that started the run how to proceed."""
        return await handle_guidance(reason)

    # Registered by function name; BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER must spell it the same.
    @tools.action(
        description=(
            "Hand control to the human for a step you must NOT do yourself: "
            "entering a payment, a password / OTP / 2FA, or confirming an "
            "irreversible action. Call this BEFORE such a step. The user completes "
            "it in the live browser; you then continue. `reason` is shown to the "
            "user verbatim as the ask itself, so write it as the ask: two short "
            "second-person sentences, what to do plus what happens after "
            "(e.g. 'Enter your password and sign in. I'll carry on the moment you're through.'). "
            "No third-person explanation, no field names, no element ids. `category` "
            "is one of payment | credentials | irreversible."
        )
    )
    async def request_human_takeover(reason: str, category: str = "irreversible") -> str:
        """Return the takeover tool that hands control to the user via live view."""
        return await handle_takeover(reason, category)

    if handle_engine_switch is not None:
        # Registered by function name; the tool exists only on the fast engine.
        @tools.action(
            description=(
                "Continue this task in the full browser (Chrome). Use it ONLY when this page "
                "does not work properly in the current fast browser: it renders wrong or stays "
                "blank, a control you need is missing or does nothing when used, or a page that "
                "fills itself in by script never does. Do NOT use it for a login, a CAPTCHA, a "
                "paywall, an error message the site itself shows, or a site that is down or "
                "slow: those look the same in any browser. The run continues from this page in "
                "the full browser, still signed in. `category` is renders_wrong | "
                "control_broken | stays_empty."
            ),
            param_model=EngineSwitchParams,
        )
        async def continue_in_full_browser(params: EngineSwitchParams) -> str:
            """Return the tool that moves the run to the full browser, carrying its logins."""
            return await handle_engine_switch(params.category)

    if solve_captcha:
        # Registered by function name; BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP must spell it the same.
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
