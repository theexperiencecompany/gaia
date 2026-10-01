"""Custom Browser-Use actions the agent can call mid-run.

Seams the agent reaches for itself: request_human_takeover is the agent's own
way to pause for the human at a sensitive step (payment, credentials,
irreversible); solve_captcha_with_help hands a CAPTCHA to the human since there
is no automatic solver; request_agent_guidance asks the agent that started the
run, not the user; continue_in_full_browser moves the run to Chrome. Each ends
its step's action sequence: the page is about to change hands, so an action
queued behind one would act on a page nobody looked at.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from browser_use import Tools
from pydantic import BaseModel

from app.constants.browser import EngineSwitchReason, SensitiveCategory

TakeoverFn = Callable[[str, SensitiveCategory], Awaitable[str]]
AgentGuidanceFn = Callable[[str], Awaitable[str]]
EngineSwitchFn = Callable[[EngineSwitchReason], Awaitable[str]]


class EngineSwitchParams(BaseModel):
    """The continue_in_full_browser action's one argument: which engine-caused breakage it was."""

    category: EngineSwitchReason


class TakeoverParams(BaseModel):
    """The request_human_takeover action's arguments: the ask shown to the user, and what kind of step it is."""

    reason: str
    category: SensitiveCategory


def build_browser_tools(
    *,
    solve_captcha: bool,
    handle_takeover: TakeoverFn,
    handle_guidance: AgentGuidanceFn,
    handle_engine_switch: EngineSwitchFn | None = None,
) -> Tools[None]:
    """Build the Browser-Use Tools the agent can call during a run.

    Each handler returns the text the agent reads as the action's result;
    handle_engine_switch, given only on the fast engine, moves the run to the
    full browser.
    """
    tools: Tools[None] = Tools()

    # Registered by function name; BrowserHandoffAction.REQUEST_AGENT_GUIDANCE must spell it the same.
    @tools.action(
        description=(
            "Ask the assistant that gave you this task what to do, when no action on "
            "this page moves the task forward and no human step is what is missing. "
            "It answers with ONE concrete instruction and you then continue. `reason` "
            "says what you tried and what the page does instead; it is read by an "
            "assistant, not by the user, so write it as a plain statement of fact."
        ),
        terminates_sequence=True,
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
            "it in the live browser and tells you when they are done; you then continue. "
            "`reason` is shown to the user verbatim as the ask itself, so write it as the "
            "ask: two short second-person sentences, what to do plus what happens after "
            "(e.g. 'Enter your password and sign in. After that I'll finish the booking.'). "
            "No third-person explanation, no field names, no element ids. `category` "
            "is one of payment | credentials | irreversible."
        ),
        param_model=TakeoverParams,
        terminates_sequence=True,
    )
    async def request_human_takeover(params: TakeoverParams) -> str:
        """Return the takeover tool that hands control to the user via live view."""
        return await handle_takeover(params.reason, params.category)

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
                "the full browser. `category` is renders_wrong | control_broken | stays_empty."
            ),
            param_model=EngineSwitchParams,
            terminates_sequence=True,
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
            ),
            terminates_sequence=True,
        )
        async def solve_captcha_with_help(challenge: str) -> str:
            """Return the CAPTCHA tool that asks the user to solve it in live view."""
            return await handle_takeover(challenge, SensitiveCategory.NONE)

    return tools
