"""MCP proxy schemas."""

from app.schemas.mcp.requests import (
    MCPProxyPromptsListRequest,
    MCPProxyResourceReadRequest,
    MCPProxyResourcesListRequest,
    MCPProxyResourceTemplatesListRequest,
    MCPProxyToolCallRequest,
)
from app.schemas.mcp.responses import (
    MCPProxyPromptsListResponse,
    MCPProxyResourceReadResponse,
    MCPProxyResourcesListResponse,
    MCPProxyResourceTemplatesListResponse,
    MCPProxyToolCallResponse,
)

__all__ = [
    "MCPProxyPromptsListRequest",
    "MCPProxyPromptsListResponse",
    "MCPProxyResourceReadRequest",
    "MCPProxyResourceReadResponse",
    "MCPProxyResourceTemplatesListRequest",
    "MCPProxyResourceTemplatesListResponse",
    "MCPProxyResourcesListRequest",
    "MCPProxyResourcesListResponse",
    "MCPProxyToolCallRequest",
    "MCPProxyToolCallResponse",
]
