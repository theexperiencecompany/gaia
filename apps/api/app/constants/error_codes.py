"""Machine-readable API error codes (mirrored in web errorCodes.ts)."""

# 401 — GAIA session missing/invalid/expired; client shows the login modal.
NOT_AUTHENTICATED = "NOT_AUTHENTICATED"

# 403 — authenticated but the integration has no active connection.
INTEGRATION_NOT_CONNECTED = "INTEGRATION_NOT_CONNECTED"

# 401 — the bot request's X-Bot-API-Key is missing or wrong (bot misconfigured).
BOT_API_KEY_INVALID = "BOT_API_KEY_INVALID"

# 401 — the platform account is not linked to a GAIA user; the bot offers /auth.
# Both bot codes are mirrored in libs/shared/ts/src/bots/utils/failure-reasons.ts.
BOT_ACCOUNT_NOT_LINKED = "BOT_ACCOUNT_NOT_LINKED"

# 409 — a user-facing feature flag is killed for everyone; the choice cannot be changed now.
FEATURE_KILLED = "FEATURE_KILLED"
