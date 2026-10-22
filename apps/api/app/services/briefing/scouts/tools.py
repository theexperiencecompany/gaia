"""The tools a scout may use: one connected integration's own tools, read-only ones only.

Native and custom MCP integrations resolve the way the agent reaches them: a registry
category for Composio and built-in providers, the user's MCP client for every MCP server.
"""

from dataclasses import dataclass
import hashlib

from langchain_core.tools import BaseTool

from app.agents.core.subagents.provider_subagents import register_composio_subagent_tools
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools.core.registry import get_tool_registry
from app.constants.scouts import SCOUTED_ELSEWHERE
from app.models.playbook_models import is_work_call
from app.services.hil.classification import is_tool_destructive, mcp_destructive_hint
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
    """The integration's read-only tools, and the fingerprint of its whole tool list."""

    read_only: dict[str, BaseTool]
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


async def integration_tools(user_id: str, integration_id: str) -> list[BaseTool]:
    """Return every tool the integration exposes to this user; raise when none can be reached."""
    subagent = get_subagent_by_id(integration_id)
    if subagent is not None and subagent.mcp_config is None:
        registry = await get_tool_registry()
        if subagent.managed_by == "composio":
            await register_composio_subagent_tools(subagent, registry)
        category = registry.get_category_by_space(subagent.config.tool_space)
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


async def _is_read_only(tool: BaseTool) -> bool:
    """Report a tool read-only when neither its name, MCP hint nor HIL risk flag says it writes."""
    if is_work_call(tool.name) or mcp_destructive_hint(tool):
        return False
    return not await is_tool_destructive(tool.name, tool.description)


def tool_fingerprint(tools: list[BaseTool]) -> str:
    """Return a stable hash of the tool names; a change means frozen calls may be gone."""
    names = "\n".join(sorted(tool.name for tool in tools))
    return hashlib.sha256(names.encode()).hexdigest()


async def scout_tools(user_id: str, integration_id: str) -> ScoutTools:
    tools = await integration_tools(user_id, integration_id)
    read_only = {tool.name: tool for tool in tools if await _is_read_only(tool)}
    return ScoutTools(read_only=read_only, fingerprint=tool_fingerprint(tools))
