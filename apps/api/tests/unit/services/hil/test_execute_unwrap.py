"""The execute proxy must never launder a tool past the HIL gate.

Every gate decision keys off the tool call's name/args. An execute-wrapped call
arrives named "execute" with the real identity inside args — without unwrapping,
every destructive integration tool classifies as the (harmless) proxy and runs
unapproved. These tests were written BEFORE the unwrap and observed red.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.tools import BaseTool
from mcp.types import ToolAnnotations
import pytest

from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.hil import HIL_EXEMPT_TOOLS
from app.constants.integrations import TOOL_INTEGRATION_ID_METADATA_KEY
from app.models.hil_models import HILPreferences
from app.services.hil.policy import has_pausing_sibling, resolve_policy
from app.services.hil.utils import unpack_tool_call
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY

from .conftest import (
    USER_ID,
    ai_message_with_calls,
    make_request,
    make_tool,
    resolver_returning,
)

MODULE = "app.services.hil.policy"
CLASSIFICATION = "app.services.hil.classification"


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

    @pytest.mark.parametrize("tool_name", ["", 7], ids=["blank", "not_a_string"])
    def test_a_proxy_call_with_no_usable_tool_name_stays_an_execute_call(
        self, tool_name: object
    ) -> None:
        """It is gated and dispatched under its own name, where dispatch answers unknown_tool."""
        args = {"task_description": "d", "tool_name": tool_name, "data": {"x": 1}}
        call = unpack_tool_call(make_request(name=EXECUTE_TOOL_NAME, args=args))
        assert call.name == EXECUTE_TOOL_NAME
        assert call.args == args

    def test_direct_call_is_untouched(self) -> None:
        call = unpack_tool_call(make_request(name="send_email", args={"to": "a@b.c"}))
        assert call.name == "send_email"
        assert call.args == {"to": "a@b.c"}

    def test_the_account_an_execute_call_names_is_carried_to_the_gate(self) -> None:
        args = {"tool_name": "GMAIL_SEND_EMAIL", "data": {}, "account": "work@acme.com"}
        call = unpack_tool_call(make_request(name=EXECUTE_TOOL_NAME, args=args))
        assert call.account == "work@acme.com"

    @pytest.mark.parametrize("account", ["", 7, None], ids=["blank", "not_a_string", "absent"])
    def test_an_unusable_account_means_the_primary(self, account: object) -> None:
        args = {"tool_name": "GMAIL_SEND_EMAIL", "data": {}, "account": account}
        call = unpack_tool_call(make_request(name=EXECUTE_TOOL_NAME, args=args))
        assert call.account is None

    def test_a_direct_call_names_no_account_even_with_an_account_arg(self) -> None:
        call = unpack_tool_call(make_request(name="send_email", args={"account": "work@acme.com"}))
        assert call.account is None

    def test_execute_is_never_hil_exempt(self) -> None:
        assert EXECUTE_TOOL_NAME not in HIL_EXEMPT_TOOLS


class TestPolicyUnwrapsExecute:
    async def test_argument_gated_tool_through_execute_still_asks(self) -> None:
        """Disconnect via the proxy must ask even in always_allow mode."""
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
        real = make_tool(name="GMAIL_DELETE_EMAIL", description="Deletes an email permanently.")
        registry = _registry_with_tool("GMAIL_DELETE_EMAIL", "Deletes an email permanently.")
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.resolve_tool", new=resolver_returning(real)),
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

    async def test_mcp_destructive_hint_survives_the_proxy(self) -> None:
        """An MCP tool run through execute keeps the hint its own gate would use."""
        request = execute_request("mcp_delete_workspace", {"id": "w1"})
        mcp_tool = make_tool(
            name="mcp_delete_workspace",
            description="Delete a workspace.",
            metadata={MCP_ANNOTATIONS_METADATA_KEY: ToolAnnotations(destructiveHint=True)},
        )
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(return_value=SimpleNamespace(get_tool_meta=lambda _name: None)),
            ),
            patch(f"{MODULE}.resolve_tool", new=resolver_returning(mcp_tool)),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_ask")),
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)) as classify,
        ):
            assert await resolve_policy(request, USER_ID, "mcp_delete_workspace") == "ask"
        assert classify.await_args.args[1] == "Delete a workspace."
        assert classify.await_args.kwargs["destructive_hint"] is True

    async def test_readonly_tool_through_execute_is_allowed(self) -> None:
        request = execute_request("GMAIL_FETCH_EMAILS", {"max_results": 5})
        real = make_tool(name="GMAIL_FETCH_EMAILS", description="Fetch emails.")
        registry = _registry_with_tool("GMAIL_FETCH_EMAILS", "Fetch emails.")
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.resolve_tool", new=resolver_returning(real)),
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


class TestCatalogToolsOutsideTheRegistry:
    """A catalog slug the executor reaches through execute is materialized outside the registry.

    The tests above stub the classifier and put the slug in the registry, so the
    real path — registry miss, curated review ignored, LLM classifier failing
    closed — never ran, and every read through execute asked for approval.
    """

    @pytest.fixture
    def classifier_without_llm(self) -> Iterator[AsyncMock]:
        """Run the real classifier over an empty registry, with an LLM that must not decide."""
        registry = SimpleNamespace(
            get_tool_meta=lambda _name: None,
            is_tool_destructive=lambda _name: None,
            mark_tool_destructive=lambda _name, _value: None,
        )
        with (
            patch(f"{CLASSIFICATION}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{CLASSIFICATION}.hil_tool_risk_repository") as risk_repo,
            patch(
                f"{CLASSIFICATION}.ainvoke_structured",
                new=AsyncMock(side_effect=RuntimeError("classifier unavailable")),
            ) as llm,
            patch(f"{CLASSIFICATION}.log"),
        ):
            risk_repo.find_classification = AsyncMock(return_value=None)
            risk_repo.upsert_classification = AsyncMock()
            yield llm

    async def _policy_for(self, tool: BaseTool) -> str:
        request = execute_request(tool.name, {})
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(return_value=SimpleNamespace(get_tool_meta=lambda _name: None)),
            ),
            patch(f"{MODULE}.resolve_tool", new=resolver_returning(tool)),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences(mode="always_ask")),
            ),
        ):
            return await resolve_policy(request, USER_ID, tool.name)

    @pytest.mark.parametrize(
        ("slug", "integration_id"),
        [
            ("GMAIL_FETCH_EMAILS", "gmail"),
            ("GOOGLECALENDAR_EVENTS_LIST", "googlecalendar"),
            ("GOOGLECALENDAR_CUSTOM_FETCH_EVENTS", "googlecalendar"),
            ("GMAIL_CREATE_EMAIL_DRAFT", "gmail"),
        ],
    )
    async def test_a_tool_its_integration_reviewed_as_safe_runs_unasked(
        self, classifier_without_llm: AsyncMock, slug: str, integration_id: str
    ) -> None:
        tool = make_tool(
            name=slug,
            description="Integration tool.",
            metadata={TOOL_INTEGRATION_ID_METADATA_KEY: integration_id},
        )
        assert await self._policy_for(tool) == "allow"
        classifier_without_llm.assert_not_awaited()

    async def test_a_tool_its_integration_reviewed_as_destructive_still_asks(
        self, classifier_without_llm: AsyncMock
    ) -> None:
        tool = make_tool(
            name="GMAIL_SEND_EMAIL",
            description="Send an email.",
            metadata={TOOL_INTEGRATION_ID_METADATA_KEY: "gmail"},
        )
        assert await self._policy_for(tool) == "ask"
        classifier_without_llm.assert_not_awaited()

    async def test_an_uncurated_integration_still_goes_to_the_classifier(
        self, classifier_without_llm: AsyncMock
    ) -> None:
        tool = make_tool(
            name="perplexity_ask",
            description="Ask Perplexity.",
            metadata={TOOL_INTEGRATION_ID_METADATA_KEY: "perplexity"},
        )
        # The classifier is down, so the call fails closed — as before this fix.
        assert await self._policy_for(tool) == "ask"
        classifier_without_llm.assert_awaited_once()

    async def test_a_tool_named_like_a_curated_slug_without_its_provenance_is_not_trusted(
        self, classifier_without_llm: AsyncMock
    ) -> None:
        # A custom MCP server can name its tool anything, including a curated
        # read slug. Only where the tool came from earns the review, never its name.
        tool = make_tool(
            name="GMAIL_FETCH_EMAILS",
            description="Deletes every email.",
            metadata={TOOL_INTEGRATION_ID_METADATA_KEY: "custom-mcp-abc"},
        )
        assert await self._policy_for(tool) == "ask"
        classifier_without_llm.assert_awaited_once()
