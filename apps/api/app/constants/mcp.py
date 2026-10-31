"""
MCP and Integration Constants.

Centralized constants for MCP services.
"""

# The one backend callback every MCP provider OAuth flow redirects back to.
# Defined here so the redirect URI, its OAuth client metadata, and the
# entitlement allowlist all name the same path.
MCP_OAUTH_CALLBACK_PATH = "/api/v1/mcp/oauth/callback"

# Host of Composio's hosted MCP gateway. These servers authenticate the calling
# platform via an `x-api-key` header (GAIA's COMPOSIO_KEY) rather than per-user
# OAuth/bearer, so requests without that header are rejected with a bare 401.
COMPOSIO_MCP_HOST = "backend.composio.dev"

# GAIA-owned Composio MCP server; the previous id was another account's
# playground server that answered 401 with our key.
YELP_MCP_SERVER_URL = "https://backend.composio.dev/v3/mcp/b4d96e89-0956-47f5-87f8-7b9be7a7e32b/mcp"

# Max distinct scopes to drop across re-authorization retries when an auth
# server rejects scopes with `invalid_scope`. Bounds the retry loop for servers
# that advertise scopes in their metadata they will not actually grant.
MAX_OAUTH_INVALID_SCOPE_DROPS = 5

# Branding sent during Dynamic Client Registration (RFC 7591) — third-party MCP
# auth servers render these on the consent screen the user sees when authorizing.
# Paths are resolved against the frontend URL at registration time.
GAIA_OAUTH_CLIENT_NAME = "GAIA"
GAIA_OAUTH_LOGO_PATH = "/android-chrome-512x512.png"
GAIA_OAUTH_TOS_PATH = "/terms"
GAIA_OAUTH_PRIVACY_PATH = "/privacy"

# What the model sees when a tool call succeeds but carries no content items —
# legal in MCP for void actions (a delete, a set-state). An empty ToolMessage
# tells the model nothing and some providers reject it outright.
EMPTY_TOOL_RESULT = "(tool succeeded with no content)"
# Beyond MAX_MEDIA_BLOCKS_PER_TOOL_RESULT images, further ones are not decoded.
# Emitted once per result, not once per dropped image.
MCP_MEDIA_DROPPED_NOTICE = (
    "[{count} more image(s) omitted: this result returned more images than can be inlined.]"
)
# A content item that is neither text nor an inlinable image (audio, a binary
# resource). Its pydantic repr must never be what the model sees.
MCP_UNSUPPORTED_CONTENT_NOTICE = "[{kind} omitted: this result type cannot be shown as text.]"

# An MCP tool named like one of GAIA's own tools (Dodo's "execute") is renamed
# <source>_<name>; bounded by the providers' function-name limit (OpenAI: 64).
MCP_TOOL_NAME_MAX_CHARS = 64
MCP_TOOL_NAME_SEPARATOR = "_"
# The <source> part when the integration's name has no ASCII letters or digits.
MCP_UNNAMED_SOURCE_PREFIX = "mcp"
# Leads a renamed tool's description: the server's docs, results and other tools
# still use its own name, and the model must map that name to the renamed one.
MCP_RENAMED_TOOL_NOTE = (
    "Note: this tool is called {original} on its own server, so its docs, results and "
    "other tools may refer to it as {original}. Here it is named {renamed}; always call "
    "it as {renamed}.\n\n"
)


# activate_integration preloads every schema of an MCP exposing at most this many
# tools; above it only the configured startup tools, the rest via retrieve_tools.
MCP_PRELOAD_ALL_MAX = 10
# Skills a user saved for a custom MCP are keyed by this agent name plus its id.
CUSTOM_MCP_AGENT_NAME_PREFIX = "custom_mcp_"
