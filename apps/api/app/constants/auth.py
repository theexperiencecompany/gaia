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

# One-tap platform-linking code minted by the web at onboarding. Travels inside
# a deep link (Telegram) or the user's own visible first message (WhatsApp /
# iMessage), so it is also what the adapters' trailing-#code regex matches:
# 16 bytes → exactly 22 urlsafe-base64 characters, 128 bits of entropy. Changing
# this changes the code length the adapters accept — update
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

# log.audit() actors for credential routes with no user session to name. Each
# identifies the *caller class* that authenticated (mirroring the "dodo-webhook"
# actor on the payment webhook); `resource`/`provider` name whose account was
# acted on. Never the credential itself.
# Self-authenticates with the pairing / refresh credential.
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
