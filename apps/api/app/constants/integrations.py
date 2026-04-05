"""Constants for integration tools."""

# Limits for LLM context to prevent overwhelming responses
MAX_CONNECTED_FOR_LLM = 20
MAX_AVAILABLE_FOR_LLM = 15
MAX_SUGGESTED_FOR_LLM = 10

# Integration connection status values
INTEGRATION_STATUS_CONNECTED = "connected"

# Integration managed_by provider identifiers
MANAGED_BY_MCP = "mcp"
MANAGED_BY_COMPOSIO = "composio"
MANAGED_BY_SELF = "self"

# Known integration IDs
GMAIL_INTEGRATION_ID = "gmail"
GOOGLE_CALENDAR_INTEGRATION_ID = "googlecalendar"
