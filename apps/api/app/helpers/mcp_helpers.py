"""
MCP Helper Functions.

Contains helper functions for MCP operations:
- Stub tool creation from cached metadata
- URL helpers for OAuth flows
"""

from app.config.settings import settings


def get_api_base_url() -> str:
    """Get the backend API base URL for callbacks."""
    return settings.HOST


def get_frontend_url() -> str:
    """Get the frontend base URL for redirects."""
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


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
