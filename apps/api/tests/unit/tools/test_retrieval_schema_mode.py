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


async def _call(exact: list[str], resolver_result: tuple[str, Any] | None) -> Any:
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
        result = await _call(["GMAIL_SEND_EMAIL"], ("GMAIL_SEND_EMAIL", tool))
        assert result["tools_to_bind"] == []
        assert "GMAIL_SEND_EMAIL" in result["response"]
        text = result["response_text"]
        assert "## GMAIL_SEND_EMAIL" in text
        assert "recipient_email" in text
        assert "execute(" in text
        assert "NOT bound" in text

    async def test_internal_tool_still_binds(self) -> None:
        result = await _call(["read"], None)
        assert result["tools_to_bind"] == ["read"]
        assert "Bound 1 tools" in result["response_text"]

    async def test_mixed_request_partitions_correctly(self) -> None:
        tool = _gmail_tool()
        result = await _call(["read", "GMAIL_SEND_EMAIL"], ("GMAIL_SEND_EMAIL", tool))
        assert result["tools_to_bind"] == ["read"]
        assert "## GMAIL_SEND_EMAIL" in result["response_text"]

    async def test_unmaterialized_catalog_slug_is_rescued_as_proxied(self) -> None:
        catalog_tool = StructuredTool.from_function(
            func=lambda **kwargs: None,
            name="ASANA_CREATE_TASK",
            description="Create a task.",
            args_schema=_GmailSendArgs,
        )
        result = await _call(["ASANA_CREATE_TASK"], ("ASANA_CREATE_TASK", catalog_tool))
        assert result["tools_to_bind"] == []
        assert "## ASANA_CREATE_TASK" in result["response_text"]

    async def test_unknown_internal_shaped_name_stays_unknown(self) -> None:
        result = await _call(["definitely_not_real"], None)
        assert result["tools_to_bind"] == []
        assert "Not found" in result["response_text"]
