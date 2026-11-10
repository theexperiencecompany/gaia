"""Which integration a tool acts on, for the run-level block on an unconnected integration."""

from langchain_core.tools import BaseTool

from app.config.oauth_config import get_integration_by_tool_slug
from app.models.mcp_config import McpToolProvenance


def tool_integration_id(tool: BaseTool) -> str | None:
    """Return the integration a tool calls (MCP stamp, else Composio slug); None for GAIA's own tools."""
    stamped = McpToolProvenance.model_validate(tool.metadata or {}).integration_id
    if stamped:
        return stamped
    integration = get_integration_by_tool_slug(tool.name)
    return integration.id if integration else None
