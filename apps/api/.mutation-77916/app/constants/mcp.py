"""
MCP and Integration Constants.

Centralized constants for MCP services.
"""

# Host of Composio's hosted MCP gateway. These servers authenticate the calling
# platform via an `x-api-key` header (GAIA's COMPOSIO_KEY) rather than per-user
# OAuth/bearer, so requests without that header are rejected with a bare 401.
COMPOSIO_MCP_HOST = "backend.composio.dev"

YELP_MCP_SERVER_URL = "https://backend.composio.dev/v3/mcp/8e1efded-6b08-4346-a657-92d0b94399e5/mcp?user_id=pg-test-15a6d21a-2a4b-4be5-98c9-d92f55b3ccc3"
INSTACART_MCP_SERVER_URL = "https://backend.composio.dev/v3/mcp/6bb2556a-57ef-4daa-81ad-bd1e3f9e443d/mcp?user_id=pg-test-15a6d21a-2a4b-4be5-98c9-d92f55b3ccc3"

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
