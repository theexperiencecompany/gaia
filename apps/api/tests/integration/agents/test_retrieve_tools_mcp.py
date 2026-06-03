"""retrieve_tools must surface per-user MCP tools end-to-end.

After the resilience rewrite removed per-user `mcp_{iid}_{user_id}` categories
from ToolRegistry, MCP tool names no longer appear in
`tool_registry.get_tool_names()`. retrieve_tools had two filters keyed against
that set — one in discovery mode (Chroma post-processing) and one in binding
mode (exact_tool_names validation). Both used to drop every MCP tool as
"unknown."

These tests exercise the live `retrieve_tools` factory with mocked Chroma /
MCPClient boundaries and verify:

1. Discovery mode returns posthog tool names from a Chroma hit.
2. Binding mode validates posthog tool names directly via MCPClient.
3. User A's tools never leak into user B's retrieve_tools results.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.tools.core.retrieval import get_retrieve_tools_function


def _fake_tool(name: str, description: str = "test tool"):
    t = MagicMock()
    t.name = name
    t.description = description
    return t


def _fake_search_item(key: str, namespace: tuple, score: float = 0.95):
    item = MagicMock()
    item.key = key
    item.namespace = namespace
    item.score = score
    item.value = {}
    return item


def _fake_mcp_client(integration_tools_map: dict[str, list[Any]]):
    """Build a MagicMock MCPClient whose `_tools` dict contains the given tools.

    integration_tools_map: {integration_id: [tool, tool, ...]}
    """
    client = MagicMock()
    client._tools = integration_tools_map
    return client


def _config(user_id: str) -> RunnableConfig:
    return RunnableConfig(
        configurable={"user_id": user_id, "thread_id": "t1"},
        metadata={"user_id": user_id},
    )


@pytest.mark.integration
class TestRetrieveToolsBindingMode:
    async def test_binding_resolves_mcp_names_from_mcp_client(self):
        """exact_tool_names that come from a user's posthog MCP should validate
        even though they're not in tool_registry.get_tool_names()."""
        user_id = "user-a"
        mcp_tools = [_fake_tool("persons-list"), _fake_tool("query-trends")]

        retrieve_tools = get_retrieve_tools_function(tool_space="posthog")

        with (
            patch(
                "app.agents.tools.core.retrieval.get_mcp_client",
                new=AsyncMock(return_value=_fake_mcp_client({"posthog": mcp_tools})),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_registry,
        ):
            registry = MagicMock()
            registry.get_tool_names = MagicMock(return_value=["search_memory"])
            get_registry.return_value = registry

            result = await retrieve_tools(
                store=MagicMock(),
                config=_config(user_id),
                exact_tool_names=["persons-list", "unknown-tool"],
            )

        assert "persons-list" in result["tools_to_bind"]
        assert "unknown-tool" not in result["tools_to_bind"]


@pytest.mark.integration
class TestRetrieveToolsDiscoveryMode:
    async def test_discovery_keeps_mcp_tool_hits(self):
        """Chroma hits with posthog tool names must survive the available-names
        filter once we union the user's MCPClient tool names in."""
        user_id = "user-a"
        mcp_tools = [_fake_tool("persons-list"), _fake_tool("query-trends")]

        retrieve_tools = get_retrieve_tools_function(tool_space="posthog")

        chroma_hits = [
            _fake_search_item("persons-list", ("posthog",)),
            _fake_search_item("query-trends", ("posthog",)),
        ]
        store = MagicMock()
        store.asearch = AsyncMock(return_value=chroma_hits)

        with (
            patch(
                "app.agents.tools.core.retrieval.get_mcp_client",
                new=AsyncMock(return_value=_fake_mcp_client({"posthog": mcp_tools})),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_registry,
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new=AsyncMock(return_value=["posthog"]),
            ),
            patch(
                "app.agents.tools.core.retrieval.search_public_integrations",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=[],
            ),
        ):
            registry = MagicMock()
            registry.get_tool_names = MagicMock(return_value=["search_memory"])
            registry.get_category_of_tool = MagicMock(return_value="")
            registry.get_category = MagicMock(return_value=None)
            get_registry.return_value = registry

            result = await retrieve_tools(
                store=store,
                config=_config(user_id),
                query="list posthog persons",
            )

        # Discovery should surface both MCP tool names in `response`.
        assert "persons-list" in result["response"]
        assert "query-trends" in result["response"]


@pytest.mark.integration
class TestRetrieveToolsCrossUserIsolation:
    async def test_user_b_only_sees_their_own_mcp_tools(self):
        """User A has posthog tools, user B has notion tools. retrieve_tools
        for each user must see only that user's MCP tool names — the
        MCPClient pool is keyed per user, and the binding filter must respect
        that scoping.
        """
        user_a = "user-a"
        user_b = "user-b"
        user_a_client = _fake_mcp_client({"posthog": [_fake_tool("persons-list")]})
        user_b_client = _fake_mcp_client({"notion": [_fake_tool("notion-search")]})

        def per_user_get(user_id: str):
            if user_id == user_a:
                return user_a_client
            if user_id == user_b:
                return user_b_client
            raise RuntimeError(f"unexpected user_id {user_id}")

        retrieve_tools = get_retrieve_tools_function(tool_space="posthog")

        with (
            patch(
                "app.agents.tools.core.retrieval.get_mcp_client",
                new=AsyncMock(side_effect=per_user_get),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_registry,
        ):
            registry = MagicMock()
            registry.get_tool_names = MagicMock(return_value=[])
            get_registry.return_value = registry

            # User A asks for persons-list — should resolve.
            res_a = await retrieve_tools(
                store=MagicMock(),
                config=_config(user_a),
                exact_tool_names=["persons-list"],
            )
            # User B asks for persons-list (which they don't have) and
            # notion-search (which they do).
            res_b = await retrieve_tools(
                store=MagicMock(),
                config=_config(user_b),
                exact_tool_names=["persons-list", "notion-search"],
            )

        assert "persons-list" in res_a["tools_to_bind"], "user A's posthog tool should resolve"
        assert "persons-list" not in res_b["tools_to_bind"], (
            "user B must NOT see user A's posthog tool"
        )
        assert "notion-search" in res_b["tools_to_bind"], "user B's notion tool should resolve"
