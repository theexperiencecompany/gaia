"""MCP proxy schemas."""

from app.schemas.mcp.requests import (
    MCPProxyPromptsListRequest,
    MCPProxyResourceReadRequest,
    MCPProxyResourceTemplatesListRequest,
    MCPProxyResourcesListRequest,
    MCPProxyToolCallRequest,
)
from app.schemas.mcp.responses import (
    MCPProxyPromptsListResponse,
    MCPProxyResourceReadResponse,
    MCPProxyResourceTemplatesListResponse,
    MCPProxyResourcesListResponse,
    MCPProxyToolCallResponse,
)

__all__ = [
    "MCPProxyToolCallRequest",
    "MCPProxyResourcesListRequest",
    "MCPProxyResourceTemplatesListRequest",
    "MCPProxyResourceReadRequest",
    "MCPProxyPromptsListRequest",
    "MCPProxyToolCallResponse",
    "MCPProxyResourcesListResponse",
    "MCPProxyResourceTemplatesListResponse",
    "MCPProxyResourceReadResponse",
    "MCPProxyPromptsListResponse",
]
