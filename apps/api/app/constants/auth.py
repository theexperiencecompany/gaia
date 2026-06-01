"""
Auth Constants.

Constants for authentication and JWT operations.
"""

# JWT algorithm
JWT_ALGORITHM = "HS256"

# Token expiration defaults (minutes)
AGENT_TOKEN_EXPIRY_MINUTES = 20

# Login-free integration-connect magic link (delivered via bots / non-UI).
# Scope-limited role so a leaked link can only start an OAuth connect for one
# integration — never act as a session/agent/bot token.
CONNECT_LINK_ROLE = "integration_connect"
# Generous window so async bot replies stay usable; bounded to limit exposure.
CONNECT_LINK_TTL_HOURS = 24

# Session cookie name (WorkOS sealed session)
WOS_SESSION_COOKIE = "wos_session"

# OAuth login/signup method identifiers
LOGIN_METHOD_WORKOS = "workos"
LOGIN_METHOD_GOOGLE = "google"
LOGIN_METHOD_EMAIL = "email"

# OAuth flow type identifiers (used in logging)
OAUTH_FLOW_MOBILE = "mobile"
OAUTH_FLOW_DESKTOP = "desktop"
OAUTH_FLOW_WEB = "web"

# Deep link URIs for native apps
MOBILE_DEEP_LINK = "gaiamobile://auth/callback"
DESKTOP_DEEP_LINK = "gaia://auth/callback"
