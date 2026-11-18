"""
Auth Constants.

Constants for authentication and JWT operations.
"""

from enum import StrEnum

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
# How long a WorkOS session cookie lives, set at sign-in and at every refresh.
WOS_SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600
# Non-secret "a session exists" cookie the web reads before asking /user/me; it rides
# with every session cookie. Paired with SESSION_HINT_COOKIE in libs/shared/ts/src/utils/sessionCookies.ts.
SESSION_HINT_COOKIE = "gaia_signed_in"

# Dev auth bypass: per-request impersonation header (development only). When the
# bypass is active, this header selects the Mongo user to authenticate as instead
# of DEV_AUTH_BYPASS_EMAIL, letting one server act as many users without restarts.
DEV_USER_HEADER = "X-Dev-User"
# Remediation shown when the resolved dev-bypass user does not exist. The exact
# "mint it via ..." phrasing is the actionable fix — keep it in the message.
DEV_USER_MISSING_HINT = "mint it via POST /api/v1/dev/users"

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


class InstanceRole(StrEnum):
    """A self-host account's role: the first account administers the instance."""

    ADMIN = "admin"
    MEMBER = "member"


class RegistrationPolicy(StrEnum):
    """Who may create a self-host account once the administrator exists."""

    INVITE_ONLY = "invite_only"
    OPEN = "open"


# Self-host invite links: 32 bytes -> 43 urlsafe chars; only the SHA-256 digest is stored.
INVITE_TOKEN_BYTES = 32

# OWASP-recommended bcrypt cost for interactive logins (~250ms per verify).
BCRYPT_ROUNDS = 12
# The shortest password a new local account or a password change accepts.
MIN_PASSWORD_LENGTH = 8

# Random bytes in the password the admin reset script prints (24 url-safe chars).
RESET_PASSWORD_TOKEN_BYTES = 18
INVITE_TTL_DAYS = 7

# instance_settings key holding the self-host registration policy.
REGISTRATION_SETTINGS_KEY = "registration"

# WorkOS JWT signing keys, cached per process. A key WorkOS removes keeps
# verifying for up to the cache lifespan; forging with it still needs our cookie
# password, since a token is checked only after its cookie unseals.
WORKOS_JWKS_CACHE_SECONDS = 120
# Minimum gap between refetches forced by a token naming a key outside the set:
# a rotated key is picked up within it, and a stale cookie cannot force a fetch
# per request.
WORKOS_JWKS_REFRESH_COOLDOWN_SECONDS = 5
# A key fetch holds the shared client's lock and a worker thread; bound it so a
# WorkOS outage fails auth fast instead of queueing every request behind it.
WORKOS_JWKS_FETCH_TIMEOUT_SECONDS = 5
