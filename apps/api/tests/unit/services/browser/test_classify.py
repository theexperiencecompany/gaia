"""Tests for the sensitive-action classifier and its fail-safe behavior."""

from unittest.mock import AsyncMock

from app.constants.browser import SensitiveCategory
from app.schemas.browser import SensitiveActionVerdict
from app.services.browser import classify as classify_mod
from app.services.browser.classify import classify_step, is_structurally_safe


def test_structurally_safe_navigation_only():
    assert is_structurally_safe(["go_to_url", "scroll"]) is True
    assert is_structurally_safe(["click_element"]) is False
    assert is_structurally_safe([]) is False


async def test_safe_step_skips_llm(monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr(classify_mod, "ainvoke_structured", called)

    verdict = await classify_step(
        goal="Search for flights", action_names=["go_to_url", "search"], actions_detail="", url="x"
    )
    assert verdict.requires_approval is False
    called.assert_not_awaited()


async def test_interactive_step_consults_llm(monkeypatch):
    llm = AsyncMock(
        return_value=SensitiveActionVerdict(
            requires_approval=True,
            category=SensitiveCategory.CREDENTIALS,
            reason="Entering a password.",
        )
    )
    monkeypatch.setattr(classify_mod, "ainvoke_structured", llm)
    verdict = await classify_step(
        goal="Sign in",
        action_names=["input_text"],
        actions_detail="input_text(password field)",
        url="https://site/login",
    )
    assert verdict.requires_approval is True
    assert verdict.category == SensitiveCategory.CREDENTIALS
    llm.assert_awaited_once()


async def test_deterministic_payment_bypasses_llm(monkeypatch):
    # A checkout-commit step forces approval WITHOUT the LLM — money never rides
    # on a single model call. The (mocked) judge would wrongly say "safe".
    llm = AsyncMock(return_value=SensitiveActionVerdict(requires_approval=False))
    monkeypatch.setattr(classify_mod, "ainvoke_structured", llm)
    verdict = await classify_step(
        goal="Complete the order",
        action_names=["click_element"],
        actions_detail="click_element(Place order)",
        url="https://shop.example.com/checkout",
    )
    assert verdict.requires_approval is True
    assert verdict.category == SensitiveCategory.PAYMENT
    llm.assert_not_awaited()


async def test_classifier_failure_fails_safe(monkeypatch):
    monkeypatch.setattr(
        classify_mod, "ainvoke_structured", AsyncMock(side_effect=RuntimeError("llm down"))
    )
    verdict = await classify_step(
        goal="Click something",
        action_names=["click_element"],
        actions_detail="click_element(x)",
        url="https://x",
    )
    # On classifier error we require approval rather than let it through.
    assert verdict.requires_approval is True
