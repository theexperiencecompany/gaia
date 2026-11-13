"""Fetch HTML content for MCP Apps UI resources from MCP servers using existing user credentials."""

from __future__ import annotations

from app.constants.log_tags import LogTag
from app.models.mcp_config import McpUiResourceDetails
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.server_routing import read_ui_resource_details
from shared.py.wide_events import McpContext, log


async def fetch_mcp_ui_resource(
    server_url: str,
    resource_uri: str,
    user_id: str,
) -> McpUiResourceDetails | None:
    """Fetch an MCP UI resource, returning its HTML plus _meta.ui hints, or None on failure."""
    log.set(
        mcp_ui={
            "server_url": server_url,
            "resource_uri": resource_uri,
            "user_id": user_id,
        }
    )
    try:
        mcp_client = await get_mcp_client(user_id=user_id)
        details = await read_ui_resource_details(
            mcp_client,
            server_url=server_url,
            resource_uri=resource_uri,
        )
        log.set(mcp=McpContext(success=True))
        return details
    except Exception as e:
        log.set(mcp=McpContext(success=False, error_type=type(e).__name__))
        log.warning(
            f"{LogTag.MCP} Failed to fetch MCP UI resource",
            resource_uri=resource_uri,
            server_url=server_url,
            error=str(e),
        )
        return None
