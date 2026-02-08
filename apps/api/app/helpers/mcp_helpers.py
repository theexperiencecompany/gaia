"""
MCP Helper Functions.

Contains helper functions for MCP operations:
- Stub tool creation from cached metadata
- URL helpers for OAuth flows
- Cache invalidation utilities
"""

from typing import TYPE_CHECKING


from app.config.loggers import langchain_logger as logger
from app.config.settings import settings
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache

if TYPE_CHECKING:
    pass


def get_api_base_url() -> str:
    """Get the backend API base URL for callbacks."""
    return settings.HOST


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


def get_tool_namespace_from_url(server_url: str, fallback: str = "") -> str:
    """Extract a consistent tool namespace from a server URL.

    Uses netloc + path to differentiate endpoints like:
    - domain.com/v1 -> "domain.com/v1"
    - domain.com/v2 -> "domain.com/v2"

    Args:
        server_url: The MCP server URL
        fallback: Value to return if URL can't be parsed

    Returns:
        Namespace string (e.g., "api.example.com/v1")
    """
    from urllib.parse import urlparse

    if not server_url:
        return fallback

    try:
        parsed = urlparse(server_url)
    except ValueError:
        return fallback

    if not parsed.netloc:
        return fallback

    path = parsed.path.rstrip("/")
    return f"{parsed.netloc}{path}" if path else parsed.netloc
