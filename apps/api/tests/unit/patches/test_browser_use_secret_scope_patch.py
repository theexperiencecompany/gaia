"""A secret's value goes only into the actions that type it into the page."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from browser_use.tools.registry.service import Registry
import pytest

import app.patches.browser_use_secret_scope_patch as patch_module

pytestmark = pytest.mark.unit

SECRETS = {"https://example.test": {"password": "hunter2"}}


def _on(url: str) -> SimpleNamespace:
    """Return a Browser-Use session whose focused tab is on url."""
    tab = SimpleNamespace(url=url)
    return SimpleNamespace(
        agent_focus_target_id="tab-1",
        session_manager=SimpleNamespace(
            get_target=lambda target: tab if target == "tab-1" else None
        ),
    )


@pytest.fixture
def executed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _original(self: object, **kwargs: Any) -> str:
        calls.append({"registry": self, **kwargs})
        return "done"

    monkeypatch.setattr(patch_module, "_original_execute_action", _original)
    return calls


async def test_the_input_action_gets_the_secret_values(executed: list[dict[str, Any]]) -> None:
    params = {"index": 3, "text": "<secret>password</secret>"}
    registry: Registry[Any] = Registry()
    session = _on("https://example.test/login")

    answer = await patch_module._execute_action(
        registry, "input", params, sensitive_data=SECRETS, browser_session=session
    )

    assert answer == "done"
    assert executed == [
        {
            "registry": registry,
            "action_name": "input",
            "params": params,
            "sensitive_data": SECRETS,
            "browser_session": session,
        }
    ]


async def test_a_typing_action_naming_a_secret_it_cannot_fill_fails_and_types_nothing(
    executed: list[dict[str, Any]],
) -> None:
    text = {"index": 3, "text": "<secret>user</secret> <secret>password</secret>"}
    unfocused = _on("https://example.test/")
    unfocused.agent_focus_target_id = None

    off_site = await patch_module._execute_action(
        Registry(), "input", text, sensitive_data=SECRETS, browser_session=_on("https://evil.test/")
    )
    no_tab = await patch_module._execute_action(
        Registry(), "input", text, sensitive_data=SECRETS, browser_session=unfocused
    )
    # Browser-Use logs send_keys' keys at INFO and keeps them in the step's memory.
    as_keys = await patch_module._execute_action(
        Registry(),
        "send_keys",
        {"keys": "<secret>password</secret>"},
        sensitive_data=SECRETS,
        browser_session=_on("https://example.test/login"),
    )

    assert executed == []
    assert off_site.error == (
        "password is not used on evil.test; user is not used on evil.test; nothing was typed."
    )
    assert no_tab.error == (
        "password is not used on this page; user is not used on this page; nothing was typed."
    )
    assert as_keys.error == (
        "password is typed only into its field, never as keys; nothing was typed."
    )


@pytest.mark.parametrize("action", ["done", "jev", "navigate", "click"])
async def test_every_other_action_keeps_the_placeholder(
    executed: list[dict[str, Any]], action: str
) -> None:
    await patch_module._execute_action(
        Registry(), action, {"text": "<secret>password</secret>"}, sensitive_data=SECRETS
    )

    [call] = executed
    assert call["sensitive_data"] is None
    assert (call["action_name"], call["params"]) == (action, {"text": "<secret>password</secret>"})


def test_apply_routes_every_action_through_the_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Registry, "execute_action", None)

    patch_module.apply()

    assert Registry.execute_action is patch_module._execute_action


async def test_an_input_typing_a_secrets_name_bare_types_nothing(
    executed: list[dict[str, Any]],
) -> None:
    """The agent dropped the tags and wrote "password": the field got the word, not the secret."""
    answer = await patch_module._execute_action(
        Registry(),
        "input",
        {"index": 3, "text": "password"},
        sensitive_data=SECRETS,
        browser_session=_on("https://example.test/login"),
    )

    assert executed == []
    assert "type <secret>password</secret>" in str(answer.error)
