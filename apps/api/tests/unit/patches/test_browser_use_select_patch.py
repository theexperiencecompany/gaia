"""Picking a dropdown option must not write option.selected, which Obscura ignores."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
import pytest

import app.patches.browser_use_select_patch as patch_module

pytestmark = pytest.mark.unit


class _Input:
    """A dropdown is set in JavaScript; reaching Input at all is the bug."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"selecting an option must not call Input.{name}")


_SESSION = "sess"
_NODE_ID = 42


class _FakeCdp:
    """A fake CDP client that runs the patch's JS against a tiny <select> model.

    Like the real protocol it answers only the session it is addressed to, finds
    the element only by its own backend node id, and hands back a plain value
    only when asked for one by value.
    """

    def __init__(
        self,
        options: list[tuple[str, str]],
        *,
        object_id: str | None = "obj-1",
        raises: bool = False,
        honour_selection: bool = True,
        script_result: dict[str, Any] | None = None,
    ) -> None:
        self.options = options
        self.selected_index = 0
        self.calls: list[str] = []
        self.honour_selection = honour_selection
        outer = self

        def _addressed(session_id: str) -> None:
            if session_id != _SESSION:
                raise RuntimeError(f"Session with given id not found: {session_id}")

        class _DOM:
            @staticmethod
            async def resolveNode(params: dict[str, Any], session_id: str) -> dict[str, Any]:
                outer.calls.append("DOM.resolveNode")
                _addressed(session_id)
                if params.get("backendNodeId") != _NODE_ID:
                    raise RuntimeError("No node with given id found")
                return {"object": {"objectId": object_id}} if object_id else {"object": {}}

        class _Runtime:
            @staticmethod
            async def callFunctionOn(params: dict[str, Any], session_id: str) -> dict[str, Any]:
                outer.calls.append("Runtime.callFunctionOn")
                _addressed(session_id)
                if params.get("objectId") != object_id:
                    raise RuntimeError("Either objectId or executionContextId must be specified")
                source = params["functionDeclaration"]
                assert "option.selected" not in source, (
                    "Obscura ignores `option.selected = true` and it corrupts the select"
                )
                if raises:
                    return {"exceptionDetails": {"text": "boom"}}
                payload = script_result if script_result is not None else _run(params)
                if params.get("returnByValue") is not True:
                    # By reference, a string result carries no `value`.
                    return {"result": {"type": "string", "objectId": "remote-1"}}
                return {"result": {"type": "string", "value": json.dumps(payload)}}

        def _run(params: dict[str, Any]) -> dict[str, Any]:
            wanted = str(params["arguments"][0]["value"]).strip().lower()
            index = next(
                (
                    i
                    for i, (text, value) in enumerate(outer.options)
                    if text.strip().lower() == wanted or value.strip().lower() == wanted
                ),
                -1,
            )
            if index < 0:
                return {
                    "error": "not-found",
                    "options": [{"text": t, "value": v} for t, v in outer.options],
                }
            if outer.honour_selection:
                outer.selected_index = index
            landed = outer.options[outer.selected_index][0]
            return {
                "selected": landed == outer.options[index][0],
                "text": outer.options[index][0],
                "value": outer.options[index][1],
                "index": outer.selected_index,
                "landed_on": landed,
            }

        self.send = SimpleNamespace(DOM=_DOM(), Runtime=_Runtime(), Input=_Input())


def _watchdog(cdp: _FakeCdp, node: object | None = None) -> SimpleNamespace:
    session = SimpleNamespace(session_id=_SESSION, cdp_client=cdp)

    async def cdp_client_for_node(asked_for: object) -> SimpleNamespace:
        if node is not None and asked_for is not node:
            raise AssertionError("the CDP session must be the one for the event's own node")
        return session

    return SimpleNamespace(browser_session=SimpleNamespace(cdp_client_for_node=cdp_client_for_node))


def _event(text: str, tag: str = "select") -> SimpleNamespace:
    return SimpleNamespace(node=SimpleNamespace(backend_node_id=_NODE_ID, tag_name=tag), text=text)


async def _select(cdp: _FakeCdp, text: str, tag: str = "select") -> dict[str, str]:
    event = _event(text, tag)
    return await patch_module.on_SelectDropdownOptionEvent(_watchdog(cdp, event.node), event)


_OPTIONS = [("Open this select menu", "Open this select menu"), ("One", "1"), ("Two", "2")]


async def test_the_option_matching_the_text_is_selected() -> None:
    cdp = _FakeCdp(_OPTIONS)

    result = await _select(cdp, "Two")

    assert result == {"success": "true", "message": "Selected option: Two (value: 2)"}
    assert cdp.selected_index == 2


async def test_an_option_is_matched_by_its_value_too() -> None:
    cdp = _FakeCdp(_OPTIONS)

    assert (await _select(cdp, "1"))["success"] == "true"
    assert cdp.selected_index == 1


