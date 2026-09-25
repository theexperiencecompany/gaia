"""Tests for the custom Browser-Use actions — registration, defaults, and the exact reason/category values handed to the takeover seam."""

from collections.abc import Awaitable, Callable

import pytest

from app.constants.browser import EngineSwitchReason
from app.services.browser.tools import build_browser_tools

CAPTCHA_DESCRIPTION = (
    "Hand a CAPTCHA to the human to solve in the live browser. Call this "
    "when you see a CAPTCHA/reCAPTCHA/hCaptcha challenge; the user solves "
    "it and you then continue. `challenge` is shown to the user verbatim "
    "as their instruction, so write it as a short second-person directive "
    "describing exactly what to solve (e.g. 'Select all squares with "
    "motorcycles, then click Verify')."
)


class _FakeGuidance:
    """Records every call to the agent-guidance seam and returns a canned instruction."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, reason: str) -> str:
        self.calls.append(reason)
        return f"guided:{reason}"


class _FakeTakeover:
    """Records every call to the takeover seam and returns a canned result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, reason: str, category: str) -> str:
        self.calls.append((reason, category))
        return f"resolved:{reason}:{category}"


def _get_action(tools, name: str):
    return tools.registry.registry.actions[name]


async def _call_action(tools, name: str, **kwargs) -> str:
    action = _get_action(tools, name)
    params = action.param_model(**kwargs)
    return await action.function(params=params)


def test_registers_takeover_action_only_when_captcha_disabled() -> None:
    takeover: Callable[[str, str], Awaitable[str]] = _FakeTakeover()
    guidance = _FakeGuidance()

    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
    )

    actions = tools.registry.registry.actions
    assert "request_human_takeover" in actions
    assert "solve_captcha_with_help" not in actions


def test_registers_both_actions_when_captcha_enabled() -> None:
    takeover: Callable[[str, str], Awaitable[str]] = _FakeTakeover()
    guidance = _FakeGuidance()

    tools = build_browser_tools(
        solve_captcha=True, handle_takeover=takeover, handle_guidance=guidance
    )

    actions = tools.registry.registry.actions
    assert "request_human_takeover" in actions
    assert "solve_captcha_with_help" in actions


async def test_takeover_defaults_category_to_irreversible() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
    )

    result = await _call_action(tools, "request_human_takeover", reason="Enter your password")

    assert takeover.calls == [("Enter your password", "irreversible")]
    assert result == "resolved:Enter your password:irreversible"


async def test_takeover_passes_explicit_category_through_unchanged() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
    )

    result = await _call_action(
        tools, "request_human_takeover", reason="Enter your card number", category="payment"
    )

    assert takeover.calls == [("Enter your card number", "payment")]
    assert result == "resolved:Enter your card number:payment"


async def test_takeover_propagates_cancellation_from_seam() -> None:
    class _Cancelled(Exception):
        pass

    async def raising_takeover(reason: str, category: str) -> str:
        raise _Cancelled("user cancelled")

    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=raising_takeover, handle_guidance=_FakeGuidance()
    )

    with pytest.raises(_Cancelled):
        await _call_action(tools, "request_human_takeover", reason="Confirm the purchase")


async def test_captcha_action_always_uses_none_category() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        solve_captcha=True, handle_takeover=takeover, handle_guidance=guidance
    )

    result = await _call_action(
        tools, "solve_captcha_with_help", challenge="Select all squares with motorcycles"
    )

    assert takeover.calls == [("Select all squares with motorcycles", "none")]
    assert result == "resolved:Select all squares with motorcycles:none"


async def test_the_guidance_action_hands_the_reason_to_the_agent_seam() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
    )

    result = await _call_action(
        tools, "request_agent_guidance", reason="The date picker never opens"
    )

    assert guidance.calls == ["The date picker never opens"]
    assert result == "guided:The date picker never opens"
    assert takeover.calls == []


def test_the_guidance_action_is_registered_even_with_captcha_off() -> None:
    """It is not a human handoff, so the captcha switch must not decide whether the run can ask the agent."""
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()

    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
    )

    assert "request_agent_guidance" in tools.registry.registry.actions


class _FakeSwitch:
    """Records every move to the full browser the agent asks for."""

    def __init__(self) -> None:
        self.calls: list[EngineSwitchReason] = []

    async def __call__(self, category: EngineSwitchReason) -> str:
        self.calls.append(category)
        return "moving"


def test_a_run_on_chrome_is_never_offered_the_full_browser() -> None:
    tools = build_browser_tools(
        solve_captcha=False, handle_takeover=_FakeTakeover(), handle_guidance=_FakeGuidance()
    )

    assert "continue_in_full_browser" not in tools.registry.registry.actions


async def test_a_run_on_the_fast_engine_can_move_to_the_full_browser_naming_why() -> None:
    switch = _FakeSwitch()
    tools = build_browser_tools(
        solve_captcha=False,
        handle_takeover=_FakeTakeover(),
        handle_guidance=_FakeGuidance(),
        handle_engine_switch=switch,
    )

    result = await _call_action(tools, "continue_in_full_browser", category="stays_empty")

    assert (switch.calls, result) == ([EngineSwitchReason.STAYS_EMPTY], "moving")
    with pytest.raises(ValueError):
        _get_action(tools, "continue_in_full_browser").param_model(category="the site is down")
