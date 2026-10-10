"""Docstrings for integration management tools."""

LIST_INTEGRATIONS = """
INTEGRATIONS (LIST): This tool lists all available integrations with their connection status.

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

This tool triggers the UI to show the list of integrations, so the RETURN VALUE is primarily for data purposes.
So no need to list out the integrations in text form.

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

LIST_DEVICES = """
DEVICES (LIST): List the user's paired machines (the `gaia bridge` daemon) and the local
MCP servers each one exposes.

Use this before anything device-related: to learn which machines are paired, whether each is
online right now, and the local MCP servers it exposes (with their integration_id, so you can
hand off to their tools).

RETURN VALUE:
A list of devices, each with:
- id, name, platform, online (is the daemon connected right now)
- servers: the local MCP servers it exposes (server_key, display_name, integration_id, kind
  (stdio | url | filesystem), status, and tools_synced_at).

NOTES:
- A server with tools_synced_at = null was never successfully reached, so its tools are not
  available yet; tell the user to make sure the device is online.
- Tools of an online, synced device server are used like any other integration (hand off to it);
  you do not connect to a device server through add_custom_mcp_server.
"""

ADD_CUSTOM_MCP_SERVER = """
INTEGRATIONS (ADD CUSTOM MCP SERVER): Add a remote MCP server the user asks for by name
(e.g. "add the Sentry MCP", "connect the Linear MCP server").

WORKFLOW (do this in order):
1. If you only have a product name, FIRST use web_search_tool / fetch_webpages to find the
   vendor's official MCP server endpoint URL from their docs. NEVER guess the URL.
2. Call this tool with the resolved `server_url`. The user is shown the name + URL and must
   approve before anything connects, so you do not need to ask separately; the approval card handles it.
3. If the result says authorization or a token is needed, a connect button is shown to the user;
   ask them to click it. Do NOT put any URL in your reply; the card handles it.

PARAMETERS:
- `server_url` (str): The exact MCP endpoint URL you resolved (e.g. "https://mcp.sentry.dev/mcp").
- `name` (str): A human-facing name for the server (e.g. "Sentry").

SECURITY (non-negotiable):
- NEVER ask the user to paste an API key or token to you, and never accept one as an argument.
  Servers that need a token are handed to a secure UI form instead.

WHEN NOT TO USE:
- Do NOT use this for integrations already in the catalog (Gmail, Notion, GitHub, Slack, ...).
  Use connect_integration with the integration's id for those.
"""

CONNECT_INTEGRATION = """
INTEGRATIONS (CONNECT): This tool initiates the connection flow for one or more integrations.

Use this tool when the user asks to:
- "Connect Gmail"
- "I want to link my Notion account"
- "Set up Twitter integration"
- "Connect my [service] account"
- "Connect Gmail and Notion"
- "Set up multiple integrations"

PARAMETERS:
- `integration_ids` (List[str]): List of exact integration IDs to connect.
  - Use integration IDs (e.g., "gmail", "notion", "twitter"); call list_integrations first if unsure
  - Can be a single ID or multiple IDs
- `force_reconnect` (bool, optional): Set true only when the user explicitly asks to reconnect or refresh an integration that may already be connected. Defaults to false.

BEHAVIOR:
- Validates each integration ID (exact match only)
- Checks if integration is available
- Checks if integration is already connected
- Initiates OAuth/connection flow for disconnected integrations
- When `force_reconnect` is true, bypasses the connected-status check and starts reauthorization

IMPORTANT:
- This tool does NOT directly connect integrations
- It initiates the OAuth flow and the user must complete authentication
- Multiple integrations can be connected in a single call
- If an integration is already connected, it will skip and inform the user
- Do not force reconnection unless the user explicitly asks to reconnect or refresh access

RETURN VALUE:
Returns a status message for each integration:
- Already connected
- Connection initiated (user needs to complete OAuth)
- Not found (suggests available IDs)
- Not available yet (coming soon)

Examples:
- User: "Connect Gmail" → integration_ids: ["gmail"]
- User: "Set up Gmail and Notion" → integration_ids: ["gmail", "notion"]
- User: "Link my calendar" → integration_ids: ["googlecalendar"]
"""

CHECK_INTEGRATIONS_STATUS = """
INTEGRATIONS (CHECK STATUS): This tool checks the connection status of specific integrations.

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


ADD_DEVICE = """
Start connecting the user's own computer (a "device") to GAIA.

Use this when the user asks to connect their laptop, computer, or machine, wants
GAIA to reach files or apps on their own machine, or has no device connected
yet. It shows the user a setup card with the install command and the pairing
command, and needs no input from you.

After they run the pairing command and get a short code, they paste it in chat;
you then call approve_device_pairing with that code. You cannot approve a code
yourself, the user confirms on the authenticated page the card links to.

To only look at already-connected devices and what they expose, use list_devices
instead.
"""


APPROVE_DEVICE_PAIRING = """
Surface the trusted approval link for a device pairing code the user pasted.

Call this with the short code the pairing command printed (for example
"NS2V-YC5S"). It shows the user a button that opens the signed-in approval page
with the code prefilled, where THEY confirm linking the device. You never
approve it yourself. This action is always confirmed with the user first.

After they approve, tell them to run the up command to bring the device online.
Do not include the approval URL in your own text on a UI client, the card
handles it.
"""


RUN_ON_DEVICE = """
Run a shell command on one of the user's paired machines and get its output.

Use this to do anything on the user's own computer: read or edit files, list a
directory, run a build or a script, install or launch a local MCP server with
the `gaia bridge` CLI, inspect the system. The command runs in the user's shell
on that machine, as that user, so paths, `~`, pipes, and installed tools all
work as they would in their terminal.

PARAMETERS:
- device_id: which machine to run on (from list_devices). Call list_devices
  first if you don't already know the id, and to check the device is online.
- command: the shell command to run (e.g. `ls ~/Downloads`, `cat report.md`,
  `gaia bridge add`).

RETURN VALUE:
The exit code plus captured stdout and stderr (output is capped and the command
is killed if it runs too long). A non-zero exit code means the command failed:
read stderr, fix, and re-run rather than assuming success.

NOTES:
- NOT for a device's MCP servers. If a device exposes an MCP server (shown under
  CONNECTED DEVICES as "exposing: <name>"), use that server's own tools to
  operate it - retrieve them and hand off to its subagent - never shell out to it
  with this tool. run_on_device is for shell commands, not for calling MCP tools.
- This is the one way to touch the user's real files; the coding sandbox is a
  cloud container that cannot see their machine.
- The device must be online (the `gaia bridge up` daemon running). If it is
  offline the call fails with a message telling the user how to bring it up.
- Commands run with NO stdin, so anything that waits for input gets EOF and
  fails. Always use non-interactive forms (flags, piped input, heredocs). To add
  an MCP server on the device, use the flag form, e.g. `gaia bridge add --type
  stdio --name github --command "npx -y @modelcontextprotocol/server-github"`;
  the bare `gaia bridge add` is an interactive wizard and will not work here.
"""