async def test_matching_ignores_case_and_surrounding_space() -> None:
    cdp = _FakeCdp(_OPTIONS)

    assert (await _select(cdp, "  tWo  "))["success"] == "true"
    assert cdp.selected_index == 2


async def test_a_missing_option_reports_every_option_that_exists() -> None:
    result = await _select(_FakeCdp(_OPTIONS), "Four")

    assert result == {
        "success": "false",
        "short_term_memory": (
            "No option 'Four' in this dropdown. Available: Open this select menu, One, Two"
        ),
        "long_term_memory": "Dropdown has no option 'Four'",
    }


async def test_a_dropdown_that_reverts_the_pick_is_reported_as_a_failure() -> None:
    # A page framework really resetting the value must still fail loudly -- the
    # patch only stops Obscura's stale `value` from faking that reversion.
    result = await _select(_FakeCdp(_OPTIONS, honour_selection=False), "Two")

    assert result == {
        "success": "false",
        "short_term_memory": "Selecting 'Two' left the dropdown on 'Open this select menu'.",
        "long_term_memory": "Dropdown reverted the selection of 'Two'",
    }


async def test_an_unresolvable_node_fails_without_running_the_script() -> None:
    cdp = _FakeCdp(_OPTIONS, object_id=None)

    result = await _select(cdp, "Two")

    assert result == {
        "success": "false",
        "short_term_memory": "Could not reach the dropdown to select 'Two'.",
        "long_term_memory": f"Dropdown at index {_NODE_ID} could not be resolved",
    }
    assert "Runtime.callFunctionOn" not in cdp.calls


async def test_a_script_that_throws_fails_instead_of_claiming_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(patch_module, "log", logger)

    result = await _select(_FakeCdp(_OPTIONS, raises=True), "Two")

    assert result == {
        "success": "false",
        "short_term_memory": "Could not select 'Two' in the dropdown.",
        "long_term_memory": "Dropdown selection of 'Two' failed to run",
    }
    (message,), fields = logger.warning.call_args
    assert "Dropdown selection script did not run" in message
    assert fields == {"error_type": "SelectScriptFailed"}


async def test_a_script_that_throws_a_string_is_not_read_as_an_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `throw "..."` comes back as a string value beside exceptionDetails; it is
    # the page's error, not the script's JSON report.
    monkeypatch.setattr(patch_module, "log", MagicMock())
    cdp = _FakeCdp(_OPTIONS)
    thrown = {
        "result": {"type": "string", "value": '{"selected": true}'},
        "exceptionDetails": {"text": "Uncaught"},
    }

    async def throws_a_string(params: dict[str, Any], session_id: str) -> dict[str, Any]:
        return thrown

    cdp.send.Runtime.callFunctionOn = throws_a_string

    assert (await _select(cdp, "Two"))["success"] == "false"


async def test_a_script_that_returns_nothing_fails_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(patch_module, "log", MagicMock())
    cdp = _FakeCdp(_OPTIONS)

    async def returns_undefined(params: dict[str, Any], session_id: str) -> dict[str, Any]:
        return {"result": {"type": "undefined"}}

    cdp.send.Runtime.callFunctionOn = returns_undefined

    assert (await _select(cdp, "Two"))["success"] == "false"


async def test_a_node_that_turns_out_not_to_be_a_select_names_what_it_is() -> None:
    # The node said <select> when the DOM was read; the element the script
    # reached has no options, so the page replaced it since.
    cdp = _FakeCdp(_OPTIONS, script_result={"error": "not-a-select", "tag": "DIV"})

    result = await _select(cdp, "Two")

    assert result == {
        "success": "false",
        "short_term_memory": "Element is a <DIV>, not a dropdown.",
        "long_term_memory": f"Index {_NODE_ID} is not a <select>",
    }


async def test_an_aria_dropdown_goes_back_to_browser_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # role=menu/listbox widgets have no options to assign; only <select> is broken.
    called: list[tuple[object, str]] = []

    async def original(watchdog: object, event: SimpleNamespace) -> dict[str, str]:
        called.append((watchdog, getattr(event.node, "tag_name", "")))
        return {"success": "true", "message": "aria"}

    monkeypatch.setattr(patch_module, "_original_on_select", original)
    cdp = _FakeCdp(_OPTIONS)
    watchdog = _watchdog(cdp)

    result = await patch_module.on_SelectDropdownOptionEvent(watchdog, _event("Two", tag="div"))

    assert result == {"success": "true", "message": "aria"}
    assert called == [(watchdog, "div")]
    assert cdp.calls == []


def test_apply_rebinds_the_watchdog_handler() -> None:
    installed = DefaultActionWatchdog.on_SelectDropdownOptionEvent
    type.__setattr__(DefaultActionWatchdog, "on_SelectDropdownOptionEvent", object())
    try:
        patch_module.apply()
        assert (
            DefaultActionWatchdog.on_SelectDropdownOptionEvent
            is patch_module.on_SelectDropdownOptionEvent
        )
    finally:
        type.__setattr__(DefaultActionWatchdog, "on_SelectDropdownOptionEvent", installed)
