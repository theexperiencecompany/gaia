"""MCP proxy response schemas.

The proxied payloads stay ``list[dict[str, Any]]``: each element is an MCP
content block / resource / prompt serialized by the MCP SDK, and the block union
is open-ended by spec (text, image, audio, resource link, embedded resource,
plus server extensions). These bodies are forwarded verbatim to the MCP App
iframe, so pinning a narrower shape here would be a change to a contract an
external consumer already depends on (Type Safety item 14).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class MCPConnectionTestResponse(BaseModel):
    """Outcome of probing an MCP server from ``POST /mcp/test/{integration_id}``.

    Exactly one of ``tools_count`` / ``oauth_url`` / ``error`` accompanies the
    status, so the route serializes with ``response_model_exclude_none=True`` to
    keep the body identical to the hand-built dict it replaced.
    """

    status: Literal["connected", "requires_oauth", "failed"]
    tools_count: int | None = None
    oauth_url: str | None = None
    error: str | None = None


class MCPProxyToolCallResponse(BaseModel):
    """Response for a proxied tools/call."""

    content: list[dict[str, Any]]
    is_error: bool = False


class MCPProxyResourcesListResponse(BaseModel):
    """Response for a proxied resources/list."""

    resources: list[dict[str, Any]]
    next_cursor: str | None = None


class MCPProxyResourceTemplatesListResponse(BaseModel):
    """Response for a proxied resources/templates/list."""

    resource_templates: list[dict[str, Any]]
    next_cursor: str | None = None


class MCPProxyResourceReadResponse(BaseModel):
    """Response for a proxied resources/read."""

    contents: list[dict[str, Any]]


class MCPProxyPromptsListResponse(BaseModel):
    """Response for a proxied prompts/list."""

    prompts: list[dict[str, Any]]
    next_cursor: str | None = None
