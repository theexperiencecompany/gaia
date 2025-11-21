"""Docstrings for integration management tools."""

LIST_INTEGRATIONS = """
INTEGRATIONS — LIST: This tool lists all available integrations with their connection status.

Use this tool when the user asks:
- "What integrations do you have?"
- "What can you connect to?"
- "What integrations are available?"
- "Show me all integrations"
- "What services can you work with?"
- "What integrations are connected?"
- "Show me my connected integrations"

PARAMETERS:
- `connected_only` (bool): If True, only return connected integrations. If False (default), return all available integrations.

BEHAVIOR:
- Fetches all available integrations from the system
- Checks connection status for each integration
- Returns structured data with id, name, description, category, and connection status
- Triggers frontend UI to display the integration list

RETURN VALUE:
Returns a list of integration objects with the following structure:
- id: Integration identifier (e.g., "gmail", "calendar", "notion")
- name: Display name (e.g., "Gmail", "Google Calendar")
- description: Brief description of the integration
- category: Integration category (e.g., "productivity", "communication")
- connected: Boolean indicating if the integration is connected

Examples:
- User: "What integrations do you have?" → connected_only: False
- User: "Show me my connected integrations" → connected_only: True
"""

CONNECT_INTEGRATION = """
INTEGRATIONS — CONNECT: This tool initiates the connection flow for one or more integrations.

Use this tool when the user asks to:
- "Connect Gmail"
- "I want to link my Notion account"
- "Set up Twitter integration"
- "Connect my [service] account"
- "Connect Gmail and Notion"
- "Set up multiple integrations"

PARAMETERS:
- `integration_names` (List[str]): List of integration names or IDs to connect
  - Can be integration IDs (e.g., "gmail", "notion")
  - Can be integration names (e.g., "Gmail", "Notion")
  - Can be short names if available
  - Can be a single integration or multiple integrations

BEHAVIOR:
- Validates each integration name/ID
- Checks if integration is available
- Checks if integration is already connected
- Initiates OAuth/connection flow for disconnected integrations
- Triggers frontend UI to handle authentication

IMPORTANT:
- This tool does NOT directly connect integrations
- It initiates the OAuth flow and the user must complete authentication
- Multiple integrations can be connected in a single call
- If an integration is already connected, it will skip and inform the user

RETURN VALUE:
Returns a status message for each integration:
- ✅ Already connected
- 🔗 Connection initiated (user needs to complete OAuth)
- ❌ Not found (suggests available integrations)
- ⏳ Not available yet (coming soon)

Examples:
- User: "Connect Gmail" → integration_names: ["gmail"]
- User: "Set up Gmail and Notion" → integration_names: ["gmail", "notion"]
- User: "Link my calendar" → integration_names: ["calendar"]
"""

CHECK_INTEGRATIONS_STATUS = """
INTEGRATIONS — CHECK STATUS: This tool checks the connection status of specific integrations.

Use this tool when the user asks:
- "Is Gmail connected?"
- "Check if Notion is connected"
- "What's the status of my integrations?"
- "Am I connected to [service]?"
- "Check my calendar connection"

PARAMETERS:
- `integration_names` (List[str]): List of integration names or IDs to check
  - Can be integration IDs (e.g., "gmail", "notion")
  - Can be integration names (e.g., "Gmail", "Notion")
  - Can check single or multiple integrations at once

BEHAVIOR:
- Validates each integration name/ID
- Checks current connection status for each integration
- Returns clear status indicator for each

RETURN VALUE:
Returns a formatted status message for each integration:
- ✅ Connected: Integration is active and connected
- ⚪ Not Connected: Integration is available but not connected
- ❓ Not found: Integration name/ID doesn't exist

Examples:
- User: "Is Gmail connected?" → integration_names: ["gmail"]
- User: "Check calendar and notion status" → integration_names: ["calendar", "notion"]
- User: "What's the status of my integrations?" → Use list_integrations instead
"""
