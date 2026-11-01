"""retrieve_tools must surface per-user MCP tools end-to-end.

After the resilience rewrite removed per-user mcp_{iid}_{user_id} categories from ToolRegistry,
MCP tool names stopped appearing in tool_registry.get_tool_names(). retrieve_tools had two filters
keyed against that set -- one in discovery mode (Chroma post-processing), one in binding mode
(exact_tool_names validation) -- and both dropped every MCP tool as "unknown".

Exercises the live retrieve_tools factory with the Chroma and MCPClient boundaries mocked:
discovery mode returns the tool names from a Chroma hit, binding mode validates them directly via
MCPClient, and user A's tools never leak into user B's results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from langgraph.store.base import PutOp, SearchItem
import pytest

from app.agents.core.subagents.integration_resolution import CustomMcpSubagent
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.integration_models import UserToolNamespaces
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.custom_mcp_index import CustomMcpIndexRequest, index_custom_mcp_as_subagent


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
    """Build a MagicMock MCPClient whose _tools dict contains the given tools.

    Models the two lookups the execute resolver performs (resolve_tool_owner +
    tools_for) so proxied schema-doc rendering exercises the same per-user
    scoping the name filters do.
    """
    client = MagicMock()
    client._tools = integration_tools_map
    client.resolve_tool_owner = AsyncMock(
        side_effect=lambda name: next(
            (
                iid
                for iid, tools in integration_tools_map.items()
                if any(t.name == name for t in tools)
            ),
            None,
        )
    )
    client.tools_for = AsyncMock(side_effect=lambda iid: integration_tools_map.get(iid, []))
    return client


def _config(user_id: str) -> RunnableConfig:
    return RunnableConfig(
        configurable={"user_id": user_id, "thread_id": "t1"},
        metadata={"user_id": user_id},
    )


@pytest.mark.integration
class TestRetrieveToolsBindingMode:
    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_binding_resolves_mcp_names_from_mcp_client(self):
        """exact_tool_names from a user's posthog MCP validate even though absent from tool_registry."""
        user_id = "user-a"
        mcp_tools = [_fake_tool("persons-list"), _fake_tool("query-trends")]

        retrieve_tools = get_retrieve_tools_function(tool_space="posthog")

        with (
            patch(
                "app.agents.tools.core.retrieval.get_mcp_client",
                new=AsyncMock(return_value=_fake_mcp_client({"posthog": mcp_tools})),
            ),
            patch(
                "app.agents.tools.execute.resolver.get_mcp_client",
                new=AsyncMock(return_value=_fake_mcp_client({"posthog": mcp_tools})),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_registry,
            patch(
                "app.agents.tools.execute.resolver.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_resolver_registry,
        ):
            registry = MagicMock()
            registry.get_tool_names = MagicMock(return_value=["search_memory"])
            registry.get_tool_meta = MagicMock(return_value=None)
            get_registry.return_value = registry
            get_resolver_registry.return_value = registry

            result = await retrieve_tools(
                store=MagicMock(),
                config=_config(user_id),
                exact_tool_names=["persons-list", "unknown-tool"],
            )

        # Cutover: MCP tools are proxied through execute — resolved and
        # documented, never bound as callable tools.
        assert result["tools_to_bind"] == []
        assert "persons-list" in result["response"]
        assert "## persons-list" in result["response_text"]
        assert "unknown-tool" not in result["response"]


@pytest.mark.integration
class TestRetrieveToolsDiscoveryMode:
    async def test_discovery_keeps_mcp_tool_hits(self):
        """Chroma hits with posthog tool names must survive the available-names filter."""
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
                new=AsyncMock(return_value=UserToolNamespaces(namespaces={"posthog"})),
            ),
            patch(
                "app.agents.tools.core.retrieval.search_public_integrations",
                new=AsyncMock(return_value=[]),
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
                # Discovery mode: langchain resolves the Field default to [] at
                # invocation; pass it explicitly when calling the tool directly.
                exact_tool_names=[],
            )

        # Discovery should surface both MCP tool names in `response`.
        assert "persons-list" in result["response"]
        assert "query-trends" in result["response"]


@pytest.mark.integration
class TestRetrieveToolsCrossUserIsolation:
    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_user_b_only_sees_their_own_mcp_tools(self):
        """retrieve_tools for each user must see only that user's MCP tool names."""
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
                "app.agents.tools.execute.resolver.get_mcp_client",
                new=AsyncMock(side_effect=per_user_get),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_registry,
            patch(
                "app.agents.tools.execute.resolver.get_tool_registry",
                new_callable=AsyncMock,
            ) as get_resolver_registry,
        ):
            registry = MagicMock()
            registry.get_tool_names = MagicMock(return_value=[])
            registry.get_tool_meta = MagicMock(return_value=None)
            get_registry.return_value = registry
            get_resolver_registry.return_value = registry

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

        assert "persons-list" in res_a["response"], "user A's posthog tool should resolve"
        assert "## persons-list" in res_a["response_text"]
        assert "persons-list" not in res_b["response"], "user B must NOT see user A's posthog tool"
        assert "## persons-list" not in res_b["response_text"], (
            "user B must NOT receive user A's tool schema doc"
        )
        assert "notion-search" in res_b["response"], "user B's notion tool should resolve"
        assert res_a["tools_to_bind"] == [] and res_b["tools_to_bind"] == [], (
            "MCP tools are proxied through execute, never bound"
        )


