"""retrieve_tools binding mode after the execute cutover.

Integration tools (Composio require_integration categories, MCP tools, catalog
slugs) come back as schema docs and are NOT bound; internal tools still bind.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
import pytest

from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.execute.resolver import ResolvedTool

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
        # bind_lines echoed every `response` entry that was not a bound tool,
        # so the block ending in "do NOT call them by name" was followed by a
        # second, unlabelled list that reads exactly like a bound-tool list.
        assert "\nGMAIL_SEND_EMAIL" not in text
        assert text.rstrip().splitlines()[-1] != "GMAIL_SEND_EMAIL"

    async def test_out_of_scope_guidance_still_reaches_the_model(self) -> None:
        """The filter the line above removed was also what carried the subagent
        and out-of-scope sentences into the rendered text."""
        fn = get_retrieve_tools_function(bindable_tool_names={"read"})
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry())),
            patch(f"{MODULE}._user_mcp_tool_names", new=AsyncMock(return_value=set())),
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=None)),
        ):
            result = await fn(
                store=MagicMock(), config=CONFIG, exact_tool_names=["GMAIL_SEND_EMAIL"]
            )
        assert "belong to the main executor" in result["response_text"]

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
        """Observed live: with Composio unreachable, the rescue path let the
        resolver's exception escape into select_tools, which retry-looped the
        graph to its recursion limit. An unreachable catalog must degrade the
        name to unknown, never wedge the whole retrieval turn."""
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
