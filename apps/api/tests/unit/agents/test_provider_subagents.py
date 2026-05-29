"""Mutation-verified unit tests for provider_subagents.

UNIT: app/agents/core/subagents/provider_subagents.py

This module materializes LangGraph subagent graphs on-demand. There are four
public/private behaviours under test plus the registration loop.

--------------------------------------------------------------------------- spec
UNIT :: create_subagent(subagent) -> CompiledStateGraph
EXPECTED: dispatch on `subagent.managed_by`, register the right tools for that
          provider type, then build and return the compiled graph.
MECHANISM: branch on managed_by:
  - "internal": no tool setup, just build the graph.
  - "mcp" + mcp_config: auth-required -> raise ValueError; otherwise, if the
    category is not already registered, connect the system MCP client and add
    the returned tools to the registry.
  - "composio": look up the OAuthIntegration; if it (or its composio_config) is
    missing -> raise ValueError; otherwise register provider tools for the
    toolkit with the configured space + specific_tools.
  Then init_llm(), create_provider_subagent(...) with the config's flags, return.
MUST-CATCH:
  - "internal" must NOT touch the MCP client or register provider tools.
  - auth-required MCP raises (no graph built).
  - composio with no integration / no composio_config raises (fail loud).
  - composio registers tools with the integration's toolkit + config.tool_space.
  - an already-registered MCP category does NOT re-connect.
  - an MCP connect that returns no tools does NOT add a category.
  - the graph returned is the factory's graph, not None.
  - the factory is called with this subagent's provider + config flags.

UNIT :: create_subagent_for_user / _build_user_subagent(integration_id, user_id)
EXPECTED: build a per-user MCP subagent graph; return None on every failure path.
MECHANISM: unknown id -> delegate to _create_custom_mcp_subagent. Non-MCP
  subagent -> None. Warm tools from mcp_client._tools, else cold connect
  (connect failure -> None). Empty tools -> None. Else build graph with
  mcp_tools=tools and return it.
MUST-CATCH:
  - unknown integration delegates to the custom-MCP builder with the same args.
  - a composio (non-MCP) subagent returns None.
  - managed_by='mcp' but no mcp_config returns None.
  - warm tools path does NOT call connect; cold path does.
  - connect raising -> None (swallowed, not propagated).
  - zero tools -> None.
  - tools are forwarded to the factory as mcp_tools.

UNIT :: _create_custom_mcp_subagent(integration_id, user_id)
EXPECTED: build a custom-MCP subagent graph from a MongoDB doc; None on failures.
MECHANISM: missing doc -> None. Derive namespace from the doc's server_url.
  Warm tools else cold connect (failure -> None). Empty tools -> None.
  use_direct = 0 < len(tools) <= 10 drives use_direct_tools/disable_retrieve_tools.
MUST-CATCH:
  - missing Mongo doc -> None.
  - connect raising -> None.
  - zero tools -> None.
  - small toolset (<=10, >0) => use_direct_tools/disable_retrieve_tools True.
  - large toolset (>10) => both False.
  - the derived namespace is passed as tool_space; provider/name use the id.

UNIT :: register_subagent_providers(integration_ids?) -> int
EXPECTED: register a lazy provider per eligible subagent; return the count.
MECHANISM: skip ids not in the filter list (when provided); skip auth-required
  MCP subagents; register the rest under their agent_name.
MUST-CATCH:
  - eligible composio subagent registers under its agent_name and counts 1.
  - auth-required MCP is skipped (count 0, never registered).
  - non-auth MCP is registered (count 1).
  - the id filter excludes non-listed subagents.

EQUIVALENT MUTANTS (proven behaviour-preserving survivors):
  1. create_subagent, `if subagent.managed_by == "internal"` with the constant
     mutated "internal" -> "". The internal branch body is a single log.info
     and nothing else; whether an internal subagent enters that branch or skips
     every branch, control reaches the same init_llm()/create_provider_subagent()
     path and returns the same graph. No observable difference.
  2. create_subagent, the composio-error message constant 'Composio subagent '
     (the cosmetic prefix before {subagent.id!r}) mutated -> ''. The raised type
     (ValueError) and the behavioural contract substring "no matching OAuth
     integration with composio_config..." are unchanged; the dropped prefix is
     a human-readable label, not a contract. Asserting on it would be a brittle
     boilerplate substring oracle. The contract-bearing segment IS killed.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.mcp_config import ComposioConfig, MCPConfig, SubAgentConfig
from app.models.oauth_models import OAuthIntegration
from app.models.subagent_models import Subagent

_MODULE = "app.agents.core.subagents.provider_subagents"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_create_task(coro, **kwargs):
    """Swallow asyncio.create_task so the fire-and-forget warm-up does not leak."""
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


def _make_subagent_config(**overrides) -> SubAgentConfig:
    defaults = {
        "has_subagent": True,
        "agent_name": "test_agent",
        "tool_space": "test_space",
        "handoff_tool_name": "handoff_test",
        "domain": "test",
        "capabilities": "test capabilities",
        "use_cases": "test use cases",
        "system_prompt": "You are a test agent.",
        "use_direct_tools": False,
        "disable_retrieve_tools": False,
    }
    defaults.update(overrides)
    return SubAgentConfig(**defaults)  # type: ignore[arg-type]


def _make_integration(
    integration_id: str = "test_int",
    managed_by: str = "composio",
    composio_config: ComposioConfig | None = None,
    provider: str = "test_provider",
) -> OAuthIntegration:
    if composio_config is None and managed_by == "composio":
        composio_config = ComposioConfig(
            auth_config_id="test_auth",
            toolkit="test_toolkit",
        )
    return OAuthIntegration(
        id=integration_id,
        name="Test Integration",
        description="Test",
        category="test",
        provider=provider,
        scopes=[],
        managed_by=managed_by,  # type: ignore[arg-type]
        composio_config=composio_config,
        subagent_config=_make_subagent_config(),
    )


def _make_subagent(
    integration_id: str = "test_int",
    managed_by: str = "composio",
    mcp_config: MCPConfig | None = None,
    provider: str = "test_provider",
    subagent_config: SubAgentConfig | None = None,
) -> Subagent:
    if subagent_config is None:
        subagent_config = _make_subagent_config()
    return Subagent(
        id=integration_id,
        name="Test Integration",
        provider=provider,
        managed_by=managed_by,  # type: ignore[arg-type]
        config=subagent_config,
        mcp_config=mcp_config,
    )


def _registry(categories: dict | None = None) -> AsyncMock:
    reg = AsyncMock()
    reg._categories = {} if categories is None else categories
    reg._add_category = MagicMock()
    reg._index_category_tools = AsyncMock()
    reg.register_provider_tools = AsyncMock()
    return reg


def _patch_factory(graph):
    return patch(
        f"{_MODULE}.SubAgentFactory.create_provider_subagent",
        new_callable=AsyncMock,
        return_value=graph,
    )


def _patch_llm():
    return patch(f"{_MODULE}.init_llm", return_value=MagicMock())


# ---------------------------------------------------------------------------
# create_subagent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSubagent:
    async def test_internal_builds_graph_without_tool_setup(self):
        """Internal subagents reuse pre-registered core tools: no MCP connect,
        no provider-tool registration. The factory's graph is returned."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(managed_by="internal", provider="internal_prov")
        graph = MagicMock()
        registry = _registry()

        with (
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
            patch(f"{_MODULE}.get_integration_by_id") as mock_lookup,
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            result = await create_subagent(subagent)

        assert result is graph
        mock_mcp.assert_not_called()
        mock_lookup.assert_not_called()
        registry.register_provider_tools.assert_not_called()
        registry._add_category.assert_not_called()
        # Factory receives THIS subagent's provider + the config flags.
        assert factory.call_args.kwargs["provider"] == "internal_prov"
        assert factory.call_args.kwargs["tool_space"] == "test_space"

    async def test_mcp_no_auth_connects_and_registers_tools(self):
        """A non-auth MCP whose category is unregistered connects the _system
        client and adds the returned tools to the registry under its id."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=False),
        )
        graph = MagicMock()
        tools = [MagicMock(), MagicMock()]
        registry = _registry()

        mcp_client = AsyncMock()
        mcp_client.connect = AsyncMock(return_value=tools)

        with (
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            patch(
                f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client
            ) as get_client,
            _patch_llm(),
            _patch_factory(graph),
        ):
            result = await create_subagent(subagent)

        assert result is graph
        # _system user is used for the shared (non-auth) connect.
        get_client.assert_awaited_once_with(user_id="_system")
        mcp_client.connect.assert_awaited_once_with("test_int")
        add_kwargs = registry._add_category.call_args.kwargs
        assert add_kwargs["name"] == "test_int"
        assert add_kwargs["tools"] is tools
        assert add_kwargs["space"] == "test_space"
        registry._index_category_tools.assert_awaited_once_with("test_int")

    async def test_mcp_requires_auth_raises_and_builds_nothing(self):
        """Auth-required MCP must be built per-user, so create_subagent refuses."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )
        registry = _registry()

        with (
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
            _patch_factory(MagicMock()) as factory,
        ):
            with pytest.raises(ValueError, match="requires authentication"):
                await create_subagent(subagent)

        mock_mcp.assert_not_called()
        factory.assert_not_called()

    async def test_mcp_category_already_registered_skips_connect(self):
        """If the category already exists the connect/add path is skipped, but a
        graph is still built and returned."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=False),
        )
        graph = MagicMock()
        registry = _registry(categories={"test_int": MagicMock()})

        with (
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
            _patch_llm(),
            _patch_factory(graph),
        ):
            result = await create_subagent(subagent)

        assert result is graph
        mock_mcp.assert_not_called()
        registry._add_category.assert_not_called()

    async def test_mcp_connect_returns_no_tools_skips_add_category(self):
        """A connect that yields no tools must NOT register an empty category,
        yet the graph is still built (degraded, tool-less)."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=False),
        )
        graph = MagicMock()
        registry = _registry()

        mcp_client = AsyncMock()
        mcp_client.connect = AsyncMock(return_value=[])

        with (
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            _patch_llm(),
            _patch_factory(graph),
        ):
            result = await create_subagent(subagent)

        assert result is graph
        mcp_client.connect.assert_awaited_once_with("test_int")
        registry._add_category.assert_not_called()
        registry._index_category_tools.assert_not_called()

    async def test_composio_with_mcp_config_still_takes_composio_branch(self):
        """The MCP branch condition is `managed_by == 'mcp' AND mcp_config`. A
        composio subagent that happens to carry an mcp_config must NOT be routed
        into the MCP branch (guards the AND vs OR in the elif)."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(
            managed_by="composio",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )
        integration = _make_integration(managed_by="composio")
        graph = MagicMock()
        registry = _registry()

        with (
            patch(f"{_MODULE}.get_integration_by_id", return_value=integration),
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
            _patch_llm(),
            _patch_factory(graph),
        ):
            result = await create_subagent(subagent)

        assert result is graph
        # Composio branch ran (registered toolkit tools); the auth-required MCP
        # branch did NOT (it would have raised / connected the MCP client).
        registry.register_provider_tools.assert_called_once()
        mock_mcp.assert_not_called()

    async def test_composio_registers_toolkit_tools(self):
        """Composio looks up the OAuthIntegration and registers the toolkit's
        tools into the config's tool space (not a constant)."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(
            managed_by="composio",
            subagent_config=_make_subagent_config(
                tool_space="composio_space",
                specific_tools=["TOOL_A", "TOOL_B"],
            ),
        )
        integration = _make_integration(
            managed_by="composio",
            composio_config=ComposioConfig(auth_config_id="ac", toolkit="GITHUB"),
        )
        graph = MagicMock()
        registry = _registry()

        with (
            patch(f"{_MODULE}.get_integration_by_id", return_value=integration),
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            _patch_llm(),
            _patch_factory(graph),
        ):
            result = await create_subagent(subagent)

        assert result is graph
        reg_kwargs = registry.register_provider_tools.call_args.kwargs
        assert reg_kwargs["toolkit_name"] == "GITHUB"
        assert reg_kwargs["space_name"] == "composio_space"
        assert reg_kwargs["specific_tools"] == ["TOOL_A", "TOOL_B"]

    async def test_composio_without_integration_raises(self):
        """A composio subagent with no matching OAuthIntegration fails loud."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(managed_by="composio")
        registry = _registry()

        with (
            patch(f"{_MODULE}.get_integration_by_id", return_value=None),
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            _patch_factory(MagicMock()) as factory,
        ):
            with pytest.raises(ValueError, match="no matching OAuth"):
                await create_subagent(subagent)

        registry.register_provider_tools.assert_not_called()
        factory.assert_not_called()

    async def test_composio_integration_missing_composio_config_raises(self):
        """A matching integration that lacks composio_config also fails loud —
        the `or integration.composio_config is None` half of the guard."""
        from app.agents.core.subagents.provider_subagents import create_subagent

        subagent = _make_subagent(managed_by="composio")
        # Build a real integration then strip composio_config to bypass the
        # model invariant (the runtime guard is what we are exercising).
        integration = _make_integration(managed_by="composio")
        object.__setattr__(integration, "composio_config", None)
        registry = _registry()

        with (
            patch(f"{_MODULE}.get_integration_by_id", return_value=integration),
            patch(f"{_MODULE}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
            _patch_factory(MagicMock()) as factory,
        ):
            with pytest.raises(ValueError, match="no matching OAuth"):
                await create_subagent(subagent)

        registry.register_provider_tools.assert_not_called()
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# create_subagent_for_user / _build_user_subagent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSubagentForUser:
    async def test_unknown_integration_delegates_to_custom_builder(self):
        """An id not in the registry is treated as a custom MCP and forwarded
        verbatim (both args) to the custom builder, whose result is returned."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        graph = MagicMock()
        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=None),
            patch(
                f"{_MODULE}._create_custom_mcp_subagent",
                new_callable=AsyncMock,
                return_value=graph,
            ) as custom,
        ):
            result = await create_subagent_for_user("custom_abc", "user_123")

        assert result is graph
        custom.assert_awaited_once_with("custom_abc", "user_123")

    async def test_non_mcp_subagent_returns_none(self):
        """A known but non-MCP (composio) subagent cannot be built per-user."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        subagent = _make_subagent(managed_by="composio")
        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None
        mock_mcp.assert_not_called()

    async def test_mcp_subagent_without_mcp_config_returns_none(self):
        """managed_by='mcp' but mcp_config missing fails the AND guard -> None."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        subagent = _make_subagent(managed_by="mcp", mcp_config=None)
        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None
        mock_mcp.assert_not_called()

    async def test_warm_tools_skip_connect_and_build_graph(self):
        """Warm tools in mcp_client._tools[id] are used directly: no connect,
        and the tools are forwarded to the factory as mcp_tools."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
            provider="warm_prov",
        )
        graph = MagicMock()
        warm_tools = [MagicMock(), MagicMock()]

        mcp_client = AsyncMock()
        mcp_client._tools = {"test_int": warm_tools}

        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is graph
        mcp_client.connect.assert_not_called()
        assert factory.call_args.kwargs["provider"] == "warm_prov"
        assert factory.call_args.kwargs["mcp_tools"] is warm_tools

    async def test_cold_connect_path_forwards_connected_tools(self):
        """No warm tools -> connect(id); connected tools are forwarded as mcp_tools."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )
        graph = MagicMock()
        cold_tools = [MagicMock()]

        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(return_value=cold_tools)

        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is graph
        mcp_client.connect.assert_awaited_once_with("test_int")
        assert factory.call_args.kwargs["mcp_tools"] is cold_tools

    async def test_connect_failure_returns_none(self):
        """A connect that raises is swallowed and yields None, not a propagated error."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(side_effect=RuntimeError("connection fail"))

        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            _patch_factory(MagicMock()) as factory,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None
        factory.assert_not_called()

    async def test_zero_tools_returns_none(self):
        """An empty tool list means no usable subagent -> None, no graph built."""
        from app.agents.core.subagents.provider_subagents import create_subagent_for_user

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(return_value=[])

        with (
            patch(f"{_MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            _patch_factory(MagicMock()) as factory,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# _create_custom_mcp_subagent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCustomMcpSubagent:
    async def test_missing_mongo_doc_returns_none(self):
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        with patch(f"{_MODULE}.integrations_collection") as col:
            col.find_one = AsyncMock(return_value=None)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is None
        col.find_one.assert_awaited_once_with({"integration_id": "custom_abc"})

    async def test_connect_failure_returns_none(self):
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        doc = {"integration_id": "custom_abc", "mcp_config": {"server_url": "https://c.example"}}
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(side_effect=RuntimeError("conn fail"))

        with (
            patch(f"{_MODULE}.integrations_collection") as col,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(f"{_MODULE}.derive_integration_namespace", return_value="c.example"),
            _patch_factory(MagicMock()) as factory,
        ):
            col.find_one = AsyncMock(return_value=doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is None
        factory.assert_not_called()

    async def test_zero_tools_returns_none(self):
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        doc = {"integration_id": "custom_abc", "mcp_config": {"server_url": "https://c.example"}}
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(return_value=[])

        with (
            patch(f"{_MODULE}.integrations_collection") as col,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(f"{_MODULE}.derive_integration_namespace", return_value="c.example"),
            _patch_factory(MagicMock()) as factory,
        ):
            col.find_one = AsyncMock(return_value=doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is None
        factory.assert_not_called()

    async def test_small_toolset_binds_directly(self):
        """1..10 tools => direct binding (use_direct_tools & disable_retrieve_tools
        True). Namespace from derive_integration_namespace becomes tool_space."""
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        doc = {"integration_id": "custom_abc", "mcp_config": {"server_url": "https://c.example"}}
        graph = MagicMock()
        tools = [MagicMock() for _ in range(10)]  # upper boundary, still "small"
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(return_value=tools)

        with (
            patch(f"{_MODULE}.integrations_collection") as col,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(f"{_MODULE}.derive_integration_namespace", return_value="c.example") as derive,
            patch("asyncio.create_task", side_effect=_noop_create_task),
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            col.find_one = AsyncMock(return_value=doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is graph
        kwargs = factory.call_args.kwargs
        assert kwargs["use_direct_tools"] is True
        assert kwargs["disable_retrieve_tools"] is True
        assert kwargs["tool_space"] == "c.example"
        assert kwargs["provider"] == "custom_abc"
        assert kwargs["name"] == "custom_mcp_custom_abc"
        assert kwargs["mcp_tools"] is tools
        derive.assert_called_once_with("custom_abc", "https://c.example", is_custom=True)

    async def test_single_tool_binds_directly(self):
        """A single tool is still a "small" toolset: 0 < 1 <= 10 => direct binding.
        This pins the lower bound `0 <` of the range check (a 1-tool integration
        must not fall into retrieve mode)."""
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        doc = {"integration_id": "custom_abc", "mcp_config": {"server_url": "https://c.example"}}
        graph = MagicMock()
        tools = [MagicMock()]  # exactly one tool
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(return_value=tools)

        with (
            patch(f"{_MODULE}.integrations_collection") as col,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(f"{_MODULE}.derive_integration_namespace", return_value="c.example"),
            patch("asyncio.create_task", side_effect=_noop_create_task),
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            col.find_one = AsyncMock(return_value=doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is graph
        assert factory.call_args.kwargs["use_direct_tools"] is True

    async def test_large_toolset_uses_retrieve(self):
        """11+ tools => retrieve-tools mode (both flags False)."""
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        doc = {"integration_id": "custom_abc", "mcp_config": {"server_url": "https://c.example"}}
        graph = MagicMock()
        tools = [MagicMock() for _ in range(11)]  # just over the boundary
        mcp_client = AsyncMock()
        mcp_client._tools = {}
        mcp_client.connect = AsyncMock(return_value=tools)

        with (
            patch(f"{_MODULE}.integrations_collection") as col,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(f"{_MODULE}.derive_integration_namespace", return_value="c.example"),
            patch("asyncio.create_task", side_effect=_noop_create_task),
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            col.find_one = AsyncMock(return_value=doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is graph
        kwargs = factory.call_args.kwargs
        assert kwargs["use_direct_tools"] is False
        assert kwargs["disable_retrieve_tools"] is False

    async def test_warm_tools_skip_connect(self):
        """Warm tools in mcp_client._tools[id] are used directly (no connect)."""
        from app.agents.core.subagents.provider_subagents import _create_custom_mcp_subagent

        doc = {"integration_id": "custom_abc", "mcp_config": {"server_url": "https://c.example"}}
        graph = MagicMock()
        warm_tools = [MagicMock() for _ in range(3)]
        mcp_client = AsyncMock()
        mcp_client._tools = {"custom_abc": warm_tools}

        with (
            patch(f"{_MODULE}.integrations_collection") as col,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(f"{_MODULE}.derive_integration_namespace", return_value="c.example"),
            patch("asyncio.create_task", side_effect=_noop_create_task),
            _patch_llm(),
            _patch_factory(graph) as factory,
        ):
            col.find_one = AsyncMock(return_value=doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is graph
        mcp_client.connect.assert_not_called()
        assert factory.call_args.kwargs["mcp_tools"] is warm_tools


# ---------------------------------------------------------------------------
# _make_subagent_loader
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMakeSubagentLoader:
    async def test_loader_builds_the_bound_subagent(self):
        """The loader returned by _make_subagent_loader is a zero-arg async that,
        when awaited, calls create_subagent with the bound subagent and returns
        that graph. (Kills `return _loader -> return None`.)"""
        from app.agents.core.subagents.provider_subagents import _make_subagent_loader

        subagent = _make_subagent(integration_id="bound_int")
        graph = MagicMock()

        loader = _make_subagent_loader(subagent)
        assert callable(loader)

        with patch(
            f"{_MODULE}.create_subagent", new_callable=AsyncMock, return_value=graph
        ) as create:
            result = await loader()

        assert result is graph
        create.assert_awaited_once_with(subagent)


# ---------------------------------------------------------------------------
# register_subagent_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterSubagentProviders:
    def test_registers_eligible_under_agent_name(self):
        """An eligible (composio) subagent registers exactly one lazy provider
        keyed by its agent_name; the count is 1."""
        from app.agents.core.subagents.provider_subagents import register_subagent_providers

        subagent = _make_subagent(
            managed_by="composio",
            subagent_config=_make_subagent_config(agent_name="github_agent"),
        )

        with (
            patch(f"{_MODULE}.all_subagents", return_value=(subagent,)),
            patch(f"{_MODULE}.providers") as providers,
        ):
            count = register_subagent_providers()

        assert count == 1
        providers.register.assert_called_once()
        assert providers.register.call_args.kwargs["name"] == "github_agent"

    def test_skips_auth_required_mcp(self):
        """Auth-required MCP subagents are built on-demand, never pre-registered."""
        from app.agents.core.subagents.provider_subagents import register_subagent_providers

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )

        with (
            patch(f"{_MODULE}.all_subagents", return_value=(subagent,)),
            patch(f"{_MODULE}.providers") as providers,
        ):
            count = register_subagent_providers()

        assert count == 0
        providers.register.assert_not_called()

    def test_registers_non_auth_mcp(self):
        """A non-auth MCP subagent IS eligible and gets registered (distinguishes
        the requires_auth half of the skip condition)."""
        from app.agents.core.subagents.provider_subagents import register_subagent_providers

        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=False),
        )

        with (
            patch(f"{_MODULE}.all_subagents", return_value=(subagent,)),
            patch(f"{_MODULE}.providers") as providers,
        ):
            count = register_subagent_providers()

        assert count == 1
        providers.register.assert_called_once()

    def test_id_filter_excludes_non_listed(self):
        """When integration_ids is given, only listed subagents are registered."""
        from app.agents.core.subagents.provider_subagents import register_subagent_providers

        sa1 = _make_subagent(
            integration_id="int1",
            subagent_config=_make_subagent_config(agent_name="agent_1"),
        )
        sa2 = _make_subagent(
            integration_id="int2",
            subagent_config=_make_subagent_config(agent_name="agent_2"),
        )

        with (
            patch(f"{_MODULE}.all_subagents", return_value=(sa1, sa2)),
            patch(f"{_MODULE}.providers") as providers,
        ):
            count = register_subagent_providers(integration_ids=["int1"])

        assert count == 1
        assert providers.register.call_args.kwargs["name"] == "agent_1"
