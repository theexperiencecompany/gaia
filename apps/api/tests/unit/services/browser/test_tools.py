"""Tests for the custom Browser-Use actions — registration, defaults, and the exact reason/category values handed to the takeover seam."""

from collections.abc import Awaitable, Callable

from pydantic import ValidationError
import pytest

from app.constants.browser import (
    BROWSER_CAPTCHA_SKIP_SOURCE,
    EngineSwitchReason,
    SensitiveCategory,
)
from app.services.browser.tools import build_browser_tools
from app.utils.sites import UserSites

#: The task names shop.test; nothing else is the user's.
SITES = UserSites("buy the red shoes on www.shop.test", None, ())


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
        self.calls: list[tuple[str, SensitiveCategory]] = []

    async def __call__(self, reason: str, category: SensitiveCategory) -> str:
        self.calls.append((reason, category))
        return f"resolved:{reason}:{category.value}"


def _get_action(tools, name: str):
    return tools.registry.registry.actions[name]


class _Session:
    """The browser session an action reads the current page from."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def get_current_page_url(self) -> str:
        return self._url


async def _call_action(tools, name: str, page: str = "https://shop.test/p", **kwargs) -> str:
    action = _get_action(tools, name)
    params = action.param_model(**kwargs)
    return await action.function(params=params, browser_session=_Session(page))


def test_registers_takeover_action_only_when_captcha_disabled() -> None:
    takeover: Callable[[str, SensitiveCategory], Awaitable[str]] = _FakeTakeover()
    guidance = _FakeGuidance()

    tools = build_browser_tools(
        user_sites=SITES, solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
    )

    actions = tools.registry.registry.actions
    assert "request_human_takeover" in actions
    assert "solve_captcha_with_help" not in actions


def test_registers_both_actions_when_captcha_enabled() -> None:
    takeover: Callable[[str, SensitiveCategory], Awaitable[str]] = _FakeTakeover()
    guidance = _FakeGuidance()

    tools = build_browser_tools(
        user_sites=SITES, solve_captcha=True, handle_takeover=takeover, handle_guidance=guidance
    )

    actions = tools.registry.registry.actions
    assert "request_human_takeover" in actions
    assert "solve_captcha_with_help" in actions


@pytest.mark.parametrize("arguments", [{}, {"category": "shipping"}])
def test_a_takeover_needs_one_of_the_known_categories(arguments: dict[str, str]) -> None:
    tools = build_browser_tools(
        user_sites=SITES,
        solve_captcha=False,
        handle_takeover=_FakeTakeover(),
        handle_guidance=_FakeGuidance(),
    )

    with pytest.raises(ValidationError):
        _get_action(tools, "request_human_takeover").param_model(
            reason="Confirm the order", **arguments
        )


async def test_takeover_passes_explicit_category_through_unchanged() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        user_sites=SITES, solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
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
        user_sites=SITES,
        solve_captcha=False,
        handle_takeover=raising_takeover,
        handle_guidance=_FakeGuidance(),
    )

    with pytest.raises(_Cancelled):
        await _call_action(
            tools, "request_human_takeover", reason="Confirm the purchase", category="irreversible"
        )


async def test_captcha_action_always_uses_none_category() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        user_sites=SITES, solve_captcha=True, handle_takeover=takeover, handle_guidance=guidance
    )

    result = await _call_action(
        tools, "solve_captcha_with_help", challenge="Select all squares with motorcycles"
    )

    assert takeover.calls == [("Select all squares with motorcycles", "none")]
    assert result == "resolved:Select all squares with motorcycles:none"


@pytest.mark.parametrize(
    ("page", "host"), [("https://ads.test/x", "ads.test"), ("about:blank", "about:blank")]
)
async def test_a_captcha_on_a_site_the_user_never_named_is_skipped_without_asking_anyone(
    page: str, host: str
) -> None:
    takeover, switch = _FakeTakeover(), _FakeSwitch()
    tools = build_browser_tools(
        user_sites=SITES,
        solve_captcha=True,
        handle_takeover=takeover,
        handle_guidance=_FakeGuidance(),
        handle_engine_switch=switch,
    )

    result = await _call_action(tools, "solve_captcha_with_help", page=page, challenge="Solve it")

    assert result == BROWSER_CAPTCHA_SKIP_SOURCE.format(host=host)
    assert (takeover.calls, switch.calls) == ([], [])


async def test_a_captcha_on_the_fast_engine_is_tried_in_the_full_browser_before_the_user() -> None:
    """Bing's bot check stopped the fast browser only, and the user was asked to pass it."""
    takeover = _FakeTakeover()
    switch = _FakeSwitch()
    tools = build_browser_tools(
        user_sites=SITES,
        solve_captcha=True,
        handle_takeover=takeover,
        handle_guidance=_FakeGuidance(),
        handle_engine_switch=switch,
    )

    result = await _call_action(tools, "solve_captcha_with_help", challenge="Solve the check")

    assert (switch.calls, result) == ([EngineSwitchReason.BOT_CHALLENGE], "moving")
    assert takeover.calls == []


async def test_the_guidance_action_hands_the_reason_to_the_agent_seam() -> None:
    takeover = _FakeTakeover()
    guidance = _FakeGuidance()
    tools = build_browser_tools(
        user_sites=SITES, solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
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
        user_sites=SITES, solve_captcha=False, handle_takeover=takeover, handle_guidance=guidance
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
        user_sites=SITES,
        solve_captcha=False,
        handle_takeover=_FakeTakeover(),
        handle_guidance=_FakeGuidance(),
    )

    assert "continue_in_full_browser" not in tools.registry.registry.actions


async def test_a_run_on_the_fast_engine_can_move_to_the_full_browser_naming_why() -> None:
    switch = _FakeSwitch()
    tools = build_browser_tools(
        user_sites=SITES,
        solve_captcha=False,
        handle_takeover=_FakeTakeover(),
        handle_guidance=_FakeGuidance(),
        handle_engine_switch=switch,
    )

    result = await _call_action(tools, "continue_in_full_browser", category="stays_empty")

    assert (switch.calls, result) == ([EngineSwitchReason.STAYS_EMPTY], "moving")
    with pytest.raises(ValueError):
        _get_action(tools, "continue_in_full_browser").param_model(category="the site is down")
