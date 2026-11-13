"""MCP proxy request schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from shared.py.analytics.catalog.properties import Identifier


class MCPProxyToolCallRequest(BaseModel):
    """Proxy a tools/call from an MCP App iframe."""

    server_url: str
    # The MCP spec's tool-name charset is [A-Za-z0-9_.-]; anything else 422s before the call.
    tool_name: Identifier
    arguments: dict[str, Any] = {}


class MCPProxyResourcesListRequest(BaseModel):
    """Proxy a resources/list request from an MCP App iframe."""

    server_url: str
    cursor: str | None = None


class MCPProxyResourceTemplatesListRequest(BaseModel):
    """Proxy a resources/templates/list request from an MCP App iframe."""

    server_url: str
    cursor: str | None = None


class MCPProxyResourceReadRequest(BaseModel):
    """Proxy a resources/read request from an MCP App iframe."""

    server_url: str
    uri: str


class MCPProxyPromptsListRequest(BaseModel):
    """Proxy a prompts/list request from an MCP App iframe."""

    server_url: str
    cursor: str | None = None
