"""Tests for the custom Browser-Use actions — registration, defaults, and the
exact reason/category values handed to the takeover seam."""

from collections.abc import Awaitable, Callable

import pytest

from app.services.browser.tools import build_browser_tools

CAPTCHA_DESCRIPTION = (
    "Hand a CAPTCHA to the human to solve in the live browser. Call this "
    "when you see a CAPTCHA/reCAPTCHA/hCaptcha challenge; the user solves "
    "it and you then continue. `challenge` is shown to the user verbatim "
    "as their instruction, so write it as a short second-person directive "
    "describing exactly what to solve (e.g. 'Select all squares with "
    "motorcycles, then click Verify')."
)


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

    tools = build_browser_tools(solve_captcha=False, handle_takeover=takeover)

    actions = tools.registry.registry.actions
    assert "request_human_takeover" in actions
    assert "solve_captcha_with_help" not in actions


def test_registers_both_actions_when_captcha_enabled() -> None:
    takeover: Callable[[str, str], Awaitable[str]] = _FakeTakeover()

    tools = build_browser_tools(solve_captcha=True, handle_takeover=takeover)

    actions = tools.registry.registry.actions
    assert "request_human_takeover" in actions
    assert "solve_captcha_with_help" in actions


async def test_takeover_defaults_category_to_irreversible() -> None:
    takeover = _FakeTakeover()
    tools = build_browser_tools(solve_captcha=False, handle_takeover=takeover)

    result = await _call_action(tools, "request_human_takeover", reason="Enter your password")

    assert takeover.calls == [("Enter your password", "irreversible")]
    assert result == "resolved:Enter your password:irreversible"


async def test_takeover_passes_explicit_category_through_unchanged() -> None:
    takeover = _FakeTakeover()
    tools = build_browser_tools(solve_captcha=False, handle_takeover=takeover)

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

    tools = build_browser_tools(solve_captcha=False, handle_takeover=raising_takeover)

    with pytest.raises(_Cancelled):
        await _call_action(tools, "request_human_takeover", reason="Confirm the purchase")


async def test_captcha_action_always_uses_none_category() -> None:
    takeover = _FakeTakeover()
    tools = build_browser_tools(solve_captcha=True, handle_takeover=takeover)

    result = await _call_action(
        tools, "solve_captcha_with_help", challenge="Select all squares with motorcycles"
    )

    assert takeover.calls == [("Select all squares with motorcycles", "none")]
    assert result == "resolved:Select all squares with motorcycles:none"


def test_captcha_action_description_is_exact() -> None:
    takeover = _FakeTakeover()
    tools = build_browser_tools(solve_captcha=True, handle_takeover=takeover)

    action = _get_action(tools, "solve_captcha_with_help")

    assert action.description == CAPTCHA_DESCRIPTION


def test_takeover_action_description_mentions_all_three_categories() -> None:
    takeover = _FakeTakeover()
    tools = build_browser_tools(solve_captcha=False, handle_takeover=takeover)

    action = _get_action(tools, "request_human_takeover")

    assert "payment | credentials | irreversible" in action.description
