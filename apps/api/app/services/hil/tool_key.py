"""The one key HIL stores a tool's per-user rules and cached verdict under.

A registry tool keys by its bare name. An MCP tool keys by its server and its
name on that server, mcp:<integration_id>:<mcp_server_name>: two servers
exposing the same name never share a rule, and the key survives the GAIA-side
collision rename (delete_item -> posthog_delete_item).
"""

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.constants.execute import MCP_SHAPE_SCOPE_PREFIX
from app.constants.mcp import MCP_INTEGRATION_ID_METADATA_KEY, MCP_SERVER_NAME_METADATA_KEY


@dataclass(frozen=True)
class MCPToolIdentity:
    """Which MCP server a tool lives on, and its name there."""

    integration_id: str
    server_name: str


def mcp_tool_identity(tool: BaseTool | None) -> MCPToolIdentity | None:
    """Return the server identity MCPClient stamped on a tool, or None for a non-MCP tool.

    Raises ValueError for a tool stamped with an integration but no server name.
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    integration_id = metadata.get(MCP_INTEGRATION_ID_METADATA_KEY)
    if not isinstance(integration_id, str) or not integration_id:
        return None
    server_name = metadata.get(MCP_SERVER_NAME_METADATA_KEY)
    if not isinstance(server_name, str) or not server_name:
        raise ValueError(
            f"MCP tool from {integration_id} carries no {MCP_SERVER_NAME_METADATA_KEY}"
        )
    return MCPToolIdentity(integration_id=integration_id, server_name=server_name)


def hil_tool_key(tool_name: str, mcp_tool: MCPToolIdentity | None) -> str:
    """Return the key a tool's override, never-auto rule and cached verdict are stored under."""
    if mcp_tool is None:
        return tool_name
    return f"{MCP_SHAPE_SCOPE_PREFIX}{mcp_tool.integration_id}:{mcp_tool.server_name}"


def parse_hil_tool_key(key: str) -> MCPToolIdentity | None:
    """Return the MCP identity a scoped key names, or None for a bare registry key."""
    if not key.startswith(MCP_SHAPE_SCOPE_PREFIX):
        return None
    integration_id, _, server_name = key.removeprefix(MCP_SHAPE_SCOPE_PREFIX).partition(":")
    if not integration_id or not server_name:
        raise ValueError(f"Malformed HIL tool key: {key}")
    return MCPToolIdentity(integration_id=integration_id, server_name=server_name)
