"""
MCP Constants.

Centralized constants for MCP services including Redis key prefixes and TTL values.
"""

from app.constants.cache import ONE_DAY_TTL, TEN_MINUTES_TTL

# Redis key prefixes for OAuth state management
OAUTH_STATE_PREFIX = "mcp_oauth_state"
OAUTH_DISCOVERY_PREFIX = "mcp_oauth_discovery"

# TTL values - use shared constants
OAUTH_STATE_TTL = TEN_MINUTES_TTL  # OAuth state is short-lived for security
OAUTH_DISCOVERY_TTL = ONE_DAY_TTL  # Discovery data changes infrequently
