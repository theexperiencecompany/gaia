"""
Auth Constants.

Constants for authentication and JWT operations.
"""

JWT_ALGORITHM = "HS256"

# Token expiration defaults (minutes)
AGENT_TOKEN_EXPIRY_MINUTES = 20

# Login-free integration-connect magic link: opaque, single-use, server-side
# bound to one (user, integration). 12 bytes -> 96 bits of entropy, unguessable
# online (only test is a request to the rate-limited endpoint).
CONNECT_LINK_CODE_BYTES = 12
# Short window: a "click to connect now" link, not a saved bookmark. Keeps the
# pool of live codes small and the leak/brute-force window tiny.
CONNECT_LINK_TTL_MINUTES = 60

# One-tap platform-linking code: 16 bytes -> 22 urlsafe-base64 chars, matched
# by the adapters' trailing-#code regex. Changing this must update
# LINK_CODE_LENGTH in libs/shared/ts/src/bots/link-codes.ts in the same commit.
PLATFORM_LINK_CODE_BYTES = 16

# Session cookie name (WorkOS sealed session)
WOS_SESSION_COOKIE = "wos_session"

# Dev auth bypass: per-request impersonation header (development only). When the
# bypass is active, this header selects the Mongo user to authenticate as instead
# of DEV_AUTH_BYPASS_EMAIL, letting one server act as many users without restarts.
DEV_USER_HEADER = "X-Dev-User"
# Remediation shown when the resolved dev-bypass user does not exist. The exact
# "mint it via ..." phrasing is the actionable fix — keep it in the message.
DEV_USER_MISSING_HINT = "mint it via POST /api/v1/dev/users"

# OAuth login/signup method identifiers
LOGIN_METHOD_WORKOS = "workos"
LOGIN_METHOD_GOOGLE = "google"
LOGIN_METHOD_EMAIL = "email"

# log.audit() actors for credential routes with no user session to name; never
# the credential itself. Self-authenticates with the pairing / refresh credential.
AUDIT_ACTOR_DEVICE_DAEMON = "device-daemon"
# Authenticated by the shared bot API key.
AUDIT_ACTOR_BOT_API = "bot-api"
# The presented credential resolved to no principal.
AUDIT_ACTOR_UNAUTHENTICATED = "unauthenticated"

# OAuth flow type identifiers (used in logging)
OAUTH_FLOW_MOBILE = "mobile"
OAUTH_FLOW_DESKTOP = "desktop"
OAUTH_FLOW_WEB = "web"

# Deep link URIs for native apps
MOBILE_DEEP_LINK = "gaiamobile://auth/callback"
DESKTOP_DEEP_LINK = "gaia://auth/callback"
