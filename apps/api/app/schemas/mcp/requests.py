"""MCP proxy request schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


# NOTE: these requests identify the target server by ``integration_id`` only.
# Resolving the actual server URL is done server-side from the user's
# integrations so the client cannot point the proxy at an arbitrary host
# (SSRF). See ``mcp_proxy.py`` and ``IntegrationResolver``.


class MCPProxyToolCallRequest(BaseModel):
    """Proxy a tools/call from an MCP App iframe."""

    integration_id: str
    tool_name: str
    arguments: dict[str, Any] = {}


class MCPProxyResourcesListRequest(BaseModel):
    """Proxy a resources/list request from an MCP App iframe."""

    integration_id: str
    cursor: Optional[str] = None


class MCPProxyResourceTemplatesListRequest(BaseModel):
    """Proxy a resources/templates/list request from an MCP App iframe."""

    integration_id: str
    cursor: Optional[str] = None


class MCPProxyResourceReadRequest(BaseModel):
    """Proxy a resources/read request from an MCP App iframe."""

    integration_id: str
    uri: str


class MCPProxyPromptsListRequest(BaseModel):
    """Proxy a prompts/list request from an MCP App iframe."""

    integration_id: str
    cursor: Optional[str] = None
