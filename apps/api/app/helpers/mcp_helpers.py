"""
MCP Helper Functions.

Contains helper functions for MCP operations:
- Stub tool creation from cached metadata
- URL helpers for OAuth flows
- Cache invalidation utilities
"""

from typing import TYPE_CHECKING, Any, Sequence
import asyncio

from langchain_core.tools import BaseTool, StructuredTool
from mcp_use.client.exceptions import OAuthAuthenticationError
from pydantic import Field, create_model

from app.config.loggers import langchain_logger as logger
from app.config.settings import settings
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.utils.mcp_utils import extract_type_from_field

if TYPE_CHECKING:
    from app.services.mcp.mcp_client import MCPClient


def get_api_base_url() -> str:
    """Get the backend API base URL for callbacks."""
    return getattr(settings, "API_BASE_URL", "http://localhost:8000")


def get_frontend_url() -> str:
    """Get the frontend base URL for redirects."""
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


async def invalidate_mcp_status_cache(user_id: str) -> None:
    """Invalidate OAuth status cache for parity with Composio."""
    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"Invalidated MCP status cache for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate status cache: {e}")
