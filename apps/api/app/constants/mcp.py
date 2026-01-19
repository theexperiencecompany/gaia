"""
MCP and Integration Constants.

Centralized constants for MCP services including Redis key prefixes, TTL values,
and integration status enums.
"""

from enum import StrEnum

from app.constants.cache import ONE_DAY_TTL, TEN_MINUTES_TTL


# Redis key prefixes for OAuth state management
OAUTH_STATE_PREFIX = "mcp_oauth_state"
OAUTH_DISCOVERY_PREFIX = "mcp_oauth_discovery"

# TTL values - use shared constants
OAUTH_STATE_TTL = TEN_MINUTES_TTL  # OAuth state is short-lived for security
OAUTH_DISCOVERY_TTL = ONE_DAY_TTL  # Discovery data changes infrequently


# Public MCP server URLs
YELP_MCP_SERVER_URL = "https://backend.composio.dev/v3/mcp/8e1efded-6b08-4346-a657-92d0b94399e5/mcp?user_id=pg-test-15a6d21a-2a4b-4be5-98c9-d92f55b3ccc3"
INSTACART_MCP_SERVER_URL = "https://backend.composio.dev/v3/mcp/6bb2556a-57ef-4daa-81ad-bd1e3f9e443d/mcp?user_id=pg-test-15a6d21a-2a4b-4be5-98c9-d92f55b3ccc3"


class UserIntegrationStatus(StrEnum):
    """Status of a user's integration in MongoDB user_integrations collection."""

    CREATED = "created"  # Added to workspace but not authenticated
    CONNECTED = "connected"  # Fully authenticated and ready to use


class ConnectResponseStatus(StrEnum):
    """Response status from POST /integrations/connect/{id} endpoint."""

    CONNECTED = "connected"  # Integration is ready to use
    REDIRECT = "redirect"  # OAuth required, redirect to redirect_url
    ERROR = "error"  # Connection failed


class ConnectionTestStatus(StrEnum):
    """Status returned from connection testing."""

    CONNECTED = "connected"  # Successfully connected
    REQUIRES_OAUTH = "requires_oauth"  # OAuth authentication needed
    FAILED = "failed"  # Connection test failed
    CREATED = "created"  # Initial state
