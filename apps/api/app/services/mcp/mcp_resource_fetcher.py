"""
MCP resource fetcher for MCP Apps UI resources.
Fetches HTML content from MCP servers using existing user credentials.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log


async def fetch_mcp_ui_resource(
    server_url: str,
    resource_uri: str,
    user_id: str,
) -> Optional[dict[str, Any]]:
    """
    Fetch an MCP UI resource from an MCP server using the user's credentials.

    Args:
        server_url: The MCP server URL (e.g. "https://mcp.example.com/mcp")
        resource_uri: The ui:// resource URI (e.g. "ui://get-time/app.html")
        user_id: The user ID for credential lookup

    Returns:
        Dict with ``html`` and optional UI metadata, or None on failure
    """
    log.set(
        mcp_ui={
            "server_url": server_url,
            "resource_uri": resource_uri,
            "user_id": user_id,
        }
    )
    try:
        mcp_client = await get_mcp_client(user_id=user_id)
        details = await mcp_client.read_ui_resource_details(
            server_url=server_url,
            resource_uri=resource_uri,
        )
        log.set(mcp_ui={"fetch_success": True})
        return details
    except Exception as e:
        log.warning(
            "Failed to fetch MCP UI resource",
            resource_uri=resource_uri,
            server_url=server_url,
            error=str(e),
        )
        return None
