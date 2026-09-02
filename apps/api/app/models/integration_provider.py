"""The transports an integration can be backed by.

One closed set, referenced from the catalog models, the API schemas, the
subagent models and the connect dispatch. It lived as a repeated
``Literal[...]`` in six places, which is exactly the shape that drifts: adding
a transport meant finding every copy, and missing one produced a validation
error far from the change.
"""

from typing import Literal

# ``self``      — GAIA runs the OAuth dance itself (Google).
# ``composio``  — Composio brokers the connection and hosts the tools.
# ``mcp``       — an MCP server, platform-configured or user-supplied.
# ``internal``  — built into GAIA; nothing to connect (todos, reminders).
# ``cli``       — a real vendor command-line tool run in the user's sandbox.
ManagedBy = Literal["self", "composio", "mcp", "internal", "cli"]
