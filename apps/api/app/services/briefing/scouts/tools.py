"""The tools a scout may use: one connected integration's own tools that declare themselves read-only.

Native and custom MCP integrations resolve the way the agent reaches them: a registry
category for Composio and built-in providers, the user's MCP client for every MCP server.
A tool is a scout's only when its own metadata marks it read-only (declares_read_only);
Composio's tags are not on the LangChain tool, so they are read from Composio's tool list
and stamped on scout-local copies.
"""

from dataclasses import dataclass
import hashlib

from langchain_core.tools import BaseTool

from app.agents.core.subagents.provider_subagents import register_composio_subagent_tools
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools.core.registry import get_composio_service, get_tool_registry
from app.agents.tools.core.store import get_tools_store
from app.constants.hil import COMPOSIO_TAGS_METADATA_KEY
from app.constants.scouts import SCOUT_MAX_BOUND_TOOLS, SCOUT_TOOL_QUERY, SCOUTED_ELSEWHERE
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.subagent_models import Subagent
from app.services.hil.classification import declares_read_only
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.user_integrations import (
    ConnectedIntegration,
    get_connected_integrations_named,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.utils.errors import AppError


@dataclass(frozen=True, slots=True)
class ScoutIntegration:
    """A connected integration a scout watches."""

    integration_id: str
    name: str


@dataclass(frozen=True, slots=True)
class ScoutTools:
    """The integration's read-only tools, the size and fingerprint of its whole tool list."""

    integration_id: str
    read_only: dict[str, BaseTool]
    total: int
    fingerprint: str


async def scout_integrations(user_id: str) -> list[ScoutIntegration]:
    """Return the user's connected external integrations the rest of the brief does not cover."""
    connected: list[ConnectedIntegration] = await get_connected_integrations_named(user_id)
    return [
        ScoutIntegration(integration_id=entry["id"], name=entry["name"])
        for entry in connected
        if entry["id"] not in SCOUTED_ELSEWHERE and _is_external(entry["id"])
    ]


def _is_external(integration_id: str) -> bool:
    """GAIA's own features (todos, memory) are not apps to scout; a custom MCP always is."""
    subagent = get_subagent_by_id(integration_id)
    return subagent is None or subagent.managed_by != "internal"


async def _composio_tools(subagent: Subagent) -> list[BaseTool]:
    """Return a Composio toolkit's tools as scout-local copies carrying their Composio tags."""
    registry = await get_tool_registry()
    toolkit = await register_composio_subagent_tools(subagent, registry)
    category = registry.get_category_by_space(subagent.config.tool_space)
    tools = category.get_tool_objects() if category else []
    raw = await get_composio_service().get_raw_tools_metadata(
        tool_kit=toolkit, specific_tools=subagent.config.specific_tools
    )
    tags = {entry.slug: list(entry.tags) for entry in raw}
    return [
        tool.model_copy(
            update={
                "metadata": {**(tool.metadata or {}), COMPOSIO_TAGS_METADATA_KEY: tags[tool.name]}
            }
        )
        if tool.name in tags
        else tool
        for tool in tools
    ]


async def integration_tools(user_id: str, integration_id: str) -> list[BaseTool]:
    """Return every tool the integration exposes to this user; raise when none can be reached.

    Raises MCPIntegrationNotFoundError when the id names no integration at all.
    """
    subagent = get_subagent_by_id(integration_id)
    if subagent is not None and subagent.mcp_config is None:
        if subagent.managed_by == "composio":
            tools = await _composio_tools(subagent)
        else:
            category = (await get_tool_registry()).get_category_by_space(subagent.config.tool_space)
            tools = category.get_tool_objects() if category else []
    else:
        client = await get_mcp_client(user_id=user_id)
        tools = await client.ensure_connected(integration_id)
    if not tools:
        raise AppError(
            message=f"no tools reachable for {integration_id}",
            why="the integration answered with an empty tool list",
            fix="reconnect the integration; the scout learns again once its tools are back",
        )
    return tools


def tool_fingerprint(tools: list[BaseTool]) -> str:
    """Return a stable hash of the tool names; a change means frozen calls may be gone."""
    names = "\n".join(sorted(tool.name for tool in tools))
    return hashlib.sha256(names.encode()).hexdigest()


async def scout_tools(user_id: str, integration_id: str) -> ScoutTools:
    tools = await integration_tools(user_id, integration_id)
    return ScoutTools(
        integration_id=integration_id,
        read_only={tool.name: tool for tool in tools if declares_read_only(tool)},
        total=len(tools),
        fingerprint=tool_fingerprint(tools),
    )


async def _index_namespace(integration_id: str) -> str:
    """Return the tool index namespace holding the integration's tools, as retrieval names it."""
    subagent = get_subagent_by_id(integration_id)
    if subagent is not None:
        return subagent.config.tool_space
    resolved = await IntegrationResolver.resolve(integration_id)
    server_url = resolved.mcp_config.server_url if resolved and resolved.mcp_config else None
    return derive_integration_namespace(integration_id, server_url, is_custom=True)


async def bound_tools(tools: ScoutTools) -> dict[str, BaseTool]:
    """Return the read-only tools a learn run binds: all, or past the ceiling the most relevant.

    Relevance is the tool index's own ranking for what a scout looks for; raises when the
    index holds none of the integration's read-only tools.
    """
    if len(tools.read_only) <= SCOUT_MAX_BOUND_TOOLS:
        return tools.read_only
    store = await get_tools_store()
    namespace = await _index_namespace(tools.integration_id)
    hits = await store.asearch((namespace,), query=SCOUT_TOOL_QUERY, limit=tools.total)
    ranked = list(dict.fromkeys(str(hit.key) for hit in hits if str(hit.key) in tools.read_only))
    if not ranked:
        raise AppError(
            message=f"the tool index ranks none of {tools.integration_id}'s read-only tools",
            why=f"searching namespace {namespace!r} matched no tool the scout may use",
            fix="reindex the integration's tools; the scout learns again on the next brief",
        )
    return {name: tools.read_only[name] for name in ranked[:SCOUT_MAX_BOUND_TOOLS]}