_ACME = CustomMcpSubagent(
    id="abc123def456",
    name="Acme MCP",
    managed_by="mcp",
    mcp_config={"server_url": "https://mcp.acme.dev/v1", "requires_auth": True},
)
_ACME_NAMESPACE = "mcp.acme.dev/v1"


async def _discover_with_activated_acme(user_namespaces: set[str]) -> tuple[dict, list, MagicMock]:
    """Discovery in a conversation that activated Acme, against a cold MCPClient."""
    searched: list[tuple[str, ...]] = []

    async def fake_asearch(namespace: tuple[str, ...], query: str = "", limit: int = 25) -> list:
        searched.append(namespace)
        if namespace == (_ACME_NAMESPACE,):
            return [_fake_search_item("ACME_LIST_INVOICES", namespace)]
        return []

    store = MagicMock()
    store.asearch = fake_asearch
    client = _fake_mcp_client({})
    client.tools_for = AsyncMock(return_value=[_fake_tool("ACME_LIST_INVOICES")])
    registry = MagicMock()
    registry.get_tool_names = MagicMock(return_value=[])
    registry.get_category_of_tool = MagicMock(return_value="")
    registry.get_category = MagicMock(return_value=None)
    registry.get_tool_meta = MagicMock(return_value=None)

    with (
        patch("app.agents.tools.core.retrieval.get_mcp_client", new=AsyncMock(return_value=client)),
        patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new=AsyncMock(return_value=registry),
        ),
        patch(
            "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
            new=AsyncMock(return_value=UserToolNamespaces(namespaces=user_namespaces)),
        ),
        patch(
            "app.agents.tools.core.retrieval._resolve_connected_subagents",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.agents.tools.core.retrieval.get_active",
            new=AsyncMock(return_value={_ACME.id}),
        ),
        patch(
            "app.agents.tools.core.retrieval.get_integration_target",
            new=AsyncMock(return_value=_ACME),
        ),
        patch.object(
            IntegrationResolver,
            "get_server_url",
            new=AsyncMock(return_value="https://mcp.acme.dev/v1"),
        ),
        patch(
            "app.agents.tools.core.retrieval.search_public_integrations",
            new=AsyncMock(return_value=[]),
        ),
    ):
        retrieve_tools = get_retrieve_tools_function(tool_space="general")
        result = await retrieve_tools(
            store=store,
            config=RunnableConfig(
                configurable={"user_id": "user-a", "conversation_id": "c1", "thread_id": "c1"},
                metadata={"user_id": "user-a"},
            ),
            query="list acme invoices",
            exact_tool_names=[],
        )
    return result, searched, client


