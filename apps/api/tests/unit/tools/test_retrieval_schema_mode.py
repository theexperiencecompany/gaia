"""retrieve_tools binding mode after the execute cutover.

Integration tools (Composio require_integration categories, MCP tools, catalog
slugs) come back as schema docs and are NOT bound; internal tools still bind.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
import pytest

from app.agents.tools.core import retrieval
from app.agents.tools.core.registry import DESKTOP_TOOL_CATEGORY
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.execute.schema_docs import render_tool_doc
from app.agents.tools.execute.tool_info import tool_contract
from app.constants.execute import RETURNS_INLINE_MAX_CHARS
from app.models.chat_models import ConversationSource
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.usefixtures("no_observed_tool_shapes")

MODULE = "app.agents.tools.core.retrieval"
CONFIG: dict[str, Any] = {"configurable": {"user_id": "u1"}}


class _GmailSendArgs(BaseModel):
    recipient_email: str = Field(description="Recipient")
    subject: str


def _gmail_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kwargs: None,
        name="GMAIL_SEND_EMAIL",
        description="Send an email.",
        args_schema=_GmailSendArgs,
    )


async def _doc(name: str, tool: StructuredTool) -> str:
    return render_tool_doc(
        await tool_contract(ResolvedTool(name, tool, True)), RETURNS_INLINE_MAX_CHARS
    )


def _registry() -> MagicMock:
    registry = MagicMock()
    registry.get_tool_names.return_value = ["read", "GMAIL_SEND_EMAIL"]
    categories = {
        "read": ("development", False),
        "GMAIL_SEND_EMAIL": ("GMAIL", True),
    }
    registry.get_category_of_tool.side_effect = lambda n: categories.get(n, ("unknown", False))[0]

    def _category(name: str | None = None) -> MagicMock | None:
        for _tool, (cat, require) in categories.items():
            if cat == name:
                c = MagicMock()
                c.require_integration = require
                return c
        return None

    registry.get_category.side_effect = _category
    return registry


async def _call(exact: list[str], resolver_result: ResolvedTool | None) -> Any:
    fn = get_retrieve_tools_function()
    with (
        patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry())),
        patch(f"{MODULE}._user_mcp_tool_names", new=AsyncMock(return_value={"NOTION_MCP_SEARCH"})),
        patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=resolver_result)),
    ):
        return await fn(store=MagicMock(), config=CONFIG, exact_tool_names=exact)


@pytest.mark.unit
class TestSchemaModeCutover:
    async def test_integration_tool_returns_schema_and_is_not_bound(self) -> None:
        tool = _gmail_tool()
        result = await _call(["GMAIL_SEND_EMAIL"], ResolvedTool("GMAIL_SEND_EMAIL", tool, True))
        assert result["tools_to_bind"] == []
        assert "GMAIL_SEND_EMAIL" in result["response"]
        text = result["response_text"]
        assert "## GMAIL_SEND_EMAIL" in text
        assert "recipient_email" in text
        assert "execute(" in text
        assert "NOT bound" in text
        # The proxied name must not ALSO come back as a bare line. It used to:
        # bind_lines echoed every response entry that was not a bound tool, so the
        # "do NOT call them by name" block was followed by a second bound-tool-like list.
        assert "\nGMAIL_SEND_EMAIL" not in text
        assert text.rstrip().splitlines()[-1] != "GMAIL_SEND_EMAIL"

    async def test_out_of_scope_guidance_still_reaches_the_model(self) -> None:
        """The filter the line above removed was also what carried the subagent and out-of-scope sentences into the rendered text."""
        fn = get_retrieve_tools_function(bindable_tool_names={"read"})
        registry = _registry()
        registry.get_tool_names.return_value = ["read", "GMAIL_SEND_EMAIL", "GMAIL_FETCH_EMAILS"]
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}._user_mcp_tool_names", new=AsyncMock(return_value=set())),
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=None)),
        ):
            result = await fn(
                store=MagicMock(),
                config=CONFIG,
                exact_tool_names=["GMAIL_SEND_EMAIL", "GMAIL_FETCH_EMAILS"],
            )
        assert (
            "bound here: GMAIL_SEND_EMAIL, GMAIL_FETCH_EMAILS. They belong to the main executor"
            in result["response_text"]
        )

    async def test_internal_tool_still_binds(self) -> None:
        result = await _call(["read"], None)
        assert result["tools_to_bind"] == ["read"]
        assert "Bound 1 tools" in result["response_text"]

    async def test_mixed_request_partitions_correctly(self) -> None:
        tool = _gmail_tool()
        result = await _call(
            ["read", "GMAIL_SEND_EMAIL"], ResolvedTool("GMAIL_SEND_EMAIL", tool, True)
        )
        assert result["tools_to_bind"] == ["read"]
        assert "## GMAIL_SEND_EMAIL" in result["response_text"]

    async def test_unmaterialized_catalog_slug_is_rescued_as_proxied(self) -> None:
        catalog_tool = StructuredTool.from_function(
            func=lambda **kwargs: None,
            name="ASANA_CREATE_TASK",
            description="Create a task.",
            args_schema=_GmailSendArgs,
        )
        result = await _call(
            ["ASANA_CREATE_TASK"], ResolvedTool("ASANA_CREATE_TASK", catalog_tool, True)
        )
        assert result["tools_to_bind"] == []
        assert "## ASANA_CREATE_TASK" in result["response_text"]

    async def test_unknown_internal_shaped_name_stays_unknown(self) -> None:
        result = await _call(["definitely_not_real"], None)
        assert result["tools_to_bind"] == []
        assert "Not found" in result["response_text"]


@pytest.mark.unit
class TestResolverOutageDegradation:
    async def test_resolver_infra_failure_degrades_to_unknown_not_crash(self) -> None:
        """Observed live: with Composio unreachable, the rescue path let the resolver's exception escape into select_tools, which retry-looped the graph to its recursion limit."""
        fn = get_retrieve_tools_function()
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry())),
            patch(f"{MODULE}._user_mcp_tool_names", new=AsyncMock(return_value=set())),
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(side_effect=RuntimeError("composio unreachable")),
            ),
        ):
            result = await fn(
                store=MagicMock(), config=CONFIG, exact_tool_names=["ASANA_CREATE_TASK"]
            )
        assert result["tools_to_bind"] == []
        assert "Not found" in result["response_text"]


