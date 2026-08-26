"""Machine-readable API error codes (mirrored in web errorCodes.ts)."""

# 401 — GAIA session missing/invalid/expired; client shows the login modal.
NOT_AUTHENTICATED = "NOT_AUTHENTICATED"

# 403 — authenticated but the integration has no active connection.
INTEGRATION_NOT_CONNECTED = "INTEGRATION_NOT_CONNECTED"

# 401 — local login presented a wrong email/password.
INVALID_CREDENTIALS = "invalid_credentials"

# 403 — self-host instance already has its administrator account; signup closed.
REGISTRATION_CLOSED = "registration_closed"