@pytest.mark.integration
class TestRetrieveToolsActivatedCustomMcp:
    async def test_an_activated_custom_mcp_is_searched_and_warmed_when_entitled(self):
        """The long tail of an activated custom MCP is discoverable even on a cold MCPClient."""
        result, searched, client = await _discover_with_activated_acme(
            {"general", "subagents", _ACME_NAMESPACE}
        )

        assert (_ACME_NAMESPACE,) in searched
        client.tools_for.assert_awaited_once_with(_ACME.id)
        assert "ACME_LIST_INVOICES" in result["response"]

    async def test_a_stamped_custom_namespace_the_user_does_not_own_is_not_searched(self):
        """A stamp is not an entitlement: without the namespace in user_namespaces it is never searched."""
        result, searched, _ = await _discover_with_activated_acme({"general", "subagents"})

        assert (_ACME_NAMESPACE,) not in searched
        assert "ACME_LIST_INVOICES" not in result["response"]


_CUSTOM_MCPS_BY_USER = {
    "user-a": CustomMcpIndexRequest(
        integration_id="aaa111aaa111",
        name="Alpha Invoices",
        description="Lists invoices",
        server_url="https://mcp.alpha.dev/v1",
    ),
    "user-b": CustomMcpIndexRequest(
        integration_id="bbb222bbb222",
        name="Beta Invoices",
        description="Lists invoices",
        server_url="https://mcp.beta.dev/v1",
    ),
}


async def _indexed_pointer_docs() -> list[SearchItem]:
    """Both users' pointer docs, as the real indexer writes them into the shared namespace."""
    store = MagicMock()
    store.abatch = AsyncMock()
    for request in _CUSTOM_MCPS_BY_USER.values():
        await index_custom_mcp_as_subagent(store, request)
    now = datetime.now(UTC)
    ops: list[PutOp] = [op for call in store.abatch.await_args_list for op in call.args[0]]
    return [
        SearchItem(
            namespace=op.namespace,
            key=op.key,
            value=op.value or {},
            created_at=now,
            updated_at=now,
            score=0.9,
        )
        for op in ops
    ]


async def _namespaces_for(user_id: str) -> UserToolNamespaces:
    own = _CUSTOM_MCPS_BY_USER[user_id]
    return UserToolNamespaces(
        namespaces={
            "general",
            "subagents",
            derive_integration_namespace(own.integration_id, own.server_url, is_custom=True),
        }
    )


@pytest.mark.integration
class TestRetrieveToolsCustomMcpPointerIsolation:
    async def test_each_user_sees_only_their_own_custom_mcp_pointer(self):
        """The subagents namespace is shared; the pointer list each user gets is not."""
        pointers = await _indexed_pointer_docs()

        async def fake_asearch(namespace: tuple[str, ...], query: str = "", limit: int = 25):
            return pointers if namespace == ("subagents",) else []

        store = MagicMock()
        store.asearch = fake_asearch
        registry = MagicMock()
        registry.get_tool_names = MagicMock(return_value=[])
        registry.get_tool_meta = MagicMock(return_value=None)

        with (
            patch(
                "app.agents.tools.core.retrieval.get_mcp_client",
                new=AsyncMock(return_value=_fake_mcp_client({})),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new=AsyncMock(return_value=registry),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new=AsyncMock(side_effect=_namespaces_for),
            ),
            patch(
                "app.agents.tools.core.retrieval._resolve_connected_subagents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_active",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "app.agents.tools.core.retrieval._unconnected_named_in",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.agents.tools.core.retrieval.search_public_integrations",
                new=AsyncMock(return_value=[]),
            ),
        ):
            retrieve_tools = get_retrieve_tools_function(tool_space="general")
            responses = {
                user_id: (
                    await retrieve_tools(
                        store=store,
                        config=_config(user_id),
                        query="list invoices",
                        exact_tool_names=[],
                    )
                )["response"]
                for user_id in _CUSTOM_MCPS_BY_USER
            }

        assert responses["user-a"] == ["mcp_integration:aaa111aaa111 (Alpha Invoices)"]
        assert responses["user-b"] == ["mcp_integration:bbb222bbb222 (Beta Invoices)"]
