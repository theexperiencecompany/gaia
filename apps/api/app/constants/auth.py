"""
Auth Constants.

Constants for authentication and JWT operations.
"""

# JWT algorithm
JWT_ALGORITHM = "HS256"

# Token expiration defaults (minutes)
AGENT_TOKEN_EXPIRY_MINUTES = 20

# Login-free integration-connect magic link (delivered via bots / non-UI).
# An opaque, single-use code bound server-side to one (user, integration).
# 12 bytes → 96 bits of entropy → unguessable online (the only way to test a
# code is a request to the rate-limited endpoint; there is no offline oracle).
CONNECT_LINK_CODE_BYTES = 12
# Short window: a "click to connect now" link, not a saved bookmark. Keeps the
# pool of live codes small and the leak/brute-force window tiny.
CONNECT_LINK_TTL_MINUTES = 60

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
