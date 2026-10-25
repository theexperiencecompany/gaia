"""
MCP Helper Functions.

Contains helper functions for MCP operations:
- Stub tool creation from cached metadata
- URL helpers for OAuth flows
"""

import ipaddress
from typing import cast

import httpx

from app.config.settings import settings
from app.utils.url_safety import assert_endpoint_url_shape

_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def get_api_base_url() -> str:
    """Get the backend API base URL for callbacks."""
    return cast(str, settings.HOST)


def get_frontend_url() -> str:
    """Get the frontend base URL for redirects."""
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


def _is_loopback(host: str) -> bool:
    if host.lower().rstrip(".") in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def dialable_mcp_server_url(server_url: str) -> str:
    """Return the custom MCP URL this process should store and dial; raise ValueError if refused.

    A loopback host means the user's own machine, so it is pointed at
    LOOPBACK_HOST_ALIAS where the API runs in a container. Private addresses
    pass only where the deployment allows private-network endpoints.
    """
    alias = settings.LOOPBACK_HOST_ALIAS
    try:
        url = httpx.URL(server_url)
    except httpx.InvalidURL as e:
        raise ValueError(f"malformed URL: {e}") from e
    if alias and url.host and _is_loopback(url.host):
        server_url = str(url.copy_with(host=alias))
    assert_endpoint_url_shape(
        server_url, allow_private=settings.deployment.private_network_endpoints
    )
    return server_url


def get_tool_namespace_from_url(server_url: str, fallback: str = "") -> str:
    """Extract a consistent tool namespace from a server URL.

    Uses netloc + path so distinct endpoints (e.g. domain.com/v1 vs.
    domain.com/v2) don't collide into one namespace.
    """
    # Deferred import: stdlib import kept local to this single-use URL helper
    from urllib.parse import urlparse  # noqa: PLC0415 -- stdlib import kept local to

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
