"""A secret's value goes only into the actions that type it into the page."""

from __future__ import annotations

from typing import Any

from browser_use.tools.registry.service import Registry
import pytest

import app.patches.browser_use_secret_scope_patch as patch_module

pytestmark = pytest.mark.unit

SECRETS = {"https://example.test": {"password": "hunter2"}}


@pytest.fixture
def executed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _original(self: object, **kwargs: Any) -> str:
        calls.append({"registry": self, **kwargs})
        return "done"

    monkeypatch.setattr(patch_module, "_original_execute_action", _original)
    return calls


@pytest.mark.parametrize("action", ["input", "send_keys"])
async def test_a_typing_action_gets_the_secret_values(
    executed: list[dict[str, Any]], action: str
) -> None:
    params = {"index": 3, "text": "<secret>password</secret>"}
    registry: Registry[Any] = Registry()

    answer = await patch_module._execute_action(
        registry, action, params, sensitive_data=SECRETS, browser_session="session"
    )

    assert answer == "done"
    assert executed == [
        {
            "registry": registry,
            "action_name": action,
            "params": params,
            "sensitive_data": SECRETS,
            "browser_session": "session",
        }
    ]


@pytest.mark.parametrize("action", ["done", "jev", "navigate", "click"])
async def test_every_other_action_keeps_the_placeholder(
    executed: list[dict[str, Any]], action: str
) -> None:
    await patch_module._execute_action(
        Registry(), action, {"text": "<secret>password</secret>"}, sensitive_data=SECRETS
    )

    [call] = executed
    assert call["sensitive_data"] is None


def test_apply_routes_every_action_through_the_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Registry, "execute_action", None)

    patch_module.apply()

    assert Registry.execute_action is patch_module._execute_action
