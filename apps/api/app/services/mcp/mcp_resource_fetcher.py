"""
MCP resource fetcher for MCP Apps UI resources.
Fetches HTML content from MCP servers using existing user credentials.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.mcp.mcp_client import get_mcp_client

logger = logging.getLogger(__name__)


async def fetch_mcp_ui_resource(
    server_url: str,
    resource_uri: str,
    user_id: str,
) -> Optional[str]:
    """
    Fetch an MCP UI resource (HTML) from an MCP server using the user's credentials.

    Args:
        server_url: The MCP server URL (e.g. "https://mcp.example.com/mcp")
        resource_uri: The ui:// resource URI (e.g. "ui://get-time/app.html")
        user_id: The user ID for credential lookup

    Returns:
        HTML content string, or None on failure
    """
    try:
        mcp_client = await get_mcp_client(user_id=user_id)
        html = await mcp_client.read_ui_resource(
            server_url=server_url,
            resource_uri=resource_uri,
        )
        return html
    except Exception as e:
        logger.warning(
            "Failed to fetch MCP UI resource %s from %s: %s",
            resource_uri,
            server_url,
            e,
        )
        return None