def _asana_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kwargs: None,
        name="ASANA_CREATE_TASK",
        description="Create a task.",
        args_schema=_GmailSendArgs,
    )


async def _bind(exact: list[str], resolver: AsyncMock, config: dict[str, Any] | None = None) -> Any:
    fn = get_retrieve_tools_function()
    with (
        patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry())),
        patch(f"{MODULE}._user_mcp_tool_names", new=AsyncMock(return_value=set())),
        patch(f"{MODULE}.resolve_tool", new=resolver),
    ):
        return await fn(store=MagicMock(), config=config or CONFIG, exact_tool_names=exact)


@pytest.mark.unit
class TestDocsCarryReturnShapes:
    async def test_a_large_return_shape_is_collapsed_to_the_inline_budget(self) -> None:
        fields = {
            f"field_{i}": {"type": "object", "properties": {"leaf": {"type": "string"}}}
            for i in range(50)
        }
        output = {
            "type": "object",
            "properties": {"data": {"type": "object", "properties": fields}},
        }
        tool = StructuredTool.from_function(
            func=lambda **kwargs: None,
            name="GMAIL_SEND_EMAIL",
            description="Send an email.",
            args_schema=_GmailSendArgs,
            metadata={"output_parameters": output},
        )
        resolver = AsyncMock(return_value=ResolvedTool("GMAIL_SEND_EMAIL", tool, True))
        text = (await _bind(["GMAIL_SEND_EMAIL"], resolver))["response_text"]
        returns = text.split("Returns: ")[1].split("\n")
        assert "field_0?:obj" in returns[0]
        assert len(returns[0]) <= RETURNS_INLINE_MAX_CHARS
        assert returns[1] == "(deeper fields omitted for size; the real data has them)"


