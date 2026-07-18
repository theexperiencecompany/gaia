"""Tests for the flexible mid-run sensitive-action policy."""

from app.constants.browser import HandoffStrategy, SensitiveCategory
from app.services.browser import policy as policy_mod
from app.services.browser.policy import resolve_strategy


def test_none_proceeds():
    assert resolve_strategy(SensitiveCategory.NONE) == HandoffStrategy.PROCEED


def test_payment_defaults_to_handoff(monkeypatch):
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_AUTONOMOUS_SENSITIVE", False)
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_PAYMENT_STRATEGY", "handoff")
    assert resolve_strategy(SensitiveCategory.PAYMENT) == HandoffStrategy.HANDOFF


def test_autonomous_setting_proceeds(monkeypatch):
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_AUTONOMOUS_SENSITIVE", True)
    assert resolve_strategy(SensitiveCategory.PAYMENT) == HandoffStrategy.PROCEED


def test_per_task_override_proceeds(monkeypatch):
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_AUTONOMOUS_SENSITIVE", False)
    assert (
        resolve_strategy(SensitiveCategory.PAYMENT, autonomous_override=True)
        == HandoffStrategy.PROCEED
    )


def test_per_task_override_forces_handoff(monkeypatch):
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_AUTONOMOUS_SENSITIVE", True)
    # Explicit False beats the autonomous default → still hands off.
    assert (
        resolve_strategy(SensitiveCategory.PAYMENT, autonomous_override=False)
        == HandoffStrategy.HANDOFF
    )


def test_configured_abort(monkeypatch):
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_AUTONOMOUS_SENSITIVE", False)
    monkeypatch.setattr(policy_mod.settings, "BROWSER_USE_CREDENTIALS_STRATEGY", "abort")
    assert resolve_strategy(SensitiveCategory.CREDENTIALS) == HandoffStrategy.ABORT
