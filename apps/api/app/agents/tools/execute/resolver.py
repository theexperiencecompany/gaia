"""Resolve a tool name to a live BaseTool across every integration source.

Three sources, tried in cost order: the global registry (materialized internal
+ Composio tools), the per-user MCPClient (MCP tools never enter the global
registry — see retrieval._user_mcp_tool_names), and on-demand Composio
materialization (the provider catalog holds metadata only until a toolkit is
first used — see ToolRegistry.populate_provider_catalog).

``ResolvedTool.is_integration`` is the single classification of what a tool IS
(Composio/MCP vs internal). The sandbox route runs integration tools only —
internal tools need graph runtime the route doesn't have, and excluding them
also shrinks what a leaked token can reach.
"""

import asyncio
from typing import NamedTuple

from langchain_core.tools import BaseTool

from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.constants.execute import (
    COMPOSIO_CATALOG_LOOKUP_TIMEOUT_SECONDS,
    GLOBAL_SHAPE_SCOPE,
    MCP_SHAPE_SCOPE_PREFIX,
    UNKNOWN_CATALOG_SLUG_CACHE_MAX,
)
from app.constants.log_tags import LogTag
from app.services.composio.composio_service import get_composio_service
from app.services.mcp.mcp_client import get_mcp_client
from app.utils.mcp_utils import canonical_tool_name_map
from shared.py.wide_events import log


class ResolvedTool(NamedTuple):
    name: str
    tool: BaseTool
    # True for Composio/MCP tools (the execute proxy's scope); False for
    # internal tools, which only run bound inside a graph.
    is_integration: bool
    # Where this tool's observed output shape is stored and read. "global" for
    # catalog tools (identical for every user); "mcp:<integration_id>" for MCP
    # tools, so a private server's shapes are visible only to users who can
    # resolve that integration — the resolver itself is the access gate.
    shape_scope: str = GLOBAL_SHAPE_SCOPE
    # True when the name came from the global registry, which is the only
    # source an agent's tool space partitions: MCP tools and on-demand catalog
    # slugs are outside every space, so no space can exclude them. Dispatch
    # applies a caller's scope to registry tools alone, matching the boundary
    # retrieve_tools enforces for binding.
    in_registry: bool = False


# Composio tools materialized on demand outside a toolkit registration; process
# lifetime, mirroring the registry's own semantics (tools are user-agnostic —
# the user attaches via config at invocation time).
_materialized_composio_tools: dict[str, BaseTool] = {}

# Slugs the catalog answered "no such tool" for. Same lifetime and reasoning as
# the positive cache above — see UNKNOWN_CATALOG_SLUG_CACHE_MAX for why a miss
# is worth remembering at all.
_unknown_composio_slugs: set[str] = set()


async def resolve_tool(user_id: str | None, tool_name: str) -> ResolvedTool | None:
    """The canonical tool for a model-supplied name, or ``None`` if unknown."""
    registry = await get_tool_registry()

    resolved = _from_registry(registry, tool_name)
    if resolved is not None:
        return resolved

    # Alias forms (dashes, casing) the model commonly emits.
    canonical = canonical_tool_name_map(set(registry.get_tool_names())).get(
        tool_name.replace("-", "_")
    )
    if canonical is not None:
        resolved = _from_registry(registry, canonical)
        if resolved is not None:
            return resolved

    mcp_resolved = await _resolve_mcp_tool(user_id, tool_name)
    if mcp_resolved is not None:
        return mcp_resolved

    return await _materialize_composio_tool(tool_name)


def _from_registry(registry: ToolRegistry, tool_name: str) -> ResolvedTool | None:
    meta = registry.get_tool_meta(tool_name)
    if meta is None:
        return None
    category = registry.get_category(registry.get_category_of_tool(meta.name))
    is_integration = bool(category is not None and category.require_integration)
    return ResolvedTool(
        name=meta.name, tool=meta.tool, is_integration=is_integration, in_registry=True
    )


async def _resolve_mcp_tool(user_id: str | None, tool_name: str) -> ResolvedTool | None:
    if not user_id:
        return None
    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
    except Exception as e:
        # An MCP outage must not take down resolution for registry/Composio
        # tools — but it is never silent (mirrors _user_mcp_tool_names).
        log.warning(
            f"{LogTag.TOOL} execute resolver: MCP client unavailable",
            user_id=user_id,
            error_type=type(e).__name__,
        )
        return None
    integration_id = mcp_client.find_integration(tool_name)
    if integration_id is None:
        return None
    for tool in await mcp_client.get_tools(integration_id):
        if tool.name == tool_name:
            return ResolvedTool(
                name=tool.name,
                tool=tool,
                is_integration=True,
                shape_scope=f"{MCP_SHAPE_SCOPE_PREFIX}{integration_id}",
            )
    return None


async def _materialize_composio_tool(tool_name: str) -> ResolvedTool | None:
    """Materialize one catalog tool by slug, without registering its whole toolkit."""
    cached = _materialized_composio_tools.get(tool_name)
    if cached is not None:
        return ResolvedTool(name=tool_name, tool=cached, is_integration=True)
    # Catalog slugs are ALLCAPS_SNAKE; anything else cannot be a Composio slug,
    # and asking Composio for it costs a network round-trip per model typo.
    if not tool_name.replace("_", "").isupper() or tool_name in _unknown_composio_slugs:
        return None
    async with asyncio.timeout(COMPOSIO_CATALOG_LOOKUP_TIMEOUT_SECONDS):
        tools = await get_composio_service().get_tools_by_name([tool_name])
    for tool in tools:
        if tool.name == tool_name:
            _materialized_composio_tools[tool_name] = tool
            log.info(
                f"{LogTag.TOOL} execute resolver: materialized catalog tool on demand",
                tool_name=tool_name,
            )
            return ResolvedTool(name=tool.name, tool=tool, is_integration=True)
    if len(_unknown_composio_slugs) >= UNKNOWN_CATALOG_SLUG_CACHE_MAX:
        _unknown_composio_slugs.clear()
    _unknown_composio_slugs.add(tool_name)
    return None