@pytest.mark.unit
class TestProxiedResolutionIsPerUser:
    async def test_a_proxied_tools_doc_is_resolved_for_the_calling_user(self) -> None:
        resolver = AsyncMock(return_value=ResolvedTool("GMAIL_SEND_EMAIL", _gmail_tool(), True))
        await _bind(["GMAIL_SEND_EMAIL"], resolver)
        resolver.assert_awaited_once_with("u1", "GMAIL_SEND_EMAIL")

    async def test_a_catalog_slug_is_rescued_and_rendered_for_the_calling_user(self) -> None:
        resolver = AsyncMock(return_value=ResolvedTool("ASANA_CREATE_TASK", _asana_tool(), True))
        result = await _bind(["ASANA_CREATE_TASK"], resolver)
        assert "## ASANA_CREATE_TASK" in result["response_text"]
        assert resolver.await_args_list == [call("u1", "ASANA_CREATE_TASK")] * 2

    async def test_a_resolver_outage_is_a_warning_naming_the_tool_and_error(self) -> None:
        resolver = AsyncMock(side_effect=RuntimeError("composio unreachable"))
        async with captured_wide_event() as event:
            await _bind(["ASANA_CREATE_TASK"], resolver)
        (warning,) = [w for w in event["warnings"] if "resolver unavailable" in w["msg"]]
        assert warning["msg"].endswith("retrieve_tools: resolver unavailable; treating as unknown")
        assert warning["tool_name"] == "ASANA_CREATE_TASK"
        assert warning["error_type"] == "RuntimeError"

    async def test_binding_text_carries_the_shared_execute_instruction(self) -> None:
        resolver = AsyncMock(return_value=ResolvedTool("GMAIL_SEND_EMAIL", _gmail_tool(), True))
        result = await _bind(["GMAIL_SEND_EMAIL"], resolver)
        assert result["response_text"].splitlines()[0] == (
            f"1 integration tool(s) ready to run via execute. {retrieval._EXECUTE_DOCS_INSTRUCTION}"
        )

    async def test_the_wide_event_counts_proxied_tools_apart_from_filtered_ones(self) -> None:
        resolver = AsyncMock(return_value=ResolvedTool("GMAIL_SEND_EMAIL", _gmail_tool(), True))
        async with captured_wide_event() as event:
            await _bind(["read", "GMAIL_SEND_EMAIL", "nope"], resolver)
        assert event["tool_retrieval"] == {
            "mode": "binding",
            "tools_requested": 3,
            "tools_bound": 1,
            "tools_proxied": 1,
            "tools_filtered": 1,
        }


@pytest.mark.unit
class TestBindingConfigSources:
    async def test_a_desktop_session_binds_desktop_tools(self) -> None:
        registry = _registry()
        registry.get_tool_names.return_value = ["desktop_click"]
        registry.get_category_of_tool.side_effect = lambda n: DESKTOP_TOOL_CATEGORY
        registry.get_category.side_effect = lambda name=None: MagicMock(require_integration=False)
        config = {
            "configurable": {
                "user_id": "u1",
                "conversation_source": ConversationSource.DESKTOP.value,
            }
        }
        fn = get_retrieve_tools_function()
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}._user_mcp_tool_names", new=AsyncMock(return_value=set())),
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=None)),
        ):
            result = await fn(store=MagicMock(), config=config, exact_tool_names=["desktop_click"])
        assert result["tools_to_bind"] == ["desktop_click"]

    async def test_a_config_with_no_user_and_no_metadata_still_binds(self) -> None:
        result = await _bind(["read"], AsyncMock(return_value=None), config={"configurable": {}})
        assert result["tools_to_bind"] == ["read"]


@pytest.mark.unit
class TestRenderPreloadBlockContract:
    async def test_the_block_is_the_header_then_each_doc(self) -> None:
        gmail, asana = _gmail_tool(), _asana_tool()
        resolver = AsyncMock(
            side_effect=[
                ResolvedTool("GMAIL_SEND_EMAIL", gmail, True),
                ResolvedTool("ASANA_CREATE_TASK", asana, True),
            ]
        )
        with patch(f"{MODULE}.resolve_tool", new=resolver):
            block = await retrieval.render_preload_block(
                "u1", ["GMAIL_SEND_EMAIL", "ASANA_CREATE_TASK"]
            )
        assert block.split("\n\n") == [
            f"2 integration tool(s) preloaded below. {retrieval._EXECUTE_DOCS_INSTRUCTION}",
            await _doc("GMAIL_SEND_EMAIL", gmail),
            await _doc("ASANA_CREATE_TASK", asana),
        ]
        assert resolver.await_args_list == [
            call("u1", "GMAIL_SEND_EMAIL"),
            call("u1", "ASANA_CREATE_TASK"),
        ]

    async def test_a_tool_that_vanished_is_skipped_with_a_warning_and_the_rest_render(
        self,
    ) -> None:
        gmail = _gmail_tool()
        resolver = AsyncMock(side_effect=[None, ResolvedTool("GMAIL_SEND_EMAIL", gmail, True)])
        with patch(f"{MODULE}.resolve_tool", new=resolver):
            async with captured_wide_event() as event:
                block = await retrieval.render_preload_block(
                    "u1", ["GMAIL_GHOST", "GMAIL_SEND_EMAIL"]
                )
        assert block.split("\n\n")[1:] == [await _doc("GMAIL_SEND_EMAIL", gmail)]
        (warning,) = event["warnings"]
        assert warning["msg"].endswith(
            "retrieve_tools: proxied tool vanished between validation and doc rendering"
        )
        assert warning["tool_name"] == "GMAIL_GHOST"
