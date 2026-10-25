"""Machine-readable API error codes (mirrored in web errorCodes.ts)."""

# 401 — GAIA session missing/invalid/expired; client shows the login modal.
NOT_AUTHENTICATED = "NOT_AUTHENTICATED"

# 403 — authenticated but the integration has no active connection.
INTEGRATION_NOT_CONNECTED = "INTEGRATION_NOT_CONNECTED"

# 401 — local login presented a wrong email/password.
INVALID_CREDENTIALS = "invalid_credentials"

# 403 — self-host signup is invite-only and no invite was presented.
REGISTRATION_CLOSED = "registration_closed"

# 403 — the self-host invite link is unknown, used, revoked or expired.
INVITE_INVALID = "invite_invalid"

# 409 — an instance administrator account cannot be removed.
CANNOT_REMOVE_ADMIN = "cannot_remove_admin"

# 503 — a removed member's automation could not all be stopped; removing again retries.
MEMBER_OFFBOARDING_INCOMPLETE = "member_offboarding_incomplete"

# 409 — a standing-instructions save raced another write; body carries current_revision.
INSTRUCTIONS_CONFLICT = "INSTRUCTIONS_CONFLICT"

# 401 — the bot request's X-Bot-API-Key is missing or wrong (bot misconfigured).
BOT_API_KEY_INVALID = "BOT_API_KEY_INVALID"

# 401 — the platform account is not linked to a GAIA user; the bot offers /auth.
# Both bot codes are mirrored in libs/shared/ts/src/bots/utils/failure-reasons.ts.
BOT_ACCOUNT_NOT_LINKED = "BOT_ACCOUNT_NOT_LINKED"

# 409 — a user-facing feature flag is killed for everyone; the choice cannot be changed now.
FEATURE_KILLED = "FEATURE_KILLED"

# 404 — a self-hosted instance sends no support request to GAIA's support team.
GAIA_SUPPORT_UNAVAILABLE = "gaia_support_unavailable"
# 404 — the conversation does not exist or belongs to another user (never told apart).
CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
