"""The execute proxy must never launder a tool past the HIL gate.

Every gate decision keys off the tool call's name/args. An execute-wrapped call
arrives named "execute" with the real identity inside args — without unwrapping,
every destructive integration tool classifies as the (harmless) proxy and runs
unapproved. These tests were written BEFORE the unwrap and observed red.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware.types import ToolCallRequest
import pytest

from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.hil import HIL_EXEMPT_TOOLS
from app.models.hil_models import HILPreferences
from app.services.hil.policy import has_pausing_sibling, resolve_policy
from app.services.hil.utils import unpack_tool_call

from .conftest import USER_ID, ai_message_with_calls, make_request, make_tool

MODULE = "app.services.hil.policy"


def execute_request(
    real_name: str,
    data: dict[str, Any],
    *,
    call_id: str = "call-x",
    messages: list[Any] | None = None,
) -> ToolCallRequest:
    return make_request(
        name=EXECUTE_TOOL_NAME,
        args={"task_description": "doing the thing", "tool_name": real_name, "data": data},
        call_id=call_id,
        tool=make_tool(name=EXECUTE_TOOL_NAME, description="Run an integration tool by name."),
        messages=messages,
    )


def _registry_with_tool(name: str, description: str) -> SimpleNamespace:
    real_tool = make_tool(name=name, description=description)

    def _meta(lookup: str) -> SimpleNamespace | None:
        if lookup == name:
            return SimpleNamespace(name=name, tool=real_tool, always_gate=False)
        return None

    return SimpleNamespace(get_tool_meta=_meta)


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


class TestUnpackUnwrapsExecute:
    def test_execute_call_unpacks_to_the_real_tool(self) -> None:
        call = unpack_tool_call(
            execute_request("GMAIL_DELETE_EMAIL", {"message_id": "m1"}, call_id="c9")
        )
        assert call.name == "GMAIL_DELETE_EMAIL"
        assert call.args == {"message_id": "m1"}
        # The ToolMessage a refusal produces must answer the actual call id.
        assert call.id == "c9"

    def test_missing_data_unwraps_to_empty_args(self) -> None:
        request = make_request(
            name=EXECUTE_TOOL_NAME,
            args={"task_description": "d", "tool_name": "GMAIL_DELETE_EMAIL"},
        )
        call = unpack_tool_call(request)
        assert call.name == "GMAIL_DELETE_EMAIL"
        assert call.args == {}

    def test_direct_call_is_untouched(self) -> None:
        call = unpack_tool_call(make_request(name="send_email", args={"to": "a@b.c"}))
        assert call.name == "send_email"
        assert call.args == {"to": "a@b.c"}

    def test_execute_is_never_hil_exempt(self) -> None:
        assert EXECUTE_TOOL_NAME not in HIL_EXEMPT_TOOLS


class TestPolicyUnwrapsExecute:
    async def test_argument_gated_tool_through_execute_still_asks(self) -> None:
        """disconnect via the proxy must ask even in always_allow mode."""
        request = execute_request("manage_linked_account", {"action": "disconnect"})
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(return_value=SimpleNamespace(get_tool_meta=lambda name: None)),
            ),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_allow")),
            ),
        ):
            assert await resolve_policy(request, USER_ID, "manage_linked_account") == "ask"

    async def test_destructive_tool_through_execute_classifies_the_real_tool(self) -> None:
        request = execute_request("GMAIL_DELETE_EMAIL", {"message_id": "m1"})
        registry = _registry_with_tool("GMAIL_DELETE_EMAIL", "Deletes an email permanently.")
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_ask")),
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)) as classify,
        ):
            policy = await resolve_policy(request, USER_ID, "GMAIL_DELETE_EMAIL")
        assert policy == "ask"
        # The classifier must see the REAL tool — its name AND its description,
        # not the proxy's ("Run an integration tool by name.").
        name_arg, description_arg = classify.await_args.args[:2]
        assert name_arg == "GMAIL_DELETE_EMAIL"
        assert description_arg == "Deletes an email permanently."

    async def test_readonly_tool_through_execute_is_allowed(self) -> None:
        request = execute_request("GMAIL_FETCH_EMAILS", {"max_results": 5})
        registry = _registry_with_tool("GMAIL_FETCH_EMAILS", "Fetch emails.")
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_ask")),
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=False)),
        ):
            assert await resolve_policy(request, USER_ID, "GMAIL_FETCH_EMAILS") == "allow"


class TestSiblingScanUnwrapsExecute:
    async def test_execute_wrapped_destructive_sibling_pauses(self) -> None:
        sibling = {
            "id": "sib-1",
            "name": EXECUTE_TOOL_NAME,
            "args": {"task_description": "d", "tool_name": "GMAIL_DELETE_EMAIL", "data": {}},
        }
        pending = {"id": "call-x", "name": "read", "args": {}}
        request = make_request(
            name="read",
            args={},
            call_id="call-x",
            messages=[ai_message_with_calls(pending, sibling)],
        )
        registry = _registry_with_tool("GMAIL_DELETE_EMAIL", "Deletes an email permanently.")

        async def _classify(name: str, description: str, **_: Any) -> bool:
            return name == "GMAIL_DELETE_EMAIL"

        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_ask")),
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(side_effect=_classify)),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-x") is True

    async def test_execute_wrapped_argument_gated_sibling_pauses_in_always_allow(self) -> None:
        sibling = {
            "id": "sib-1",
            "name": EXECUTE_TOOL_NAME,
            "args": {
                "task_description": "d",
                "tool_name": "manage_linked_account",
                "data": {"action": "disconnect"},
            },
        }
        pending = {"id": "call-x", "name": "read", "args": {}}
        request = make_request(
            name="read",
            args={},
            call_id="call-x",
            messages=[ai_message_with_calls(pending, sibling)],
        )
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(return_value=SimpleNamespace(get_tool_meta=lambda name: None)),
            ),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_allow")),
            ),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-x") is True
